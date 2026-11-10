"""Capability A end to end with a fake LLM and no embeddings (no Gemini)."""

import json
from pathlib import Path

import pytest

from app.core import confidence
from app.core.llm import LLMOutputError
from app.flows.proposal_flow import run_match_flow
from app.models.catalog import CatalogEntry
from app.tools.catalog_search import CatalogSearch
from tests.conftest import FakeLLM

ITEMS = json.loads(
    (Path(__file__).resolve().parents[1] / "data/demo/catalog.json").read_text(encoding="utf-8")
)["items"]
CATALOG = [CatalogEntry(**c) for c in ITEMS]
SEARCH = CatalogSearch(embedder=None)  # BM25 only

CORNICE = {"task": "ייצוב ושיקום קרניז 3 מדרגות", "quantity": 12, "unit": "מטר", "location": "חזית"}
CAMERAS = {"task": "התקנת מצלמות אבטחה", "quantity": None, "unit": None, "location": None}


def intake(*tasks):
    return json.dumps({"tasks": list(tasks)}, ensure_ascii=False)


def matcher(*picks):
    return json.dumps({"matches": list(picks)}, ensure_ascii=False)


def pick(item, code, confidence="high", alternatives=()):
    return {"item": item, "code": code, "alternatives": list(alternatives),
            "reason": "הסבר קצר", "confidence": confidence}


def run(intake_replies, matcher_replies, text="תיאור"):
    i, m = FakeLLM(model="fake", replies=intake_replies), FakeLLM(model="fake", replies=matcher_replies)
    return run_match_flow(text, CATALOG, i, m, SEARCH), i, m


def test_happy_path_one_line_and_one_unmatched():
    result, i, m = run(
        [intake(CORNICE, CAMERAS)],
        [matcher(pick(1, "01.09.001.0230", "medium", ["01.09.001.0240"]), pick(2, None, "low"))],
        text="ייצוב ושיקום קרניז 3 מדרגות בחזית, כ-12 מטר. התקנת מצלמות אבטחה.",
    )
    assert (i.calls, m.calls) == (1, 1)  # one Intake call, one Matcher call for all items
    [line] = result.lines
    assert line.catalog_code == "01.09.001.0230"
    assert line.unit == "מ'" and line.quantity == 12  # "מטר" -> catalog unit, no warning
    assert 0 <= line.confidence <= 1
    assert result.unmatched == ["התקנת מצלמות אבטחה"]


def test_similar_codes_offer_alternatives_first_then_search_candidates():
    result, _, _ = run(
        [intake(CORNICE, CAMERAS)],
        # One alternative is real and offered, one is invented, one repeats the pick.
        [matcher(pick(1, "01.09.001.0230", "medium", ["99.99.999.9999", "01.09.001.0240", "01.09.001.0230"]),
                 pick(2, None, "low"))],
    )
    [line] = result.lines
    assert line.similar[0] == "01.09.001.0240"  # the Matcher's own alternative leads
    assert len(line.similar) == 3 and len(set(line.similar)) == 3
    assert "01.09.001.0230" not in line.similar and "99.99.999.9999" not in line.similar
    codes = {c.code for c in CATALOG}
    assert set(line.similar) <= codes
    # The red line gets the nearest search candidates, not an empty choice.
    [cameras] = result.unmatched_items
    assert cameras.source_text == CAMERAS["task"] and len(cameras.similar) == 3
    assert set(cameras.similar) <= codes
    assert result.unmatched == [CAMERAS["task"]]  # the plain list is unchanged


def test_code_outside_the_items_candidates_is_dropped():
    # A real catalog code, but not one the search offered for this item.
    result, _, _ = run([intake(CORNICE)], [matcher(pick(1, "01.70.001.0010"))])
    assert result.lines == [] and result.unmatched == [CORNICE["task"]]
    assert any("לא היה ברשימת המועמדים" in w for w in result.warnings)


