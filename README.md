# RAG Application

A **Retrieval-Augmented Generation (RAG)** web application that enables users to upload documents and ask natural language questions about their content. Instead of relying only on a Large Language Model's pretrained knowledge, the application retrieves relevant document context and uses it to generate accurate, context-aware responses.

---

## Features

* Document upload and ingestion
* AI-powered question answering over uploaded documents
* Semantic search using vector embeddings
* FAISS-based vector indexing
* Automatic replacement of the previous document index when a new document is uploaded
* OpenRouter as the primary LLM provider
* Groq as the fallback LLM provider
* Health monitoring endpoint
* Simple and responsive user interface built with HTML, CSS, and JavaScript

---

## Tech Stack

### Frontend

* HTML5
* CSS3
* JavaScript (Vanilla)

### Backend

* FastAPI
* Uvicorn

### AI & Retrieval

* FAISS
* sentence-transformers
* all-MiniLM-L6-v2
* OpenRouter
* Groq

### Python Libraries

* NumPy
* Requests
* python-dotenv
* python-docx
* pypdf
* pandas
* openpyxl

---

## How It Works

1. The user uploads a document (PDF, DOCX, XLSX, or CSV).
2. The application extracts text from the uploaded document.
3. The extracted text is split into smaller chunks.
4. Each chunk is converted into embeddings using **sentence-transformers/all-MiniLM-L6-v2**.
5. The embeddings are normalized and stored in a **FAISS** vector index.
6. When the user asks a question, the query is embedded using the same embedding model.
7. FAISS performs semantic similarity search to retrieve the most relevant document chunks.
8. The retrieved context and the user's question are sent to the LLM.
9. **OpenRouter** uses **Mistral 7B Instruct** as the primary model, while **Groq** with **Llama 3.1 8B Instant** serves as the fallback.
10. The generated answer is returned to the user.

---

## API Endpoints

| Method | Endpoint      | Description                               |
| ------ | ------------- | ----------------------------------------- |
| POST   | `/api/ingest` | Upload and process a document             |
| POST   | `/api/ask`    | Ask questions about the uploaded document |
| GET    | `/health`     | Health check endpoint                     |

---

## Installation

```bash
git clone https://github.com/your-username/rag-application.git

cd rag-application

python -m venv venv

# Windows
venv\Scripts\activate

# Linux/macOS
source venv/bin/activate

pip install -r requirements.txt

uvicorn app.main:app --reload
```

Open your browser:

```text
http://127.0.0.1:8000
```

---

## Environment Variables

```env
OPENROUTER_API_KEY=your_openrouter_api_key
OPENROUTER_MODEL=mistralai/mistral-7b-instruct:free

GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=llama-3.1-8b-instant
```

---

## Future Improvements

* Support multiple documents with metadata filtering.
* Integrate a dedicated vector database for large-scale deployments.
* Add cross-encoder reranking.
* Implement streaming responses.
* Add OCR support for scanned PDFs.
* Cache embeddings for improved performance.
* Add monitoring, logging, and evaluation metrics.

---

## License

This project is intended for educational, research, and portfolio purposes.
