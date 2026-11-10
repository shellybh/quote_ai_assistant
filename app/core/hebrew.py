"""Hebrew text normalization (SPEC 5.3).

- `normalize`: clean text for display and comparison (niqqud, bidi marks,
  quote variants, spaces, the price list's reversed parentheses).
- `normalize_unit`: unit variants -> the catalog's unit spelling.
- `search_tokens`: words for BM25 (no quotes, unified final letters, and
  prefix-stripped variants so "בקיר", "הקיר" and "לקיר" all meet "קיר").
"""

import re
import unicodedata

# Niqqud and cantillation marks (U+0591-U+05C7), except maqaf (U+05BE),
# sof pasuq (U+05C3) and the punctuation marks (U+05C0, U+05C6).
_NIQQUD = re.compile(r"[֑-ׇֽֿׁׂׅׄ]")
# Invisible direction marks and zero-width characters.
_BIDI = re.compile(r"[​-‏‪-‮⁦-⁩﻿]")
_QUOTES = str.maketrans({
    "״": '"',  # Hebrew gershayim
    "“": '"', "”": '"', "„": '"',
    "׳": "'",  # Hebrew geresh
    "‘": "'", "’": "'", "´": "'", "`": "'",
    "־": "-",  # maqaf
    "–": "-", "—": "-",
    " ": " ",
})
# The price list came out of a right-to-left PDF: some parentheses are
# mirrored, e.g. ")3-2 מדרגות)" or "(מפלדת פלב"מ(". Any pair of parenthesis
# characters around text without parentheses becomes "( ... )".
_PAREN_PAIR = re.compile(r"[()]([^()]*)[()]")
# Also mirrored: "%10" means "10%".
_PERCENT_FIRST = re.compile(r"%(\d+(?:\.\d+)?)")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([.,;:!?])")
_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = _BIDI.sub("", text)
    text = _NIQQUD.sub("", text)
    text = text.translate(_QUOTES)
    text = _PAREN_PAIR.sub(lambda m: f"({m.group(1).strip()})", text)
    text = _PERCENT_FIRST.sub(r"\1%", text)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    return _SPACES.sub(" ", text).strip()


# Unit spellings found in the catalog: מ"ר מ' מ"ק יח' קומפ ש"ע טון
_UNITS = {
    'מ"ר': ['מ"ר', "מר", "מ'ר", "מטר רבוע", "מטרים רבועים", "מטר מרובע",
            "מטרים מרובעים", "מ2", "m2", "sqm"],
    "מ'": ["מ'", "מ", "מטר", "מטרים", "מטר אורך", "מטרים אורך", 'מ"א', "מא",
           "מטר רץ", "מטרים רצים", "m"],
    'מ"ק': ['מ"ק', "מק", "מטר מעוקב", "מטרים מעוקבים", "קוב", "קוב'", "מ3", "m3"],
    "יח'": ["יח'", "יח", "יחידה", "יחידות", "יח׳"],
    "קומפ": ["קומפ", "קומפ'", "קומפלט", "קומפלקט", "קומפלטים"],
    'ש"ע': ['ש"ע', "שע", "שעה", "שעות", "שעת עבודה", "שעות עבודה"],
    "טון": ["טון", "טונות", "טונה"],
    # Not catalog units, but said units all the same: "2 מכולות" of waste
    # must not become 2 m3 (owner round 3, 2.11.2026: waste per container).
    "מכולה": ["מכולה", "מכולות"],
    "משאית": ["משאית", "משאיות"],
}
_UNIT_LOOKUP = {
    _SPACES.sub(" ", v.lower()): canon for canon, variants in _UNITS.items() for v in variants
}


def normalize_unit(unit: str | None) -> str | None:
    """Return the catalog spelling of a unit, or the cleaned text if unknown."""
    if unit is None:
        return None
    cleaned = normalize(unit).rstrip(".").strip()
    if not cleaned:
        return None
    return _UNIT_LOOKUP.get(cleaned.lower(), cleaned)


def is_known_unit(unit: str | None) -> bool:
    """A unit of measure the catalog uses, in any of its spellings."""
    return normalize_unit(unit) in _UNITS


_FINALS = str.maketrans("ךםןףץ", "כמנפצ")
_PREFIXES = "והבלמשכ"
_MIN_STEM = 3  # never strip a word below three letters ("מעקה" -> "עקה" is a cost we accept)
_WORD = re.compile(r"[0-9a-zא-ת]+(?:\.[0-9]+)*")


def _variants(word: str) -> list[str]:
    """The word, plus up to two leading prefix letters stripped ("והקיר")."""
    out = [word]
    stem = word
    for _ in range(2):
        if len(stem) - 1 >= _MIN_STEM and stem[0] in _PREFIXES and not stem.isdigit():
            stem = stem[1:]
            out.append(stem)
        else:
            break
    return out


# Customers' words for a damp problem; the catalog says "לחות" and "עלייה
# קפילרית". The words are the owner's (round 3, 2.11.2026), not picked by
# looking at the evaluation sets. Keys are in search-token form (no final
# letters). Added to the keyword query only, never removed from it.
_DAMP = ("לחות", "קפילרית")
_SYNONYMS = {
    **{w: _DAMP for w in ("רטיבות", "רטיבויות", "רטוב", "רטובה", "רטובימ", "רטובות", "מלחימ")},
    **{w: ("לחות",) for w in ("עובש", "מתקלפ", "מתקלפת", "מתקלפימ", "מתקלפות")},
}


def synonym_tokens(tokens: list[str]) -> list[str]:
    """Catalog words for customers' words among `tokens` (once each)."""
    extra: list[str] = []
    for tok in tokens:
        for word in _SYNONYMS.get(tok, ()):
            if word not in extra:
                extra.append(word)
    return extra


def search_tokens(text: str) -> list[str]:
    """Tokens for keyword search. Order is kept; duplicates are allowed."""
    text = normalize(text).lower()
    # Quotes inside abbreviations go away: מ"ר -> מר, יח' -> יח, פלב"מ -> פלבמ
    text = text.replace('"', "").replace("'", "")
    text = text.translate(_FINALS)
    tokens: list[str] = []
    for word in _WORD.findall(text):
        if len(word) < 2 and not word.isdigit():
            continue
        tokens.extend(_variants(word))
    return tokens
