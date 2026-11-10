"""ConditionsCheck for capability B (SPEC 5.3): missing conditions,
conditions that contradict each other, and units that differ from the
catalog. Rules live in app/core/rules.yaml."""

from collections.abc import Iterable, Sequence

from app.api.schemas import ProposalLine
from app.core.hebrew import normalize_unit
from app.core.rules import ConditionRules
from app.core.validation import clean_code
from app.models.catalog import CatalogEntry
from app.models.review import CheckKind, CheckResult


# The app's library ids are `cond-<key>` (same as review_request_builder.dart).
CONDITION_ID_PREFIX = "cond-"


def library_conflicts(library_ids: Iterable[str], rules: ConditionRules) -> list[list[str]]:
    """The rules' contradicting pairs, as ids of the library the app sent;
    only groups with two or more of their conditions in it."""
    ids = set(library_ids)
    groups = []
    for conflict in rules.conflicts:
        present = [f"{CONDITION_ID_PREFIX}{k}" for k in conflict.keys if f"{CONDITION_ID_PREFIX}{k}" in ids]
        if len(present) > 1:
            groups.append(present)
    return groups


def _condition(label: str) -> str:
    """"תנאי <label>", without doubling the word when the label already
    starts with it ("תנאי תשלום" came out as "תנאי תנאי תשלום", 30.10.2026)."""
    return label if label.startswith("תנאי") else f"תנאי {label}"


def missing_conditions(
    lines: Sequence[ProposalLine],
    condition_keys: Iterable[str],
    rules: ConditionRules,
) -> list[CheckResult]:
    selected = set(condition_keys)
    results = [
        CheckResult(
            kind=CheckKind.missing_condition,
            facts=f"לא נבחר {_condition(cond.label)}, שצריך להופיע בכל הצעה.",
        )
        for cond in rules.always
        if cond.key not in selected
    ]
    codes = [clean_code(line.code) for line in lines]
    for rule in rules.rules:
        if selected & set(rule.require_any):
            continue
        triggering = [
            c for c in codes
            if c.startswith(tuple(rule.code_prefixes)) and c not in rule.except_codes
        ]
        if triggering:
            results.append(CheckResult(
                kind=CheckKind.missing_condition,
                line_code=triggering[0],
                facts=f"בהצעה יש {rule.work} ({len(triggering)} סעיפים), "
                      f"אבל לא נבחר {_condition(rule.label)}.",
            ))
    return results


def conflicting_conditions(
    condition_keys: Iterable[str], rules: ConditionRules
) -> list[CheckResult]:
    selected = set(condition_keys)
    return [
        CheckResult(
            kind=CheckKind.wording,
            facts=f"נבחרו שני תנאים שסותרים זה את זה: {conflict.label}.",
        )
        for conflict in rules.conflicts
        if len(selected & set(conflict.keys)) > 1
    ]


def unit_mismatches(
    lines: Sequence[ProposalLine], catalog: Iterable[CatalogEntry]
) -> list[CheckResult]:
    units = {clean_code(e.code): e.unit for e in catalog}
    results = []
    for line in lines:
        expected = units.get(clean_code(line.code))
        actual = normalize_unit(line.unit)
        if expected and actual and actual != normalize_unit(expected):
            results.append(CheckResult(
                kind=CheckKind.unit_mismatch,
                line_code=line.code,
                facts=f"היחידה בשורה היא {actual}, אבל הסעיף במחירון נמדד ב-{expected}.",
            ))
    return results
