"""Capability B, end to end (SPEC 5.1, "review" branch):

code checks (PriceStats, CatalogPriceCheck, ConditionsCheck) -> Reviewer,
one call, no prices (AI) -> validation (code) -> ReviewResult.

Code decides what is wrong; the Reviewer only phrases it and may add
wording findings. Every code check reaches the user: if the Reviewer drops
one, or its note is incomplete or names a money amount, a plain finding
built from the check's facts takes its place. Severity is set here.
"""

import json
import re
from functools import cache
from pathlib import Path

from crewai.llms.base_llm import BaseLLM

from app.agents.reviewer import run_reviewer
from app.api.schemas import ReviewRequest
from app.core import tracing
from app.core.hebrew import normalize
from app.core.rules import Rules
from app.core.validation import clean_code
from app.models.catalog import CatalogEntry
from app.models.review import (
    CheckKind,
    CheckResult,
    ReviewerNote,
    ReviewerResult,
    ReviewFinding,
    ReviewResult,
    Severity,
    WordingNote,
)
from app.tools.review_checks import run_checks

CONDITIONS_FILE = Path(__file__).resolve().parents[2] / "data" / "demo" / "conditions.json"
MAX_WORDING = 10  # extra findings the Reviewer may add

SEVERITY = {
    CheckKind.missing_condition: Severity.high,
    CheckKind.price_vs_catalog: Severity.high,  # an extra or missing zero
    CheckKind.price_vs_history: Severity.medium,
    CheckKind.unit_mismatch: Severity.medium,
    CheckKind.wording: Severity.low,
}

# Used when the Reviewer's note for a code check is missing or rejected.
FALLBACK = {
    CheckKind.missing_condition: (
        "בלי התנאי לא ברור ללקוח מה כלול בהצעה ומה לא, וזה עלול להוביל למחלוקת.",
        "להוסיף את התנאי המתאים מספריית התנאים.",
    ),
    CheckKind.price_vs_history: (
        "מחיר רחוק מהרגיל עלול להיות טעות הקלדה, או לדרוש הסבר ללקוח.",
        "לבדוק אם זו טעות הקלדה. אם המחיר מכוון, אפשר להשאיר אותו או להסביר אותו בהצעה.",
    ),
    CheckKind.price_vs_catalog: (
        "מחיר רחוק מאוד מהמחירון הוא בדרך כלל טעות הקלדה, למשל אפס חסר או מיותר.",
        "לבדוק את מחיר היחידה בשורה. אם המחיר מכוון, אפשר להשאיר אותו או להסביר אותו בהצעה.",
    ),
    CheckKind.unit_mismatch: (
        "יחידה שונה מהמחירון משנה את המשמעות של הכמות ושל המחיר.",
        "לבדוק את היחידה ואת הכמות בשורה, ולתקן לפי המחירון.",
    ),
    CheckKind.wording: (  # conflicting conditions (rules.yaml)
        "כשתנאים סותרים זה את זה, לא ברור ללקוח מה מחייב, וזה עלול להוביל למחלוקת.",
        "להשאיר רק את התנאי הנכון ולהסיר את השני.",
    ),
}

# A money amount in the Reviewer's text (ratios like "פי 2.1" are allowed).
_MONEY = re.compile(r'₪|ש"ח|שקל|\bNIS\b|\bILS\b', re.IGNORECASE)
# The model sometimes slips a letter of another script (Georgian, Arabic) or
# a niqqud mark into a Hebrew word (tuning set, 30.10.2026). Anything that is
# not Hebrew, Latin, a digit, punctuation or a space is removed.
_FOREIGN = re.compile(r"[^א-תװ-״\x20-\x7E\s״׳–—“”‘’…]")


@cache
def _demo_condition_texts() -> dict[str, str]:
    items = json.loads(CONDITIONS_FILE.read_text(encoding="utf-8"))["items"]
    return {c["key"]: c["text"] for c in items}


