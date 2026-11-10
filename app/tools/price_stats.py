"""Price checks for capability B (SPEC 5.3). Code only, on ratios.

The app computes the ratios on the phone (decided 30.10.2026), so no price
reaches this server; the thresholds stay here, in rules.yaml.

- History check: the line's unit price (after discount) against the median
  of the same code in previous proposals (`history_ratio`, `history_count`).
- CatalogPriceCheck: the same price against the catalog price
  (`catalog_ratio`); only extreme deviations (likely typos).

One price finding per line: a line flagged by the history check is not
flagged again by the catalog check. The facts carry ratios and counts only,
never an amount: they are what the Reviewer (Gemini) sees.
"""

from collections.abc import Iterable, Sequence

from app.api.schemas import ProposalLine
from app.core.rules import PriceRules
from app.models.review import CheckKind, CheckResult


def _ratio_text(ratio: float) -> str:
    if ratio >= 1:
        return f"גבוה פי {ratio:.1f}"
    return f"נמוך פי {1 / ratio:.1f}"


def history_price_check(lines: Sequence[ProposalLine], rules: PriceRules) -> list[CheckResult]:
    results = []
    for line in lines:
        ratio = line.history_ratio
        if ratio is None or line.history_count < rules.history_min_samples:
            continue
        if ratio > rules.history_max_ratio or ratio < 1 / rules.history_max_ratio:
            results.append(CheckResult(
                kind=CheckKind.price_vs_history,
                line_code=line.code,
                facts=f"מחיר היחידה {_ratio_text(ratio)} מהחציון של הסעיף "
                      f"ב-{line.history_count} הצעות קודמות.",
            ))
    return results


def catalog_price_check(
    lines: Sequence[ProposalLine],
    rules: PriceRules,
    already_flagged: Iterable[str] = (),
) -> list[CheckResult]:
    skip = set(already_flagged)
    results = []
    for line in lines:
        ratio = line.catalog_ratio
        if line.code in skip or ratio is None:
            continue
        if ratio > rules.catalog_max_ratio or ratio < rules.catalog_min_ratio:
            results.append(CheckResult(
                kind=CheckKind.price_vs_catalog,
                line_code=line.code,
                facts=f"מחיר היחידה {_ratio_text(ratio)} ממחיר המחירון של הסעיף. "
                      "ייתכן שזו טעות הקלדה.",
            ))
    return results
