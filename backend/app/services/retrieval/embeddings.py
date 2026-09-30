"""
Local embedding generation using Sentence Transformers (all-MiniLM-L6-v2
by default). Model is loaded lazily and once per process.

Embeddings are stored as comma-separated floats in SQLite (Project.embedding)
rather than a dedicated vector DB — this keeps the system CPU-only and
dependency-light, per spec section 30. Swapping in FAISS later only
requires changing `similarity_search` below.
"""
from functools import lru_cache
from typing import List
import numpy as np

from app.config import settings


@lru_cache(maxsize=1)
def _get_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(settings.EMBEDDING_MODEL)


def embed_text(text: str) -> np.ndarray:
    model = _get_model()
    vec = model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
    return vec


def embedding_to_str(vec: np.ndarray) -> str:
    return ",".join(f"{x:.6f}" for x in vec)


def str_to_embedding(s: str) -> np.ndarray:
    return np.array([float(x) for x in s.split(",")], dtype=np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    # Vectors are already normalized at encode time, so dot product = cosine.
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)
