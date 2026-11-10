"""Evaluation runner (SPEC 12). Every run is saved to eval/results/.

Baselines (stage 2, no agents):
    uv run python eval/run_eval.py match --set tune            # A: search alone
    uv run python eval/run_eval.py match --set tune --no-embed  # BM25 only, no Gemini
    uv run python eval/run_eval.py review --set tune           # B: code checks alone
    uv run python eval/run_eval.py review --set tune --agent   # B: checks + Reviewer (Gemini)
    uv run python eval/run_eval.py match --set tune --agent    # A: Intake + Matcher (Gemini)
    uv run python eval/run_eval.py aplus --set tune            # A+: condition keywords alone
    uv run python eval/run_eval.py aplus --set tune --agent    # A+: Intake + Matcher (Gemini)

A (match): each dataset item is one job phrase with its accepted codes (an
empty list = no catalog line fits). The search runs on the phrase, i.e. as if
Intake split the text perfectly. Metrics: Top-1, Top-3, Recall@15 over items
that have a code. "No match" accuracy needs the agent, so the baseline
reports only how many such items there are.

A with --agent: the full match branch runs on each case's text (2 model
calls per case). An expected item counts as found when a suggested line has
one of its codes; a suggested line whose code is no expected item's code is a
wrong suggestion (this includes a line for a job with no catalog line). Each
line's search score and model confidence are saved, to set the weights and
the review threshold in app/core/confidence.py on the tuning set.

A+ (aplus): each case is one message as the server gets it (amounts
masked), its condition keys, the condition sentences with no library
condition, and the payment stages. Conditions: recall, precision, exact
cases, and the precision of the ones the app ticks in advance.

B (review): see eval/datasets/README.md for the counting rule (SPEC 12.3).
With --agent the full review branch runs (one Reviewer call per case), so
wording findings count too; the prompt hash and model are saved with it.

Gemini quota: catalog vectors come from data/demo/catalog_embeddings.npz
(scripts/build_catalog_embeddings.py); each match phrase costs one request.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.api.schemas import ReviewRequest  # noqa: E402
from app.models.catalog import CatalogEntry  # noqa: E402
from app.tools.catalog_search import CatalogIndex, EmbeddingStore  # noqa: E402
from app.tools.review_checks import run_checks  # noqa: E402
from eval.client_ratios import price_history, ratio_line  # noqa: E402

DATASETS = ROOT / "eval" / "datasets"
RESULTS = ROOT / "eval" / "results"
STORE = ROOT / "data" / "demo" / "catalog_embeddings.npz"
DEMO = ROOT / "data" / "demo"
# Free tier: 15 model calls a minute (found 30.10.2026). Agent runs keep to 12.
CALLS_PER_MINUTE = 12


def _pace(start: float, calls: int) -> None:
    """Sleep so that `calls` model calls since `start` stay under the limit."""
    time.sleep(max(0.0, calls * 60 / CALLS_PER_MINUTE - (time.perf_counter() - start)))


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def _catalog_items() -> list[dict]:
    return json.loads((DEMO / "catalog.json").read_text(encoding="utf-8"))["items"]


def _save(name: str, payload: dict) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{datetime.now():%Y-%m-%d_%H%M}_{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _pct(n: int, d: int) -> float | None:
    return round(100 * n / d, 1) if d else None


# --- A: match -----------------------------------------------------------------

def eval_match(dataset: Path, use_embeddings: bool) -> dict:
    catalog = [CatalogEntry(**c) for c in _catalog_items()]
    embedder = None
    embedder_name = None
    if use_embeddings:
        from app.config import get_settings
        from app.tools.catalog_search import GeminiEmbedder

        s = get_settings()
        if s.gemini_api_key is None:
            raise SystemExit("GEMINI_API_KEY missing in .env (or use --no-embed)")
        embedder = GeminiEmbedder(s.gemini_api_key.get_secret_value(), s.gemini_embedding_model)
        embedder_name = embedder.name
    index = CatalogIndex(catalog, embedder, EmbeddingStore(STORE))
    modes = ["bm25", "embedding", "hybrid"] if use_embeddings else ["bm25"]

    cases = _load_jsonl(dataset)
    rows = []
    for case in cases:
        for i, item in enumerate(case["items"]):
            row = {"id": f"{case['id']}.{i + 1}", "phrase": item["phrase"], "expected": item["codes"]}
            if item["codes"]:
                for mode in modes:
                    found = [c.code for c in index.search(item["phrase"], k=15, mode=mode)]
                    hits = [found.index(c) + 1 for c in item["codes"] if c in found]
                    row[mode] = {"rank": min(hits) if hits else None, "top3": found[:3]}
            rows.append(row)

    summary = {}
    with_code = [r for r in rows if r["expected"]]
    for mode in modes:
        ranks = [r[mode]["rank"] for r in with_code]
        summary[mode] = {
            "top1": _pct(sum(1 for r in ranks if r == 1), len(ranks)),
            "top3": _pct(sum(1 for r in ranks if r and r <= 3), len(ranks)),
            "recall15": _pct(sum(1 for r in ranks if r), len(ranks)),
        }
    return {
        "capability": "A",
        "kind": "baseline_search",
        "dataset": dataset.name,
        "dataset_hash": _file_hash(dataset),
        "embedding_model": embedder_name,
        "items_with_code": len(with_code),
        "items_no_match": len(rows) - len(with_code),
        "summary_pct": summary,
        "rows": rows,
    }


def eval_match_agent(dataset: Path) -> dict:
    from app.config import get_settings
    from app.core import confidence
    from app.core.llm import build_llm
    from app.flows.proposal_flow import run_match_flow
    from app.models.match import IntakeResult, MatcherResult
    from app.tools.catalog_search import CatalogSearch, GeminiEmbedder

    settings = get_settings()
    catalog = [CatalogEntry(**c) for c in _catalog_items()]
    embedder = GeminiEmbedder(settings.gemini_api_key.get_secret_value(), settings.gemini_embedding_model)
    search = CatalogSearch(embedder, EmbeddingStore(STORE, persist=False))
    intake = build_llm(settings, IntakeResult)
    matcher = build_llm(settings, MatcherResult)

    # Record the parts of every confidence value (eval only).
    parts: list[tuple[float, str, bool]] = []
    combine = confidence.combine

    def recording(search_score, model_confidence, has_alternatives):
        parts.append((search_score, model_confidence, has_alternatives))
        return combine(search_score, model_confidence, has_alternatives)

    confidence.combine = recording
    rows, found_n, expected_n, wrong_n, lines_n = [], 0, 0, 0, 0
    try:
        for case in _load_jsonl(dataset):
            parts.clear()
            start = time.perf_counter()
            result = run_match_flow(case["text"], catalog, intake, matcher, search)
            seconds = round(time.perf_counter() - start, 2)
            _pace(start, 2)
            coded = [set(i["codes"]) for i in case["items"] if i["codes"]]
            accepted = set().union(*coded) if coded else set()
            lines = []
            for line, (score, model, alts) in zip(result.lines, parts):
                lines.append({
                    "code": line.catalog_code, "correct": line.catalog_code in accepted,
                    "quantity": line.quantity, "unit": line.unit,
                    "search_score": score, "model_confidence": model, "alternatives": alts,
                    "confidence": line.confidence, "needs_review": line.needs_review,
                })
            codes = {ln["code"] for ln in lines}
            found = sum(1 for c in coded if c & codes)
            wrong = sum(1 for ln in lines if not ln["correct"])
            found_n += found
            expected_n += len(coded)
            wrong_n += wrong
            lines_n += len(lines)
            rows.append({"id": case["id"], "seconds": seconds, "found": found, "expected": len(coded),
                         "wrong": wrong, "lines": lines, "unmatched": result.unmatched,
                         "warnings": result.warnings})
    finally:
        confidence.combine = combine
    return {
        "capability": "A",
        "kind": "agent",
        "dataset": dataset.name,
        "dataset_hash": _file_hash(dataset),
        "model": settings.gemini_model,
        "prompt_hash": {n: _file_hash(ROOT / "prompts" / f"{n}.md") for n in ("intake", "matcher")},
        "confidence": {"search_weight": confidence.SEARCH_WEIGHT, "review_below": confidence.REVIEW_BELOW},
        "summary_pct": {
            "found": _pct(found_n, expected_n),
            "wrong_suggestions": wrong_n,
            "lines": lines_n,
            "no_match_items": sum(1 for c in _load_jsonl(dataset) for i in c["items"] if not i["codes"]),
        },
        "rows": rows,
    }


# --- A+: conditions (and later payment) from one message ---------------------

def _conditions_library() -> list[dict]:
    return json.loads((DEMO / "conditions.json").read_text(encoding="utf-8"))["items"]


def _stages(stages: list[dict]) -> list[tuple]:
    """A stage as compared: kind and value, not the description."""
    return [(s.get("percent") and round(float(s["percent"]), 1), s.get("amount_ref"),
             bool(s.get("is_remainder")))
            for s in stages]


def _payment_ok(case: dict, found: list[dict]) -> bool:
    """The plan said, or one of the case's equally right readings."""
    return _stages(found) in [_stages(p) for p in [case["payment"], *case.get("payment_also", [])]]


