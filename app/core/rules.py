"""Load app/core/rules.yaml into typed settings (B checks, A special items)."""

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

RULES_FILE = Path(__file__).with_name("rules.yaml")


class PriceRules(BaseModel):
    history_min_samples: int = Field(ge=1)
    history_max_ratio: float = Field(gt=1)
    catalog_check_enabled: bool = True
    catalog_min_ratio: float = Field(gt=0, lt=1)
    catalog_max_ratio: float = Field(gt=1)


class AlwaysCondition(BaseModel):
    key: str
    label: str


class ConditionRule(BaseModel):
    id: str
    work: str
    code_prefixes: list[str] = Field(min_length=1)
    except_codes: list[str] = Field(default_factory=list)
    require_any: list[str] = Field(min_length=1)
    label: str


class ConflictingConditions(BaseModel):
    keys: list[str] = Field(min_length=2)
    label: str


class ConditionRules(BaseModel):
    always: list[AlwaysCondition] = Field(default_factory=list)
    rules: list[ConditionRule] = Field(default_factory=list)
    conflicts: list[ConflictingConditions] = Field(default_factory=list)


class SpecialItem(BaseModel):
    """A catalog item for one special case: kept only when the message says it."""
    code: str
    case: str
    any_of: list[str] = Field(min_length=1)


class Rules(BaseModel):
    price: PriceRules
    conditions: ConditionRules
    special_items: list[SpecialItem] = Field(default_factory=list)


def load_rules(path: Path = RULES_FILE) -> Rules:
    return Rules.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache
def get_rules() -> Rules:
    return load_rules()