def condition_texts(keys: list[str]) -> list[str]:
    """Texts of the fictional demo conditions; an unknown key is shown as is."""
    known = _demo_condition_texts()
    return [known.get(k, k) for k in keys]


def _clean(note: ReviewerNote | WordingNote):
    for name in ("problem", "why", "suggestion"):
        setattr(note, name, normalize(_FOREIGN.sub("", getattr(note, name))))
    return note


def _names_money(note: ReviewerNote | WordingNote) -> bool:
    """Checked on the raw text: `_clean` strips "₪" (not a Hebrew letter),
    so "500 ₪" would pass as "500" after it."""
    return any(_MONEY.search(normalize(t)) for t in (note.problem, note.why, note.suggestion))


def _usable(note: ReviewerNote | WordingNote) -> bool:
    texts = (note.problem, note.why, note.suggestion)
    return all(t.strip() for t in texts) and not any(_MONEY.search(normalize(t)) for t in texts)


def _cleaned(notes: list):
    """The notes that name no money amount, cleaned."""
    return [_clean(n) for n in notes if not _names_money(n)]


def _finding(kind: CheckKind, line_code: str | None, problem: str, why: str, suggestion: str):
    return ReviewFinding(
        severity=SEVERITY[kind], kind=kind, line_code=line_code,
        problem=problem, why=why, suggestion=suggestion,
    )


def merge(
    checks: list[CheckResult],
    reply: ReviewerResult,
    line_codes: set[str],
    catalog_text: set[str] = frozenset(),
) -> ReviewResult:
    """One finding per code check (the Reviewer's wording, else the fallback),
    then the Reviewer's wording findings on edited lines of this proposal."""
    by_check: dict[int, ReviewerNote] = {}
    for note in _cleaned(reply.findings):
        if 1 <= note.check <= len(checks) and note.check not in by_check and _usable(note):
            by_check[note.check] = note

    findings = []
    for n, check in enumerate(checks, start=1):
        note = by_check.get(n)
        if note is not None:
            # kind and line_code always come from the check, never the model.
            findings.append(_finding(check.kind, check.line_code, note.problem, note.why, note.suggestion))
        else:
            why, suggestion = FALLBACK[check.kind]
            findings.append(_finding(check.kind, check.line_code, check.facts, why, suggestion))

    seen = {c.line_code for c in checks if c.kind is CheckKind.wording}
    added = 0
    for note in _cleaned(reply.wording):
        code = clean_code(note.line_code) if note.line_code else None
        if not _usable(note) or code in seen or added >= MAX_WORDING:
            continue
        if code is not None and (code not in line_codes or code in catalog_text):
            continue  # not a line of this proposal, or the catalog's own text
        seen.add(code)
        added += 1
        findings.append(_finding(CheckKind.wording, code, note.problem, note.why, note.suggestion))

    order = list(Severity)
    findings.sort(key=lambda f: order.index(f.severity))  # stable: check order kept
    return ReviewResult(findings=findings)


def catalog_wording(request: ReviewRequest) -> set[str]:
    """Codes of lines whose description is exactly the catalog text (needs
    the catalog in the request). Only an edited description can be vague."""
    texts = {clean_code(e.code): normalize(e.description) for e in request.catalog}
    return {
        clean_code(li.code) for li in request.lines
        if texts.get(clean_code(li.code)) == normalize(li.description)
    }


def review_proposal(request: ReviewRequest, llm: BaseLLM, rules: Rules | None = None) -> ReviewResult:
    with tracing.step("checks"):
        checks = run_checks(request, rules)
        unedited = catalog_wording(request)
    # Price-free view of the proposal: this is all the Reviewer sees.
    lines = [CatalogEntry(code=clean_code(li.code), description=li.description or "-",
                          unit=li.unit or "-") for li in request.lines]
    with tracing.step("reviewer"):
        reply = run_reviewer(lines, condition_texts(request.condition_keys), checks, llm, unedited)
    with tracing.step("merge"):
        return merge(checks, reply, {clean_code(li.code) for li in request.lines}, unedited)
