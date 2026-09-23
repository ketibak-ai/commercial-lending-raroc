"""REST API: portfolio analytics, deal pricing, policy search and the AI pricing copilot.

Run:  uvicorn raroc.api:app --reload
"""

from __future__ import annotations

import logging
import os
import secrets
import time
import uuid
from typing import Literal

import anthropic
from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import PlainTextResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from . import service
from .config import ModelSettings
from .observability import METRICS, log_event, request_id, setup_logging

setup_logging(os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("raroc.api")

app = FastAPI(
    title="Commercial Lending RAROC Pricing API",
    version="1.0.0",
    description="Synthetic commercial banking portfolio: RAROC analytics, deal pricing, "
                "policy RAG and a Claude-powered pricing copilot.",
)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(key: str | None = Security(_api_key_header)) -> None:
    """If APP_API_KEY is set, every data endpoint requires a matching X-API-Key header."""
    expected = os.getenv("APP_API_KEY")
    if expected and not (key and secrets.compare_digest(key, expected)):
        raise HTTPException(status_code=401, detail="invalid or missing API key")


@app.middleware("http")
async def observe(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    token = request_id.set(rid)
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = rid
        return response
    finally:
        elapsed = time.perf_counter() - start
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        METRICS.inc("http_requests_total", method=request.method, path=path, status=status)
        METRICS.observe("http_request_seconds", elapsed, path=path)
        log_event(log, "request", method=request.method, path=path, status=status,
                  latency_ms=round(elapsed * 1000, 1))
        request_id.reset(token)


# ---------- schemas ----------------------------------------------------------------------
class DealIn(BaseModel):
    product: Literal["Term Loan", "Revolver"] = "Term Loan"
    amount: float = Field(10_000_000, gt=0, le=5e9)
    tenor_yrs: float = Field(5, gt=0, le=30)
    rating: int = Field(5, ge=1, le=10)
    collateral: Literal["Senior Secured", "Real Estate", "Unsecured"] = "Senior Secured"
    orig_fee_pct: float = Field(0.005, ge=0, le=0.05)
    utilization: float = Field(0.5, ge=0, le=1)
    unused_fee: float = Field(0.0025, ge=0, le=0.02)
    relationship_id: str | None = Field(None, pattern=r"^R\d{3}$")
    target_raroc: float = Field(0.12, gt=0, le=1)


class ModelIn(BaseModel):
    """Risk and capital model choices (all optional; defaults = economic-capital RAROC)."""
    capital_basis: Literal["economic", "regulatory", "max"] = "economic"
    basel_approach: Literal["SA", "FIRB", "AIRB"] = "AIRB"
    output_floor: bool = False
    cet1_target: float = Field(0.105, ge=0.04, le=0.30)
    el_pd_basis: Literal["TTC", "PIT"] = "TTC"
    ecap_method: Literal["analytic", "factor"] = "analytic"
    cycle_shift: float = Field(0.0, ge=-3, le=3)

    def settings(self) -> ModelSettings:
        return ModelSettings(**self.model_dump())


class PriceIn(DealIn):
    model: ModelIn = Field(default_factory=ModelIn)


class QueryIn(BaseModel):
    query: str = Field(..., min_length=2, max_length=500)


class AskIn(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)


# ---------- endpoints --------------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    return {"status": "ok", "accounts": int(len(service.portfolio()["result_accounts"]))}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    return METRICS.render()


@app.get("/portfolio/summary", dependencies=[Depends(require_api_key)])
def portfolio_summary(model: ModelIn = Depends()) -> dict:
    return service.portfolio_summary(model.settings())


@app.get("/relationships/key", dependencies=[Depends(require_api_key)])
def key_relationships(model: ModelIn = Depends()) -> list[dict]:
    return service.key_relationships(model.settings())


@app.get("/relationships/{relationship_id}", dependencies=[Depends(require_api_key)])
def relationship(relationship_id: str, model: ModelIn = Depends()) -> dict:
    try:
        return service.relationship_detail(relationship_id, model.settings())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/price", dependencies=[Depends(require_api_key)])
def price(deal: PriceIn) -> dict:
    args = deal.model_dump(exclude={"model"})
    try:
        return service.price(settings=deal.model.settings(), **args)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/models/ecap-factors", dependencies=[Depends(require_api_key)])
def ecap_factors() -> dict:
    return service.ecap_factors()


@app.get("/models/pit-factors", dependencies=[Depends(require_api_key)])
def pit_factors(cycle_shift: float = 0.0) -> list[dict]:
    if not -3 <= cycle_shift <= 3:
        raise HTTPException(status_code=422, detail="cycle_shift must be between -3 and 3")
    return service.pit_factors(cycle_shift)


@app.post("/policy/search", dependencies=[Depends(require_api_key)])
def policy_search(q: QueryIn) -> list[dict]:
    return service.policy_search(q.query)


@app.post("/ask", dependencies=[Depends(require_api_key)])
def ask(body: AskIn) -> dict:
    from .agent import ask as agent_ask  # lazy: API works without LLM credentials

    try:
        r = agent_ask(body.question)
    except (anthropic.AuthenticationError, TypeError) as exc:  # TypeError: no credentials
        raise HTTPException(503, "LLM credentials not configured (set ANTHROPIC_API_KEY)") from exc
    except anthropic.RateLimitError as exc:
        raise HTTPException(429, "LLM rate limited; retry shortly") from exc
    except anthropic.APIConnectionError as exc:
        raise HTTPException(502, "LLM service unreachable") from exc
    except anthropic.APIStatusError as exc:
        log.exception("llm_error")
        raise HTTPException(502, f"LLM error {exc.status_code}") from exc
    return {"answer": r.answer, "tool_calls": r.tool_calls, "usage": r.usage,
            "model": r.model, "stop_reason": r.stop_reason, "latency_s": r.latency_s}
