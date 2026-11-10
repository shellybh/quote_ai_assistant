"""A+ conditions in the match branch, with a fake LLM (no Gemini)."""

import json

from app.core import confidence
from app.flows.proposal_flow import run_match_flow
from app.models.match import LibraryCondition
from tests.conftest import FakeLLM
from tests.test_match_flow import CATALOG, CORNICE, SEARCH, intake, pick

LIBRARY = [
    LibraryCondition(id="c-1", text="פיגום אינו כלול במחיר ההצעה."),
    LibraryCondition(id="c-2", text="אחריות לעבודה לשנתיים מיום המסירה."),
    LibraryCondition(id="c-3", text="התשלום לפי אבני הדרך המפורטות בהצעה."),
]


def intake_with(tasks, conditions):
    return json.dumps({"tasks": list(tasks), "conditions": list(conditions)}, ensure_ascii=False)


def cond(sentence, cid, conf="high"):
    return {"sentence": sentence, "condition_id": cid, "reason": "הסבר", "confidence": conf}


def matcher_with(picks, conds):
    return json.dumps({"matches": list(picks), "conditions": list(conds)}, ensure_ascii=False)


def run(intake_reply, matcher_reply, library=LIBRARY):
    i = FakeLLM(model="fake", replies=[intake_reply])
    m = FakeLLM(model="fake", replies=[matcher_reply])
    return run_match_flow("הודעה", CATALOG, i, m, SEARCH, library), i, m


def test_conditions_come_back_with_lines_in_one_matcher_call():
    result, i, m = run(
        intake_with([CORNICE], ["המחיר לא כולל פיגום", "אחריות לשנתיים"]),
        matcher_with([pick(1, "01.09.001.0230")], [cond(1, "c-1"), cond(2, "c-2", "medium")]),
    )
    assert (i.calls, m.calls) == (1, 1)
    assert result.lines[0].catalog_code == "01.09.001.0230"
    scaffolding, warranty = result.conditions
    assert (scaffolding.condition_id, scaffolding.source_text) == ("c-1", "המחיר לא כולל פיגום")
    assert not scaffolding.needs_review  # high: the app ticks it in advance
    assert warranty.needs_review  # medium: shown, not ticked
    assert result.unmatched_conditions == []
    # The Matcher saw the library and the sentences.
    assert "c-2 | אחריות לעבודה לשנתיים" in m.sent[0] and "משפט 1: המחיר לא כולל פיגום" in m.sent[0]


def test_unknown_id_null_and_skipped_sentence_are_unmatched():
    result, _, _ = run(
        intake_with([CORNICE], ["פינוי פסולת על חשבון המזמין", "חניה למשאית", "ביטוח מלא"]),
        # An invented id, a null, and no answer at all for sentence 3.
        matcher_with([pick(1, "01.09.001.0230")], [cond(1, "c-99"), cond(2, None, "low")]),
    )
    assert result.conditions == []
    assert result.unmatched_conditions == ["פינוי פסולת על חשבון המזמין", "חניה למשאית", "ביטוח מלא"]


def test_two_sentences_for_one_condition_give_one_suggestion_the_surer_one():
    result, _, _ = run(
        intake_with([], ["מקדמה [סכום1]", "יתרה בסיום"]),
        matcher_with([], [cond(1, "c-3", "medium"), cond(2, " c-3 ", "high")]),
    )
    [payment] = result.conditions
    assert payment.condition_id == "c-3" and payment.source_text == "יתרה בסיום"
    assert payment.confidence == confidence.for_condition("high")


def test_message_with_conditions_only_still_calls_the_matcher_once():
    result, i, m = run(intake_with([], ["אחריות לשנתיים"]), matcher_with([], [cond(1, "c-2")]))
    assert m.calls == 1 and result.lines == [] and result.warnings == []
    assert [c.condition_id for c in result.conditions] == ["c-2"]


def test_without_a_library_conditions_are_ignored_as_before():
    result, _, m = run(
        intake_with([CORNICE], ["המחיר לא כולל פיגום"]),
        matcher_with([pick(1, "01.09.001.0230")], [cond(1, "c-1")]),
        library=[],
    )
    assert result.conditions == [] and result.unmatched_conditions == []
    assert "(אין משפטי תנאים)" in m.sent[0]


def test_nothing_found_makes_no_matcher_call():
    result, _, m = run(intake_with([], []), matcher_with([], []))
    assert m.calls == 0 and result.warnings == ["לא זוהו עבודות בתיאור."]


def test_old_intake_reply_without_conditions_still_parses():
    result, _, _ = run(intake(CORNICE), matcher_with([pick(1, "01.09.001.0230")], []))
    assert result.lines and result.conditions == []


def test_low_pick_is_unmatched_so_the_app_offers_a_new_condition():
    result, _, _ = run(
        intake_with([], ["פינוי הפסולת על חשבון המזמין"]),
        matcher_with([], [cond(1, "c-1", "low")]),
    )
    assert result.conditions == [] and result.unmatched_conditions == ["פינוי הפסולת על חשבון המזמין"]


def test_contradicting_library_conditions_come_back_as_id_groups():
    # 2.11.2026: the app must not tick "waste not included" (always in a
    # proposal) when the message chose "waste included".
    from app.core.rules import get_rules
    from app.tools.conditions_check import library_conflicts
    rules = get_rules().conditions
    ids = ["cond-waste", "cond-waste_excluded", "cond-scaffolding_included", "cond-payment"]
    assert library_conflicts(ids, rules) == [["cond-waste", "cond-waste_excluded"]]
    assert library_conflicts(["c-1", "c-2"], rules) == []
    lib = [LibraryCondition(id=i, text="x") for i in ("cond-waste", "cond-waste_excluded")]
    result, _, _ = run(intake_with([], ["פינוי פסולת כלול"]),
                       matcher_with([], [cond(1, "cond-waste")]), lib)
    assert [c.condition_id for c in result.conditions] == ["cond-waste"]
    assert result.condition_conflicts == [["cond-waste", "cond-waste_excluded"]]
