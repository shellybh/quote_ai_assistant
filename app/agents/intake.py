"""Intake agent: free text -> separate work items (prompt v2, AI Studio), and
since v4 (A+) the condition sentences apart from the work, and since v5 the
payment stages as said (percent, amount label or remainder)."""

from crewai.llms.base_llm import BaseLLM

from app.agents.base import load_prompt, render, run_structured
from app.models.match import IntakeResult

PROMPT = load_prompt("intake")


def run_intake(text: str, llm: BaseLLM) -> IntakeResult:
    return run_structured(
        llm,
        role="מפרק תיאורי עבודה",
        goal="לפרק תיאור עבודה חופשי לרשימת עבודות נפרדות",
        description=render(PROMPT, text=text),
        output=IntakeResult,
    )
