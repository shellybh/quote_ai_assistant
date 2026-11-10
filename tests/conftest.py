import os

# Fixed fake settings, before anything imports app.config. CI never calls Gemini.
os.environ["APP_TOKEN"] = "test-token"
os.environ["GEMINI_MODEL"] = "gemini-test-model"
os.environ["GEMINI_API_KEY"] = "fake-key"

from typing import Any  # noqa: E402

import pytest  # noqa: E402
from crewai.llms.base_llm import BaseLLM  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

AUTH = {"Authorization": "Bearer test-token"}


class FakeLLM(BaseLLM):
    """Returns canned replies in order, counts calls and keeps what was sent."""

    replies: list[str]
    calls: int = 0
    sent: list[str] = []

    def call(self, messages, tools=None, callbacks=None, available_functions=None,
             from_task=None, from_agent=None, response_model=None) -> Any:
        if isinstance(messages, str):
            self.sent.append(messages)
        else:
            self.sent.append("\n".join(str(m.get("content", "")) for m in messages))
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return reply

    def supports_function_calling(self) -> bool:
        return False


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


@pytest.fixture
def client():
    return TestClient(create_app(make_settings()))
