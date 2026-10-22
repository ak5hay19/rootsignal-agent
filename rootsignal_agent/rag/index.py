"""In-memory FAISS index over runbook chunks."""

from pathlib import Path
from typing import Any

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from rootsignal_agent.rag.chunking import Chunk, chunk_dir

MODEL_NAME = "all-MiniLM-L6-v2"
CANDIDATE_CHUNKS = 10  # chunks retrieved before grouping by runbook


class RunbookIndex:
    def __init__(self, chunks: list[Chunk]) -> None:
        if not chunks:
            raise ValueError("no runbook chunks to index")
        self._chunks = chunks
        self._model: SentenceTransformer | None = None  # loaded lazily, once
        vectors = self._embed([c.embed_text for c in chunks])
        # Flat exact index on purpose: at ~50 chunks HNSW would add approximation
        # error for no speed benefit. Inner product on normalized vectors is cosine.
        self._index = faiss.IndexFlatIP(vectors.shape[1])
        self._index.add(vectors)

    @classmethod
    def from_dir(cls, path: Path | str | None = None) -> "RunbookIndex":
        return cls(chunk_dir(path))

    def _embed(self, texts: list[str]) -> np.ndarray:
        if self._model is None:
            self._model = SentenceTransformer(MODEL_NAME)
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return np.asarray(vectors, dtype=np.float32)

    def search(self, query: str, k: int = 3) -> list[dict[str, Any]]:
        """Return up to k DISTINCT runbooks, each shown by its best-scoring chunk.

        Grouping matters: the agent must choose between runbooks, and three chunks
        of one runbook would crowd out the alternatives.
        """
        if not query.strip():
            raise ValueError("query must not be empty")
        if k < 1:
            raise ValueError("k must be at least 1")

        top = min(CANDIDATE_CHUNKS, len(self._chunks))
        scores, ids = self._index.search(self._embed([query]), top)
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        # FAISS returns hits best-first, so the first chunk seen per runbook is its best.
        for score, i in zip(scores[0], ids[0], strict=True):
            chunk = self._chunks[i]
            if chunk.runbook in seen:
                continue
            seen.add(chunk.runbook)
            results.append(
                {
                    "runbook": chunk.runbook,
                    "title": chunk.title,
                    "section": chunk.section,
                    "text": chunk.text,
                    "score": float(score),
                }
            )
            if len(results) == k:
                break
        return results
