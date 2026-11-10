import json
from pathlib import Path

import numpy as np
import pytest

from app.core.hebrew import normalize
from app.models.catalog import CatalogEntry
from app.tools.catalog_search import CatalogIndex, CatalogSearch, EmbeddingStore, catalog_fingerprint

CATALOG_FILE = Path(__file__).resolve().parents[1] / "data" / "demo" / "catalog.json"


class FakeEmbedder:
    """Fixed, deterministic vectors: hashed letter trigrams. No Gemini call."""

    name = "fake@64"

    def __init__(self):
        self.document_calls = 0
        self.query_calls = 0

    @staticmethod
    def _vector(text: str) -> np.ndarray:
        v = np.zeros(64, dtype=np.float32)
        padded = f"  {normalize(text)}  "
        for i in range(len(padded) - 2):
            v[sum(map(ord, padded[i : i + 3])) % 64] += 1
        return v

    def embed_documents(self, texts):
        self.document_calls += 1
        return np.stack([self._vector(t) for t in texts])

    def embed_query(self, text):
        self.query_calls += 1
        return self._vector(text)


@pytest.fixture(scope="module")
def catalog() -> list[CatalogEntry]:
    items = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))["items"]
    return [CatalogEntry(**i) for i in items]


@pytest.fixture(scope="module")
def index(catalog) -> CatalogIndex:
    return CatalogIndex(catalog, FakeEmbedder())


def _codes(cands):
    return [c.code for c in cands]


def test_returns_k_candidates_with_scores(index):
    cands = index.search("חידוש טיח סיד בחזית", k=15)
    assert len(cands) == 15
    scores = [c.search_score for c in cands]
    assert scores == sorted(scores, reverse=True)
    assert all(0 <= s <= 100 for s in scores)
    assert len(set(_codes(cands))) == 15


def test_bm25_finds_exact_terms_with_prefixes(index):
    # "בקרניז" must meet "קרניז" in the catalog.
    top = index.search("שיקום בקרניז במשיכה", k=5, mode="bm25")
    assert top and all("קרניז" in c.description for c in top[:3])


def test_typo_is_corrected(index):
    good = _codes(index.search("כיחול אבן", k=5, mode="bm25"))
    typo = _codes(index.search("כיחוול אבן", k=5, mode="bm25"))
    assert good and typo[0] == good[0]


def test_unknown_words_give_no_bm25_result(index):
    assert index.search("קקקקק זזזזז", mode="bm25") == []


def test_candidate_description_is_normalized(index):
    cands = index.search("קרניז במשיכה מדרגות", k=15, mode="bm25")
    assert all(")" not in c.description.split("(")[0] for c in cands)


def test_hybrid_merges_both_retrievers(index):
    hybrid = set(_codes(index.search("צביעת מעקה ברזל", k=15)))
    bm25 = set(_codes(index.search("צביעת מעקה ברזל", k=15, mode="bm25")))
    emb = set(_codes(index.search("צביעת מעקה ברזל", k=15, mode="embedding")))
    assert hybrid <= bm25 | set(_codes(index.search("צביעת מעקה ברזל", k=50, mode="embedding")))
    assert hybrid & bm25 and hybrid & emb


def test_without_embedder_hybrid_falls_back_to_bm25(catalog):
    idx = CatalogIndex(catalog, embedder=None)
    assert _codes(idx.search("טיח סיד")) == _codes(idx.search("טיח סיד", mode="bm25"))
    with pytest.raises(RuntimeError):
        idx.search("טיח", mode="embedding")


def test_index_is_cached_by_catalog_fingerprint(catalog):
    embedder = FakeEmbedder()
    search = CatalogSearch(embedder)
    first = search.index_for(catalog)
    assert search.index_for(list(catalog)) is first  # same catalog -> same index
    calls = embedder.document_calls
    changed = catalog[:-1]
    assert catalog_fingerprint(changed) != catalog_fingerprint(catalog)
    assert search.index_for(changed) is not first
    assert embedder.document_calls == calls  # its texts are already in the store


def test_disk_cache_avoids_embedding_again(catalog, tmp_path):
    path = tmp_path / "vectors.npz"
    first = FakeEmbedder()
    CatalogIndex(catalog, first, EmbeddingStore(path))
    second = FakeEmbedder()
    CatalogIndex(catalog, second, EmbeddingStore(path))
    assert first.document_calls > 0 and second.document_calls == 0


def test_store_embeds_only_new_texts(catalog, tmp_path):
    path = tmp_path / "vectors.npz"
    CatalogIndex(catalog[:100], FakeEmbedder(), EmbeddingStore(path))
    embedder = FakeEmbedder()
    texts = []
    embedder.embed_documents = lambda t, f=embedder.embed_documents: (texts.extend(t), f(t))[1]
    CatalogIndex(catalog[:105], embedder, EmbeddingStore(path))
    assert len(texts) == 5


def test_empty_catalog_rejected():
    with pytest.raises(ValueError):
        CatalogIndex([], None)
