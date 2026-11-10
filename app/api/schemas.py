"""Request bodies that the app sends.

No price ever reaches this server (decided 30.10.2026): the app computes
price *ratios* on the phone and sends only those. Unknown fields are
refused (extra="forbid"), so a request that tries to send a price gets a
422 instead of being quietly accepted (tests/test_safety.py).
"""

from pydantic import BaseModel, ConfigDict, Field

from app.models.catalog import CatalogEntry
from app.models.match import LibraryCondition


class RequestCatalogEntry(CatalogEntry):
    """A catalog line as the app sends it: code, description and unit only.
    CatalogEntry itself ignores extra keys (the eval reads the demo catalog,
    which has prices); a request refuses them, so a catalog price gets a 422.
    from_attributes: a CatalogEntry built in code (eval, tests) is accepted."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class ProposalLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=40)
    description: str = Field(max_length=1000)
    unit: str = Field(max_length=20)
    quantity: float = Field(ge=0)
    # The line's unit price after discount divided by the median price of the
    # same code in previous proposals, computed in the app. None: no history.
    history_ratio: float | None = Field(default=None, gt=0)
    # How many previous prices that median is based on.
    history_count: int = Field(default=0, ge=0)
    # The same price divided by the catalog price of the code (None if unknown).
    catalog_ratio: float | None = Field(default=None, gt=0)


class MatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)
    catalog: list[RequestCatalogEntry] = Field(min_length=1, max_length=5000)
    # A+: the app's conditions library (masked). Empty: lines only, as before.
    conditions: list[LibraryCondition] = Field(default_factory=list, max_length=100)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: list[ProposalLine] = Field(min_length=1, max_length=300)
    # Stable keys of the selected conditions (see data/demo/conditions.json).
    condition_keys: list[str] = Field(default_factory=list, max_length=100)
    # Catalog units by code, for the unit check (optional).
    catalog: list[RequestCatalogEntry] = Field(default_factory=list, max_length=5000)
