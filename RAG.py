import faiss
import os
import pickle
import numpy as np
from sentence_transformers import SentenceTransformer
import torch

device = "cuda" if torch.cuda.is_available() else "cpu"

embed_model = SentenceTransformer("all-MiniLM-L6-v2", device=device)


def _index_paths(user_email: str) -> tuple:
    safe = user_email.replace("@", "_at_").replace(".", "_")
    return f"indexes/{safe}.bin", f"indexes/{safe}.pkl"


def retrieve(query: str, user_email: str, top_k: int = 4) -> tuple:
    """
    Returns (context, avg_score, sources).
    avg_score is in [0, 1] — higher is better.
    Returns ("", 0.0, []) if no index exists or retrieval fails.
    """
    index_file, docs_file = _index_paths(user_email)
    if not os.path.exists(index_file) or not os.path.exists(docs_file):
        return "", 0.0, []

    try:
        index = faiss.read_index(index_file)
        with open(docs_file, "rb") as f:
            docs = pickle.load(f)

        query_embedding = np.array(embed_model.encode([query]), dtype="float32")
        faiss.normalize_L2(query_embedding)
        distances, indices = index.search(query_embedding, min(top_k, index.ntotal))

        chunks = []
        scores = []
        is_ip_index = getattr(index, "metric_type", faiss.METRIC_L2) == faiss.METRIC_INNER_PRODUCT
        for dist, idx in zip(distances[0], indices[0]):
            if idx < len(docs):
                chunks.append(docs[idx])
                if is_ip_index:
                    # Inner product on normalized vectors approximates cosine similarity.
                    scores.append((float(dist) + 1.0) / 2.0)
                else:
                    # Backward-compat path for older L2 indexes.
                    scores.append(1.0 / (1.0 + float(dist)))

        if not chunks:
            return "", 0.0, []

        context   = "\n\n".join(chunks)
        max_score = max(scores)
        return context, max_score, []

    except Exception:
        return "", 0.0, []