def _payment_metrics(rows: list[dict]) -> dict:
    with_plan = [r for r in rows if r["payment_expected"]]
    return {
        "exact_all_cases": _pct(sum(1 for r in rows if r["payment_exact"]), len(rows)),
        "exact_with_payment": _pct(sum(1 for r in with_plan if r["payment_exact"]), len(with_plan)),
        "invented_plan": sum(1 for r in rows if not r["payment_expected"] and r["payment_found"]),
    }


def _condition_metrics(rows: list[dict]) -> dict:
    tp = sum(len(set(r["expected"]) & set(r["found"])) for r in rows)
    fp = sum(len(set(r["found"]) - set(r["expected"])) for r in rows)
    fn = sum(len(set(r["expected"]) - set(r["found"])) for r in rows)
    out = {
        "recall": _pct(tp, tp + fn),
        "precision": _pct(tp, tp + fp),
        "exact_cases": _pct(sum(1 for r in rows if set(r["expected"]) == set(r["found"])), len(rows)),
        "false_positives": fp,
        "missed": fn,
    }
    if rows and "ticked" in rows[0]:
        # The app ticks only these in advance (needs_review false).
        ticked = [k for r in rows for k in r["ticked"]]
        out["ticked_precision"] = _pct(sum(1 for r in rows for k in r["ticked"] if k in r["expected"]), len(ticked))
        out["unmatched_found"] = _pct(
            sum(min(r["unmatched_expected"], r["unmatched_found"]) for r in rows),
            sum(r["unmatched_expected"] for r in rows))
        out["unmatched_extra"] = sum(max(0, r["unmatched_found"] - r["unmatched_expected"]) for r in rows)
    return out


