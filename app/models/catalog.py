"""Catalog entries and search candidates. No prices: the app keeps them."""

from pydantic import BaseModel, ConfigDict, Field


class CatalogEntry(BaseModel):
    """One catalog line as the app sends it for matching (code, text, unit)."""

    model_config = ConfigDict(extra="ignore")

    code: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=1, max_length=1000)
    unit: str = Field(min_length=1, max_length=20)


class Candidate(BaseModel):
    """A catalog line that the search found for one work item."""

    code: str
    description: str
    unit: str
    search_score: float = Field(ge=0, le=100, description="ציון החיפוש, 0–100")
