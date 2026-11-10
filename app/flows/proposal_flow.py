"""The one CrewAI Flow (SPEC 5.1): receive -> route by request kind -> branch.

"match" is capability A, "review" capability B.
CrewAI's tracing and memory stay off: request content must not be stored or
sent anywhere except the Gemini call itself. Each run writes one
content-free trace line instead (app/core/tracing.py).

The review request carries prices, so it is kept in a private attribute,
not in the Flow state (CrewAI attaches the state to its internal events).
"""

from typing import Literal

from crewai.flow.flow import Flow, listen, router, start
from crewai.llms.base_llm import BaseLLM
from pydantic import BaseModel, Field, PrivateAttr

from app.api.schemas import ReviewRequest
from app.core import tracing
from app.flows.match import match_items
from app.flows.review import review_proposal
from app.models.catalog import CatalogEntry
from app.models.match import LibraryCondition, MatchResult
from app.models.review import ReviewResult
from app.tools.catalog_search import CatalogSearch


class ProposalState(BaseModel):
    kind: Literal["match", "review"] = "match"
    text: str = ""
    catalog: list[CatalogEntry] = Field(default_factory=list)
    conditions: list[LibraryCondition] = Field(default_factory=list)
    match_result: MatchResult | None = None
    review_result: ReviewResult | None = None


class ProposalFlow(Flow[ProposalState]):
    _intake_llm: BaseLLM | None = PrivateAttr(default=None)
    _matcher_llm: BaseLLM | None = PrivateAttr(default=None)
    _search: CatalogSearch | None = PrivateAttr(default=None)
    _reviewer_llm: BaseLLM | None = PrivateAttr(default=None)
    _review_request: ReviewRequest | None = PrivateAttr(default=None)

    @classmethod
    def create(
        cls,
        *,
        intake_llm: BaseLLM | None = None,
        matcher_llm: BaseLLM | None = None,
        search: CatalogSearch | None = None,
        reviewer_llm: BaseLLM | None = None,
        review_request: ReviewRequest | None = None,
    ) -> "ProposalFlow":
        flow = cls(tracing=False)
        flow._intake_llm = intake_llm
        flow._matcher_llm = matcher_llm
        flow._search = search
        flow._reviewer_llm = reviewer_llm
        flow._review_request = review_request
        return flow

    @start()
    def receive(self):
        if self.state.kind == "match":
            if not (self.state.text.strip() and self.state.catalog):
                raise ValueError("match needs text and a catalog")
            if None in (self._intake_llm, self._matcher_llm, self._search):
                raise ValueError("match needs the Intake and Matcher LLMs and a search")
        elif self._review_request is None or self._reviewer_llm is None:
            raise ValueError("review needs a request and the Reviewer LLM")

    @router(receive)
    def route(self):
        return self.state.kind

    @listen("match")
    def match_branch(self):
        self.state.match_result = match_items(
            self.state.text,
            self.state.catalog,
            self._intake_llm,
            self._matcher_llm,
            self._search,
            self.state.conditions,
        )
        return self.state.match_result

    @listen("review")
    def review_branch(self):
        self.state.review_result = review_proposal(self._review_request, self._reviewer_llm)
        return self.state.review_result


def run_match_flow(
    text: str,
    catalog: list[CatalogEntry],
    intake_llm: BaseLLM,
    matcher_llm: BaseLLM,
    search: CatalogSearch,
    conditions: list[LibraryCondition] | None = None,
) -> MatchResult:
    flow = ProposalFlow.create(intake_llm=intake_llm, matcher_llm=matcher_llm, search=search)
    with tracing.Trace("match"):
        flow.kickoff(inputs={
            "kind": "match", "text": text, "catalog": catalog, "conditions": conditions or [],
        })
    if flow.state.match_result is None:
        raise RuntimeError("match branch produced no result")
    return flow.state.match_result


def run_review_flow(request: ReviewRequest, reviewer_llm: BaseLLM) -> ReviewResult:
    flow = ProposalFlow.create(reviewer_llm=reviewer_llm, review_request=request)
    with tracing.Trace("review"):
        flow.kickoff(inputs={"kind": "review"})
    if flow.state.review_result is None:
        raise RuntimeError("review branch produced no result")
    return flow.state.review_result
