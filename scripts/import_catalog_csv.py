"""Convert the public conservation price list (CSV) into data/demo/catalog.json.

The CSV has the columns: קוד, תיאור, יחידה, מחיר, קטגוריה (code, description,
unit, price, category). It is the public price list for conservation works;
its codes, descriptions, units and prices are used unchanged.

Usage:
    python scripts/import_catalog_csv.py <path/to/price_list.csv>
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "demo" / "catalog.json"
CODE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{3}\.\d{4}$")
SOURCE = "מחירון לעבודות שימור (מחירון פומבי), 5.1.2023"


def convert(csv_path: Path) -> dict:
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    items = []
    for row in rows:
        code = row["קוד"].strip()
        if not CODE_RE.match(code):
            raise ValueError(f"unexpected code shape: {code!r}")
        items.append({
            "id": f"cat-{code}",
            "code": code,
            "description": " ".join(row["תיאור"].split()),
            "unit": row["יחידה"].strip(),
            "base_price": float(row["מחיר"]),
            "category": row["קטגוריה"].strip(),
            "is_active": True,
        })
    return {"source": SOURCE, "count": len(items), "items": items}


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    data = convert(Path(sys.argv[1]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {data['count']} items to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
