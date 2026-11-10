"""Build the capability-B evaluation sets: demo proposals with planted errors.

Each case is one fictional demo proposal (data/demo/proposals.json) with 0-2
errors planted on purpose, and the list of those errors, (line_code, kind),
for the counting rule in SPEC 12.3. Tuning cases use proposals 21-30, test
cases proposals 1-20, so the Reviewer prompt is never tuned on test text.

A fixed seed makes every run produce the same files.

Usage:
    python scripts/build_review_eval.py
"""

from __future__ import annotations

import json
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.rules import load_rules  # noqa: E402

DEMO = ROOT / "data" / "demo"
OUT = ROOT / "eval" / "datasets"
SEED = 30102026

VAGUE = [
    "עבודות שונות בחזית לפי הצורך",
    "תיקונים כלליים",
    "השלמות לפי מה שיידרש באתר",
    "טיפול בבעיות שיתגלו במהלך העבודה",
    "עבודות נוספות לפי הנחיית המזמין",
    "שיפוץ כללי",
]
OTHER_UNIT = {'מ"ר': "מ'", "מ'": 'מ"ר', "יח'": "מ'", 'מ"ק': 'מ"ר', "קומפ": "יח'", 'ש"ע': "יח'", "טון": 'מ"ק'}

# No price_vs_catalog errors: the owner turned that alert off (30.10.2026).
TUNE_PLAN = [
    ["missing_condition"], ["price_vs_history"], ["vague"], ["unit_mismatch"],
    ["vague"], ["contradiction"], ["missing_condition", "price_vs_history"],
    ["unit_mismatch", "vague"], ["price_vs_history", "missing_condition"], [],
]
TEST_PLAN = [
    *[["missing_condition"]] * 3, *[["price_vs_history"]] * 4,
    *[["unit_mismatch"]] * 4, *[["vague"]] * 5, *[["contradiction"]] * 2,
    ["missing_condition", "price_vs_history"], ["missing_condition", "unit_mismatch"],
    ["price_vs_history", "vague"], ["price_vs_history", "unit_mismatch"],
    ["missing_condition", "vague"], ["unit_mismatch", "vague"],
    ["missing_condition", "contradiction"],
    [], [], [], [], [],
]


class Skip(Exception):
    """This proposal cannot take this error; try the next one."""


def _load(name: str) -> list[dict]:
    return json.loads((DEMO / name).read_text(encoding="utf-8"))["items"]


