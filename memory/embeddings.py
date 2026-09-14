"""Semantic search over the memory store — meaning, not just matching words.

THE PROBLEM THIS SOLVES
search_memory() scores by word overlap. Ask "who is my sister?" when the store
holds `relationships/ayse: older sister` and it scores zero: the question and
the answer share no words. Every fact whose wording the user does not happen to
reproduce is effectively lost.

WHY fastembed AND NOT sentence-transformers
Same model — all-MiniLM-L6-v2 — but fastembed runs it through ONNX rather than
PyTorch: about 50 MB instead of roughly 2 GB, and it imports in milliseconds. On
an assistant that is supposed to answer within a second of being spoken to, a
multi-second import at startup is not a detail.

THREE RULES THIS MODULE FOLLOWS
1. It never blocks startup. The model loads on a background thread the first
   time it is needed; until it is ready, callers get None and fall back to the
   existing lexical search.
2. It never breaks the assistant. fastembed missing, model download failing,
   cache corrupt — every path returns None or an empty result. A memory search
   that degrades is an inconvenience; one that raises stops JARVIS answering.
3. It touches nothing that already exists. Its own cache file, its own module.
   memory/vector_db/ and anything else already in memory/ is left alone.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
from pathlib import Path

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

_BASE_DIR   = Path(__file__).resolve().parent
_CACHE_PATH = _BASE_DIR / "embeddings_cache.json"

# Loading state. The lock guards the handle; the flag stops a failed load from
# being retried on every single search.
_model        = None
_model_lock   = threading.Lock()
_load_started = False
_load_failed  = False

_cache: dict[str, list[float]] | None = None
_cache_dirty = False


# ── Model ─────────────────────────────────────────────────────────────────────

def _load_model() -> None:
    global _model, _load_failed
    try:
        import time as _time
        from fastembed import TextEmbedding

        # Say something BEFORE the slow part. The first run downloads ~50 MB and
        # can take minutes; with no line here the log is simply silent, which
        # looks identical to the feature not being installed at all.
        print("[Memory] Loading semantic search model "
              "(first run downloads ~50 MB — keyword search works meanwhile)...")
        t0 = _time.monotonic()

        model = TextEmbedding(model_name=MODEL_NAME)
        with _model_lock:
            _model = model
        print(f"[Memory] 🧠 Semantic search ready ({_time.monotonic() - t0:.1f}s).")
    except ImportError:
        _load_failed = True
        print("[Memory] Semantic search unavailable (fastembed not installed) — "
              "keyword search still works. Enable with: pip install fastembed")
    except Exception as e:
        _load_failed = True
        print(f"[Memory] Semantic search unavailable ({e}) — keyword search still works.")


def start_loading() -> None:
    """Begin loading in the background. Safe to call repeatedly; call it once at
    startup so the first real search does not pay for the model."""
    global _load_started
    with _model_lock:
        if _load_started or _load_failed:
            return
        _load_started = True
    threading.Thread(target=_load_model, daemon=True, name="embeddings").start()


def is_ready() -> bool:
    with _model_lock:
        return _model is not None


def _embed(texts: list[str]) -> list[list[float]] | None:
    """Vectors for these texts, or None if the model is not available."""
    with _model_lock:
        model = _model
    if model is None or not texts:
        return None
    try:
        return [list(map(float, v)) for v in model.embed(texts)]
    except Exception as e:
        print(f"[Memory] Embedding failed: {e}")
        return None


# ── Cache ─────────────────────────────────────────────────────────────────────

def _key(text: str) -> str:
    """Content hash, so an edited fact is re-embedded and an unchanged one is
    never paid for twice."""
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:16]


def _load_cache() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    try:
        _cache = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        if not isinstance(_cache, dict):
            _cache = {}
    except Exception:
        _cache = {}
    return _cache


def save_cache() -> None:
    global _cache_dirty
    if not _cache_dirty or _cache is None:
        return
    try:
        _CACHE_PATH.write_text(json.dumps(_cache), encoding="utf-8")
        _cache_dirty = False
    except Exception as e:
        print(f"[Memory] Could not save embedding cache: {e}")


def _vectors_for(texts: list[str]) -> dict[str, list[float]] | None:
    """Vectors for these texts, reusing the cache and embedding only what is new."""
    global _cache_dirty
    cache   = _load_cache()
    missing = [t for t in texts if _key(t) not in cache]

    if missing:
        fresh = _embed(missing)
        if fresh is None:
            # Model not ready. Anything already cached is still usable.
            return {t: cache[_key(t)] for t in texts if _key(t) in cache} or None
        for text, vec in zip(missing, fresh):
            cache[_key(text)] = vec
        _cache_dirty = True

    return {t: cache[_key(t)] for t in texts if _key(t) in cache}


# ── Similarity ────────────────────────────────────────────────────────────────

def _cosine(a: list[float], b: list[float]) -> float:
    try:
        dot = sum(x * y for x, y in zip(a, b))
        na  = math.sqrt(sum(x * x for x in a))
        nb  = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0
    except Exception:
        return 0.0


def rank(query: str, documents: list[str]) -> dict[str, float] | None:
    """Similarity of each document to the query, 0..1.

    Returns None when semantic search is unavailable — callers must treat that
    as "use the lexical score alone", never as an error."""
    if not query or not documents:
        return None
    if not is_ready():
        start_loading()          # warm it for next time
        return None

    q = _embed([query])
    if not q:
        return None
    vectors = _vectors_for(documents)
    if not vectors:
        return None

    scores = {doc: _cosine(q[0], vec) for doc, vec in vectors.items()}
    save_cache()
    return scores
