import os
import jwt
import httpx
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from typing import List
from google import genai
from google.genai import types
from motor.motor_asyncio import AsyncIOMotorClient
from contextlib import asynccontextmanager
from datetime import datetime
import json
from fastapi.responses import StreamingResponse

# --- 1. CONFIG & SECURITY ---

# This secret must match the one used by the service generating the tokens
JWT_SECRET = os.getenv("JWT_SECRET")
ALGORITHM = "HS256"

# This utility finds the 'Authorization: Bearer <token>' header
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

async def get_current_user_id(token: str = Depends(oauth2_scheme)):
    """Decodes the JWT and returns the user_id (sub). No DB lookup needed."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="User ID missing in token")
        return user_id
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

# --- 2. SETUP & MODELS ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Added user_id to the index for faster sidebar lookups
    await sessions_collection.create_index([("user_id", 1), ("session_id", 1), ("timestamp", -1)])
    await sessions_collection.create_index("timestamp", expireAfterSeconds=604800)
    yield
    mongo_client.close()

app = FastAPI(title="Stateless Secure RAG", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],  # Allows GET, POST, OPTIONS, etc.
    allow_headers=["*"],  # Allows Authorization, X-Roll-No, Content-Type, etc.
)

# Clients (Keep your existing env vars)
genai_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
mongo_client = AsyncIOMotorClient(os.getenv("MONGO_URI"))
db = mongo_client["rag_pdfs"]
collection, rules_collection, sessions_collection = db["pdfs"], db["result"], db["sessions"]

class SessionItem(BaseModel):
    session_id: str
    title: str

class QueryRequest(BaseModel):
    question: str
    session_id: str

class ResultAnalysisRequest(BaseModel):
    question: str
    session_id: str

class SearchResult(BaseModel):
    text: str
    score: float
    source: str

class QueryResponse(BaseModel):
    answer: str
    context_used: List[SearchResult]

class ChatMessage(BaseModel):
    role: str
    content: str

class HistoryResponse(BaseModel):
    session_id: str
    messages: List[ChatMessage]

# --- 3. HELPER FUNCTIONS ---

async def get_sliding_window_history(session_id: str, user_id: str, limit: int = 4):
    """Fetches last N messages for the specific user and session."""
    cursor = sessions_collection.find({"session_id": session_id, "user_id": user_id}).sort("timestamp", -1).limit(limit)
    history_docs = await cursor.to_list(length=limit)
    history_docs.reverse()
    
    chat_history = []
    for doc in history_docs:
        chat_history.append(types.Content(role="user", parts=[types.Part(text=doc["user_query"])]))
        chat_history.append(types.Content(role="model", parts=[types.Part(text=doc["bot_response"])]))
    return chat_history

def safe_generate(chat_session, prompt: str):
    try:
        response = chat_session.send_message(prompt)
        return response.text.strip() if response.text else "Response filtered by safety settings."
    except Exception:
        return "The AI is currently unavailable. Please try again."

# --- 4. ROUTES ---

@app.get("/sessions", response_model=List[SessionItem])
async def list_sessions(user_id: str = Depends(get_current_user_id)):
    """Fetches sidebar titles for the LOGGED-IN user only."""
    pipeline = [
        {"$match": {"user_id": user_id}}, # Security: Only see your own chats
        {"$sort": {"timestamp": 1}},
        {"$group": {
            "_id": "$session_id",
            "first_query": {"$first": "$user_query"},
            "last_active": {"$last": "$timestamp"}
        }},
        {"$sort": {"last_active": -1}}
    ]
    cursor = sessions_collection.aggregate(pipeline)
    results = await cursor.to_list(length=100)
    return [SessionItem(session_id=s["_id"], title=s["first_query"][:35] + "...") for s in results]

@app.get("/history/{session_id}", response_model=HistoryResponse)
async def get_chat_history(session_id: str, user_id: str = Depends(get_current_user_id)):
    """Loads chat bubbles for the specific session, verifying ownership."""
    cursor = sessions_collection.find({"session_id": session_id, "user_id": user_id}).sort("timestamp", 1)
    docs = await cursor.to_list(length=100) 
    
    messages = []
    for d in docs:
        messages.append(ChatMessage(role="user", content=d["user_query"]))
        messages.append(ChatMessage(role="model", content=d["bot_response"]))
    return HistoryResponse(session_id=session_id, messages=messages)


@app.post("/ask")
async def ask_college_bot(request: QueryRequest, user_id: str = Depends(get_current_user_id)):
    # 1. History (Last 2 turns)
    chat_history = await get_sliding_window_history(request.session_id, user_id, limit=4)

    # 2. Vector Search
    embed = genai_client.models.embed_content(model="gemini-embedding-001", contents=request.question)
    cursor = collection.aggregate([
        {"$vectorSearch": {"index": "vector_index", "queryVector": embed.embeddings[0].values, "path": "embedding", "numCandidates": 50, "limit": 3}},
        {"$project": {"text": 1, "metadata": 1, "score": {"$meta": "vectorSearchScore"}}}
    ])
    results = await cursor.to_list(length=3)
    context_text = "\n".join([r['text'] for r in results])

    # Pre-format the sources exactly like your original QueryResponse
    context_used = [
        {"text": r['text'], "score": r['score'], "source": "PDF"} 
        for r in results
    ]

    # 3. Stream Generator
    async def stream_generator():
        full_ans = ""
        
        # FIRST: Send the sources immediately so the UI can show them
        # We send it as a single JSON line
        yield json.dumps({"context_used": context_used}) + "\n"
        
        # SECOND: Start streaming the AI text
        chat = genai_client.chats.create(model="gemini-2.5-flash", history=chat_history)
        
        # Use the stream method
        response_stream = chat.send_message_stream(
            f"CONTEXT:\n{context_text}\n\nQUESTION: {request.question}"
        )

        for chunk in response_stream:
            if chunk.text:
                full_ans += chunk.text
                # Yield only the raw text chunk
                yield chunk.text

        # 4. Save to DB (Runs after the loop finishes)
        await sessions_collection.insert_one({
            "user_id": user_id, 
            "session_id": request.session_id, 
            "user_query": request.question, 
            "bot_response": full_ans, 
            "timestamp": datetime.utcnow()
        })

    return StreamingResponse(stream_generator(), media_type="text/plain")


@app.post("/analyze-result")
async def analyze_result(
    data: ResultAnalysisRequest, 
    user_id: str = Depends(get_current_user_id), 
    x_roll_no: str = Header(None)
):
    if not x_roll_no: 
        raise HTTPException(status_code=400, detail="Roll No Header missing")
    
    # 1. History & External API Call
    chat_history = await get_sliding_window_history(data.session_id, user_id, limit=4)

    async with httpx.AsyncClient() as client:
        res = await client.get(f"https://singularity-server.devxoshakya.workers.dev/api/result/by-rollno?rollNo={x_roll_no}")
        student_data = res.json().get("data") if res.status_code == 200 else None
            
    if not student_data: 
        raise HTTPException(status_code=404, detail="Student record not found.")

    # 2. Vector Search for Rules
    embed = genai_client.models.embed_content(model="gemini-embedding-001", contents=data.question)
    cursor = rules_collection.aggregate([
        {"$vectorSearch": {
            "index": "vector_index", 
            "queryVector": embed.embeddings[0].values, 
            "path": "embedding", 
            "numCandidates": 50, 
            "limit": 2
        }},
        {"$project": {"text": 1, "metadata": 1, "score": {"$meta": "vectorSearchScore"}}}
    ])
    results = await cursor.to_list(length=2)
    rules_text = "\n".join([r['text'] for r in results])

    # 3. Define the Streaming Generator
    async def stream_generator():
        full_ans = ""
        
        # A. Send context/rules first (Metadata)
        context_used = [
            {"text": r['text'], "score": r['score'], "source": "Rules"} 
            for r in results
        ]
        yield json.dumps({"context_used": context_used}) + "\n"

        # B. Initialize Streaming Chat
        chat = genai_client.chats.create(model="gemini-2.5-flash", history=chat_history)
        
        # Combine student info and rules into one prompt
        prompt = f"STUDENT_DATA: {student_data}\nRULES: {rules_text}\nQUERY: {data.question}"
        
        response_stream = chat.send_message_stream(prompt)

        for chunk in response_stream:
            if chunk.text:
                full_ans += chunk.text
                yield chunk.text

        # 4. Save to Database after stream finishes
        await sessions_collection.insert_one({
            "user_id": user_id, 
            "session_id": data.session_id, 
            "user_query": data.question, 
            "bot_response": full_ans, 
            "timestamp": datetime.utcnow()
        })

    return StreamingResponse(stream_generator(), media_type="text/plain")