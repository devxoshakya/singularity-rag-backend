import os
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from typing import List
from google import genai
from google.genai import types
from motor.motor_asyncio import AsyncIOMotorClient

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

# --- 2. DATA MODELS (PYDANTIC) ---
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