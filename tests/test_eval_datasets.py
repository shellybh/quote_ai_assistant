"""The evaluation sets are well formed (no Gemini calls)."""

import json
from pathlib import Path

import pytest

from app.api.schemas import ReviewRequest
from app.models.review import CheckKind
from eval.client_ratios import ratio_line

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "eval" / "datasets"
CODES = {c["code"] for c in json.loads((ROOT / "data/demo/catalog.json").read_text(encoding="utf-8"))["items"]}


def _cases(name):
    path = DATASETS / name
    if not path.exists():
        pytest.skip(f"{name} not written yet")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.mark.parametrize("name", ["match_tune.jsonl", "match_test.jsonl"])
def test_match_set(name):
    cases = _cases(name)
    assert len({c["id"] for c in cases}) == len(cases)
    for case in cases:
        assert case["text"] and case["items"]
        for item in case["items"]:
            assert item["phrase"]
            assert set(item["codes"]) <= CODES, case["id"]


@pytest.mark.parametrize("name", ["review_tune.jsonl", "review_test.jsonl"])
def test_review_set(name):
    cases = _cases(name)
    assert len({c["id"] for c in cases}) == len(cases)
    for case in cases:
        # The sets hold prices, as the phone does; what is sent is ratios.
        ReviewRequest(lines=[ratio_line(li, {}, {}) for li in case["lines"]],
                      condition_keys=case["condition_keys"])
        codes = {line["code"] for line in case["lines"]}
        for error in case["errors"]:
            assert CheckKind(error["kind"])
            assert error["line_code"] is None or error["line_code"] in codes


def test_tune_and_test_use_different_proposals():
    tune = {c["base_proposal"] for c in _cases("review_tune.jsonl")}
    test = {c["base_proposal"] for c in _cases("review_test.jsonl")}
    assert not tune & test


KEYS = {c["key"] for c in json.loads((ROOT / "data/demo/conditions.json").read_text(encoding="utf-8"))["items"]}


@pytest.mark.parametrize("name", ["aplus_tune.jsonl", "aplus_test.jsonl"])
def test_aplus_set(name):
    cases = _cases(name)
    assert len({c["id"] for c in cases}) == len(cases)
    for case in cases:
        assert case["text"]
        assert set(case["conditions"]) <= KEYS, case["id"]
        assert all(u in case["text"] for u in case["unmatched_conditions"]), case["id"]
        # Text as the server gets it: amounts already masked on the phone.
        assert not any(w in case["text"] for w in ("₪", 'ש"ח', "שקל")), case["id"]
        stages = case["payment"]
        assert sum(bool(s.get("is_remainder")) for s in stages) <= 1, case["id"]
        for s in stages:
            # Each stage is exactly one of: a percent, an amount label, the remainder.
            kinds = [k for k in ("percent", "amount_ref", "is_remainder") if s.get(k) is not None]
            assert len(kinds) == 1, case["id"]
            assert s.get("amount_ref") is None or s["amount_ref"] in case["text"]
            assert s.get("percent") is None or 0 < s["percent"] <= 100
        # Payment terms said -> the general payment condition (user, 31.10.2026).
        assert ("payment" in case["conditions"]) == bool(stages), case["id"]


def test_aplus_tune_and_test_do_not_share_a_message():
    tune = {c["text"] for c in _cases("aplus_tune.jsonl")}
    assert not tune & {c["text"] for c in _cases("aplus_test.jsonl")}


def test_aplus_natural_payment_set():
    for case in _cases("aplus_natural.jsonl"):
        for plan in [case["payment"], *case.get("payment_also", [])]:
            assert sum(bool(s.get("is_remainder")) for s in plan) <= 1, case["id"]
            for s in plan:
                kinds = [k for k in ("percent", "amount_ref", "is_remainder") if s.get(k) is not None]
                assert len(kinds) == 1, case["id"]
                assert s.get("amount_ref") is None or s["amount_ref"] in case["text"]