class Builder:
    def __init__(self, rng: random.Random):
        self.rng = rng
        self.rules = load_rules()
        self.catalog_price = {c["code"]: c["base_price"] for c in _load("catalog.json")}
        self.proposals = _load("proposals.json")

    def history(self, base_id: str) -> dict[str, list[float]]:
        prices: dict[str, list[float]] = defaultdict(list)
        for p in self.proposals:
            if p["id"] != base_id:
                for li in p["line_items"]:
                    if li["unit_price"] > 0:
                        prices[li["code"]].append(li["unit_price"] * (1 - li["discount_percent"] / 100))
        return prices

    def case(self, case_id: str, proposal: dict, kinds: list[str]) -> dict:
        lines = [
            {
                "code": li["code"], "description": li["description"], "unit": li["unit"],
                "quantity": li["quantity"], "unit_price": li["unit_price"],
                "discount_percent": li["discount_percent"],
                "catalog_price": self.catalog_price.get(li["code"]),
            }
            for li in proposal["line_items"]
        ]
        state = {
            "lines": lines,
            "keys": [c.removeprefix("cond-") for c in proposal["condition_ids"]],
            "used": set(),  # lines already changed: one error per line
            "history": self.history(proposal["id"]),
        }
        errors = [getattr(self, f"_{kind}")(state) for kind in kinds]
        return {
            "id": case_id,
            "base_proposal": proposal["id"],
            "lines": lines,
            "condition_keys": state["keys"],
            "errors": errors,
        }

    def _pick_line(self, state, ok) -> dict:
        options = [li for li in state["lines"] if li["code"] not in state["used"] and ok(li)]
        if not options:
            raise Skip
        line = self.rng.choice(options)
        state["used"].add(line["code"])
        return line

    def _triggered_rules(self, state):
        codes = [li["code"] for li in state["lines"]]
        for rule in self.rules.conditions.rules:
            hits = [c for c in codes if c.startswith(tuple(rule.code_prefixes)) and c not in rule.except_codes]
            if hits and set(state["keys"]) & set(rule.require_any):
                yield rule, hits[0]

    def _missing_condition(self, state):
        rules = list(self._triggered_rules(state))
        if rules and self.rng.random() < 0.75:
            rule, first_code = self.rng.choice(rules)
            state["keys"] = [k for k in state["keys"] if k not in rule.require_any]
            return {"line_code": first_code, "kind": "missing_condition", "note": f"removed: {rule.id}"}
        cond = self.rng.choice(self.rules.conditions.always)
        state["keys"] = [k for k in state["keys"] if k != cond.key]
        return {"line_code": None, "kind": "missing_condition", "note": f"removed: {cond.key}"}

    def _price_vs_history(self, state):
        hist = state["history"]
        line = self._pick_line(state, lambda li: len(hist.get(li["code"], [])) >= 3)
        factor = self.rng.choice([1.8, 2.2, 2.6, 0.5, 0.55])
        line["unit_price"] = round(statistics.median(hist[line["code"]]) * factor)
        line["discount_percent"] = 0.0
        return {"line_code": line["code"], "kind": "price_vs_history", "note": f"x{factor} of median"}

    def _price_vs_catalog(self, state):
        hist = state["history"]
        line = self._pick_line(
            state, lambda li: len(hist.get(li["code"], [])) < 3 and (li["catalog_price"] or 0) > 0
        )
        factor = self.rng.choice([10, 0.1])  # an extra or a missing zero
        line["unit_price"] = round(line["catalog_price"] * factor, 1)
        line["discount_percent"] = 0.0
        return {"line_code": line["code"], "kind": "price_vs_catalog", "note": f"x{factor} of catalog"}

    def _unit_mismatch(self, state):
        line = self._pick_line(state, lambda li: li["unit"] in OTHER_UNIT)
        line["unit"] = OTHER_UNIT[line["unit"]]
        return {"line_code": line["code"], "kind": "unit_mismatch", "note": "unit changed"}

    def _vague(self, state):
        line = self._pick_line(state, lambda li: True)
        line["description"] = self.rng.choice(VAGUE)
        return {"line_code": line["code"], "kind": "wording", "note": "vague description"}

    def _contradiction(self, state):
        # A proposal that already has one side of a conflict gets the other.
        for conflict in self.rules.conditions.conflicts:
            selected = [k for k in conflict.keys if k in state["keys"]]
            if len(selected) == 1:
                state["keys"].extend(k for k in conflict.keys if k not in selected)
                return {"line_code": None, "kind": "wording", "note": f"conflict: {'+'.join(conflict.keys)}"}
        raise Skip


def build(builder: Builder, plan: list[list[str]], pool: list[dict], prefix: str) -> list[dict]:
    cases = []
    start = 0
    for n, kinds in enumerate(plan, start=1):
        for offset in range(len(pool)):
            proposal = pool[(start + offset) % len(pool)]
            try:
                cases.append(builder.case(f"{prefix}{n:02d}", proposal, kinds))
            except Skip:
                continue
            start = (start + offset + 1) % len(pool)
            break
        else:
            raise SystemExit(f"no proposal can take {kinds}")
    return cases


def main() -> None:
    builder = Builder(random.Random(SEED))
    proposals = builder.proposals
    sets = {
        "review_tune.jsonl": build(builder, TUNE_PLAN, proposals[20:30], "rt"),
        "review_test.jsonl": build(builder, TEST_PLAN, proposals[0:20], "rx"),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    for name, cases in sets.items():
        text = "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases)
        (OUT / name).write_text(text, encoding="utf-8")
        errors = sum(len(c["errors"]) for c in cases)
        print(f"{name}: {len(cases)} cases, {errors} planted errors")


if __name__ == "__main__":
    main()
