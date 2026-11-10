"""A+ payment stages: Intake says kind + value, code checks and converts
them; never an amount (no Gemini)."""

import json

import pytest

from app.core.validation import check_payment
from app.flows.proposal_flow import run_match_flow
from app.models.match import SaidPaymentStage
from tests.conftest import FakeLLM
from tests.test_conditions_flow import LIBRARY, intake_with, matcher_with, run
from tests.test_match_flow import CATALOG, SEARCH

TEXT = "מקדמה [סכום1], 30% באמצע, יתרה בסיום."
REFUSED = ["תנאי התשלום לא נקראו בבירור. אפשר להזין אותם בעצמך."]


def said(kind, value=None, description="שלב"):
    return SaidPaymentStage(description=description, kind=kind, value=value)


def test_good_stages_pass_in_order():
    stages, warnings = check_payment(
        [said("amount", " [סכום1] ", "מקדמה"), said("percent", "30%", "באמצע"),
         said("remainder", "is_remainder", "בסיום")],
        TEXT,
    )
    assert warnings == []
    assert [(s.description, s.percent, s.amount_ref, s.is_remainder) for s in stages] == [
        ("מקדמה", None, "[סכום1]", False), ("באמצע", 30, None, False), ("בסיום", None, None, True)]


@pytest.mark.parametrize("bad", [
    said("amount", "[סכום2]"),     # a label the text does not have
    said("amount", "10000"),       # a number: never an amount
    said("percent", "0"), said("percent", "150"), said("percent", "שלושים"),
    said("percent", None),
    said("percent", "30", "  "),   # no description
])
def test_any_broken_stage_drops_the_whole_plan(bad):
    stages, warnings = check_payment([said("percent", "50"), bad], TEXT)
    assert stages == [] and warnings == REFUSED


def test_two_remainders_are_refused():
    assert check_payment([said("remainder"), said("remainder")], TEXT) == ([], REFUSED)


PLAN = [{"description": "מקדמה", "kind": "amount", "value": "[סכום1]"},
        {"description": "בסיום", "kind": "remainder", "value": None}]


def _intake(payment, conditions=("מקדמה [סכום1], יתרה בסיום",)):
    reply = json.loads(intake_with([], list(conditions)))
    reply["payment"] = payment
    return json.dumps(reply, ensure_ascii=False)


def test_payment_with_its_label_in_the_text():
    i = FakeLLM(model="fake", replies=[_intake(PLAN)])
    m = FakeLLM(model="fake", replies=[matcher_with([], [])])
    result = run_match_flow("מקדמה [סכום1], יתרה בסיום", CATALOG, i, m, SEARCH, LIBRARY)
    assert [(s.amount_ref, s.is_remainder) for s in result.payment] == [("[סכום1]", False), (None, True)]


def test_a_label_the_message_does_not_have_refuses_the_plan():
    # run() sends the text "הודעה": no [סכום1] in it.
    result, _, _ = run(_intake(PLAN), matcher_with([], [{"sentence": 1, "condition_id": "c-3",
                                                         "reason": "", "confidence": "high"}]))
    assert result.payment == [] and result.warnings == REFUSED
    assert [c.condition_id for c in result.conditions] == ["c-3"], "the conditions still come back"


def test_no_library_no_payment():
    result, _, _ = run(_intake(PLAN), matcher_with([], []), library=[])
    assert result.payment == []


# --- decision c (2.11.2026): a percent must be said in the message -----------

from app.core.validation import stated_percents  # noqa: E402


def test_percent_words_and_parts_are_said():
    assert {30.0} <= stated_percents("שלושים אחוז מקדמה, והשאר בסוף העבודה.")
    assert 25.0 in stated_percents("עשרים וחמישה אחוז מקדמה.")
    assert 15.0 in stated_percents("חמש עשרה אחוז בהזמנה")
    assert 50.0 in stated_percents("חצי בתחילת העבודה וחצי בסיום.")
    assert any(abs(p - 33.3) < 0.5 for p in stated_percents("שליש בחתימה ושליש באמצע"))
    assert any(abs(p - 66.7) < 0.5 for p in stated_percents("שני שלישים בסוף"))
    assert 75.0 in stated_percents("שלושה רבעים בגמר")
    assert 25.0 in stated_percents("רבע מהסכום מראש")
    assert 70.0 in stated_percents("ושבעים בסיום")


def test_an_invented_plan_is_dropped_silently():
    # Seen on the A+ test set (bt06): no payment in the message.
    stages, warnings = check_payment(
        [said("percent", "30", "מקדמה"), said("remainder", None, "בסיום")],
        "ניקוי חזית אבן, 50 מ\"ר. הפיגום כלול.")
    assert (stages, warnings) == ([], [])


def test_a_plan_with_one_invented_percent_is_dropped_with_the_warning():
    stages, warnings = check_payment(
        [said("percent", "30", "מקדמה"), said("percent", "40", "באמצע"), said("remainder", None, "בסוף")],
        "30% מקדמה, עוד חלק באמצע והשאר בסוף.")
    assert (stages, warnings) == ([], REFUSED)


@pytest.mark.parametrize("text,stages", [
    ("שלושים אחוז מקדמה, והשאר בסוף העבודה.", [("percent", "30"), ("remainder", None)]),
    ("חצי בתחילת העבודה וחצי בסיום.", [("percent", "50"), ("percent", "50")]),
    ("שליש בחתימה, שליש באמצע ושליש בגמר.", [("percent", "33.3"), ("percent", "33.33"), ("remainder", None)]),
    ("עשרים וחמישה אחוז מקדמה. אחרי הטיח עוד [סכום1].", [("percent", "25"), ("amount", "[סכום1]")]),
    ("משלמים הכול בסוף, תוך 30 יום מהחשבון.", [("percent", "100")]),
    ("תשלום אחד בסיום העבודה.", [("percent", "100")]),
])
def test_said_percents_are_kept(text, stages):
    kept, warnings = check_payment([said(k, v) for k, v in stages], text)
    assert len(kept) == len(stages) and warnings == []
