"""Capability A, end to end (SPEC 5.1, "match" branch):

Intake (AI) -> CatalogSearch (code) -> Matcher, one call (AI) -> validation
and confidence (code) -> MatchResult, a draft for a person to approve.

A+ (SPEC 17.3): Intake also returns the condition sentences; the same
Matcher call picks a library condition for each. Code keeps only ids that
the app sent, one suggestion per condition, and computes the confidence.
"""

from collections.abc import Sequence

from crewai.llms.base_llm import BaseLLM

from app.agents.intake import run_intake
from app.agents.matcher import run_matcher
from app.core import confidence, tracing
from app.core.validation import (
    catalog_by_code,
    check_line,
    check_payment,
    clean_code,
    keep_stated_quantity,
    says_special_case,
)
from app.models.catalog import Candidate, CatalogEntry
from app.models.match import (
    ConditionPick,
    LibraryCondition,
    MatchedLine,
    MatchResult,
    SuggestedCondition,
    UnmatchedItem,
)
from app.core.rules import get_rules
from app.tools.catalog_search import CatalogSearch
from app.tools.conditions_check import library_conflicts

MAX_ITEMS = 15  # one Matcher call carries every item with its candidates
CANDIDATES = 15
SIMILAR = 3  # other codes offered in the app's "switch item" choice


def similar_codes(
    cands: Sequence[Candidate], chosen: str | None, alternatives: Sequence[str] = ()
) -> list[str]:
    """The Matcher's alternatives first, then the next search candidates.

    Every code comes from this item's own candidates (so it is in the
    catalog), in its catalog spelling, without the chosen code or repeats.
    """
    offered = {clean_code(c.code): c.code for c in cands}
    out: list[str] = []
    for key in [clean_code(a) for a in alternatives] + list(offered):
        if key in offered and key != chosen and offered[key] not in out:
            out.append(offered[key])
        if len(out) == SIMILAR:
            break
    return out


def check_conditions(
    sentences: Sequence[str],
    picks: Sequence[ConditionPick],
    library: Sequence[LibraryCondition],
) -> tuple[list[SuggestedCondition], list[str]]:
    """Every sentence ends up either as a library condition or unmatched.

    An id the app did not send is dropped (the sentence is unmatched); a
    sentence the model skipped is unmatched too, so the person still sees
    it. A "low" pick is unmatched as well: on the tuning set (31.10.2026) the
    model gave "low" when it fell back on the nearest condition for a
    sentence the library does not have, and then the app should offer a new
    condition with the text instead. Two sentences for one condition give
    one suggestion, the surer one.
    """
    ids = {c.id for c in library}
    by_sentence = {p.sentence: p for p in picks}
    chosen: dict[str, SuggestedCondition] = {}
    unmatched: list[str] = []
    for n, sentence in enumerate(sentences, start=1):
        pick = by_sentence.get(n)
        cid = pick.condition_id.strip() if pick and pick.condition_id else None
        if cid not in ids or pick.confidence == "low":
            unmatched.append(sentence)
            continue
        conf = confidence.for_condition(pick.confidence)
        if cid in chosen and chosen[cid].confidence >= conf:
            continue
        chosen[cid] = SuggestedCondition(
            condition_id=cid,
            source_text=sentence,
            reason=pick.reason,
            confidence=conf,
            needs_review=confidence.needs_review(conf),
        )
    return list(chosen.values()), unmatched


def match_items(
    text: str,
    catalog: Sequence[CatalogEntry],
    intake_llm: BaseLLM,
    matcher_llm: BaseLLM,
    search: CatalogSearch,
    library: Sequence[LibraryCondition] = (),
) -> MatchResult:
    """Each agent gets its own LLM: the output schema is set on the LLM.

    `library` empty (the app sent no conditions): lines only, as before.
    """
    with tracing.step("intake"):
        intake = run_intake(text, intake_llm)
    items = intake.tasks
    sentences = [s.strip() for s in intake.conditions if s.strip()] if library else []
    payment, warnings = check_payment(intake.payment, text) if library else ([], [])
    conflicts = library_conflicts((c.id for c in library), get_rules().conditions)
    if not items and not sentences:
        return MatchResult(payment=payment, condition_conflicts=conflicts,
                           warnings=warnings or ["לא זוהו עבודות בתיאור."])

    if len(items) > MAX_ITEMS:
        warnings.append(f"זוהו {len(items)} עבודות. הוצעו סעיפים רק ל-{MAX_ITEMS} הראשונות.")
        items = items[:MAX_ITEMS]

    with tracing.step("search"):
        index = search.index_for(catalog)
        candidates = [index.search(item.task, k=CANDIDATES) for item in items]
    with tracing.step("matcher"):
        reply = run_matcher(items, candidates, matcher_llm, sentences, library)
    picks = {p.item: p for p in reply.matches}
    conditions, unmatched_conditions = check_conditions(sentences, reply.conditions, library)
    by_code = catalog_by_code(catalog)
    special_items = {clean_code(s.code): s for s in get_rules().special_items}

    lines: list[MatchedLine] = []
    unmatched: list[UnmatchedItem] = []
    for n, (item, cands) in enumerate(zip(items, candidates), start=1):
        pick = picks.get(n)
        offered = {clean_code(c.code): c for c in cands}
        code = clean_code(pick.code) if pick and pick.code else None
        if code and code not in offered:
            # Only a code from this item's own candidates is accepted.
            warnings.append(f"הסעיף שהוצע עבור '{item.task}' לא היה ברשימת המועמדים, ולכן הוסר.")
            code = None
        if code and (special := special_items.get(code)) and not says_special_case(special.any_of, text):
            # "פינוי פסולת" is not others' existing debris (user, 3.11.2026):
            # a red row, priced by the owner as a free line.
            code = None
        if code is None:
            unmatched.append(UnmatchedItem(source_text=item.task, similar=similar_codes(cands, None)))
            continue

        quantity = keep_stated_quantity(item.quantity, text)
        check = check_line(item.task, code, quantity, item.unit, by_code)
        warnings.extend(check.warnings)
        if check.code is None:
            unmatched.append(UnmatchedItem(source_text=item.task, similar=similar_codes(cands, None)))
            continue
        alternatives = [a for a in pick.alternatives if clean_code(a) in offered]
        conf = confidence.combine(offered[code].search_score, pick.confidence, bool(alternatives))
        lines.append(MatchedLine(
            source_text=item.task,
            catalog_code=check.code,
            quantity=check.quantity,
            unit=check.unit,
            confidence=conf,
            needs_review=confidence.needs_review(conf) or not check.ok,
            reason=pick.reason,
            similar=similar_codes(cands, clean_code(check.code), pick.alternatives),
        ))
    return MatchResult(
        lines=lines,
        unmatched=[u.source_text for u in unmatched],
        unmatched_items=unmatched,
        conditions=conditions,
        unmatched_conditions=unmatched_conditions,
        payment=payment,
        condition_conflicts=conflicts,
        warnings=warnings,
    )
