import json
from pathlib import Path

import pytest

from app.core.hebrew import normalize, normalize_unit, search_tokens

CATALOG = Path(__file__).resolve().parents[1] / "data" / "demo" / "catalog.json"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("טִיחַ סִיד", "טיח סיד"),  # niqqud
        ("‏קוד‎ 01.09", "קוד 01.09"),  # bidi marks
        ("מ״ר", 'מ"ר'),  # gershayim
        ("יח׳", "יח'"),  # geresh
        ("“מרכאות”", '"מרכאות"'),  # curly quotes
        ("רווחים   כפולים וטאב\t", "רווחים כפולים וטאב"),
        ("על בסיס סיד .", "על בסיס סיד."),  # space before punctuation
        ("קרניז במשיכה )3-2 מדרגות)", "קרניז במשיכה (3-2 מדרגות)"),
        ('פלדה (מפלדת פלב"מ( 16 מ"מ', 'פלדה (מפלדת פלב"מ) 16 מ"מ'),
        ("תוספת )לפי 50 ש\"ח לכל %5(", 'תוספת (לפי 50 ש"ח לכל 5%)'),
        ("עולה על %10", "עולה על 10%"),
        ("(תקין) ו-(גם תקין)", "(תקין) ו-(גם תקין)"),  # correct pairs untouched
        ("", ""),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


def test_normalize_is_idempotent_on_catalog():
    items = json.loads(CATALOG.read_text(encoding="utf-8"))["items"]
    for item in items:
        once = normalize(item["description"])
        assert normalize(once) == once
        # After the fix every description has balanced, ordered parentheses.
        depth = 0
        for ch in once:
            depth += {"(": 1, ")": -1}.get(ch, 0)
            assert depth >= 0, once
        assert depth == 0, once


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('מ"ר', 'מ"ר'), ("מ״ר", 'מ"ר'), ("מטר רבוע", 'מ"ר'), ("מ2", 'מ"ר'), ("מר", 'מ"ר'),
        ("מטר", "מ'"), ("מטר אורך", "מ'"), ('מ"א', "מ'"), ("מטרים רצים", "מ'"),
        ("קוב", 'מ"ק'), ("מטר מעוקב", 'מ"ק'),
        ("יחידות", "יח'"), ("יח", "יח'"), ("יח׳", "יח'"),
        ("קומפלט", "קומפ"), ("שעות עבודה", 'ש"ע'), ("טונות", "טון"),
        ("  מ\"ר. ", 'מ"ר'),
        ("משהו אחר", "משהו אחר"),  # unknown units stay (cleaned)
        (None, None), ("", None),
    ],
)
def test_normalize_unit(raw, expected):
    assert normalize_unit(raw) == expected


def test_catalog_units_are_already_canonical():
    items = json.loads(CATALOG.read_text(encoding="utf-8"))["items"]
    for item in items:
        assert normalize_unit(item["unit"]) == item["unit"]


def test_search_tokens_prefixes_meet_the_stem():
    for word in ("בקיר", "הקיר", "לקיר", "והקיר"):
        assert "קיר" in search_tokens(word), word
    # Short words are not stripped below three letters.
    assert search_tokens("בית") == ["בית"]


def test_search_tokens_quotes_finals_and_numbers():
    assert search_tokens('40 מ"ר') == ["40", "מר"]
    assert "פלבמ" in search_tokens('פלב"מ')
    # Final letters unified: "חלון" and "חלונות" share the "חלונ" form.
    assert search_tokens("חלון") == ["חלונ"]
    assert search_tokens("01.09.001.0030") == ["01.09.001.0030"]


def test_search_tokens_niqqud_and_bidi_do_not_matter():
    assert search_tokens("‏טִיחַ") == search_tokens("טיח")


def test_damp_words_add_catalog_words():
    # Owner round 3 (2.11.2026): customers say רטיבות, the catalog says לחות.
    from app.core.hebrew import search_tokens, synonym_tokens
    assert synonym_tokens(search_tokens("תיקון נזקי רטיבויות")) == ["לחות", "קפילרית"]
    assert synonym_tokens(search_tokens("יש עובש והקיר מתקלף")) == ["לחות"]
    assert synonym_tokens(search_tokens("חידוש טיח בחזית")) == []
