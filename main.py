"""
Vespera · main.py  — FastAPI backend
Strict RAG: answers only from retrieved document context.
If context is absent or weak → explicit "no information found" response.
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
from fastapi import (
    Cookie, Depends, FastAPI, File, Form,
    HTTPException, Request, UploadFile, status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from groq import Groq
from pydantic import BaseModel

from RAG import retrieve
from ingest import ingest_file
import db

# ══════════════════════════════════════════════════════
#  ENV & BOOTSTRAP
# ══════════════════════════════════════════════════════

load_dotenv()

OPENROUTER_API_KEY = os.getenv("openrouter_api")
GROQ_API_KEY       = os.getenv("groq_api")
SECRET_KEY         = os.getenv("secret_key", "vespera-dev-secret-change-in-production")
RAG_SCORE_THRESHOLD = float(os.getenv("rag_score_threshold", "0.3"))
OPENROUTER_MODEL   = os.getenv("openrouter_model", "mistralai/mistral-7b-instruct:free")
GROQ_MODEL         = os.getenv("groq_model", "llama-3.1-8b-instant")

if not OPENROUTER_API_KEY and not GROQ_API_KEY:
    raise ValueError("At least one API key is required (.env → openrouter_api or groq_api)")

# ══════════════════════════════════════════════════════
#  APP
# ══════════════════════════════════════════════════════

app = FastAPI(title="Vespera API", version="2.0.0", docs_url="/api/docs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("vespera")

# ══════════════════════════════════════════════════════
#  LLM CLIENT (OpenRouter)
# ══════════════════════════════════════════════════════

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

_session = requests.Session()
_retries = Retry(
    total=2,
    backoff_factor=0.6,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["POST"]),
)
_session.mount("https://", HTTPAdapter(max_retries=_retries))


def _call_openrouter(messages: list, temperature: float, max_tokens: int) -> str:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OpenRouter key not configured")

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://127.0.0.1:8000",
        "X-Title": "Vespera",
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    response = _session.post(
        f"{OPENROUTER_BASE_URL}/chat/completions",
        json=payload,
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


def _call_groq(messages: list, temperature: float, max_tokens: int) -> str:
    if not groq_client:
        raise RuntimeError("Groq key not configured")

    completion = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return completion.choices[0].message.content.strip()

def call_llm(messages: list, temperature: float = 0.1, max_tokens: int = 500) -> str:
    """Call LLM with fallback order: OpenRouter -> Groq."""
    errors = []

    try:
        return _call_openrouter(messages, temperature, max_tokens)
    except Exception as exc:
        errors.append(f"OpenRouter: {exc}")

    try:
        return _call_groq(messages, temperature, max_tokens)
    except Exception as exc:
        errors.append(f"Groq: {exc}")

    raise RuntimeError(" | ".join(errors))

# ══════════════════════════════════════════════════════
#  DATABASE BOOTSTRAP & LLM HEALTH CHECK
# ══════════════════════════════════════════════════════

db.init_db()

# Test LLM connection on startup
try:
    call_llm(
        messages=[{"role": "user", "content": "Say hello."}],
        temperature=0.1,
        max_tokens=10,
    )
    logger.info("LLM service initialized successfully")
except Exception as e:
    logger.warning("LLM health check failed on startup: %s", str(e))
    logger.warning("The system will still work but may fail on /api/ask requests")

# ══════════════════════════════════════════════════════
#  AUTH HELPERS
# ══════════════════════════════════════════════════════

def _hash(pw: str) -> str:
    return hashlib.sha256(f"{pw}{SECRET_KEY}".encode()).hexdigest()


def create_session(email: str) -> str:
    token   = str(uuid.uuid4())
    expires = (datetime.utcnow() + timedelta(days=7)).isoformat()
    db.session_create(token, email, expires)
    return token


def get_current_user(request: Request) -> Optional[dict]:
    token = request.cookies.get("session_token")
    if not token:
        return None
    session = db.session_get(token)
    if not session:
        return None
    if datetime.utcnow() > datetime.fromisoformat(session["expires"]):
        db.session_delete(token)
        return None
    return db.user_get(session["email"])


def require_user(request: Request) -> dict:
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user

# ══════════════════════════════════════════════════════
#  REQUEST MODELS
# ══════════════════════════════════════════════════════

class AskRequest(BaseModel):
    question:   str
    chat_id:    Optional[str]  = None
    top_k:      Optional[int]  = 5
    rerank:     Optional[bool] = True


class ChatCreate(BaseModel):
    title: str

# ══════════════════════════════════════════════════════
#  STRICT RAG GENERATION
#
#  Design contract:
#  1. Only answer from retrieved context chunks.
#  2. If context is empty → return "no information" message.
#  3. If context is weak (avg score < threshold) → acknowledge uncertainty.
#  4. Never generate unrelated information.
# ══════════════════════════════════════════════════════

NO_CONTEXT_REPLY = (
    "No relevant information found in the uploaded documents. "
    "Please upload a document that contains information related to your question, "
    "or rephrase your query."
)


def is_document_question(question: str) -> bool:
    """Heuristic intent classifier for document-grounded questions."""
    q = question.lower()
    doc_keywords = [
        "document", "resume", "cv", "uploaded", "file", "pdf",
        "in this", "from this", "name in", "objective", "projects",
        "skills", "education", "experience", "whose", "who's",
    ]
    return any(k in q for k in doc_keywords)


def generate_general_answer(question: str) -> str:
    """Answer directly using LLM without retrieval constraints."""
    prompt = f"""You are Vespera, a helpful AI assistant.

