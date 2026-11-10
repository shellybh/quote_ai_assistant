import json
from pathlib import Path

import pytest

from pydantic import ValidationError

from app.api.schemas import ProposalLine, ReviewRequest
from app.core.rules import get_rules, load_rules
from app.models.catalog import CatalogEntry
from app.models.review import CheckKind
from app.tools.conditions_check import conflicting_conditions, missing_conditions, unit_mismatches
from app.tools.price_stats import catalog_price_check, history_price_check
from app.tools.review_checks import run_checks
from eval.client_ratios import price_history, ratio_line

DEMO = Path(__file__).resolve().parents[1] / "data" / "demo"
RULES = get_rules()
ALWAYS = ["payment"]
FACADE_CODE = "01.09.001.0100"  # plaster renewal: scaffolding, samples


def line(code=FACADE_CODE, unit='מ"ר', history_ratio=None, history_count=0, catalog_ratio=1.0):
    return ProposalLine(code=code, description="x", unit=unit, quantity=10,
                        history_ratio=history_ratio, history_count=history_count,
                        catalog_ratio=catalog_ratio)


# --- rules file -------------------------------------------------------------

def test_rules_file_loads_and_uses_known_condition_keys():
    rules = load_rules()
    keys = {c["key"] for c in json.loads((DEMO / "conditions.json").read_text(encoding="utf-8"))["items"]}
    used = {c.key for c in rules.conditions.always}
    for rule in rules.conditions.rules:
        used |= set(rule.require_any)
    for conflict in rules.conditions.conflicts:
        used |= set(conflict.keys)
    assert used <= keys


# --- history check (ratios computed in the app) ----------------------------

def test_history_flags_high_and_low_but_not_normal():
    lines = [line("A", history_ratio=1.6, history_count=4), line("A", history_ratio=0.6, history_count=4),
             line("A", history_ratio=1.2, history_count=4)]
    flagged = history_price_check(lines, RULES.price)
    assert [r.facts.split()[2] for r in flagged] == ["גבוה", "נמוך"]
    assert all(r.kind is CheckKind.price_vs_history for r in flagged)


def test_history_needs_minimum_samples_and_a_ratio():
    assert history_price_check([line("A", history_ratio=5, history_count=2)], RULES.price) == []
    assert history_price_check([line("A", history_ratio=None, history_count=9)], RULES.price) == []


def test_facts_have_ratio_and_count_only():
    [result] = history_price_check([line("A", history_ratio=2.13, history_count=6)], RULES.price)
    assert result.facts == "מחיר היחידה גבוה פי 2.1 מהחציון של הסעיף ב-6 הצעות קודמות."


# --- no price reaches the server -------------------------------------------

@pytest.mark.parametrize("field", ["unit_price", "discount_percent", "catalog_price", "line_total"])
def test_a_line_with_a_price_field_is_refused(field):
    with pytest.raises(ValidationError):
        ProposalLine(code="A", description="x", unit="יח'", quantity=1, **{field: 100})


def test_a_request_with_price_history_is_refused():
    with pytest.raises(ValidationError):
        ReviewRequest(lines=[line()], price_history=[{"code": "A", "unit_price": 100}])


# --- what the app computes (mirrored in eval/client_ratios.py) -------------

def test_client_ratio_uses_price_after_discount_and_other_proposals_only():
    proposals = [
        {"id": "p1", "line_items": [{"code": "A", "unit_price": 100, "discount_percent": 0}]},
        {"id": "p2", "line_items": [{"code": "A", "unit_price": 200, "discount_percent": 50}]},
        {"id": "me", "line_items": [{"code": "A", "unit_price": 9999, "discount_percent": 0}]},
    ]
    history = price_history(proposals, exclude_id="me")
    assert history == {"A": [100, 100]}
    li = {"code": "A", "description": "x", "unit": "יח'", "quantity": 2,
          "unit_price": 300, "discount_percent": 50, "catalog_price": 75}
    sent = ratio_line(li, history, {})
    assert sent == {"code": "A", "description": "x", "unit": "יח'", "quantity": 2,
                    "history_ratio": 1.5, "history_count": 2, "catalog_ratio": 2.0}
    assert ratio_line({**li, "code": "B"}, history, {})["history_ratio"] is None


# --- CatalogPriceCheck ------------------------------------------------------

