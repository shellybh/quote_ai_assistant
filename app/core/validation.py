"""Code checks on what an agent suggested (SPEC 5.3 `validation`).

- The code must exist in the catalog; anything else is dropped.
- The unit is always the catalog unit of the code; a different unit that the
  user wrote is reported, not silently taken, and its number is not used as
  the line's quantity.
- A quantity must be > 0; otherwise it is left empty for the user to fill.
  0 means "not stated" (the model writes it instead of null), so it gets
  only the missing-quantity warning.
- A unit spelled as a null word ("null", "None") was not said.
- A quantity whose number is not in the text was not said: the model reads
  "replace a window sill" as 1 although the prompt forbids it (seen live,
  30.10.2026), so code checks it (`keep_stated_quantity`).
- A special-case item (others' existing debris) fits only a message that
  says that case (`says_special_case`, rules.yaml `special_items`).
Prices never appear here: output models have no price field (test_safety).
"""

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from app.core.hebrew import is_known_unit, normalize, normalize_unit, search_tokens
from app.models.catalog import CatalogEntry
from app.models.match import PaymentStage, SaidPaymentStage

# What the model sometimes writes as text when it means "not stated".
_NULL_WORDS = {"", "null", "none", "nil", "undefined", "n/a"}


# Hebrew number words, masculine and feminine, plain and construct forms.
_NUMBER_WORDS = {
    "אחד": 1, "אחת": 1,
    "שניים": 2, "שנים": 2, "שתיים": 2, "שתים": 2, "שני": 2, "שתי": 2, "זוג": 2,
    "שלוש": 3, "שלושה": 3, "שלושת": 3,
    "ארבע": 4, "ארבעה": 4, "ארבעת": 4,
    "חמש": 5, "חמישה": 5, "חמשת": 5,
    "שש": 6, "שישה": 6, "ששת": 6,
    "שבע": 7, "שבעה": 7, "שבעת": 7,
    "שמונה": 8, "שמונת": 8,
    "תשע": 9, "תשעה": 9, "תשעת": 9,
    "עשר": 10, "עשרה": 10, "עשרת": 10,
    "עשרים": 20, "שלושים": 30, "ארבעים": 40, "חמישים": 50,
    "שישים": 60, "ששים": 60, "שבעים": 70, "שמונים": 80, "תשעים": 90, "מאה": 100,
}
# Parts of a whole, said instead of a percent ("חצי בהתחלה").
_FRACTIONS = {"חצי": 50.0, "מחצית": 50.0, "רבע": 25.0, "שליש": 100 / 3}
_PREFIXES = "ובלהמשכ"
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def stated_quantities(text: str) -> set[float]:
    """Every number written in the text: digits ("12", "1.5", "1,200") and
    number words, also after a one- or two-letter prefix ("ושתי", "בשלושה")."""
    found: set[float] = set()
    # A masked amount ("[סכום1]") is a label, not a number the user said
    # (seen 3.11.2026: "מצלמות אבטחה" got quantity 1 from it).
    text = AMOUNT_LABEL.sub(" ", text)
    for raw in _NUMBER.findall(text):
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+", raw):
            found.add(float(raw.replace(",", "")))  # thousands separator
        else:
            try:
                found.add(float(raw.replace(",", ".")))
            except ValueError:  # e.g. "1.2.3"
                pass
    for word in re.findall(r"[א-ת]+", text):
        for cut in range(min(3, len(word))):
            if cut and word[cut - 1] not in _PREFIXES:
                break
            if (value := _NUMBER_WORDS.get(word[cut:])) is not None:
                found.add(float(value))
                break
    return found


def _word_value(word: str, table: dict) -> float | None:
    """The value of `word` in `table`, also after a one- or two-letter prefix."""
    for cut in range(min(3, len(word))):
        if cut and word[cut - 1] not in _PREFIXES:
            return None
        if (value := table.get(word[cut:])) is not None:
            return float(value)
    return None


def stated_percents(text: str) -> set[float]:
    """Every number a percent stage may come from: the stated quantities,
    compound number words ("עשרים וחמישה", "חמש עשרה") and parts of a whole
    ("חצי", "שליש", "שני שלישים", "שלושה רבעים")."""
    found = stated_quantities(text)
    words = re.findall(r"[א-ת]+", text)
    for i, word in enumerate(words):
        value = _word_value(word, _NUMBER_WORDS)
        before = _word_value(words[i - 1], _NUMBER_WORDS) if i else None
        if value in (10.0,) and before is not None and before < 10 and word.endswith(("עשר", "עשרה")):
            found.add(before + 10)
        if value is not None and value < 10 and word.startswith("ו") and before in (
                20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0):
            found.add(before + value)
        if (part := _word_value(word, _FRACTIONS)) is not None:
            found.add(part)
        if word.endswith(("שלישים", "שליש")) and before == 2.0:
            found.add(200 / 3)
        if word.endswith(("רבעים", "רבעי")) and before == 3.0:
            found.add(75.0)
    return found


