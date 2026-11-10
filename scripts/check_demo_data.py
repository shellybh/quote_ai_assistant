"""Load data/demo/*.json and check that they are consistent.

Stage-0 exit check: the demo data loads with no errors. Exits 1 and lists
every problem otherwise.

Usage:
    python scripts/check_demo_data.py
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

DEMO = Path(__file__).resolve().parent.parent / "data" / "demo"
CODE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{3}\.\d{4}$")
UNITS = {"מ\"ר", "יח'", "מ'", "מ\"ק", "קומפ", "ש\"ע", "טון"}
STATUSES = {"draft", "issued", "sent"}


def _load(name: str) -> list[dict]:
    return json.loads((DEMO / name).read_text(encoding="utf-8"))["items"]


def check() -> tuple[list[str], dict]:
    problems: list[str] = []
    catalog = _load("catalog.json")
    conditions = _load("conditions.json")
    proposals = _load("proposals.json")

    codes = Counter(c["code"] for c in catalog)
    problems += [f"catalog: duplicate code {c}" for c, n in codes.items() if n > 1]
    for c in catalog:
        if not CODE_RE.match(c["code"]):
            problems.append(f"catalog: bad code {c['code']}")
        if c["unit"] not in UNITS:
            problems.append(f"catalog {c['code']}: unknown unit {c['unit']}")
        if not c["description"].strip():
            problems.append(f"catalog {c['code']}: empty description")
        if c["base_price"] < 0:
            problems.append(f"catalog {c['code']}: negative price")
    by_id = {c["id"]: c for c in catalog}

    cond_ids = {c["id"] for c in conditions}
    if len(cond_ids) != len(conditions):
        problems.append("conditions: duplicate id")
    keys = {c["key"] for c in conditions}

    numbers = Counter(p["proposal_number"] for p in proposals)
    problems += [f"proposals: duplicate number {n}" for n, k in numbers.items() if k > 1]
    for p in proposals:
        pid = p["id"]
        if p["status"] not in STATUSES:
            problems.append(f"{pid}: bad status {p['status']}")
        if not p["line_items"]:
            problems.append(f"{pid}: no line items")
        for line in p["line_items"]:
            item = by_id.get(line["catalog_item_id"])
            if item is None:
                problems.append(f"{pid}: unknown catalog item {line['catalog_item_id']}")
                continue
            for field, src in (("code", "code"), ("description", "description"), ("unit", "unit")):
                if line[field] != item[src]:
                    problems.append(f"{pid} {line['code']}: {field} differs from the catalog")
            if line["quantity"] <= 0 or line["unit_price"] <= 0:
                problems.append(f"{pid} {line['code']}: quantity and price must be positive")
        if any(c not in cond_ids for c in p["condition_ids"]):
            problems.append(f"{pid}: unknown condition id")
        if sum(1 for c in p["condition_ids"] if c.startswith("cond-scaffolding")) > 1:
            problems.append(f"{pid}: both scaffolding conditions")
        total = sum(m["percent"] for m in p["payment_milestones"])
        if abs(total - 100) > 1e-9:
            problems.append(f"{pid}: milestones sum to {total}, not 100")

    # How close quoted prices sit to the catalog price (sanity for PriceStats).
    ratios = [line["unit_price"] / by_id[line["catalog_item_id"]]["base_price"]
              for p in proposals for line in p["line_items"] if line["catalog_item_id"] in by_id]
    used = Counter(line["code"] for p in proposals for line in p["line_items"])
    summary = {
        "catalog items": len(catalog),
        "catalog categories": len({c["category"] for c in catalog}),
        "conditions": len(conditions),
        "condition keys": len(keys),
        "proposals": len(proposals),
        "line items": sum(len(p["line_items"]) for p in proposals),
        "distinct codes used": len(used),
        "codes used in 3+ proposals": sum(1 for n in used.values() if n >= 3),
        "price / catalog ratio (min, median, max)":
            (round(min(ratios), 2), round(statistics.median(ratios), 2), round(max(ratios), 2)) if ratios else None,
    }
    return problems, summary


def main() -> int:
    problems, summary = check()
    for key, value in summary.items():
        print(f"{key}: {value}")
    if problems:
        print(f"\n{len(problems)} problem(s):")
        print("\n".join(f"  {p}" for p in problems))
        return 1
    print("\nOK: demo data loads with no problems")
    return 0


if __name__ == "__main__":
    sys.exit(main())
