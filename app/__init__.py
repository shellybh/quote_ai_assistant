"""price-ai-backend: AI server for the price-proposal app."""

import os

__version__ = "0.1.0"

# CrewAI must never send anything to its own services (telemetry, traces).
# Set before any crewai import; `app` is always imported first.
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
