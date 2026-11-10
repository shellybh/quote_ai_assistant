"""The one place that builds the LLM for all agents."""

from crewai import LLM
from google.genai import types
from pydantic import BaseModel

from app.config import Settings


class LLMOutputError(Exception):
    """The model returned malformed output, also on the retry (-> 502)."""


class LLMRateLimited(Exception):
    """Gemini refused the call: too many requests or the daily quota (-> 429).
    The free tier allows 15 calls a minute (found 30.10.2026)."""


def is_rate_limit(exc: BaseException) -> bool:
    """True if a 429 from Gemini is anywhere in the exception chain
    (CrewAI may wrap the google-genai error)."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if getattr(exc, "code", None) == 429 or getattr(exc, "status_code", None) == 429:
            return True
        if "RESOURCE_EXHAUSTED" in str(exc)[:500]:
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def build_llm(settings: Settings, response_format: type[BaseModel]) -> LLM:
    """response_format is sent to Gemini as the structured-output schema."""
    if settings.gemini_api_key is None:
        raise RuntimeError("GEMINI_API_KEY is not set")
    kwargs = {
        "model": f"gemini/{settings.gemini_model}",
        "api_key": settings.gemini_api_key.get_secret_value(),
        "response_format": response_format,
        "thinking_config": types.ThinkingConfig(
            thinking_level=settings.gemini_thinking_level, include_thoughts=False
        ),
    }
    if settings.gemini_temperature is not None:
        kwargs["temperature"] = settings.gemini_temperature
    return LLM(**kwargs)
