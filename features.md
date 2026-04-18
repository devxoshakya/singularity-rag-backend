# Singularity RAG Backend — Features & Technology Deep Dive

This document focuses on **what the system does**, **which user pain points it solves**, and **how backend components support those outcomes**.

---

## 1) Product Goal

The backend provides two primary assistants:

1. **College Information RAG Assistant**: answers academic and administrative questions from institutional PDFs.
2. **Result Analysis Assistant**: interprets a student’s result data using official rules/ordinance documents.

The system is designed to reduce manual PDF lookup, improve answer relevance, and deliver responses in a chat-friendly streaming experience.

---

## 2) Pain Points Solved

### A. "I cannot search long policy PDFs quickly"
- PDFs are converted into chunked vectorized knowledge.
- Semantic retrieval brings relevant passages even when question wording differs from document wording.

### B. "Some PDFs are scanned images; text copy does not work"
- Ingestion first tries direct text extraction.
- If text is missing/too weak, OCR fallback is triggered at page level.

### C. "Chatbots hallucinate when context is weak"
- Retrieval happens before generation.
- Context snippets from vector search are fed to the model and sent to UI as `context_used` metadata.

### D. "Result status interpretation is confusing"
- Result analysis combines student marks data (by roll number) with ordinance rule context to generate an interpretable explanation.

### E. "I need quick interaction, not delayed full answer blocks"
- Response is streamed token-by-token.
- Source context is emitted first so frontend can display grounding metadata immediately.

### F. "I need my own chat sessions isolated"
- JWT user identity is enforced server-side.
- Session listing/history is filtered by authenticated user only.

### G. "Deployment should be simple"
- Docker and Docker Compose are supported for reproducible deployment.

---

## 3) Feature Deep Dive

### 3.1 College RAG Chat (`POST /ask`)

#### Input
- `question`: user query
- `session_id`: chat session identity
- JWT bearer token in `Authorization`

#### Backend flow
1. Fetch recent chat memory for this user and session (sliding window).
2. Generate embedding for the new question.
3. Run MongoDB Atlas vector search on collection `pdfs` using index `vector_index`.
4. Build context from top retrieved chunks.
5. Initialize chat model with prior history and system instruction.
6. Stream answer text back to client.
7. Save query + generated response to session store.

#### Output behavior
- First line includes JSON with `context_used` (retrieved snippets + scores).
- Remaining stream is model-generated plain text chunks.

#### User impact
- Better answer relevance from document grounding.
- More responsive UI because of streaming.

---

### 3.2 Result Analysis Assistant (`POST /analyze-result`)

#### Input
- `question`
- `session_id`
- `X-Roll-No` header
- JWT bearer token

#### Backend flow
1. Validate roll number header.
2. Pull recent chat memory for this user/session.
3. Fetch student result payload from external API.
4. Embed query and vector-retrieve rule chunks from collection `result`.
5. Construct prompt with student data + rules context + user query.
6. Stream analysis output.
7. Persist query and analysis in sessions collection.

#### User impact
- Converts raw marks/rule data into understandable decisions or guidance.
- Avoids manual rule matching across long ordinance documents.

---

### 3.3 Session Management and User Isolation

#### Session list (`GET /sessions`)
- Returns user’s sessions with title (first query preview).
- Sorted by last active timestamp.

#### Session history (`GET /history/{session_id}`)
- Returns full ordered message timeline for that session.

#### Security boundaries
- JWT is decoded with `JWT_SECRET`.
- `sub` claim is treated as `user_id`.
- All session queries are filtered by `user_id` and `session_id`.

#### Data lifecycle
- TTL index on `timestamp` supports automatic session record expiry (7 days configured).

---

## 4) PDF Ingestion Pipeline Deep Dive

Ingestion is demonstrated in:
- `./notebooks/ingest.ipynb`
- `./notebooks/result_analysis.ipynb`

Two corpora are prepared separately:
- `clg_pdfs/` → inserted into `pdfs`
- `result_pdfs/` → inserted into `result`

#### 4.1 Extraction

1. Enumerate all `*.pdf` files in the target directory.
2. Open each PDF page-by-page via `pdfplumber`.
3. Attempt standard text extraction.
4. If text is absent/very short, render page image and run OCR (`RapidOCR`).

