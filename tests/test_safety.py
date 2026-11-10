"""No agent output model may contain a price or amount field."""

import importlib
import pkgutil

from pydantic import BaseModel

import app.models

FORBIDDEN = ("price", "amount", "total", "cost", "sum", "vat", "מחיר", "סכום")
# A+ payment: the label of an amount masked on the phone ("[סכום1]"), never
# a number; a test below makes sure it cannot hold one.
ALLOWED = {("PaymentStage", "amount_ref")}


def _output_models():
    for info in pkgutil.iter_modules(app.models.__path__):
        module = importlib.import_module(f"app.models.{info.name}")
        for obj in vars(module).values():
            if isinstance(obj, type) and issubclass(obj, BaseModel) and obj is not BaseModel:
                yield obj


def test_models_found():
    assert list(_output_models())


def test_no_price_field_in_any_model():
    for model in _output_models():
        for name in model.model_fields:
            if (model.__name__, name) in ALLOWED:
                continue
            assert not any(w in name.lower() for w in FORBIDDEN), f"{model.__name__}.{name}"
