"""Matcher agent: picks a catalog line for every work item, one call for all
(prompt v3: v2 from AI Studio + the stated quantity and unit, tuned on
match_tune 30.10.2026). Candidates come from CatalogSearch; no prices.

Prompt v4 (A+, SPEC 17.3): the same call also picks a library condition for
every condition sentence. The library is small, so it is sent whole, with
no search: one call per request stays (15 calls a minute on the free tier).
"""

from collections.abc import Sequence

from crewai.llms.base_llm import BaseLLM

from app.agents.base import load_prompt, render, run_structured
from app.models.catalog import Candidate
from app.models.match import LibraryCondition, MatcherResult, WorkItem

PROMPT = load_prompt("matcher")


def _number(value: float | None) -> str | None:
    if value is None:
        return None
    return str(int(value)) if float(value).is_integer() else str(value)


def format_items(items: Sequence[WorkItem], candidates: Sequence[Sequence[Candidate]]) -> str:
    blocks = []
    for n, (item, cands) in enumerate(zip(items, candidates, strict=True), start=1):
        said = " ".join(str(x) for x in (_number(item.quantity), item.unit) if x)
        head = f"עבודה {n}: {item.task}" + (f" (כמות: {said})" if said else "")
        lines = [head, "מועמדים:"]
        lines += [f"{c.code} | {c.unit} | {c.description}" for c in cands] or ["(אין מועמדים)"]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) or "(אין עבודות)"


def format_conditions(sentences: Sequence[str], library: Sequence[LibraryCondition]) -> str:
    if not sentences:
        return "(אין משפטי תנאים)"
    said = [f"משפט {n}: {s}" for n, s in enumerate(sentences, start=1)]
    lib = [f"{c.id} | {c.text}" for c in library]
    return "\n".join(said + ["", "ספריית התנאים:"] + lib)


def run_matcher(
    items: Sequence[WorkItem],
    candidates: Sequence[Sequence[Candidate]],
    llm: BaseLLM,
    sentences: Sequence[str] = (),
    library: Sequence[LibraryCondition] = (),
) -> MatcherResult:
    return run_structured(
        llm,
        role="מתאים סעיפי מחירון ותנאים",
        goal="לבחור לכל עבודה את סעיף המחירון המתאים, ולכל משפט תנאי את התנאי מהספרייה",
        description=render(
            PROMPT,
            items=format_items(items, candidates),
            conditions=format_conditions(sentences, library),
        ),
        output=MatcherResult,
    )