def test_invented_code_is_dropped():
    result, _, _ = run([intake(CORNICE)], [matcher(pick(1, "99.99.999.9999"))])
    assert result.lines == []


def test_missing_pick_counts_as_unmatched():
    result, _, _ = run([intake(CORNICE, CAMERAS)], [matcher(pick(1, "01.09.001.0230"))])
    assert result.unmatched == [CAMERAS["task"]]


def test_bad_quantity_is_emptied_and_flagged():
    bad = {**CORNICE, "quantity": -4}
    result, _, _ = run([intake(bad)], [matcher(pick(1, "01.09.001.0230"))])
    [line] = result.lines
    assert line.quantity is None and line.needs_review


def test_no_work_items_skips_the_matcher():
    result, _, m = run([intake()], [matcher()])
    assert m.calls == 0 and result.lines == [] and result.warnings


def test_malformed_output_retries_once_then_raises():
    with pytest.raises(LLMOutputError):
        run(["not json"], [matcher()])


def test_matcher_retry_recovers():
    result, _, m = run([intake(CORNICE)], ["{bad", matcher(pick(1, "01.09.001.0230"))])
    assert m.calls == 2 and result.lines


def test_output_has_no_price():
    result, _, _ = run([intake(CORNICE)], [matcher(pick(1, "01.09.001.0230"))])
    dumped = result.model_dump_json()
    for word in ("price", "amount", "total", "מחיר", "סכום"):
        assert word not in dumped


def test_braces_in_text_do_not_break_the_prompt():
    result, _, _ = run([intake(CORNICE)], [matcher(pick(1, "01.09.001.0230"))], text="טיח {x} {{y}}")
    assert result.lines


def test_confidence_combine():
    assert confidence.combine(100, "high", False) == 1.0
    assert confidence.combine(0, "low", False) < confidence.REVIEW_BELOW
    # Alternatives cap the model's part at "medium".
    assert confidence.combine(80, "high", True) == confidence.combine(80, "medium", False)


def test_quantity_not_written_in_the_text_is_not_stated():
    # Seen live (30.10.2026): "replace a stone window sill" came back as 1.
    sill = {"task": "החלפת אדן חלון אבן", "quantity": 1, "unit": None, "location": None}
    result, _, _ = run([intake(CORNICE, sill)],
                       [matcher(pick(1, "01.09.001.0230"), pick(2, "01.19.001.0070"))],
                       text="קרניז 12 מטר, החלפת אדן חלון אבן")
    cornice, window = result.lines
    assert cornice.quantity == 12  # written, kept
    assert window.quantity is None and window.needs_review  # the app asks
    assert "לא צוינה כמות עבור 'החלפת אדן חלון אבן'." in result.warnings


WASTE = {"task": "פינוי פסולת", "quantity": None, "unit": None, "location": None}
OTHERS_DEBRIS = "01.24.040.0010"


def test_others_debris_item_needs_the_message_to_say_so():
    # Tuning set, 3.11.2026: the bare "פינוי פסולת" got the others'-debris
    # item in 3 of 4 runs. Our own waste has no catalog item: a red row.
    result, _, _ = run([intake(WASTE)], [matcher(pick(1, OTHERS_DEBRIS, "medium"))],
                       text="חידוש צבע סיד בחדר המדרגות. תוסיף פינוי פסולת.")
    assert result.lines == [] and result.unmatched == ["פינוי פסולת"]
    [red] = result.unmatched_items
    assert len(red.similar) == 3  # the red row still offers codes to choose


def test_others_debris_item_kept_when_the_message_says_old_debris():
    old = {"task": "פינוי פסולת ישנה מהדיירים הקודמים", "quantity": 8, "unit": "קוב", "location": None}
    result, _, _ = run([intake(old)], [matcher(pick(1, OTHERS_DEBRIS))],
                       text="בחצר נשארה פסולת ישנה מהדיירים הקודמים, 8 קוב.")
    [line] = result.lines
    assert line.catalog_code == OTHERS_DEBRIS and line.quantity == 8
