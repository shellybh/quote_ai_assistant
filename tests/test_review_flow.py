"""Capability B end to end with a fake LLM (no Gemini)."""

import json
import logging

import pytest

from app.api.schemas import ProposalLine, ReviewRequest
from app.core.llm import LLMOutputError
from app.flows.proposal_flow import run_review_flow
from app.flows.review import FALLBACK
from app.models.catalog import CatalogEntry
from app.models.review import CheckKind, Severity
from eval.client_ratios import ratio_line
from tests.conftest import FakeLLM

ALWAYS = ["payment"]
FACADE = "01.09.001.0100"  # plaster renewal
STONE = "01.14.001.0060"

# Prices with distinctive digits, to search for them in what the model got.
PRICES = (98765.4, 43210.9, 56789.1, 12345.6, 777.7)


# The proposal as the phone holds it; the app turns it into ratios (as
# eval/client_ratios.py does) and only those are sent.
RAW_LINES = [
    {"code": FACADE, "description": "חידוש טיח על בסיס סיד", "unit": 'מ"ר', "quantity": 40,
     "unit_price": PRICES[0], "catalog_price": PRICES[1]},  # x2.3 of its history
    {"code": STONE, "description": "תיקונים לפי הצורך", "unit": 'מ"ר', "quantity": 12,
     "unit_price": PRICES[2], "discount_percent": 5, "catalog_price": PRICES[2]},
]
HISTORY = {FACADE: [PRICES[1]] * 3, STONE: list(PRICES[3:]) * 2}


def request(**overrides) -> ReviewRequest:
    body = {
        "lines": [ProposalLine(**ratio_line(li, HISTORY, {})) for li in RAW_LINES],
        "condition_keys": [*ALWAYS, "scaffolding_included", "hidden_defects"],
        "catalog": [CatalogEntry(code=FACADE, description="חידוש טיח", unit='מ"ר'),
                    CatalogEntry(code=STONE, description="שיקום קיר אבן", unit='מ"ר')],
    }
    return ReviewRequest(**{**body, **overrides})


def note(check, problem="בעיה", why="סיבה", suggestion="הצעה"):
    return {"check": check, "problem": problem, "why": why, "suggestion": suggestion}


def wording(line_code, problem="ניסוח מעורפל", why="סיבה", suggestion="הצעה"):
    return {"line_code": line_code, "problem": problem, "why": why, "suggestion": suggestion}


def reply(*notes, words=()):
    return json.dumps({"findings": list(notes), "wording": list(words)}, ensure_ascii=False)


def run(replies, req=None):
    llm = FakeLLM(model="fake", replies=replies)
    return run_review_flow(req or request(), llm), llm


def test_checks_are_phrased_and_wording_added():
    # run_checks order: history on
    # FACADE (check 1, x2.3), history on STONE (check 2, x8.2), and a vague
    # line on STONE. Output is sorted by severity.
    result, llm = run([reply(
        note(1, problem="מחיר היחידה גבוה פי 2.3 מהחציון."),
        note(2, problem="המחיר גבוה פי 8.2 מהחציון."),
        words=[wording(STONE, problem='התיאור "תיקונים לפי הצורך" לא מגדיר היקף.')],
    )])
    assert llm.calls == 1
    kinds = [(f.kind, f.line_code) for f in result.findings]
    assert kinds == [
        (CheckKind.price_vs_history, FACADE),
        (CheckKind.price_vs_history, STONE),
        (CheckKind.wording, STONE),
    ]
    assert [f.severity for f in result.findings] == [Severity.medium, Severity.medium, Severity.low]
    assert result.findings[0].problem == "מחיר היחידה גבוה פי 2.3 מהחציון."


def test_no_price_reaches_the_server_or_the_model():
    sent = request().model_dump_json()
    for price in PRICES:
        assert str(int(price)) not in sent
    _, llm = run([reply()])
    [prompt] = llm.sent
    for price in PRICES:
        for text in (str(price), f"{price:.0f}", str(int(price))):
            assert text not in prompt
    # It does see the ratio and the line descriptions.
    assert "פי 2.3" in prompt and "תיקונים לפי הצורך" in prompt


def test_dropped_check_gets_a_fallback_finding():
    result, _ = run([reply()])  # the Reviewer returned nothing
    assert [(f.kind, f.line_code) for f in result.findings] == [
        (CheckKind.price_vs_history, FACADE), (CheckKind.price_vs_history, STONE),
    ]
    first = result.findings[0]
    assert "פי 2.3" in first.problem
    assert (first.why, first.suggestion) == FALLBACK[CheckKind.price_vs_history]


def test_blank_or_money_note_is_replaced_by_the_fallback():
    result, _ = run([reply(
        note(1, why="  "),
        note(2, suggestion='להוריד את המחיר ל-500 ש"ח.'),
    )])
    assert [f.why for f in result.findings] == [FALLBACK[CheckKind.price_vs_history][0]] * 2


def test_kind_and_line_code_come_from_the_check():
    result, _ = run([reply(note(2, problem="ניסוח"), note(9), note(2, problem="שוב"))])
    assert (result.findings[1].kind, result.findings[1].line_code) == (CheckKind.price_vs_history, STONE)
    assert result.findings[1].problem == "ניסוח"  # the first note for a check wins; 9 is ignored