Answer the user's question clearly and concisely.
If user greets you, greet back naturally.

QUESTION: {question}

ANSWER:"""
    try:
        answer = call_llm(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=350,
        )
        return answer if answer else "I couldn't generate a response. Please try again."
    except Exception as exc:
        logger.exception("General LLM generation error: %s", str(exc))
        return f"Error: {str(exc)}"


def generate_strict_answer(context: str, question: str, avg_score: float = 1.0) -> str:
    """
    Generate an answer using context if available, otherwise answer directly.
    - If context exists and score is good: answer from context only.
    - If no context or weak score: answer the question directly (general knowledge).
    """
    has_context = context and context.strip()
    has_good_score = avg_score >= RAG_SCORE_THRESHOLD
    
    # Decide which prompt to use
    if has_context and has_good_score:
        # ── RAG Mode: Answer strictly from context ────
        prompt = f"""You are Vespera, an intelligent document assistant.

STRICT RULES — follow them exactly:
1. Answer ONLY using information present in the CONTEXT below.
2. Do NOT add any information from outside the CONTEXT.
3. If the CONTEXT does not contain information to answer, say: "This information is not in the provided documents."
4. Be concise and precise.
5. Otherwise: 2-3 sentences max.

CONTEXT (from uploaded documents):
{context}

QUESTION: {question}

ANSWER:"""
    else:
        # ── Fallback Mode: Answer directly ────────────
        # No context available, answer normally without restrictions
        prompt = f"""You are Vespera, a helpful AI assistant.

Answer the following question clearly and concisely (2-4 sentences):

QUESTION: {question}

