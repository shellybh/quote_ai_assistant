"""CatalogSearch: hybrid search over the catalog (SPEC 5.3).

Two retrievers run side by side and are merged with Reciprocal Rank Fusion:
1. BM25 (bm25s) over `hebrew.search_tokens`, with query words that are not in
   the catalog vocabulary corrected by rapidfuzz (typos).
2. Embeddings (gemini-embedding-2, 768 dims) with cosine similarity.

Quota: Gemini counts every embedded text as one request (100 a minute,
1,000 a day on the free tier), so the 471-line catalog costs ~471. Vectors are
therefore kept per text in an `EmbeddingStore`; the public catalog's vectors
ship in data/demo/catalog_embeddings.npz (scripts/build_catalog_embeddings.py)
and only texts missing from it are sent to Gemini. The index itself lives in
memory, keyed by a hash of the catalog. Tests use a fake embedder.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import deque
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, Protocol

import bm25s
import numpy as np
from rapidfuzz import fuzz, process

from app.core.hebrew import normalize, search_tokens, synonym_tokens
from app.models.catalog import Candidate, CatalogEntry

Mode = Literal["hybrid", "bm25", "embedding"]

DEFAULT_K = 15
RRF_K = 60  # the usual RRF constant
POOL = 50  # how many results each retriever passes to the fusion
TYPO_MIN_SCORE = 85  # rapidfuzz ratio to accept a vocabulary word for a typo
TYPO_MIN_LEN = 4  # don't "correct" short words


class Embedder(Protocol):
    name: str

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


class GeminiEmbedder:
    """gemini-embedding-2 via google-genai. One Content per text, otherwise
    the model returns a single aggregated vector for all of them."""

    BATCH = 40  # texts per call; well under the 8,192-token request limit
    PER_MINUTE = 90  # each text counts as a request; the free tier allows 100/min

    def __init__(self, api_key: str, model: str, dimensions: int = 768):
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._dims = dimensions
        self.name = f"{model}@{dimensions}"
        self._queries: dict[str, np.ndarray] = {}  # same query -> one request
        self._sent: deque[tuple[float, int]] = deque()  # (time, texts) last minute

    def _throttle(self, count: int) -> None:
        while True:
            now = time.monotonic()
            while self._sent and now - self._sent[0][0] > 60:
                self._sent.popleft()
            if sum(n for _, n in self._sent) + count <= self.PER_MINUTE:
                self._sent.append((now, count))
                return
            time.sleep(max(0.5, 60 - (now - self._sent[0][0])))

    def _call(self, chunk: Sequence[str]):
        from google.genai import errors, types

        for attempt in range(2):
            self._throttle(len(chunk))
            try:
                return self._client.models.embed_content(
                    model=self._model,
                    contents=[types.Content(parts=[types.Part.from_text(text=t)]) for t in chunk],
                    config=types.EmbedContentConfig(output_dimensionality=self._dims),
                )
            except errors.ClientError as exc:
                # Per-minute limit: wait once as Google asks. A daily limit fails.
                if exc.code != 429 or attempt or "per day" in str(exc).lower():
                    raise
                delay = re.search(r"retry in ([\d.]+)s", str(exc))
                time.sleep(float(delay.group(1)) + 1 if delay else 61)
        raise RuntimeError("unreachable")

    def _embed(self, texts: Sequence[str]) -> np.ndarray:
        out: list[list[float]] = []
        for start in range(0, len(texts), self.BATCH):
            chunk = texts[start : start + self.BATCH]
            result = self._call(chunk)
            if len(result.embeddings) != len(chunk):
                raise RuntimeError("embedding count does not match the input")
            out.extend(e.values for e in result.embeddings)
        return np.asarray(out, dtype=np.float32)

    # gemini-embedding-2 takes the task as a text prefix (no task_type).
    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        return self._embed([f"title: none | text: {t}" for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        if text not in self._queries:
            if len(self._queries) >= 1000:
                self._queries.clear()
            self._queries[text] = self._embed([f"task: search result | query: {text}"])[0]
        return self._queries[text]


class EmbeddingStore:
    """Document vectors by (embedder, text), optionally kept in an .npz file.

    Embeds only the texts it does not have yet, in chunks, and saves after
    each chunk, so a run stopped by the quota keeps what it already paid for.
    """

    CHUNK = 40

    def __init__(self, path: Path | None = None, persist: bool = True):
        self._path = path
        self._persist = persist and path is not None
        self._vectors: dict[str, np.ndarray] = {}
        self._lock = threading.Lock()
        if path is not None and path.exists():
            with np.load(path) as data:
                self._vectors = {k: data[k].astype(np.float32) for k in data.files}

    @staticmethod
    def key(embedder_name: str, text: str) -> str:
        return hashlib.sha256(f"{embedder_name}|{text}".encode()).hexdigest()[:24]

    def __len__(self) -> int:
        return len(self._vectors)

    def vectors_for(self, texts: Sequence[str], embedder: Embedder) -> np.ndarray:
        with self._lock:
            keys = [self.key(embedder.name, t) for t in texts]
            missing = list(dict.fromkeys(t for t, k in zip(texts, keys) if k not in self._vectors))
            for start in range(0, len(missing), self.CHUNK):
                chunk = missing[start : start + self.CHUNK]
                for text, vec in zip(chunk, embedder.embed_documents(chunk)):
                    self._vectors[self.key(embedder.name, text)] = np.asarray(vec, dtype=np.float32)
                self._save()
            return np.stack([self._vectors[k] for k in keys])

    def _save(self) -> None:
        if not self._persist:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp.npz")
        np.savez_compressed(tmp, **{k: v.astype(np.float16) for k, v in self._vectors.items()})
        tmp.replace(self._path)


def catalog_fingerprint(catalog: Sequence[CatalogEntry]) -> str:
    payload = json.dumps(
        [[e.code, e.description, e.unit] for e in catalog], ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _unit_rows(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
    return matrix / np.where(norms == 0, 1, norms)


class CatalogIndex:
    """Search index for one catalog."""

    def __init__(
        self,
        catalog: Sequence[CatalogEntry],
        embedder: Embedder | None,
        store: EmbeddingStore | None = None,
    ):
        if not catalog:
            raise ValueError("empty catalog")
        self.entries = list(catalog)
        self.fingerprint = catalog_fingerprint(self.entries)
        self._embedder = embedder

        texts = [normalize(e.description) for e in self.entries]
        doc_tokens = [search_tokens(t) or ["_"] for t in texts]
        self._bm25 = bm25s.BM25()
        self._bm25.index(doc_tokens, show_progress=False)
        self._vocab = sorted({tok for doc in doc_tokens for tok in doc})
        self._vocab_set = set(self._vocab)

        self._vectors: np.ndarray | None = None
        if embedder is not None:
            store = store if store is not None else EmbeddingStore()
            self._vectors = _unit_rows(store.vectors_for(texts, embedder))

    # --- retrievers ---------------------------------------------------------

    def _query_tokens(self, query: str) -> list[str]:
        tokens = []
        said = search_tokens(query)
        for tok in said:
            if tok in self._vocab_set or len(tok) < TYPO_MIN_LEN or tok.isdigit():
                tokens.append(tok)
                continue
            best = process.extractOne(
                tok, self._vocab, scorer=fuzz.ratio, score_cutoff=TYPO_MIN_SCORE
            )
            tokens.append(best[0] if best else tok)
        # Synonyms of the words as said, before the typo fix can change them.
        return tokens + synonym_tokens(said)

    def bm25_ranking(self, query: str) -> list[int]:
        tokens = self._query_tokens(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        order = np.argsort(-scores, kind="stable")[:POOL]
        return [int(i) for i in order if scores[i] > 0]

    def embedding_ranking(self, query: str) -> list[int]:
        if self._vectors is None or self._embedder is None:
            return []
        q = _unit_rows(np.asarray(self._embedder.embed_query(normalize(query)), dtype=np.float32))
        sims = self._vectors @ q
        return [int(i) for i in np.argsort(-sims, kind="stable")[:POOL]]

    # --- public -------------------------------------------------------------

    def search(self, query: str, k: int = DEFAULT_K, mode: Mode = "hybrid") -> list[Candidate]:
        rankings = []
        if mode in ("hybrid", "bm25"):
            rankings.append(self.bm25_ranking(query))
        if mode in ("hybrid", "embedding"):
            if self._vectors is None:
                if mode == "embedding":
                    raise RuntimeError("index has no embeddings")
            else:
                rankings.append(self.embedding_ranking(query))

        fused: dict[int, float] = {}
        for ranking in rankings:
            for rank, idx in enumerate(ranking, start=1):
                fused[idx] = fused.get(idx, 0.0) + 1.0 / (RRF_K + rank)
        if not fused:
            return []

        # 100 = first place in every retriever that ran.
        best_possible = len(rankings) / (RRF_K + 1)
        top = sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
        return [
            Candidate(
                code=self.entries[i].code,
                description=normalize(self.entries[i].description),
                unit=self.entries[i].unit,
                search_score=round(min(100.0, 100 * score / best_possible), 1),
            )
            for i, score in top
        ]


class CatalogSearch:
    """Keeps one index per catalog fingerprint (the app sends the catalog
    with every request; embeddings are computed only when it changes)."""

    MAX_INDEXES = 4

    def __init__(self, embedder: Embedder | None, store: EmbeddingStore | None = None):
        self._embedder = embedder
        self._store = store if store is not None else EmbeddingStore()
        self._indexes: dict[str, CatalogIndex] = {}
        self._lock = threading.Lock()

    def index_for(self, catalog: Sequence[CatalogEntry]) -> CatalogIndex:
        key = catalog_fingerprint(catalog)
        with self._lock:
            index = self._indexes.get(key)
            if index is None:
                index = CatalogIndex(catalog, self._embedder, self._store)
                if len(self._indexes) >= self.MAX_INDEXES:
                    self._indexes.pop(next(iter(self._indexes)))
                self._indexes[key] = index
            return index

    def search(
        self,
        catalog: Sequence[CatalogEntry],
        query: str,
        k: int = DEFAULT_K,
        mode: Mode = "hybrid",
    ) -> list[Candidate]:
        return self.index_for(catalog).search(query, k=k, mode=mode)

