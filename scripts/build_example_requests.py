"""Write example request bodies for trying the server without the app.

The app is a separate, private project, so the README shows how to call the
server directly. Both bodies are built from the demo data in the shape the
app sends: catalog lines with code, description and unit only (no price),
the conditions library as id + text, and price *ratios* for the review.

Usage:
    python scripts/build_example_requests.py
Writes examples/match_request.json and examples/review_request.json.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "data" / "demo"
OUT = ROOT / "examples"

MATCH_TEXT = (
    'ניקוי וכיחול קיר אבן בכניסה, 40 מ"ר. החלפת אדן חלון אבן. '
    "הפיגום כלול במחיר. תשלום: 30% בתחילת העבודה והיתרה בסיום."
)


def _load(name: str) -> dict:
    return json.loads((DEMO / name).read_text(encoding="utf-8"))


def _write(name: str, body: dict) -> None:
    path = OUT / name
    path.write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}")


def main() -> None:
    catalog_items = [i for i in _load("catalog.json")["items"] if i.get("is_active", True)]
    catalog = [{"code": i["code"], "description": i["description"], "unit": i["unit"]} for i in catalog_items]
    by_code = {c["code"]: c for c in catalog}
    conditions = [
        {"id": c["id"], "text": c["text"]} for c in _load("conditions.json")["items"] if c.get("is_active", True)
    ]

    OUT.mkdir(exist_ok=True)
    _write("match_request.json", {"text": MATCH_TEXT, "catalog": catalog, "conditions": conditions})

    plaster = by_code["01.09.001.0060"]
    paint = by_code["01.11.001.0070"]
    roof = by_code["01.29.001.0900"]
    lines = [
        # Price 2.3 times the median of 6 earlier proposals.
        {**plaster, "quantity": 120, "history_ratio": 2.3, "history_count": 6},
        # Running metres instead of the catalog's square metres.
        {**paint, "unit": "מ'", "quantity": 85, "history_ratio": 1.0, "history_count": 4},
        # The catalog wording was replaced by a vague one.
        {**roof, "description": "עבודות שונות בגג לפי הצורך", "quantity": 1},
    ]
    review = {
        "lines": lines,
        # No payment condition, which every proposal needs (rules.yaml).
        "condition_keys": ["scaffolding_included", "waste", "insurance"],
        "catalog": [plaster, paint, roof],
    }
    _write("review_request.json", review)


if __name__ == "__main__":
    main()
