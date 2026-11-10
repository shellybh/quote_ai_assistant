"""FastAPI app: token, rate limit, size limit, timeout, content-free logging."""

import asyncio
import logging
import secrets
import time
import hashlib
import threading
from collections import OrderedDict
from collections.abc import Callable
from functools import partial
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from pydantic import BaseModel
from slowapi.util import get_remote_address

from app import __version__
from app.api.schemas import MatchRequest, ReviewRequest
from app.config import Settings, get_settings
from app.core.llm import LLMOutputError, LLMRateLimited, build_llm
from app.flows.proposal_flow import run_match_flow, run_review_flow
from app.models.match import IntakeResult, MatcherResult, MatchResult
from app.models.review import ReviewerResult, ReviewResult
from app.tools.catalog_search import (
    CatalogSearch,
    EmbeddingStore,
    GeminiEmbedder,
    catalog_fingerprint,
)

# Only time, method, path, status and duration. Never bodies or headers.
log = logging.getLogger("price_ai.access")

PUBLIC_PATHS = {"/health"}
# Vectors of the public catalog, built once (scripts/build_catalog_embeddings.py)
# so a Railway cold start costs no embedding quota.
CATALOG_VECTORS = Path(__file__).resolve().parents[1] / "data" / "demo" / "catalog_embeddings.npz"
CACHE_SIZE = 64  # identical match requests are answered from memory


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


def _build_search(settings: Settings) -> CatalogSearch:
    embedder = None
    if settings.gemini_api_key is not None:
        embedder = GeminiEmbedder(
            settings.gemini_api_key.get_secret_value(), settings.gemini_embedding_model
        )
    # persist=False: vectors of new catalog lines stay in memory only.
    return CatalogSearch(embedder, EmbeddingStore(CATALOG_VECTORS, persist=False))


class ResultCache:
    """Identical requests are answered from memory (keys are hashes only)."""

    def __init__(self, size: int = CACHE_SIZE):
        self._size = size
        self._items: OrderedDict[str, BaseModel] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
        return None

    def put(self, key: str, value: BaseModel) -> None:
        with self._lock:
            self._items[key] = value
            if len(self._items) > self._size:
                self._items.popitem(last=False)


def _key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class MatchService:
    """Builds the search once, caches identical requests, runs the Flow."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._search: CatalogSearch | None = None
        self._cache = ResultCache()
        self._lock = threading.Lock()

    def __call__(self, body: MatchRequest) -> MatchResult:
        library = "|".join(f"{c.id}={c.text}" for c in body.conditions)
        key = _key(f"{body.text}|{catalog_fingerprint(body.catalog)}|{library}")
        if (hit := self._cache.get(key)) is not None:
            return hit
        with self._lock:
            if self._search is None:
                self._search = _build_search(self._settings)
        result = run_match_flow(
            body.text,
            body.catalog,
            build_llm(self._settings, IntakeResult),
            build_llm(self._settings, MatcherResult),
            self._search,
            body.conditions,
        )
        self._cache.put(key, result)
        return result


class ReviewService:
    """Caches identical review requests and runs the Flow's review branch."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._cache = ResultCache()

    def __call__(self, body: ReviewRequest) -> ReviewResult:
        key = _key(body.model_dump_json())
        if (hit := self._cache.get(key)) is not None:
            return hit
        result = run_review_flow(body, build_llm(self._settings, ReviewerResult))
        self._cache.put(key, result)
        return result


def get_match_runner(request: Request) -> Callable[[MatchRequest], MatchResult]:
    return request.app.state.match_service


def get_review_runner(request: Request) -> Callable[[ReviewRequest], ReviewResult]:
    return request.app.state.review_service


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="price-ai-backend",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.match_service = MatchService(settings)
    app.state.review_service = ReviewService(settings)

    limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit])
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    expected_auth = f"Bearer {settings.app_token.get_secret_value()}"

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # Registered last, so it wraps everything (including the rate limiter).
        start = time.perf_counter()
        status = 500
        try:
            if request.url.path not in PUBLIC_PATHS:
                auth = request.headers.get("authorization", "")
                if not secrets.compare_digest(auth.encode(), expected_auth.encode()):
                    status = 401
                    return _error(401, "טוקן חסר או שגוי")

            length = request.headers.get("content-length")
            if length is not None:
                too_big = not length.isdigit() or int(length) > settings.max_request_bytes
            else:
                too_big = len(await request.body()) > settings.max_request_bytes
            if too_big:
                status = 413
                return _error(413, "הבקשה גדולה מדי")

            try:
                response = await asyncio.wait_for(
                    call_next(request), timeout=settings.request_timeout_s
                )
            except TimeoutError:
                status = 504
                return _error(504, "עבר הזמן המקסימלי לבקשה")
            status = response.status_code
            return response
        finally:
            ms = (time.perf_counter() - start) * 1000
            log.info("%s %s %s %.0fms", request.method, request.url.path, status, ms)

    @app.exception_handler(LLMOutputError)
    async def llm_output_error(request: Request, exc: LLMOutputError):
        return _error(502, "המודל החזיר תשובה פגומה. נסו שוב.")

    @app.exception_handler(LLMRateLimited)
    async def llm_rate_limited(request: Request, exc: LLMRateLimited):
        response = _error(429, "יותר מדי בקשות למודל כרגע. נסו שוב בעוד דקה.")
        response.headers["Retry-After"] = "60"
        return response

    @app.get("/health")
    @limiter.exempt
    async def health():
        return {"status": "ok", "version": __version__, "model": settings.gemini_model}

    @app.post("/v1/match-items", response_model=MatchResult)
    async def match_items(
        body: MatchRequest,
        runner: Callable[[MatchRequest], MatchResult] = Depends(get_match_runner),
    ):
        return await run_in_threadpool(partial(runner, body))

    @app.post("/v1/review-proposal", response_model=ReviewResult)
    async def review_proposal(
        body: ReviewRequest,
        runner: Callable[[ReviewRequest], ReviewResult] = Depends(get_review_runner),
    ):
        return await run_in_threadpool(partial(runner, body))

    return app


# Third-party loggers stay at WARNING; only our access and trace lines are INFO.
logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s")
log.setLevel(logging.INFO)
logging.getLogger("price_ai.trace").setLevel(logging.INFO)
app = create_app()
