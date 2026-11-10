"""Confidence shown to the user, computed in code (SPEC 5.3).

AI Studio (29.10.2026): the model's own confidence is unreliable (high when
wrong, medium when obvious), so the search score carries most of the weight.

Set on the tuning set only (eval/datasets/match_tune.jsonl, three agent
runs, 30.10.2026, 45 suggested lines): every correct line scored 0.80 or
more; the wrong lines that came from a weak search (search score about 50,
e.g. a job with no catalog line) scored 0.52-0.64. REVIEW_BELOW = 0.75
flags those and no correct line. A confident wrong pick with a strong
search score (an extra line from a job split in two) is not caught by any
threshold: the person approving the draft catches it. SEARCH_WEIGHT stays.
"""

from typing import Literal

MODEL_SCORE = {"high": 1.0, "medium": 0.6, "low": 0.3}
SEARCH_WEIGHT = 0.7
REVIEW_BELOW = 0.75
CONDITION_SCORE = {"high": 0.9, "medium": 0.6, "low": 0.3}


def combine(
    search_score: float,
    model_confidence: Literal["high", "medium", "low"],
    has_alternatives: bool,
) -> float:
    """search_score is 0-100 (CatalogSearch); the result is 0-1."""
    model = MODEL_SCORE[model_confidence]
    if has_alternatives:
        model = min(model, MODEL_SCORE["medium"])
    value = SEARCH_WEIGHT * (search_score / 100) + (1 - SEARCH_WEIGHT) * model
    return round(max(0.0, min(1.0, value)), 2)


def for_condition(model_confidence: Literal["high", "medium", "low"]) -> float:
    """A+ conditions have no search score: the library is small and the
    Matcher sees all of it. Only "high" passes REVIEW_BELOW, so the app
    ticks a condition in advance only when the model is sure (SPEC 17.5)."""
    return CONDITION_SCORE[model_confidence]


def needs_review(confidence: float) -> bool:
    return confidence < REVIEW_BELOW
