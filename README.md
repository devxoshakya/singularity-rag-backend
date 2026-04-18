# Singularity RAG Backend — Feature README

This backend helps students and applicants get reliable answers from college PDFs and result-rule documents, without manually searching long files.

## What problems this service solves

- **Information is scattered across long PDFs**  
  The service turns PDF content into searchable knowledge and returns direct, contextual answers.

- **Scanned/low-quality PDFs are hard to use**  
  The ingestion flow falls back to OCR when normal text extraction is weak.

- **Generic chatbot answers can miss official rules**  
  Answers are grounded in retrieved chunks from uploaded academic documents.

- **Rule-based result interpretation is hard for students**  
  The result analysis flow combines student data + official ordinance context before generating analysis.

- **Users need fast chat UX, not delayed full responses**  
  Responses are streamed, with source context sent first so UI can render supporting references immediately.

- **Deploying AI services is often complex**  
  This project is Docker-ready and can be started with a small environment setup.

---

## Core product features

### 1) College RAG chat (`/ask`)

- Accepts a question plus `session_id`
- Retrieves semantically relevant chunks from the **`pdfs` collection**
- Uses conversation window memory from prior turns in that session
- Streams answer text to the client
- Sends `context_used` metadata first (score + source-ready snippets)
- Stores question/answer pairs for session history

### 2) Result analysis assistant (`/analyze-result`)

- Accepts a question plus `session_id`
- Requires `X-Roll-No` header
- Fetches student result data from external API by roll number
- Retrieves relevant rule chunks from the **`result` collection**
- Combines student data + retrieved rules into one analysis prompt
- Streams the final explanation and saves it to chat history

### 3) Secure user-scoped sessions

- JWT-based identity extraction (`sub` as user_id)
- Session listing is filtered to logged-in user only
- History retrieval is user-scoped per session
- Session data has TTL cleanup behavior for old records

### 4) Session and history APIs

- `GET /sessions` → user’s recent chat sessions
- `GET /history/{session_id}` → full message timeline for one session

---

## PDF ingestion depth (how knowledge is built)

The ingestion notebooks (`notebooks/ingest.ipynb` and `notebooks/result_analysis.ipynb`) implement the end-to-end indexing flow.

### Ingestion pipeline behavior

1. **Load all PDFs from target folders**
   - `clg_pdfs/` for general college query corpus
   - `result_pdfs/` for rule/ordinance result analysis corpus

2. **Extract page text with fallback OCR**
   - Uses standard PDF text extraction first
   - If page text is missing/too short, OCR is executed

3. **Attach source metadata per page**
   - Source file name
   - Page number
   - File path

4. **Chunk documents for retrieval quality**
   - Recursive splitting with overlap
   - Keeps chunks small enough for accurate semantic matching

5. **Generate embeddings in controlled batches**
   - Uses Gemini embedding model
   - Includes rate-limit-aware retry and wait handling

6. **Insert vectorized records into MongoDB**
   - Stores `text`, `embedding`, `metadata`

7. **Create and poll vector index readiness**
   - Creates `vector_index`
   - Waits until queryable before usage

### Why this ingestion approach matters

- Handles both native-text and scanned PDFs
- Improves recall with chunk overlap
- Reduces ingestion failures from API rate limits
- Preserves citation-ready metadata
- Keeps retrieval usable immediately after index readiness

---

## What is used in the backend (concise)

- **FastAPI** for HTTP APIs and streaming responses
- **MongoDB** for vector search + session storage
- **Google Gemini APIs** for embeddings and generation
- **JWT auth** for user isolation
- **HTTP integration** for roll-number-based student result fetch

---

## API summary

- `GET /sessions`
- `GET /history/{session_id}`
- `POST /ask`
- `POST /analyze-result`

> Notes:
> - Protected routes expect `Authorization: Bearer <token>`
> - `/analyze-result` also expects `X-Roll-No` header

---

## Docker deployment

### Prerequisites

- Docker + Docker Compose
- Valid `GEMINI_API_KEY`
- Valid `MONGO_URI`
- `JWT_SECRET`

### Run

```bash
cp .env.example .env
# add GEMINI_API_KEY, MONGO_URI, JWT_SECRET in .env

docker compose up --build
```

Service runs at: `http://localhost:8000`
Docs: `http://localhost:8000/docs`

---

## Environment variables

- `GEMINI_API_KEY` — embedding + generation access
- `MONGO_URI` — MongoDB connection
- `JWT_SECRET` — JWT decode secret for user-scoped APIs

---

## Repo paths relevant to these features

- Backend API: `/home/runner/work/singularity-rag-backend/singularity-rag-backend/src/main.py`
- General ingestion workflow: `/home/runner/work/singularity-rag-backend/singularity-rag-backend/notebooks/ingest.ipynb`
- Result-analysis ingestion workflow: `/home/runner/work/singularity-rag-backend/singularity-rag-backend/notebooks/result_analysis.ipynb`
- Docker setup: `/home/runner/work/singularity-rag-backend/singularity-rag-backend/docker-compose.yml`
