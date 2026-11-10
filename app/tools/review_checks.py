"""All capability-B code checks in one call (the B baseline, and the first
step of the review branch of the Flow)."""

from app.api.schemas import ReviewRequest
from app.core.rules import Rules, get_rules
from app.models.review import CheckResult
from app.tools.conditions_check import conflicting_conditions, missing_conditions, unit_mismatches
from app.tools.price_stats import catalog_price_check, history_price_check


def run_checks(request: ReviewRequest, rules: Rules | None = None) -> list[CheckResult]:
    rules = rules or get_rules()
    history = history_price_check(request.lines, rules.price)
    catalog = []
    if rules.price.catalog_check_enabled:
        catalog = catalog_price_check(
            request.lines, rules.price, already_flagged=(r.line_code for r in history)
        )
    return [
        *missing_conditions(request.lines, request.condition_keys, rules.conditions),
        *conflicting_conditions(request.condition_keys, rules.conditions),
        *unit_mismatches(request.lines, request.catalog),
        *history,
        *catalog,
    ]
