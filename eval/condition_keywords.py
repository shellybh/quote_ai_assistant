"""A+ baseline (SPEC 17.6): condition keys found by keywords, no AI.

Eval only. Every keyword is a word of the demo library wording itself (no
synonyms: they would be picked by looking at the sets). A keyword cannot
tell "included" from "not included" except for scaffolding and waste, and cannot
find a condition the library does not have.
"""

import re

NOT_INCLUDED = re.compile(r"אינו כלול|לא כלול|לא כולל")

KEYWORDS = {
    "payment": ("תשלום", "אבני הדרך"),
    "schedule": ("חגים", "מזג האוויר", "ייבוש"),
    "permits": ("היתר", "מחלקת השימור"),
    "utilities": ("חשמל", "מים "),
    "hidden_defects": ("ליקויים", "נסתר", "ברזל חלוד", "סדוק"),
    "changes": ("שינויים", "תוספות"),
    "measurement": ("מדידה", "משוער"),
    "warranty": ("אחריות",),
    "access": ("גישה",),
    "samples": ("דוגמ",),
    "insurance": ("ביטוח",),
}


def keyword_conditions(text: str) -> set[str]:
    found = {key for key, words in KEYWORDS.items() if any(w in text for w in words)}
    if "פיגום" in text:
        found.add("scaffolding_excluded" if NOT_INCLUDED.search(text) else "scaffolding_included")
    if "פסולת קיימת" in text:
        found.add("existing_waste")
    elif "פסולת" in text:
        found.add("waste_excluded" if NOT_INCLUDED.search(text) else "waste")
    return found
