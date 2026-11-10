"""Capability A (and C): work items and suggested catalog lines.

No price or amount field anywhere: the app takes the price from its own
catalog by `catalog_code` (tests/test_safety.py).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LibraryCondition(BaseModel):
    """One condition of the app's library, as the app sends it (A+, SPEC
    17.3). The real app has no stable key, so the id is the app's own id."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=2000)


class WorkItem(BaseModel):
    """One separate job found in the free text (Intake output).

    Fields follow the schema tested in AI Studio (Intake prompt v2).
    No constraints here: bad values are handled by validation, not by a retry.
    """

    task: str = Field(description="תיאור קצר של העבודה, עם כל פרט שמבחין בין סעיפי מחירון")
    quantity: float | None = Field(default=None, description="הכמות אם נאמרה במפורש, אחרת null")
    unit: str | None = Field(default=None, description="היחידה אם נאמרה, אחרת null")
    location: str | None = Field(default=None, description="היכן במבנה, אם נאמר, אחרת null")


class PaymentStage(BaseModel):
    """One payment stage said in the message (A+, SPEC 17.3).

    Exactly one of: a percent, the label of an amount the phone masked
    (`[סכום1]`; the model never sees the number), or the remainder. The
    label is not an amount: the phone puts its own number back.
    """

    description: str
    percent: float | None = None
    amount_ref: str | None = None
    is_remainder: bool = False


class SaidPaymentStage(BaseModel):
    """A payment stage as Intake reports it (prompt v5). One explicit kind
    and one value: with three optional fields the model filled all of them
    (percent 0, a label "is_remainder"; tuning set, 31.10.2026). Code turns
    it into a PaymentStage (app/core/validation.py: check_payment)."""

    description: str = Field(description="תיאור קצר של השלב, למשל מקדמה או בסיום העבודה")
    kind: Literal["percent", "amount", "remainder"]
    value: str | None = Field(
        default=None, description="percent: המספר שנאמר; amount: התווית כפי שמופיעה בהודעה; remainder: null"
    )


class IntakeResult(BaseModel):
    tasks: list[WorkItem]
    # A+ (Intake v4): sentences that are terms of the proposal, not work.
    conditions: list[str] = Field(
        default_factory=list, description="משפטים מההודעה שהם תנאי ההצעה ולא עבודות, בנוסח שנאמר"
    )
    payment: list[SaidPaymentStage] = Field(default_factory=list, description="שלבי התשלום שנאמרו, לפי הסדר")


class MatcherPick(BaseModel):
    """The Matcher's choice for one work item (prompt v2, one call for all)."""

    item: int = Field(description="מספר העבודה ברשימה")
    code: str | None = Field(description="קוד הסעיף מתוך המועמדים של העבודה, או null")
    alternatives: list[str] = Field(default_factory=list, description="עד 2 קודים נוספים מהמועמדים")
    reason: str = Field(description="משפט אחד בעברית פשוטה")
    confidence: Literal["high", "medium", "low"]


class ConditionPick(BaseModel):
    """The Matcher's choice for one condition sentence (prompt v4)."""

    sentence: int = Field(description="מספר המשפט ברשימת משפטי התנאים")
    condition_id: str | None = Field(description="מזהה התנאי מהספרייה, או null")
    reason: str = Field(description="משפט אחד בעברית פשוטה")
    confidence: Literal["high", "medium", "low"]


class MatcherResult(BaseModel):
    matches: list[MatcherPick]
    conditions: list[ConditionPick] = Field(default_factory=list)


class MatchedLine(BaseModel):
    """A suggested catalog line, for a person to approve in the app."""

    source_text: str
    catalog_code: str | None = None
    quantity: float | None = Field(default=None, gt=0)
    unit: str
    confidence: float = Field(ge=0, le=1)
    needs_review: bool
    reason: str
    is_estimate: bool = False
    page: int | None = Field(default=None, ge=1)
    # Up to 3 other catalog codes the person may switch to in the app
    # (the Matcher's alternatives first, then the next search candidates).
    similar: list[str] = Field(default_factory=list, max_length=3)


class UnmatchedItem(BaseModel):
    """A work item with no catalog line: the nearest search candidates, for
    the person to pick from (or to search the whole catalog in the app)."""

    source_text: str
    similar: list[str] = Field(default_factory=list, max_length=3)


class SuggestedCondition(BaseModel):
    """A library condition the message asked for, for a person to approve.
    The app ticks it in advance only when needs_review is false."""

    condition_id: str
    source_text: str
    reason: str
    confidence: float = Field(ge=0, le=1)
    needs_review: bool


class MatchResult(BaseModel):
    lines: list[MatchedLine] = Field(default_factory=list)
    # The texts only, as before; `unmatched_items` adds the similar codes.
    unmatched: list[str] = Field(default_factory=list)
    unmatched_items: list[UnmatchedItem] = Field(default_factory=list)
    # A+: conditions from the library, and condition sentences that have
    # none (the app offers its "new condition" window with the text).
    conditions: list[SuggestedCondition] = Field(default_factory=list)
    unmatched_conditions: list[str] = Field(default_factory=list)
    # A+: payment stages as said, checked in code. The app shows them after
    # the lines are approved, when the total is known.
    payment: list[PaymentStage] = Field(default_factory=list)
    # A+: library condition ids that contradict each other (rules.yaml
    # `conflicts`, by the app's `cond-<key>` ids), so the app does not tick
    # an "always" condition against the one the message chose (2.11.2026).
    condition_conflicts: list[list[str]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ExtractedQuantity(BaseModel):
    """Capability C only: a quantity read from a plan, always an estimate."""

    element: str
    quantity: float = Field(gt=0)
    unit: str
    page: int = Field(ge=1)
    is_estimate: bool = True
