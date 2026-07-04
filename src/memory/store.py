"""Shared memory store for agent handoff.

Two flavors of storage:

1. **Structured KV memory** — `get(key)` / `put(key, value)` for explicit
   agent handoff. Examples of keys: `topics`, `constraints`, `stories`,
   `epics`, `gaps`, `conflicts`, `duplicates`, `existing_tickets`.

2. **Vector memory** — `index_tickets()` / `search_similar()` for semantic
   lookup. Used by the Gap Detector to find candidate JIRA/GitHub tickets
   that look semantically similar to a new story before LLM reranking.

The vector layer supports three backends (selected by env vars):

  - **ChromaDB** (USE_CHROMADB=1): persistent, multi-replica-safe, file-backed
    ChromaDB collection. Data survives process restarts and is shared across
    all replicas that mount the same volume. Best for production deployments.
    Collection path: `.cache/memory/chroma/`.
  - **NPZ file cache** (MEMORY_PERSISTENT=1, default persistent mode): stores
    embeddings in `.cache/memory/<corpus_hash>.npz`. Single-process, fast.
    Right for single-host deployments and development.
  - **in-process** (default): numpy + sentence-transformers, no persistence.
    Right for unit tests, dry runs, and short-lived demo runs.

A simple .json file under `.cache/memory/kv/<key>.json` is also written for
each `put()` when persistence is on, so a follow-up run can hydrate the
last orchestrator's state for inspection / replay.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any

from logger_setup import get_logger

logger = get_logger(__name__)

_RETRIEVAL_THRESHOLD = 20  # Below this, skip embeddings and return everything.
_DEFAULT_CACHE_DIR = Path(".cache") / "memory"
_EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# ---- Process-level embedder singleton ----------------------------------------
# The sentence-transformer model takes ~300ms to load on a CPU-only container.
# Loading it once and reusing the instance across all MemoryStore objects avoids
# blocking every new run that needs duplicate detection.
_EMBEDDER_SINGLETON: Any = None
_EMBEDDER_LOCK = threading.Lock()


def _get_embedder() -> Any:
    """Return the shared SentenceTransformer instance, loading it once."""
    global _EMBEDDER_SINGLETON
    if _EMBEDDER_SINGLETON is None:
        with _EMBEDDER_LOCK:
            if _EMBEDDER_SINGLETON is None:
                from sentence_transformers import SentenceTransformer
                logger.info("Loading embedding model %s …", _EMBEDDING_MODEL)
                _EMBEDDER_SINGLETON = SentenceTransformer(_EMBEDDING_MODEL)
                logger.info("Embedding model loaded")
    return _EMBEDDER_SINGLETON


def preload_embedder() -> None:
    """Warm up the embedding model in a daemon background thread.

    Call once at process start (e.g. right after start_metrics_server() in
    app.py) so the first synthesis that needs duplicate detection does not
    pay the 300ms load cost inline.
    """
    threading.Thread(
        target=_get_embedder,
        daemon=True,
        name="embedder-preload",
    ).start()


class MemoryStore:
    """KV + vector store. Optionally persists to disk across runs."""

    def __init__(
        self,
        *,
        persistent: bool | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self._kv: dict[str, Any] = {}
        self._written_keys: set[str] = set()  # tracks keys written via put()/append()
        self._embedder = None  # Lazy-loaded sentence-transformer
        self._np = None
        self._ticket_vectors = None
        self._tickets_for_vectors: list[dict] = []
        self._chroma_collection = None  # ChromaDB collection (when USE_CHROMADB=1)

        if persistent is None:
            persistent = os.environ.get("MEMORY_PERSISTENT", "").lower() in ("1", "true", "yes")
        self._persistent = bool(persistent)
        self._use_chromadb = os.environ.get("USE_CHROMADB", "").lower() in ("1", "true", "yes")
        self._cache_dir = Path(cache_dir) if cache_dir else _DEFAULT_CACHE_DIR
        if self._persistent or self._use_chromadb:
            (self._cache_dir / "kv").mkdir(parents=True, exist_ok=True)
            (self._cache_dir / "vectors").mkdir(parents=True, exist_ok=True)
        if self._use_chromadb:
            self._init_chromadb()

    # ----------------------------------------------------- KV interface

    def get(self, key: str, default: Any = None) -> Any:
        return self._kv.get(key, default)

    def put(self, key: str, value: Any) -> None:
        self._kv[key] = value
        self._written_keys.add(key)
        if self._persistent:
            self._persist_kv(key, value)

    def append(self, key: str, value: Any) -> None:
        """Append to a list at `key`. Creates the list if missing."""
        if key not in self._kv:
            self._kv[key] = []
        self._kv[key].append(value)
        self._written_keys.add(key)
        if self._persistent:
            self._persist_kv(key, self._kv[key])

    def all_keys(self) -> set[str]:
        """Return the set of all keys currently held in the KV store."""
        return set(self._kv.keys())

    # ----------------------------------------------------- KV persistence

    def _persist_kv(self, key: str, value: Any) -> None:
        path = self._cache_dir / "kv" / f"{key}.json"
        try:
            path.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")
        except (TypeError, OSError) as e:
            logger.warning("Could not persist KV key %r: %s", key, e)

    def hydrate_from_disk(self) -> int:
        """Reload KV state from `<cache_dir>/kv/*.json`. Returns count loaded.

        Useful when a follow-up process wants to inspect the last run's
        memory contents without re-running the pipeline. Has no effect when
        persistence wasn't enabled at the time of the previous run.
        """
        kv_dir = self._cache_dir / "kv"
        if not kv_dir.exists():
            return 0
        count = 0
        for f in kv_dir.glob("*.json"):
            try:
                self._kv[f.stem] = json.loads(f.read_text(encoding="utf-8"))
                count += 1
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Skipping KV cache %s: %s", f.name, e)
        return count

    # ----------------------------------------------------- ChromaDB backend

    def _init_chromadb(self) -> None:
        """Initialise a ChromaDB client + collection.

        Two modes:
        - CHROMADB_SERVER_URL set → HttpClient pointing at an external Chroma
          server (can be made HA with multiple replicas behind a load balancer).
          This eliminates the single-volume SPOF.
        - Unset (default) → PersistentClient backed by a local directory.
          Fast and zero-config for single-pod deployments; a volume failure
          loses the index (recoverable by re-running index_tickets on the
          next synthesis).
        """
        _server_url = os.environ.get("CHROMADB_SERVER_URL", "").strip()
        try:
            import chromadb
            if _server_url:
                # External HA server — parse host/port from the URL.
                # Expected format: http[s]://host:port  (port defaults to 8000)
                from urllib.parse import urlparse
                _parsed = urlparse(_server_url)
                _host = _parsed.hostname or "localhost"
                _port = _parsed.port or 8000
                _ssl  = _parsed.scheme == "https"
                client = chromadb.HttpClient(host=_host, port=_port, ssl=_ssl)
                client.heartbeat()  # fail fast if unreachable at startup
                logger.info("ChromaDB HttpClient connected to %s", _server_url)
            else:
                chroma_path = str(self._cache_dir / "chroma")
                client = chromadb.PersistentClient(path=chroma_path)
                logger.info(
                    "ChromaDB PersistentClient ready at %s "
                    "(single-volume — set CHROMADB_SERVER_URL for HA)",
                    chroma_path,
                )
            self._chroma_collection = client.get_or_create_collection(
                name="backlog_tickets",
                metadata={"hnsw:space": "cosine"},
            )
        except ImportError:
            logger.warning("chromadb not installed — falling back to NPZ vector cache")
            self._use_chromadb = False
        except Exception as e:  # noqa: BLE001
            logger.warning("ChromaDB init failed (%s) — falling back to NPZ cache", e)
            self._use_chromadb = False

    def _chroma_index(self, tickets: list[dict]) -> bool:
        """Upsert tickets into ChromaDB collection using sentence-transformers."""
        if self._chroma_collection is None:
            return False
        try:
            embedder = _get_embedder()
            texts = [self._ticket_text(t) for t in tickets]
            ids   = [str(t.get("id", f"ticket_{i}")) for i, t in enumerate(tickets)]
            vecs  = embedder.encode(texts, convert_to_numpy=True,
                                    normalize_embeddings=True, show_progress_bar=False)
            # Upsert in chunks to avoid ChromaDB batch limits
            chunk = 100
            for i in range(0, len(tickets), chunk):
                self._chroma_collection.upsert(
                    ids=ids[i:i+chunk],
                    embeddings=vecs[i:i+chunk].tolist(),
                    metadatas=[{"title": t.get("title", ""), "id": t.get("id", "")}
                               for t in tickets[i:i+chunk]],
                )
            self._tickets_for_vectors = list(tickets)
            logger.info("ChromaDB: upserted %d tickets into persistent collection", len(tickets))
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("ChromaDB index failed (%s) — falling back to NPZ", e)
            self._use_chromadb = False
            return False

    def _chroma_search(self, query_text: str, top_k: int = 5) -> list[dict]:
        """Query ChromaDB collection for top-K similar tickets."""
        if self._chroma_collection is None or not self._tickets_for_vectors:
            return list(self._tickets_for_vectors)
        try:
            self._embedder = _get_embedder()
            qvec = self._embedder.encode([query_text], convert_to_numpy=True,
                                         normalize_embeddings=True, show_progress_bar=False)
            results = self._chroma_collection.query(
                query_embeddings=qvec.tolist(),
                n_results=min(top_k, self._chroma_collection.count()),
            )
            ids = results.get("ids", [[]])[0]
            distances = results.get("distances", [[]])[0]
            # Build lookup and return in similarity order
            id_to_ticket = {str(t.get("id", "")): t for t in self._tickets_for_vectors}
            out = []
            for tid, dist in zip(ids, distances):
                ticket = id_to_ticket.get(tid)
                if ticket:
                    out.append(dict(ticket, _similarity=float(1.0 - dist)))
            return out or list(self._tickets_for_vectors[:top_k])
        except Exception as e:  # noqa: BLE001
            logger.warning("ChromaDB search failed (%s) — returning all tickets", e)
            return list(self._tickets_for_vectors[:top_k])

    # ----------------------------------------------------- Vector interface

    def _cs(self, name: str, **attrs):
        """Shortcut: child span or no-op."""
        try:
            from telemetry import child_span
            return child_span(name, **attrs)
        except ImportError:
            from contextlib import nullcontext
            return nullcontext()

    def index_tickets(self, tickets: list[dict]) -> bool:
        """Embed and index existing tickets for semantic search.

        Returns True if embeddings were built, False if the system fell back
        to no-embedding mode (small ticket set or sentence-transformers not
        installed). When `persistent=True` and a matching cache file exists,
        embeddings are loaded from disk instead of being recomputed.
        """
        self._tickets_for_vectors = list(tickets)
        if len(tickets) < _RETRIEVAL_THRESHOLD:
            logger.info("Only %d tickets — skipping embeddings (under threshold)", len(tickets))
            return False

        # ChromaDB path — preferred persistent backend for multi-replica safety.
        if self._use_chromadb:
            with self._cs("embedding.index", **{"embedding.backend": "chromadb",
                                                 "embedding.ticket_count": len(tickets)}):
                return self._chroma_index(tickets)

        try:
            import sentence_transformers as _st  # noqa: F401 — availability check
            import numpy as np
        except ImportError:
            logger.warning("sentence-transformers not installed — falling back to no-embedding mode")
            return False

        self._np = np

        with self._cs("embedding.index", **{"embedding.backend": "numpy",
                                             "embedding.ticket_count": len(tickets),
                                             "embedding.model": _EMBEDDING_MODEL}):
            # Persistent path: try to load embeddings keyed by content hash.
            if self._persistent:
                cache_hit = self._try_load_vectors(tickets, np)
                if cache_hit:
                    logger.info("Hydrated %d embeddings from cache", len(tickets))
                    return True

            self._embedder = _get_embedder()
            texts = [self._ticket_text(t) for t in tickets]
            self._ticket_vectors = self._embedder.encode(
                texts,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )

            if self._persistent:
                self._save_vectors(tickets)

            logger.info("Indexed %d tickets for semantic search", len(tickets))
            return True

    def search_similar(self, query_text: str, top_k: int = 5) -> list[dict]:
        """Return top-K most similar tickets to query_text.

        Routes to ChromaDB when USE_CHROMADB=1, otherwise uses in-process
        numpy vectors. Falls back to returning all tickets if index wasn't built.
        """
        if self._use_chromadb and self._chroma_collection is not None:
            with self._cs("embedding.search", **{"embedding.backend": "chromadb", "embedding.top_k": top_k}):
                return self._chroma_search(query_text, top_k)
        if self._ticket_vectors is None:
            return list(self._tickets_for_vectors)
        if self._embedder is None:
            self._embedder = _get_embedder()
        query_vec = self._embedder.encode(
            [query_text],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        sims = (query_vec @ self._ticket_vectors.T)[0]
        top_indices = self._np.argsort(-sims)[:top_k]
        return [
            dict(self._tickets_for_vectors[i], _similarity=float(sims[i]))
            for i in top_indices
        ]

    # ----------------------------------------------------- vector cache

    def _corpus_hash(self, tickets: list[dict]) -> str:
        """Stable hash of the ticket corpus — invalidates the cache on change."""
        h = hashlib.sha256()
        h.update(_EMBEDDING_MODEL.encode())
        for t in tickets:
            h.update((self._ticket_text(t) + "\0").encode("utf-8"))
        return h.hexdigest()[:16]

    def _vector_cache_path(self, tickets: list[dict]) -> Path:
        return self._cache_dir / "vectors" / f"{self._corpus_hash(tickets)}.npz"

    def _try_load_vectors(self, tickets: list[dict], np) -> bool:
        path = self._vector_cache_path(tickets)
        if not path.exists():
            return False
        try:
            data = np.load(path)
            self._ticket_vectors = data["vectors"]
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to load vector cache %s: %s", path, e)
            return False

    def _save_vectors(self, tickets: list[dict]) -> None:
        path = self._vector_cache_path(tickets)
        try:
            import numpy as np
            np.savez_compressed(path, vectors=self._ticket_vectors)
            logger.info("Wrote vector cache to %s", path)
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to save vector cache: %s", e)

    @staticmethod
    def _ticket_text(t: dict) -> str:
        title = (t.get("title") or "").strip()
        description = (t.get("description") or "").strip()
        if title and description:
            return f"{title}. {description}"
        return title or description