@pytest.mark.parametrize(("ratio", "flagged"), [(1.0, False), (0.49, True), (2.01, True), (0.5, False), (2.0, False)])
def test_catalog_check_flags_only_extremes(ratio, flagged):
    assert bool(catalog_price_check([line(catalog_ratio=ratio)], RULES.price)) is flagged


def test_catalog_check_skips_lines_already_flagged_and_unknown_catalog_price():
    lines = [line("A", catalog_ratio=10), line("B", catalog_ratio=None)]
    assert catalog_price_check(lines, RULES.price, already_flagged=["A"]) == []


def test_one_price_finding_per_line():
    req = ReviewRequest(
        lines=[line("A", history_ratio=10, history_count=3, catalog_ratio=10)],
        condition_keys=ALWAYS,
    )
    kinds = [r.kind for r in run_checks(req)]
    assert kinds == [CheckKind.price_vs_history]


# --- ConditionsCheck --------------------------------------------------------

def test_always_conditions():
    [found] = missing_conditions([line("01.24.001.0010")], [], RULES.conditions)
    assert found.line_code is None and "תנאי תשלום" in found.facts
    # Validity and VAT are not conditions (31.10.2026): the PDF shows both.
    assert missing_conditions([line("01.24.001.0010")], ["payment"], RULES.conditions) == []


def test_stone_work_needs_hidden_defects():
    [r] = missing_conditions([line("01.14.001.0060")], ALWAYS, RULES.conditions)
    assert r.line_code == "01.14.001.0060" and "ליקויים נסתרים" in r.facts
    assert missing_conditions([line("01.14.001.0060")], [*ALWAYS, "hidden_defects"], RULES.conditions) == []


def test_roof_sealing_needs_warranty():
    [r] = missing_conditions([line("01.05.003.0008")], ALWAYS, RULES.conditions)
    assert "אחריות" in r.facts


def test_scaffolding_and_samples_are_on_request_only():
    # The owner (30.10.2026): facade plaster does not demand either condition.
    assert missing_conditions([line()], ALWAYS, RULES.conditions) == []


def test_catalog_check_is_off_by_the_owners_answer():
    assert RULES.price.catalog_check_enabled is False
    req = ReviewRequest(lines=[line(catalog_ratio=10)], condition_keys=ALWAYS)  # x10 of catalog
    assert run_checks(req) == []


def test_conflicting_conditions():
    both = [*ALWAYS, "scaffolding_included", "scaffolding_excluded"]
    [r] = conflicting_conditions(both, RULES.conditions)
    assert r.kind is CheckKind.wording and r.line_code is None and "פיגום" in r.facts
    assert conflicting_conditions([*ALWAYS, "scaffolding_included"], RULES.conditions) == []
    [r] = conflicting_conditions([*ALWAYS, "waste", "waste_excluded"], RULES.conditions)
    assert "פסולת" in r.facts


def test_unit_mismatch():
    catalog = [CatalogEntry(code=FACADE_CODE, description="x", unit='מ"ר')]
    assert unit_mismatches([line(unit="מטר רבוע")], catalog) == []
    [r] = unit_mismatches([line(unit="מטר")], catalog)
    assert r.kind is CheckKind.unit_mismatch and r.line_code == FACADE_CODE


# --- the clean demo proposals raise nothing --------------------------------

def test_clean_demo_proposals_have_no_findings():
    catalog = json.loads((DEMO / "catalog.json").read_text(encoding="utf-8"))["items"]
    prices = {c["code"]: c["base_price"] for c in catalog}
    proposals = json.loads((DEMO / "proposals.json").read_text(encoding="utf-8"))["items"]
    entries = [CatalogEntry(**c) for c in catalog]
    for p in proposals:
        history = price_history(proposals, exclude_id=p["id"])
        req = ReviewRequest(
            lines=[ratio_line(li, history, prices) for li in p["line_items"]],
            condition_keys=[c.removeprefix("cond-") for c in p["condition_ids"]],
            catalog=entries,
        )
        assert run_checks(req) == [], p["id"]


def test_missing_condition_does_not_double_the_word_condition():
    # Seen on the phone (30.10.2026): "לא נבחר תנאי תנאי תשלום".
    facts = [r.facts for r in missing_conditions([], [], RULES.conditions)]
    assert any("לא נבחר תנאי תשלום," in f for f in facts)
    assert not any("תנאי תנאי" in f for f in facts)