def eval_aplus(dataset: Path, agent: bool) -> dict:
    cases = _load_jsonl(dataset)
    if not agent:
        from eval.condition_keywords import keyword_conditions
        from eval.payment_regex import regex_payment

        rows = []
        for c in cases:
            found = regex_payment(c["text"])
            rows.append({"id": c["id"], "expected": c.get("conditions", []),
                         "found": sorted(keyword_conditions(c["text"])),
                         "payment_expected": _stages(c["payment"]), "payment_found": _stages(found),
                         "payment_exact": _payment_ok(c, found)})
        return {"capability": "A+", "kind": "baseline_keywords_regex", "dataset": dataset.name,
                "dataset_hash": _file_hash(dataset), "conditions": _condition_metrics(rows),
                "payment": _payment_metrics(rows), "rows": rows}

    from app.config import get_settings
    from app.core import confidence
    from app.core.llm import build_llm
    from app.flows.proposal_flow import run_match_flow
    from app.models.match import IntakeResult, LibraryCondition, MatcherResult
    from app.tools.catalog_search import CatalogSearch, GeminiEmbedder

    settings = get_settings()
    catalog = [CatalogEntry(**c) for c in _catalog_items()]
    embedder = GeminiEmbedder(settings.gemini_api_key.get_secret_value(), settings.gemini_embedding_model)
    search = CatalogSearch(embedder, EmbeddingStore(STORE, persist=False))
    intake = build_llm(settings, IntakeResult)
    matcher = build_llm(settings, MatcherResult)
    lib = _conditions_library()
    library = [LibraryCondition(id=c["id"], text=c["text"]) for c in lib]
    key_of = {c["id"]: c["key"] for c in lib}

    rows = []
    for case in cases:
        start = time.perf_counter()
        result = run_match_flow(case["text"], catalog, intake, matcher, search, library)
        seconds = round(time.perf_counter() - start, 2)
        _pace(start, 2)
        rows.append({
            "id": case["id"], "seconds": seconds,
            "expected": case.get("conditions", []),
            "found": [key_of[c.condition_id] for c in result.conditions],
            "ticked": [key_of[c.condition_id] for c in result.conditions if not c.needs_review],
            "suggested": [{"key": key_of[c.condition_id], "source_text": c.source_text,
                           "confidence": c.confidence} for c in result.conditions],
            "unmatched_expected": len(case.get("unmatched_conditions", [])),
            "unmatched_found": len(result.unmatched_conditions),
            "unmatched": result.unmatched_conditions,
            "payment_expected": _stages(case["payment"]),
            "payment_found": _stages([s.model_dump() for s in result.payment]),
            "payment_exact": _payment_ok(case, [s.model_dump() for s in result.payment]),
            "payment_said": [s.model_dump() for s in result.payment],
            "lines": [ln.catalog_code for ln in result.lines],
            "warnings": result.warnings,
        })
    return {
        "capability": "A+", "kind": "agent", "dataset": dataset.name, "dataset_hash": _file_hash(dataset),
        "model": settings.gemini_model,
        "prompt_hash": {n: _file_hash(ROOT / "prompts" / f"{n}.md") for n in ("intake", "matcher")},
        "confidence": {"condition_score": confidence.CONDITION_SCORE, "review_below": confidence.REVIEW_BELOW},
        "conditions": _condition_metrics(rows),
        "payment": _payment_metrics(rows),
        "rows": rows,
    }


