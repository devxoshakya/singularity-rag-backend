import os
import requests
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from typing import List
from google import genai
from google.genai import types
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi import Header

# --- 1. CONFIGURATION & LIFESPAN ---
app = FastAPI(title="College RAG API")

# Use environment variables
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")

# Initialize clients
genai_client = genai.Client(api_key=GEMINI_API_KEY)
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client["rag_pdfs"]
collection = db["pdfs"]
rules_collection = db["result"]

# --- 2. DATA MODELS (PYDANTIC) ---
class ResultAnalysisRequest(BaseModel):
    question: str


class QueryRequest(BaseModel):
    question: str

class SearchResult(BaseModel):
    text: str
    score: float
    source: str

class QueryResponse(BaseModel):
    answer: str
    context_used: List[SearchResult]

# --- 3. THE RAG LOGIC ---
async def get_rag_context(query: str):
    """Refactored version of your get_query_results for Production"""
    # Generate embedding
    response = genai_client.models.embed_content(
        model="gemini-embedding-001",
        contents=query,
        config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY")
    )
    query_embedding = response.embeddings[0].values

    # Vector Search Pipeline
    pipeline = [
        {
            "$vectorSearch": {
                "index": "vector_index", 
                "queryVector": query_embedding,
                "path": "embedding",
                "numCandidates": 100,
                "limit": 5
            }
        },
        {
            "$project": {
                "_id": 0,
                "text": 1,
                "metadata": 1,
                "score": {"$meta": "vectorSearchScore"}
            }
        }
    ]
    
    # Motor uses 'to_list' for async iteration
    cursor = collection.aggregate(pipeline)
    results = await cursor.to_list(length=5)
    return results

# --- 4. THE API ENDPOINT ---
@app.post("/ask", response_model=QueryResponse)
async def ask_college_bot(request: QueryRequest):
    # 1. Get relevant chunks from MongoDB
    raw_results = await get_rag_context(request.question)
    
    if not raw_results:
        raise HTTPException(status_code=404, detail="No relevant information found.")

    # 2. Build context for LLM
    context_text = "\n\n".join([r['text'] for r in raw_results])
    
    # 3. Generate final answer
    prompt = f"Answer the question based ONLY on this context:\n{context_text}\n\nQuestion: {request.question}"
    
    llm_response = genai_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    # 4. Format response
    formatted_context = [
        SearchResult(
            text=r['text'], 
            score=r['score'], 
            source=r['metadata'].get('source', 'Unknown')
        ) for r in raw_results
    ]

    return QueryResponse(
        answer=llm_response.text,
        context_used=formatted_context
    )



@app.post("/analyze-result", response_model=QueryResponse)
async def analyze_result(
    request: ResultAnalysisRequest, 
    x_roll_no: str = Header(None) # Looks for 'x-roll-no' in request headers
):
    # 1. Validation Guard
    if not x_roll_no:
        raise HTTPException(status_code=400, detail="Header 'x-roll-no' is required.")

    # 2. Fetch Student Data (External API)
    api_url = f"https://singularity-server.devxoshakya.workers.dev/api/result/by-rollno?rollNo={x_roll_no}"
    try:
        api_res = requests.get(api_url)
        student_data = api_res.json().get("data") if api_res.status_code == 200 else None
        if not student_data:
            raise HTTPException(status_code=404, detail="Student record not found.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Result API Error: {str(e)}")

    # 3. Vector Search (Using the Grading Rules Collection)
    # We use gemini-embedding-001 for the search
    embed_resp = genai_client.models.embed_content(
        model="gemini-embedding-001",
        contents=request.question,
        config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY")
    )
    query_embedding = embed_resp.embeddings[0].values

    pipeline = [
        {
            "$vectorSearch": {
                "index": "vector_index", # The index on your grading_rules collection
                "queryVector": query_embedding,
                "path": "embedding",
                "numCandidates": 100,
                "limit": 5
            }
        },
        {"$project": {"_id": 0, "text": 1, "metadata": 1, "score": {"$meta": "vectorSearchScore"}}}
    ]
    
    # We target rules_collection specifically
    cursor = rules_collection.aggregate(pipeline)
    raw_results = await cursor.to_list(length=5)
    context_text = "\n\n".join([r['text'] for r in raw_results])

    # 4. Strict LLM Generation
    prompt = f"""
    You are an Academic Auditor. Compare the Student Data to the University Rules.
    
    STUDENT DATA: {student_data}
    UNIVERSITY RULES: {context_text}
    QUERY: {request.question}
    
    Analyze the eligibility for Pass/Fail/PWG strictly based on these rules.
    """

    llm_response = genai_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0)
    )

    # 5. Format Response
    return QueryResponse(
        answer=llm_response.text,
        context_used=[
            SearchResult(
                text=r['text'], 
                score=r['score'], 
                source=r['metadata'].get('source', 'Criteria PDF')
            ) for r in raw_results
        ]
    )

# --- 4. HEALTH CHECK ENDPOINT ---
@app.get("/health")
async def health_check():
    """Health check endpoint for Docker."""
    try:
        # Check MongoDB connection
        await mongo_client.admin.command('ping')
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database connection failed: {str(e)}")