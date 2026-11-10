"""Embed the public catalog once and save the vectors to
data/demo/catalog_embeddings.npz (committed: the catalog is public).

Gemini counts every text as one request (free tier: 100 a minute, 1,000 a
day), so this costs ~471 requests the first time and nothing afterwards.
Run again after the catalog or `hebrew.normalize` changes: only texts that
are not in the file yet are sent. Progress is saved after every chunk.

Usage:
    uv run python scripts/build_catalog_embeddings.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.core.hebrew import normalize  # noqa: E402
from app.tools.catalog_search import EmbeddingStore, GeminiEmbedder  # noqa: E402

CATALOG = ROOT / "data" / "demo" / "catalog.json"
STORE = ROOT / "data" / "demo" / "catalog_embeddings.npz"


def main() -> None:
    settings = get_settings()
    if settings.gemini_api_key is None:
        raise SystemExit("GEMINI_API_KEY missing in .env")
    embedder = GeminiEmbedder(settings.gemini_api_key.get_secret_value(), settings.gemini_embedding_model)
    texts = [normalize(i["description"]) for i in json.loads(CATALOG.read_text(encoding="utf-8"))["items"]]
    store = EmbeddingStore(STORE)
    before = len(store)
    vectors = store.vectors_for(texts, embedder)
    print(f"{embedder.name}: {len(texts)} texts, {len(store) - before} newly embedded, shape {vectors.shape}")


if __name__ == "__main__":
    main()
