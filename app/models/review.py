"""Capability B: code check results and the findings the app shows.

`CheckResult.facts` carries ratios and units only ("פי 2.1 מהחציון"),
never a money amount: it is what the Reviewer sees.
"""

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class CheckKind(StrEnum):
    missing_condition = "missing_condition"
    price_vs_history = "price_vs_history"
    price_vs_catalog = "price_vs_catalog"
    unit_mismatch = "unit_mismatch"
    wording = "wording"


class Severity(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class CheckResult(BaseModel):
    """One problem found by a code check, before the Reviewer phrases it."""

    kind: CheckKind
    line_code: str | None = None
    facts: str


class ReviewFinding(BaseModel):
    severity: Severity
    kind: CheckKind
    line_code: str | None = None
    problem: str = Field(min_length=1)
    why: str = Field(min_length=1)
    suggestion: str = Field(min_length=1)

    @field_validator("problem", "why", "suggestion")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


class ReviewResult(BaseModel):
    findings: list[ReviewFinding] = Field(default_factory=list)


class ReviewerNote(BaseModel):
    """The Reviewer's wording of one code check (prompt v3).

    kind and line_code are not asked for: code takes them from the check.
    Fields are plain strings on purpose: a blank or bad note is replaced in
    code, not re-asked. Severity is set in code.
    """

    check: int = Field(description="מספר הממצא של הבדיקה האוטומטית")
    problem: str
    why: str
    suggestion: str


class WordingNote(BaseModel):
    """A wording problem the Reviewer found itself: a vague line or a contradiction."""

    line_code: str | None = Field(description="קוד הסעיף המעורפל, או null לסתירה בין תנאים")
    problem: str
    why: str
    suggestion: str


class ReviewerResult(BaseModel):
    findings: list[ReviewerNote] = Field(description="ממצא אחד לכל ממצא של הבדיקה האוטומטית")
    wording: list[WordingNote] = Field(description="בעיות ניסוח שמצאת: סעיף מעורפל או סתירה. רשימה ריקה אם אין")