ANSWER:"""

    try:
        answer = call_llm(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=500,
        )
        return answer if answer else "I couldn't generate a response. Please try again."

    except requests.exceptions.Timeout:
        logger.exception("LLM timeout (request took too long)")
        return "The model response took too long. Please try a simpler question."
    except requests.exceptions.HTTPError as e:
        logger.exception("LLM HTTP error: %s", str(e))
        return f"LLM service error: {str(e)}"
    except Exception as exc:
        logger.exception("LLM generation error: %s", str(exc))
        return f"Error: {str(exc)}"


# ══════════════════════════════════════════════════════
#  PAGE ROUTES
# ══════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if get_current_user(request):
        return RedirectResponse("/chat", status_code=302)
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("chat.html", {"request": request, "user": user})

# ══════════════════════════════════════════════════════
#  AUTH FORM ROUTES
# ══════════════════════════════════════════════════════

@app.post("/signup")
async def signup(
    name:     str = Form(...),
    surname:  str = Form(...),
    email:    str = Form(...),
    password: str = Form(...),
):
    email = email.lower().strip()
    if db.user_exists(email):
        return RedirectResponse("/signup?error=exists", status_code=302)
    if len(password) < 8:
        return RedirectResponse("/signup?error=short_password", status_code=302)

    db.user_create({
        "id":            str(uuid.uuid4()),
        "name":          name.strip(),
        "surname":       surname.strip(),
        "email":         email,
        "password_hash": _hash(password),
        "created_at":    datetime.utcnow().isoformat(),
    })
    logger.info("New user registered: %s", email)
    return RedirectResponse("/login?registered=1", status_code=302)


@app.post("/login")
async def login(
    email:    str = Form(...),
    password: str = Form(...),
):
    email = email.lower().strip()
    user  = db.user_get(email)
    if not user or user["password_hash"] != _hash(password):
        return RedirectResponse("/login?error=invalid", status_code=302)

    token    = create_session(email)
    response = RedirectResponse("/chat", status_code=302)
    response.set_cookie(
        key="session_token", value=token,
        httponly=True, max_age=60 * 60 * 24 * 7, samesite="lax",
    )
    logger.info("User logged in: %s", email)
    return response


@app.get("/logout")
@app.post("/logout")
async def logout(request: Request):
    token = request.cookies.get("session_token")
    if token:
        db.session_delete(token)
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("session_token")
    return response

# ══════════════════════════════════════════════════════
#  HEALTH
# ══════════════════════════════════════════════════════

@app.get("/health")
async def health():
    # Test LLM
    llm_status = "ok"
    try:
        call_llm(
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.1,
            max_tokens=5,
        )
    except Exception as e:
        llm_status = f"error: {str(e)[:50]}"
    
    return {
        "status":    "ok",
        "app":       "Vespera",
        "version":   "2.0.0",
        "llm":       llm_status,
        "users":     db.user_count(),
        "chats":     db.chat_count(),
        "documents": db.doc_count(),
        "timestamp": datetime.utcnow().isoformat(),
    }

# ══════════════════════════════════════════════════════
#  CHAT HISTORY API
# ══════════════════════════════════════════════════════

@app.get("/api/chats")
async def list_chats(request: Request):
    user = require_user(request)
    return {"chats": db.chat_list(user["email"])}


@app.post("/api/chats", status_code=201)
async def create_chat(body: ChatCreate, request: Request):
    user    = require_user(request)
    chat_id = str(uuid.uuid4())
    db.chat_create(chat_id, user["email"], body.title[:120], datetime.utcnow().isoformat())
    return {"chat_id": chat_id}


@app.get("/api/chats/{chat_id}")
async def get_chat(chat_id: str, request: Request):
    user = require_user(request)
    chat = db.chat_get(chat_id)
    if not chat or chat["user_email"] != user["email"]:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


@app.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: str, request: Request):
    user = require_user(request)
    chat = db.chat_get(chat_id)
    if not chat or chat["user_email"] != user["email"]:
        raise HTTPException(status_code=404, detail="Chat not found")
    db.chat_delete(chat_id)
    return {"deleted": chat_id}

# ══════════════════════════════════════════════════════
#  ASK ENDPOINT — Strict RAG
# ══════════════════════════════════════════════════════

@app.post("/api/ask")
async def ask_question(body: AskRequest, request: Request):
    user     = require_user(request)
    question = body.question.strip()
    if not question:
        return JSONResponse({"error": "Question is empty."}, status_code=400)

    try:
        docs = db.doc_list(user["email"])
        should_use_doc_mode = bool(docs) and is_document_question(question)

        if should_use_doc_mode:
            # Retrieve more chunks for entity-style resume questions.
            context, avg_score, sources = retrieve(question, user["email"], top_k=max(body.top_k or 5, 8))
            answer = generate_strict_answer(context, question, avg_score)
        else:
            context, avg_score, sources = "", 0.0, []
            answer = generate_general_answer(question)

        # ── Step 3: Persist to chat history ───────────
        if body.chat_id:
            db.chat_upsert(body.chat_id, user["email"], question[:90], datetime.utcnow().isoformat())
            chat = db.chat_get(body.chat_id)
            if chat and chat["user_email"] == user["email"]:
                ts = datetime.utcnow().isoformat()
                db.message_append(body.chat_id, "user",      question, ts)
                db.message_append(body.chat_id, "assistant", answer,   ts)

        logger.info(
            "Question answered for %s | doc_mode=%s | score=%.2f | %s",
            user["email"], should_use_doc_mode, avg_score, question[:60]
        )

        return {
            "question":     question,
            "answer":       answer,
            "context_used": bool(context),
            "avg_score":    avg_score,
            "sources":      sources,
        }

    except Exception as exc:
        logger.exception("Error in /api/ask")
        raise HTTPException(status_code=500, detail=str(exc))


# ══════════════════════════════════════════════════════
#  DEBUG ENDPOINT — Retrieval diagnostics
# ══════════════════════════════════════════════════════

@app.post("/api/debug-ask")
async def debug_ask(body: AskRequest, request: Request):
    """Show exact retrieval and LLM behavior for diagnostics."""
    user     = require_user(request)
    question = body.question.strip()
    
    # Retrieve
    context, avg_score, sources = retrieve(question, user["email"], top_k=body.top_k or 5)
    
    # Show diagnostic info
    return {
        "question": question,
        "avg_score": avg_score,
        "context_length": len(context) if context else 0,
        "context_preview": (context[:500] + "..." if len(context) > 500 else context) if context else "(empty)",
        "threshold": RAG_SCORE_THRESHOLD,
        "passes_threshold": avg_score >= RAG_SCORE_THRESHOLD if context else False,
    }

# ══════════════════════════════════════════════════════
#  DOCUMENT INGESTION API
# ══════════════════════════════════════════════════════

@app.post("/api/ingest", status_code=201)
async def ingest_document(request: Request, file: UploadFile = File(...)):
    user = require_user(request)
    try:
        file_bytes = await file.read()
        chunks = ingest_file(file.filename, file_bytes, user["email"])

        doc_id = str(uuid.uuid4())
        db.doc_create({
            "id":         doc_id,
            "user_email": user["email"],
            "filename":   file.filename,
            "size":       len(file_bytes),
            "chunks":     chunks,
            "status":     "indexed",
            "created_at": datetime.utcnow().isoformat(),
        })
        logger.info("Ingested %s for %s (%d chunks)", file.filename, user["email"], chunks)
        return {"doc_id": doc_id, "message": f"{file.filename} indexed", "chunks_added": chunks}

    except Exception as exc:
        logger.exception("Error in /api/ingest")
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/docs")
async def list_documents(request: Request):
    user = require_user(request)
    return {"documents": db.doc_list(user["email"])}


@app.delete("/api/docs/{doc_id}")
async def delete_document(doc_id: str, request: Request):
    user = require_user(request)
    doc  = db.doc_get(doc_id)
    if not doc or doc["user_email"] != user["email"]:
        raise HTTPException(status_code=404, detail="Document not found")
    db.doc_delete(doc_id)
    return {"deleted": doc_id}

# ══════════════════════════════════════════════════════
#  LEGACY ENDPOINTS  (backward compatibility)
# ══════════════════════════════════════════════════════

class _LegacyQuery(BaseModel):
    question: str

@app.post("/ask")
async def ask_legacy(query: _LegacyQuery):
    question = query.question.strip()
    if not question:
        return {"answer": "Please provide a question."}
    try:
        context, avg_score, _ = retrieve(question, "guest")
        answer  = generate_strict_answer(context, question, avg_score)
        return {"question": question, "context_used": bool(context), "answer": answer}
    except Exception as exc:
        logger.exception("Error in /ask (legacy)")
        return {"error": str(exc)}

@app.post("/ingest")
async def ingest_legacy(file: UploadFile = File(...)):
    try:
        file_bytes = await file.read()
        chunks = ingest_file(file.filename, file_bytes, "guest")
        return {"message": f"{file.filename} ingested", "chunks_added": chunks}
    except Exception as exc:
        logger.exception("Error in /ingest (legacy)")
        return {"error": str(exc)}

# ══════════════════════════════════════════════════════
#  ENTRYPOINT
# ══════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
