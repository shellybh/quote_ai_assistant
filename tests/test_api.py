from fastapi.testclient import TestClient

from app.api.schemas import MatchRequest, ReviewRequest
from app.main import MatchService, ReviewService, create_app, get_match_runner, get_review_runner
from app.models.match import MatchedLine, MatchResult
from app.models.review import ReviewFinding, ReviewResult
from tests.conftest import AUTH, make_settings

CATALOG = [{"code": "01.09.001.0270", "description": "ייצוב ושיקום טיח על בסיס סיד", "unit": 'מ"ר'}]
BODY = {"text": "לייצב טיח בחזית", "catalog": CATALOG}


def test_health_is_public(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["model"] == "gemini-test-model"


def test_missing_or_wrong_token_is_401(client):
    assert client.post("/v1/match-items", json=BODY).status_code == 401
    wrong = {"Authorization": "Bearer nope"}
    assert client.post("/v1/match-items", json=BODY, headers=wrong).status_code == 401


def test_match_items_returns_structured_output():
    app = create_app(make_settings())
    line = MatchedLine(source_text="ייצוב טיח", catalog_code="01.09.001.0270", quantity=None,
                       unit='מ"ר', confidence=0.9, needs_review=False, reason="התאמה")
    app.dependency_overrides[get_match_runner] = lambda: (lambda body: MatchResult(lines=[line]))
    r = TestClient(app).post("/v1/match-items", json=BODY, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["lines"][0]["catalog_code"] == "01.09.001.0270"


def test_bad_body_is_422(client):
    assert client.post("/v1/match-items", json={"text": "", "catalog": CATALOG}, headers=AUTH).status_code == 422


def test_too_large_is_413():
    client = TestClient(create_app(make_settings(max_request_mb=0.001)))
    r = client.post("/v1/match-items", json={"text": "א" * 2000, "catalog": CATALOG}, headers=AUTH)
    assert r.status_code == 413


def test_rate_limit_is_429():
    client = TestClient(create_app(make_settings(rate_limit="2/minute")))
    codes = [client.post("/v1/match-items", json={}, headers=AUTH).status_code for _ in range(3)]
    assert codes == [422, 422, 429]


REVIEW = {
    "lines": [{"code": "01.09.001.0270", "description": "ייצוב טיח", "unit": 'מ"ר',
               "quantity": 10, "history_ratio": 1.1, "history_count": 4, "catalog_ratio": 1.0}],
    "condition_keys": ["payment"],
}


def test_review_refuses_a_price():
    # No price may reach the server (30.10.2026): the app sends ratios only.
    body = {**REVIEW, "lines": [{**REVIEW["lines"][0], "unit_price": 100}]}
    r = TestClient(create_app(make_settings())).post("/v1/review-proposal", json=body, headers=AUTH)
    assert r.status_code == 422


def test_review_needs_a_token(client):
    assert client.post("/v1/review-proposal", json=REVIEW).status_code == 401


def test_review_returns_findings():
    app = create_app(make_settings())
    finding = ReviewFinding(severity="high", kind="missing_condition", problem="חסר תנאי",
                            why="סיבה", suggestion="להוסיף")
    app.dependency_overrides[get_review_runner] = lambda: (lambda body: ReviewResult(findings=[finding]))
    r = TestClient(app).post("/v1/review-proposal", json=REVIEW, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["findings"][0]["kind"] == "missing_condition"


def test_review_bad_body_is_422(client):
    bad = {**REVIEW, "lines": []}
    assert client.post("/v1/review-proposal", json=bad, headers=AUTH).status_code == 422


def test_review_identical_request_is_cached(monkeypatch):
    calls = []
    monkeypatch.setattr("app.main.run_review_flow", lambda body, llm: calls.append(1) or ReviewResult())
    service = ReviewService(make_settings())
    body = ReviewRequest(**REVIEW)
    service(body), service(body)
    assert len(calls) == 1


def test_rate_limited_model_is_429_with_retry_after():
    from app.core.llm import LLMRateLimited

    def limited(body):
        raise LLMRateLimited("ReviewerResult")

    app = create_app(make_settings())
    app.dependency_overrides[get_review_runner] = lambda: limited
    r = TestClient(app).post("/v1/review-proposal", json=REVIEW, headers=AUTH)
    assert r.status_code == 429 and r.headers["retry-after"] == "60"


def test_match_accepts_a_conditions_library_and_caches_by_it(monkeypatch):
    calls = []
    monkeypatch.setattr("app.main._build_search", lambda settings: None)
    monkeypatch.setattr("app.main.run_match_flow",
                        lambda text, catalog, i, m, search, conditions: calls.append(conditions) or MatchResult())
    service = MatchService(make_settings())
    lib = [{"id": "c-1", "text": "פיגום אינו כלול"}]
    service(MatchRequest(**BODY, conditions=lib)), service(MatchRequest(**BODY, conditions=lib))
    service(MatchRequest(**BODY, conditions=[{"id": "c-1", "text": "פיגום כלול"}]))
    assert len(calls) == 2  # same library: cached; another wording: a new run
    assert calls[0][0].id == "c-1"


def test_condition_with_an_unknown_field_is_422(client):
    body = {**BODY, "conditions": [{"id": "c-1", "text": "תנאי", "key": "x"}]}
    assert client.post("/v1/match-items", json=body, headers=AUTH).status_code == 422


def test_catalog_line_with_a_price_is_refused(client):
    # Catalog lines take code, description and unit only (7.11.2026).
    priced = [{**CATALOG[0], "base_price": 100}]
    assert client.post("/v1/match-items", json={"text": "ייצוב טיח", "catalog": priced},
                       headers=AUTH).status_code == 422
    review = {**REVIEW, "catalog": priced}
    assert client.post("/v1/review-proposal", json=review, headers=AUTH).status_code == 422
