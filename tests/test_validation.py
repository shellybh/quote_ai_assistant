from app.core.validation import (
    catalog_by_code,
    check_line,
    keep_stated_quantity,
    stated_quantities,
)
from app.models.catalog import CatalogEntry

CATALOG = catalog_by_code([
    CatalogEntry(code="01.09.001.0100", description="חידוש טיח", unit='מ"ר'),
    CatalogEntry(code="01.14.001.0130", description="החלפת אבן", unit="יח'"),
])


def test_valid_line():
    c = check_line("טיח 40 מ\"ר", "01.09.001.0100", 40, "מטר רבוע", CATALOG)
    assert c.ok and c.code == "01.09.001.0100" and c.quantity == 40 and c.unit == 'מ"ר'


def test_unknown_code_is_dropped():
    c = check_line("משהו", "99.99.999.9999", 5, None, CATALOG)
    assert c.code is None and not c.ok


def test_code_with_bidi_marks_is_accepted_but_one_digit_off_is_not():
    assert check_line("x", "‏01.09.001.0100 ", 1, None, CATALOG).code == "01.09.001.0100"
    assert check_line("x", "01.09.001.0101", 1, None, CATALOG).code is None


def test_bad_quantity_is_emptied():
    for q in (0, -3, float("nan")):
        c = check_line("x", "01.09.001.0100", q, None, CATALOG)
        assert c.quantity is None and not c.ok


def test_zero_quantity_and_null_unit_mean_not_stated():
    # Seen live (30.10.2026): the model wrote 0 and the text "null" instead of null.
    c = check_line("מצלמות", "01.14.001.0130", 0, "null", CATALOG)
    assert c.quantity is None and c.unit == "יח'"
    assert c.warnings == ["לא צוינה כמות עבור 'מצלמות'."]
    assert check_line("x", None, 3, "None", CATALOG).unit == ""


def test_missing_quantity_is_a_warning():
    c = check_line("x", "01.09.001.0100", None, None, CATALOG)
    assert c.code and c.quantity is None and len(c.warnings) == 1


def test_unit_is_always_the_catalog_unit():
    c = check_line("x", "01.14.001.0130", 3, 'מ"ר', CATALOG)
    assert c.unit == "יח'" and not c.ok
    assert c.quantity is None  # 3 m2 is not 3 units


def test_containers_are_a_said_unit():
    # Probe 2.11.2026: "פינוי פסולת 2 מכולות" came back as 2 m3.
    c = check_line("פינוי פסולת", "01.09.001.0100", 2, "מכולות", CATALOG)
    assert c.quantity is None and c.unit == 'מ"ר' and not c.ok
    assert check_line("x", None, 2, "משאיות", CATALOG).unit == "משאית"


def test_no_code_keeps_the_said_unit():
    c = check_line("x", None, 3, "מטר", CATALOG)
    assert c.code is None and c.unit == "מ'" and c.ok


def test_stated_quantities_digits_and_words():
    assert stated_quantities('טיח 40 מ"ר, 1.5 מטר, 2,5 מ"ק ו-1,200 אבנים') == {40, 1.5, 2.5, 1200}
    assert stated_quantities("דלת עם כנף אחת ושתי חלונות, בשלושה מקומות") == {1, 2, 3}
    assert stated_quantities("עשרה רוכבים, עשרים מטר") == {10, 20}
    assert stated_quantities("החלפת אדן חלון אבן") == set()
    assert stated_quantities("מכסה, חשמל, מחלון") == set()  # no number hidden inside words


def test_keep_stated_quantity():
    assert keep_stated_quantity(1, "החלפת אדן חלון אבן") is None
    assert keep_stated_quantity(1, "החלפת אדן חלון אחד") == 1
    assert keep_stated_quantity(15, "להחליף רוכבים, משהו כמו 15.") == 15
    assert keep_stated_quantity(30, "3 קירות של 10 מ\"ר") is None  # computed, not said
    assert keep_stated_quantity(None, "5") is None
    assert keep_stated_quantity(-3, "x") == -3  # check_line reports bad values


def test_a_word_that_is_no_unit_of_measure_is_not_a_said_unit():
    # Seen live (31.10.2026): "שיפוץ חזית" came back with the unit "מקדמה".
    from app.core.validation import check_line
    from app.models.catalog import CatalogEntry
    catalog = {"01.09.001.0100": CatalogEntry(code="01.09.001.0100", description="חידוש טיח", unit='מ"ר')}
    for word in ("מקדמה", "גג"):
        check = check_line("שיפוץ חזית", "01.09.001.0100", 80, word, catalog)
        assert check.warnings == [] and check.unit == 'מ"ר'
    assert check_line("שיפוץ חזית", "01.09.001.0100", 80, "מטר", catalog).warnings  # a real unit, still checked


def test_says_special_case_with_prefixes():
    from app.core.validation import says_special_case
    words = ["אחרים", "קודמים", "ישנה"]
    assert says_special_case(words, "פסולת מהדיירים הקודמים")
    assert says_special_case(words, "פסולת של אחרים")
    assert says_special_case(words, "ערמה ישנה בחצר")
    assert not says_special_case(words, "תוסיף פינוי פסולת")
    assert not says_special_case(words, "פינוי פסולת 2 מכולות")


def test_masked_amount_label_is_not_a_said_number():
    from app.core.validation import keep_stated_quantity, stated_quantities
    text = "התקנת מצלמות אבטחה. מקדמה [סכום1] והיתרה בסיום, [סכום2] באמצע."
    assert stated_quantities(text) == set()
    assert keep_stated_quantity(1, text) is None
    assert keep_stated_quantity(15, "החלפת 15 רוכבים, מקדמה [סכום1]") == 15
