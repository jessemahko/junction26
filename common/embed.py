"""bge-m3 query embeddings on CPU, for the worklist's semantic search.

The same model as dataset S's article vectors and lang_sentence (BAAI/bge-m3, dense, normalised), so a
query vector can be compared with them by VEC_DISTANCE_COSINE. Loaded once, lazily (about 10 s), from
the local Hugging Face cache only: no network calls from the server. warm() loads it in the background
at startup so the first search does not wait.
"""
from __future__ import annotations

import os
import threading

MODEL = "BAAI/bge-m3"
_model = None
_lock = threading.Lock()


def _load():
    global _model
    with _lock:
        if _model is None:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")      # the model is in the local cache
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer(MODEL, device="cpu")
    return _model


def warm() -> None:
    threading.Thread(target=_load, daemon=True, name="bge-m3-warm").start()


def ready() -> bool:
    return _model is not None


def embed(text: str) -> bytes:
    """The query's bge-m3 vector as MariaDB's VECTOR binary format (1024 little-endian float32)."""
    v = _load().encode([text], normalize_embeddings=True, show_progress_bar=False)[0]
    return v.astype("<f4").tobytes()
