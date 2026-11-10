# CLAUDE.md

Guidance for Claude Code in this repository.

## What this is

`quote_ai_assistant` — the AI server for a price-proposal app used by a
building-conservation business (final project, AI Developers course, 2026).
It adds two abilities to an existing offline Flutter app:

- **A — free text → suggested catalog lines, conditions and payment stages**
  (`POST /v1/match-items`)
- **B — review a proposal before sending** (`POST /v1/review-proposal`)

Stack: Python 3.12, `uv`, FastAPI, CrewAI Flow (one Flow, three agents:
Intake, Matcher, Reviewer), Gemini via CrewAI's native provider
(`crewai[google-genai]`, no LiteLLM), hosted on Railway (Serverless).

`SPEC x.y` in code comments points to the design document of the app
project, which is private and not part of this repository.

## Guiding principle

**AI suggests, a person approves, code computes.**
- The AI never sets or outputs a price or an amount. No agent output model may
  contain a price/amount field — there is a test for it.
- Every catalog code an agent returns must exist in the catalog; code validates
  it and drops anything else.
- Totals and VAT are computed only in the app, never on the server.
- **No price reaches the server.** For the B checks the app computes ratios on
  the phone (`history_ratio` + `history_count` against the median of other
  issued/sent proposals, `catalog_ratio`); the thresholds stay here in
  `rules.yaml`. Request models use `extra="forbid"`, so a price field is
  refused with 422. `eval/client_ratios.py` mirrors the app's computation for
  the evaluation and tests only. The Reviewer gets only the finding.

## Privacy rules (non-negotiable)

1. **Data tiers.** `data/demo/catalog.json` is a *public* conservation price
   list (its use was approved). Conditions, previous proposals, clients and
   evaluation sets are **fictional** and written for this project. No real
   proposal, client, condition wording or business document ever enters this
   repo, a prompt, a test or a log.
2. **No business name anywhere.** Prompts and docs say "a building-conservation
   business" / "עסק לשימור מבנים". No owner name, phone, email or address.
3. **Forbidden-words check before every commit** (`.githooks/`,
   `tools/check_forbidden_words.py`). The list itself lives outside this repo
   and must never be copied in, printed or quoted. Never bypass the hook
   (`--no-verify`); if it blocks, rewrite the text.
4. **No keys in git.** `GEMINI_API_KEY`, `APP_TOKEN` etc. live only in `.env`
   (git-ignored) locally and in the host's variables. `.env.example` has
   names, no values. Never print a key in chat.
5. **No request content in logs** — only time, endpoint, duration, status.
6. **Nothing is copied from the private app project** into this repository.

## Working style

- Ask instead of assuming a product decision, and push back when a request
  has a flaw.
- Code, comments, commit messages: English. User-facing strings and prompts
  for Gemini: Hebrew.
- Model name from settings (`GEMINI_MODEL`), never hard-coded. Temperature is
  not sent (the model ignores it and Google advises the default for Gemini 3).
  Thinking MINIMAL. Stability comes from structured output, code validation
  and caching.
- Structured output: pass the schema via `build_llm(settings, Model)` and
  validate the raw reply in code. Never `Task.output_pydantic` (hidden re-asks).
- One Matcher call per request (search narrows the catalog first).
- Malformed model output → one retry → clear error (502).

## Layout

```
app/        main.py, config.py, api/, flows/, agents/, tools/, core/, models/
prompts/    intake.md, matcher.md, reviewer.md
data/demo/  catalog.json (public), conditions.json, proposals.json (fictional)
eval/       datasets/ (*_tune.jsonl, *_test.jsonl), results/, run_eval.py
docs/       ai_studio_notes.md, limits_and_costs.md, evaluation.md
scripts/    demo-data import / build / check
tools/      check_forbidden_words.py
tests/
```

## Commands

```bash
git config core.hooksPath .githooks                       # once per clone
git config privacy.forbiddenWordsFile "<path outside repo>"  # once per clone
python scripts/check_demo_data.py                         # demo-data check
uv sync                                                   # install (Python 3.12)
uv run pytest -q                                          # tests (no Gemini calls)
uv run uvicorn app.main:app --port 8765 --no-access-log   # local server
```

**Windows:** if Smart App Control blocks uv's downloaded Python, use the
official python.org 3.12:
`uv venv --python "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"`.
On Windows, send Hebrew JSON to curl from a file (`--data-binary @body.json`).

## Testing

- Unit tests for all deterministic code (normalization, search, validation,
  confidence, PriceStats, ConditionsCheck).
- CI never calls Gemini: fake LLM responses and fixed fake embeddings.
- Safety tests: no price field in any output; unknown codes rejected.
- Evaluation: tuning and test sets are separate; never tune on the test set.
  Every run is saved to `eval/results/` with prompt and model version.