def test_wording_only_on_lines_of_this_proposal():
    result, _ = run([reply(words=[
        wording("01.70.001.0010"),                   # not a line of this proposal
        wording(STONE),
        wording(STONE),                              # duplicate
        wording(None, problem="שני תנאים סותרים."),
        wording(FACADE, why=""),                     # incomplete: dropped
    ])])
    extra = [(f.kind, f.line_code) for f in result.findings if f.kind is CheckKind.wording]
    assert extra == [(CheckKind.wording, STONE), (CheckKind.wording, None)]


def test_missing_condition_comes_first():
    req = request(condition_keys=["scaffolding_included", "hidden_defects"])
    result, _ = run([reply()], req)
    assert result.findings[0].kind is CheckKind.missing_condition
    assert result.findings[0].severity is Severity.high


def test_clean_proposal_still_asks_for_wording_once():
    req = request(lines=[ProposalLine(code=FACADE, description="חידוש טיח", unit='מ"ר',
                                      quantity=10, catalog_ratio=1.0)])
    result, llm = run([reply()], req)
    assert result.findings == [] and llm.calls == 1
    assert "(אין ממצאים)" in llm.sent[0]


def test_malformed_output_retries_once_then_raises():
    with pytest.raises(LLMOutputError):
        run(["not json", "{bad"])


def test_output_has_no_amount():
    result, _ = run([reply(note(2))])
    dumped = result.model_dump_json()
    for price in PRICES:
        assert str(int(price)) not in dumped


def test_trace_line_has_no_content(caplog):
    with caplog.at_level(logging.INFO, logger="price_ai.trace"):
        run([reply(words=[wording(STONE)])])
    [line] = [r.getMessage() for r in caplog.records if r.name == "price_ai.trace"]
    assert line.startswith("trace review ") and "llm_calls=1" in line and line.endswith(" ok")
    assert "checks=" in line and "reviewer=" in line and "merge=" in line
    for secret in (FACADE, STONE, "טיח", "תיקונים", str(int(PRICES[0]))):
        assert secret not in line


def test_trace_records_the_failure_class_only(caplog):
    with caplog.at_level(logging.INFO, logger="price_ai.trace"), pytest.raises(LLMOutputError):
        run(["not json"])
    [line] = [r.getMessage() for r in caplog.records if r.name == "price_ai.trace"]
    assert line.endswith(" LLMOutputError") and "llm_calls=2" in line


def test_catalog_wording_is_marked_and_never_called_vague():
    # FACADE keeps the catalog text; STONE's description was edited.
    req = request(catalog=[CatalogEntry(code=FACADE, description="חידוש טיח על בסיס סיד", unit='מ"ר'),
                           CatalogEntry(code=STONE, description="שיקום קיר אבן", unit='מ"ר')])
    result, llm = run([reply(words=[wording(FACADE), wording(STONE)])], req)
    assert "חידוש טיח על בסיס סיד [נוסח המחירון]" in llm.sent[0]
    assert "תיקונים לפי הצורך [נוסח המחירון]" not in llm.sent[0]
    assert [f.line_code for f in result.findings if f.kind is CheckKind.wording] == [STONE]


def test_conflict_from_code_is_not_doubled_by_the_model():
    keys = [*ALWAYS, "scaffolding_included", "scaffolding_excluded", "hidden_defects"]
    result, _ = run([reply(words=[wording(None, problem="תנאי הפיגום סותרים.")])],
                    request(condition_keys=keys))
    conflicts = [f for f in result.findings if f.kind is CheckKind.wording and f.line_code is None]
    assert len(conflicts) == 1 and "פיגום" in conflicts[0].problem  # the code check's facts


def test_letters_of_other_scripts_are_removed():
    result, _ = run([reply(note(1, problem="אי-הتאמה ביחידות", suggestion="להתანּות את הסעיף"))])
    history = result.findings[0]
    assert history.problem == "אי-האמה ביחידות" and history.suggestion == "להתות את הסעיף"
    # Hebrew punctuation survives (and is normalized).
    result, _ = run([reply(note(1, problem="נמדד ב-מ״ר – פי 2.1"))])
    assert result.findings[0].problem == 'נמדד ב-מ"ר - פי 2.1'


class RateLimitedLLM(FakeLLM):
    def call(self, *args, **kwargs):
        self.calls += 1
        error = RuntimeError("429 RESOURCE_EXHAUSTED: per-minute limit")
        raise ValueError("LLM call failed") from error


def test_gemini_rate_limit_becomes_llm_rate_limited():
    from app.core.llm import LLMRateLimited
    llm = RateLimitedLLM(model="fake", replies=[""])
    with pytest.raises(LLMRateLimited):
        run_review_flow(request(), llm)
    assert llm.calls == 1  # no retry into a rate limit


def test_shekel_sign_note_is_replaced_by_the_fallback():
    # The cleaning step strips "₪"; the money check runs before it (7.11.2026).
    result, _ = run([reply(note(1, suggestion="להוריד את המחיר ל-500 ₪."))])
    assert result.findings[0].why == FALLBACK[CheckKind.price_vs_history][0]
    assert not any("500" in f.suggestion for f in result.findings)