def keep_stated_quantity(quantity: float | None, text: str) -> float | None:
    """A positive quantity that the text does not contain becomes not stated.
    Bad values (negative, NaN) pass through for `check_line` to report."""
    if quantity is None or math.isnan(quantity) or quantity <= 0:
        return quantity
    if any(math.isclose(quantity, s) for s in stated_quantities(text)):
        return quantity
    return None


def says_special_case(any_of: Iterable[str], text: str) -> bool:
    """True if one of the words, with or without a Hebrew prefix
    ("מהדיירים", "הקודמים"), is in the text."""
    said = set(search_tokens(text))
    return any(tok in said for word in any_of for tok in search_tokens(word)[:1])


AMOUNT_LABEL = re.compile(r"\[סכום\d+\]")


def check_payment(said: Iterable[SaidPaymentStage], text: str) -> tuple[list[PaymentStage], list[str]]:
    """A+ payment stages (SPEC 17.3), from Intake's kind + value: a percent
    above 0 and up to 100, an amount label that is in the text (never a
    number), or the remainder; at most one remainder. Any broken stage
    drops them all, with a warning: half a payment plan is worse than none,
    and the app then asks the owner to type it."""
    labels = set(AMOUNT_LABEL.findall(text))
    stages: list[PaymentStage] = []
    ok = True
    for s in said:
        description = s.description.strip()
        value = (s.value or "").strip()
        if not description:
            ok = False
        elif s.kind == "remainder":
            stages.append(PaymentStage(description=description, is_remainder=True))
        elif s.kind == "amount" and value in labels:
            stages.append(PaymentStage(description=description, amount_ref=value))
        elif s.kind == "percent" and (percent := _percent(value)) is not None:
            stages.append(PaymentStage(description=description, percent=percent))
        else:
            ok = False
    if ok and sum(s.is_remainder for s in stages) <= 1:
        return _said_percents_only(stages, text)
    return [], [_PAYMENT_UNCLEAR]


_PAYMENT_UNCLEAR = "תנאי התשלום לא נקראו בבירור. אפשר להזין אותם בעצמך."


def _said_percents_only(stages: list[PaymentStage], text: str) -> tuple[list[PaymentStage], list[str]]:
    """Decision c (user, 2.11.2026), like `keep_stated_quantity`: a percent
    whose number the message does not say was invented (seen once on the
    A+ test set: "30% and the rest" for a message with no payment). One
    100% stage alone is "all at once" ("משלמים הכול בסוף") and stays. A plan
    with nothing taken from the message goes silently; one with something
    said and a percent invented goes with the "not clear" warning."""
    said = stated_percents(text)
    percents = [s.percent for s in stages if s.percent is not None]
    unsaid = [p for p in percents if not any(abs(p - n) < 0.5 for n in said)]
    if not unsaid or (len(stages) == 1 and percents == [100]):
        return stages, []
    grounded = any(s.amount_ref for s in stages) or len(unsaid) < len(percents)
    return [], [_PAYMENT_UNCLEAR] if grounded else []


def _percent(value: str) -> float | None:
    try:
        number = float(value.rstrip("%").strip())
    except ValueError:
        return None
    return number if 0 < number <= 100 else None


def catalog_by_code(catalog: Iterable[CatalogEntry]) -> dict[str, CatalogEntry]:
    return {clean_code(e.code): e for e in catalog}


def clean_code(code: str) -> str:
    """Bidi marks, odd dashes and spaces removed. No fuzzy matching: codes
    that differ by one digit are different catalog lines."""
    return normalize(code).replace(" ", "")


@dataclass
class LineCheck:
    code: str | None
    quantity: float | None
    unit: str
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.warnings


def check_line(
    source_text: str,
    code: str | None,
    quantity: float | None,
    unit: str | None,
    catalog: Mapping[str, CatalogEntry],
) -> LineCheck:
    warnings: list[str] = []
    if unit is not None and unit.strip().lower() in _NULL_WORDS:
        unit = None
    # Seen live (31.10.2026, Intake v5): a payment word or a place came back
    # as the unit ("מקדמה", "גג"). Only a unit of measure counts as said.
    said_unit = normalize_unit(unit) if is_known_unit(unit) else None

    entry = None
    if code:
        entry = catalog.get(clean_code(code))
        if entry is None:
            warnings.append(f"הסעיף שהוצע עבור '{source_text}' לא קיים במחירון, ולכן הוסר.")

    if quantity == 0:
        quantity = None
    if quantity is not None and (math.isnan(quantity) or quantity < 0):
        warnings.append(f"הכמות עבור '{source_text}' לא תקינה, ולכן נשארה ריקה.")
        quantity = None

    if entry is None:
        return LineCheck(code=None, quantity=quantity, unit=said_unit or "", warnings=warnings)

    if quantity is None:
        warnings.append(f"לא צוינה כמות עבור '{source_text}'.")
    if said_unit and said_unit != entry.unit:
        # The number was said in another unit ("2 מכולות" is not 2 m3), so
        # it is not a quantity of this line: the user fills it in.
        quantity = None
        warnings.append(
            f"עבור '{source_text}' נאמרה יחידה {said_unit}, אבל הסעיף נמדד ב-{entry.unit}. "
            "הכמות נשארה ריקה."
        )
    return LineCheck(code=entry.code, quantity=quantity, unit=entry.unit, warnings=warnings)
