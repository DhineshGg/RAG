import faiss
import io
import os
import pickle
import numpy as np
from sentence_transformers import SentenceTransformer
from pypdf import PdfReader
from docx import Document
import pandas as pd

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100

embed_model = SentenceTransformer("all-MiniLM-L6-v2")


def _index_paths(user_email: str) -> tuple:
    safe = user_email.replace("@", "_at_").replace(".", "_")
    os.makedirs("indexes", exist_ok=True)
    return f"indexes/{safe}.bin", f"indexes/{safe}.pkl"


def chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap

    return chunks


def read_txt(file_bytes):
    return file_bytes.decode("utf-8", errors="replace")


def read_pdf(file_bytes):
    reader = PdfReader(io.BytesIO(file_bytes))
    return "".join(page.extract_text() or "" for page in reader.pages)


def read_docx(file_bytes):
    doc = Document(io.BytesIO(file_bytes))
    return "\n".join(p.text for p in doc.paragraphs)


def read_csv(file_bytes):
    df = pd.read_csv(io.BytesIO(file_bytes))
    return df.to_string()


def ingest_file(file_name: str, file_bytes: bytes, user_email: str) -> int:
    extension = file_name.rsplit(".", 1)[-1].lower()

    if extension in ["txt", "md"]:
        text = read_txt(file_bytes)
    elif extension == "pdf":
        text = read_pdf(file_bytes)
    elif extension == "docx":
        text = read_docx(file_bytes)
    elif extension == "csv":
        text = read_csv(file_bytes)
    else:
        raise ValueError(f"Unsupported file type: {extension}")

    text = text.strip()
    if not text:
        raise ValueError("Could not extract readable text from this file.")

    chunks = chunk_text(text)
    embeddings = np.array(embed_model.encode(chunks), dtype="float32")
    faiss.normalize_L2(embeddings)

    index_file, docs_file = _index_paths(user_email)

    try:
        index = faiss.read_index(index_file)
        with open(docs_file, "rb") as f:
            existing_docs = pickle.load(f)

        # Migrate older L2 indexes to normalized cosine retrieval (IndexFlatIP).
        if getattr(index, "metric_type", faiss.METRIC_L2) != faiss.METRIC_INNER_PRODUCT:
            all_docs = existing_docs + chunks
            all_embeddings = np.array(embed_model.encode(all_docs), dtype="float32")
            faiss.normalize_L2(all_embeddings)
            index = faiss.IndexFlatIP(all_embeddings.shape[1])
            index.add(all_embeddings)

            faiss.write_index(index, index_file)
            with open(docs_file, "wb") as f:
                pickle.dump(all_docs, f)
            return len(chunks)
    except Exception:
        index = faiss.IndexFlatIP(embeddings.shape[1])
        existing_docs = []

    index.add(embeddings)
    faiss.write_index(index, index_file)
    with open(docs_file, "wb") as f:
        pickle.dump(existing_docs + chunks, f)

    return len(chunks)