"""Run one CrewAI agent once and validate its raw reply in code.

The schema reaches the model via the LLM's response_format (see build_llm).
Task.output_pydantic is not used: on bad output its converter silently
re-asks the model several times. Here: first try + one retry, then 502.
"""

from pathlib import Path
from typing import TypeVar

from crewai import Agent, Crew, Task
from crewai.llms.base_llm import BaseLLM
from pydantic import BaseModel, ValidationError

from app.core import tracing
from app.core.llm import LLMOutputError, LLMRateLimited, is_rate_limit

PROMPTS = Path(__file__).resolve().parents[2] / "prompts"
ATTEMPTS = 2

M = TypeVar("M", bound=BaseModel)


def load_prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


def render(template: str, **values: str) -> str:
    """Plain placeholder replacement. No str.format and no CrewAI inputs, so
    braces in user text or catalog lines cannot break the prompt."""
    for key, value in values.items():
        template = template.replace(f"<<{key}>>", value)
    return template


def run_structured(
    llm: BaseLLM,
    *,
    role: str,
    goal: str,
    description: str,
    output: type[M],
) -> M:
    for _ in range(ATTEMPTS):
        agent = Agent(
            role=role,
            goal=goal,
            backstory="עוזר לעסק לשימור מבנים.",
            llm=llm,
            allow_delegation=False,
            verbose=False,
            # CrewAI re-runs a failed call twice by itself; the retry policy
            # is ours (one retry on malformed output), and a 429 is not retried.
            max_retry_limit=0,
        )
        task = Task(description=description, expected_output="JSON לפי הסכמה", agent=agent)
        tracing.llm_call()
        try:
            result = Crew(agents=[agent], tasks=[task], verbose=False).kickoff()
        except Exception as exc:
            if is_rate_limit(exc):
                raise LLMRateLimited(output.__name__) from exc
            raise
        try:
            return output.model_validate_json(result.raw)
        except ValidationError:
            continue
    raise LLMOutputError(f"{output.__name__}: malformed output twice")
