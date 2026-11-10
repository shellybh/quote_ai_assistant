"""Local, content-free tracing of one Flow run.

CrewAI's own tracing sends run data (prompts, replies) to its cloud, so it
stays off (app/__init__.py). Instead each request writes one log line with
step names, durations, the number of model calls and the status, never any
text, code, quantity or price:

    trace review checks=2ms reviewer=2104ms merge=0ms llm_calls=1 total=2107ms ok

The current trace lives in a ContextVar, so the Flow's steps (which CrewAI
may run in another thread or task) record into it without extra arguments.
"""

import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar

log = logging.getLogger("price_ai.trace")

_current: ContextVar["Trace | None"] = ContextVar("price_ai_trace", default=None)


class Trace:
    def __init__(self, name: str):
        self.name = name
        self.steps: list[tuple[str, float]] = []
        self.llm_calls = 0
        self.status = "ok"
        self.total_ms = 0.0

    def __enter__(self) -> "Trace":
        self._token = _current.set(self)
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.total_ms = (time.perf_counter() - self._start) * 1000
        if exc_type is not None:
            self.status = exc_type.__name__  # the class name only, never the message
        _current.reset(self._token)
        log.info("%s", self.line())

    def line(self) -> str:
        steps = " ".join(f"{name}={ms:.0f}ms" for name, ms in self.steps)
        return (f"trace {self.name} {steps} llm_calls={self.llm_calls} "
                f"total={self.total_ms:.0f}ms {self.status}")


@contextmanager
def step(name: str):
    trace = _current.get()
    start = time.perf_counter()
    try:
        yield
    finally:
        if trace is not None:
            trace.steps.append((name, (time.perf_counter() - start) * 1000))


def llm_call() -> None:
    trace = _current.get()
    if trace is not None:
        trace.llm_calls += 1