# --- B: review ----------------------------------------------------------------

def _demo_proposals() -> list[dict]:
    return json.loads((DEMO / "proposals.json").read_text(encoding="utf-8"))["items"]


def eval_review(dataset: Path, agent: bool = False) -> dict:
    catalog = [CatalogEntry(**c) for c in _catalog_items()]
    cases = _load_jsonl(dataset)
    llm = model = None
    if agent:
        from app.config import get_settings
        from app.core.llm import build_llm
        from app.flows.review import review_proposal
        from app.models.review import ReviewerResult

        settings = get_settings()
        model = settings.gemini_model
        llm = build_llm(settings, ReviewerResult)
    per_kind: dict[str, Counter] = {}
    rows = []
    for case in cases:
        # As the app does: prices become ratios on the phone, only they are sent.
        history = price_history(_demo_proposals(), exclude_id=case["base_proposal"])
        request = ReviewRequest(
            lines=[ratio_line(li, history, {}) for li in case["lines"]],
            condition_keys=case["condition_keys"],
            catalog=catalog,
        )
        start = time.perf_counter()
        if agent:
            results = review_proposal(request, llm).findings
        else:
            results = run_checks(request)
        seconds = round(time.perf_counter() - start, 2)
        if agent:
            _pace(start, 1)
        found = {(r.line_code, r.kind.value) for r in results}
        expected = {(e["line_code"], e["kind"]) for e in case["errors"]}
        for line_code, kind in expected | found:
            c = per_kind.setdefault(kind, Counter())
            key = (line_code, kind)
            c["tp" if key in expected and key in found else "fn" if key in expected else "fp"] += 1
        rows.append({
            "id": case["id"],
            "expected": sorted(map(list, expected), key=str),
            "found": sorted(map(list, found), key=str),
            "seconds": seconds,
            # The Reviewer's text is fictional demo data; kept for reading the run.
            **({"findings": [r.model_dump(mode="json") for r in results]} if agent else {}),
        })

    def metrics(c: Counter) -> dict:
        return {
            **c,
            "recall": _pct(c["tp"], c["tp"] + c["fn"]),
            "precision": _pct(c["tp"], c["tp"] + c["fp"]),
        }

    total = sum(per_kind.values(), Counter())
    return {
        "capability": "B",
        "kind": "reviewer" if agent else "baseline_code_checks",
        "dataset": dataset.name,
        "dataset_hash": _file_hash(dataset),
        "rules_hash": _file_hash(ROOT / "app" / "core" / "rules.yaml"),
        "model": model,
        "prompt_hash": _file_hash(ROOT / "prompts" / "reviewer.md") if agent else None,
        "by_kind": {k: metrics(v) for k, v in sorted(per_kind.items())},
        "total": metrics(total),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("capability", choices=["match", "review", "aplus"])
    parser.add_argument("--set", choices=["tune", "test", "natural"], default="tune",
                        help="natural: A+ payment in natural speech (aplus only)")
    parser.add_argument("--no-embed", action="store_true", help="BM25 only, no Gemini calls")
    parser.add_argument("--agent", action="store_true", help="run the agents (Gemini)")
    args = parser.parse_args()

    dataset = DATASETS / f"{args.capability}_{args.set}.jsonl"
    if args.capability == "match":
        if args.agent:
            result = eval_match_agent(dataset)
        else:
            result = eval_match(dataset, use_embeddings=not args.no_embed)
        print(json.dumps(result["summary_pct"], ensure_ascii=False, indent=2))
    elif args.capability == "aplus":
        result = eval_aplus(dataset, agent=args.agent)
        print(json.dumps({"conditions": result["conditions"], "payment": result["payment"]},
                         ensure_ascii=False, indent=2))
    else:
        result = eval_review(dataset, agent=args.agent)
        print(json.dumps({"by_kind": result["by_kind"], "total": result["total"]}, ensure_ascii=False, indent=2))
    name = f"{args.capability}_{args.set}" if args.agent else f"baseline_{args.capability}_{args.set}"
    print("saved:", _save(name, result).relative_to(ROOT))


if __name__ == "__main__":
    main()