#### 4.2 Structuring and Metadata

Each page-level document stores:
- `page_content` (text)
- metadata:
  - `source` (PDF filename)
  - `page` (page number)
  - `path` (file path)

This metadata enables source-aware debugging and potential UI citations.

#### 4.3 Chunking Strategy

- Uses `RecursiveCharacterTextSplitter`
- Typical settings in notebooks:
  - `chunk_size`: 1000
  - `chunk_overlap`: 100
  - separator priority for paragraph/line coherence

Why this matters:
- Preserves semantic completeness in each chunk.
- Overlap reduces boundary information loss.

#### 4.4 Embedding Generation

- Model: `gemini-embedding-001`
- Batched embedding requests (e.g., batch size 30)
- Includes throttling strategy:
  - planned cooldown between batches
  - retry wait parsing on 429/rate-limit responses

Why this matters:
- Stable ingestion on free-tier or rate-limited quotas.
- Reduces ingestion failure rate during large imports.

#### 4.5 Storage in MongoDB

Each inserted record contains:
- `text`
- `embedding` (vector)
- `metadata`

Target DB: `rag_pdfs`
Collections:
- `pdfs` (college info corpus)
- `result` (rules/ordinance corpus)

#### 4.6 Vector Indexing

- Search index name: `vector_index`
- Type: `vectorSearch`
- Path: `embedding`
- Similarity: cosine
- Dimensions: 3072 (aligned with `gemini-embedding-001`)

Index readiness is polled before query usage.

---

## 5) Technology Used and Why

### 5.1 FastAPI
- Provides async HTTP endpoints, request validation, and OpenAPI docs.
- Enables clean route design for chat, history, and health flows.

### 5.2 Google Gemini APIs (`google-genai`)
- Embeddings: semantic vector representation for retrieval.
- Generation: response synthesis using retrieved context and session history.
- Streaming API support for incremental response delivery.

### 5.3 MongoDB + Vector Search
- Stores embeddings and supports `$vectorSearch` retrieval.
- Also stores session logs and supports indexing for fast user/session queries.
- TTL index supports lifecycle management for old chat records.

### 5.4 OCR + PDF stack
- `pdfplumber` for direct PDF text extraction.
- `RapidOCR` fallback for scanned/non-selectable text pages.
- Makes ingestion robust across mixed PDF quality.

### 5.5 LangChain text splitter components
- Used in notebooks for consistent chunking behavior.
- Produces retrieval-optimized chunks with overlap.

### 5.6 JWT Authentication (`pyjwt`)
- Validates bearer token and extracts user identity.
- Enforces per-user data isolation in session APIs.

### 5.7 HTTP client (`httpx`)
- Used by result analysis endpoint to fetch roll-number-based student data.

### 5.8 Docker / Docker Compose
- Containerized runtime for backend deployment.
- Simplifies local and production-like environment consistency.

---

## 6) API Surface (Feature-Oriented View)

- `GET /health` — service and DB health check
- `GET /sessions` — list user sessions (auth required)
- `GET /history/{session_id}` — get ordered chat history (auth required)
- `POST /ask` — college RAG Q&A (auth required)
- `POST /analyze-result` — result analysis using roll number + rules corpus (auth + `X-Roll-No`)

---

## 7) Deployment Notes (Docker)

### Required environment variables
- `GEMINI_API_KEY`
- `MONGO_URI`
- `JWT_SECRET`

### Operational defaults
- Session message retention is configured with a MongoDB TTL index at **7 days** (`604800` seconds) on `timestamp`.

### Standard startup
```bash
cp .env.example .env
# fill required variables

docker compose up --build
```

Service:
- API: `http://localhost:8000`
- Docs: `http://localhost:8000/docs`

---

## 8) Operational Reliability Highlights

- OCR fallback for difficult PDFs
- Rate-limit-aware embedding ingestion
- User-scoped session security
- Streaming responses for UX responsiveness
- Source context emission for transparency
- Dockerized runtime for reproducible deployment

---

## 9) Relevant Source Paths

- Backend app: `./src/main.py`
- Ingestion notebook (college corpus): `./notebooks/ingest.ipynb`
- Ingestion notebook (result corpus): `./notebooks/result_analysis.ipynb`
- Compose config: `./docker-compose.yml`
