"""Reviewer agent: phrases the code check results and adds wording findings.

Prompt v3 = AI Studio v2 for the phrasing, plus a separate `wording` list
(v2-with-wording on the tuning set, 30.10.2026: the model never added a
wording finding while it shared the list with the check findings).

It never sees a price: lines arrive as CatalogEntry (code, description,
unit) and the checks carry ratios only (CheckResult.facts).
"""

import json
from collections.abc import Collection, Sequence

from crewai.llms.base_llm import BaseLLM

from app.agents.base import load_prompt, render, run_structured
from app.models.catalog import CatalogEntry
from app.models.review import CheckResult, ReviewerResult

PROMPT = load_prompt("reviewer")


CATALOG_WORDING = "[נוסח המחירון]"


def format_input(
    lines: Sequence[CatalogEntry],
    conditions: Sequence[str],
    checks: Sequence[CheckResult],
    catalog_wording: Collection[str] = (),
) -> dict[str, str]:
    """Checks are numbered from 1; the Reviewer answers with the same number.
    Lines whose description is the catalog's own text are marked, so the
    Reviewer does not call the public price list's wording vague."""
    check_rows = [
        json.dumps(
            {"check": n, "kind": c.kind.value, "line_code": c.line_code, "details": c.facts},
            ensure_ascii=False,
        )
        for n, c in enumerate(checks, start=1)
    ]
    return {
        "lines": "\n".join(
            f"{e.code} | {e.unit} | {e.description}"
            + (f" {CATALOG_WORDING}" if e.code in catalog_wording else "")
            for e in lines
        ),
        "conditions": "\n".join(f"- {c}" for c in conditions) or "(לא נבחרו תנאים)",
        "checks": "\n".join(check_rows) or "(אין ממצאים)",
    }


def run_reviewer(
    lines: Sequence[CatalogEntry],
    conditions: Sequence[str],
    checks: Sequence[CheckResult],
    llm: BaseLLM,
    catalog_wording: Collection[str] = (),
) -> ReviewerResult:
    return run_structured(
        llm,
        role="בודק הצעות מחיר",
        goal="לנסח בעברית פשוטה את הבעיות שנמצאו בהצעה לפני שליחה",
        description=render(PROMPT, **format_input(lines, conditions, checks, catalog_wording)),
        output=ReviewerResult,
    )
