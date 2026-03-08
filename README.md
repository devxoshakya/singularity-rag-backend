# RAGBot - College Document RAG API

A FastAPI-based RAG (Retrieval-Augmented Generation) system for college document analysis using Google Gemini and MongoDB vector search.

## Features

- 🤖 **RAG System**: Intelligent document retrieval and response generation
- 📚 **PDF Processing**: Handles college documents and ordinances
- 🔍 **Vector Search**: MongoDB-powered semantic search
- 🚀 **FastAPI**: Modern, fast web API framework
- 🐳 **Docker Ready**: Containerized for easy deployment

## Quick Start with Docker

### Prerequisites

- Docker and Docker Compose installed
- Google Gemini API key

### Setup

1. **Clone the repository**
   ```bash
   git clone <your-repo-url>
   cd ragbot
   ```

2. **Set up environment variables**
   ```bash
   cp .env.example .env
   # Edit .env and add your GEMINI_API_KEY
   ```

3. **Run with Docker Compose**
   ```bash
   docker-compose up --build
   ```

The API will be available at `http://localhost:8000`

### API Documentation

Visit `http://localhost:8000/docs` for interactive API documentation.

## API Endpoints

### 1. Health Check
```
GET /health
```
Returns the health status of the application and database connection.

### 2. Ask Questions
```
POST /ask
```
Query the document collection with natural language questions.

**Request Body:**
```json
{
  "question": "What are the eligibility criteria for B.Tech?"
}
```

### 3. Analyze Results
```
POST /analyze-result
```
Analyze student data against university rules for Pass/Fail/PWG determination.

**Request Body:**
```json
{
  "question": "Analyze eligibility for student with CGPA 7.5"
}
```

## Development

### Local Development Setup

1. **Install dependencies**
   ```bash
   pip install uv
   uv sync
   ```

2. **Set up MongoDB**
   ```bash
   # Using Docker
   docker run -d -p 27017:27017 --name ragbot-mongodb mongo:7.0
   ```

3. **Set environment variables**
   ```bash
   export GEMINI_API_KEY=your_key_here
   export MONGO_URI=mongodb://localhost:27017/rag_pdfs
   ```

4. **Run the application**
   ```bash
   uv run uvicorn src.main:app --reload
   ```

### Docker Commands

**Build the Docker image:**
```bash
docker build -t ragbot .
```

**Run with custom environment:**
```bash
docker run -p 8000:8000 \
  -e GEMINI_API_KEY=your_key \
  -e MONGO_URI=mongodb://host.docker.internal:27017/rag_pdfs \
  ragbot
```

**Run development environment:**
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

## Project Structure

```
ragbot/
├── src/
│   └── main.py              # FastAPI application
├── clg_pdfs/               # College PDF documents
├── result_pdfs/            # Result analysis PDFs
├── notebooks/              # Jupyter notebooks for development
├── Dockerfile              # Docker image configuration
├── docker-compose.yml      # Multi-container setup
├── pyproject.toml         # Python dependencies
└── requirements.txt       # Alternative dependency file
```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `GEMINI_API_KEY` | Google Gemini API key | Yes |
| `MONGO_URI` | MongoDB connection string | Yes |

## Troubleshooting

### Common Issues

1. **MongoDB Connection Failed**
   - Ensure MongoDB is running
   - Check the `MONGO_URI` environment variable
   - For Docker: use service name `mongodb` instead of `localhost`

2. **Gemini API Errors**
   - Verify your `GEMINI_API_KEY` is correct
   - Check API quota and billing

3. **Port Already in Use**
   ```bash
   # Change port in docker-compose.yml or stop conflicting service
   docker-compose down
   sudo lsof -i :8000
   ```

### Logs

**View application logs:**
```bash
docker-compose logs -f ragbot
```

**View MongoDB logs:**
```bash
docker-compose logs -f mongodb
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test with Docker
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.
