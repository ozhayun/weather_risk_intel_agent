"""FastAPI app: chat endpoint (LLM) plus deterministic read endpoints (no LLM)."""

import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request

from app.agent.llm import InstructorLLM
from app.agent.pipeline import Agent
from app.api.models import ChatRequest, ChatResponse, HubSummary
from app.config import Settings, get_settings, load_scoring_config
from app.data.db import connect, load_daily, load_meta, load_nri
from app.domain.hubs import HubRegistry, Region
from app.domain.queries import QueryContext, rank_hubs
from app.domain.results import RankResult
from app.domain.scoring import Hazard, HubScore, build_scorebook

log = logging.getLogger(__name__)
AgentFactory = Callable[[QueryContext], Agent]


def load_context(settings: Settings) -> QueryContext:
    cfg = load_scoring_config()
    registry = HubRegistry.from_json(settings.hubs_path)
    conn = connect(settings.db_path)
    try:
        daily, nri = load_daily(conn), load_nri(conn)
    finally:
        conn.close()
    return QueryContext(registry, build_scorebook(registry.all(), daily, nri, cfg), daily, cfg)


def _default_agent(settings: Settings) -> AgentFactory:
    return lambda ctx: Agent(InstructorLLM(settings.llm_model), ctx)


def build_app(agent_factory: AgentFactory | None = None) -> FastAPI:
    settings = get_settings()
    factory = agent_factory or _default_agent(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.ctx = load_context(settings)
        conn = connect(settings.db_path)
        app.state.meta = load_meta(conn)
        conn.close()
        try:
            app.state.agent = factory(app.state.ctx)
        except Exception:  # keep deterministic endpoints up without an LLM
            log.exception("LLM agent unavailable")
            app.state.agent = None
        yield

    app = FastAPI(title="Weather Risk Intelligence Agent", lifespan=lifespan)

    @app.post("/chat", response_model=ChatResponse)
    def chat(req: ChatRequest, request: Request) -> ChatResponse:
        agent: Agent | None = request.app.state.agent
        if agent is None:
            raise HTTPException(
                503,
                f"LLM not configured for {settings.llm_model}: set the "
                "provider key (e.g. OPENAI_API_KEY) in .env and restart.",
            )
        session_id = req.session_id or uuid4().hex
        out = agent.run(session_id, req.message)
        return ChatResponse(
            session_id=session_id, answer=out.answer, plan=out.plan, result=out.result
        )

    @app.get("/hubs", response_model=list[HubSummary])
    def hubs(request: Request) -> list[HubSummary]:
        ctx: QueryContext = request.app.state.ctx
        return [
            HubSummary(**s.model_dump(), state=ctx.registry.get(s.hub_id).state)
            for s in ctx.book.ranked()
        ]

    @app.get("/hubs/{hub}", response_model=HubScore)
    def hub_detail(hub: str, request: Request) -> HubScore:
        ctx: QueryContext = request.app.state.ctx
        found = ctx.registry.get(hub) or ctx.registry.resolve(hub)
        if found is None:
            raise HTTPException(404, f"Unknown hub '{hub}'. See GET /hubs.")
        return ctx.book.hubs[found.hub_id]

    @app.get("/rankings", response_model=RankResult)
    def rankings(
        request: Request,
        hazard: Hazard | Literal["overall"] = "overall",
        region: Region | None = None,
        top_n: int | None = Query(default=None, ge=1),
    ) -> RankResult:
        return rank_hubs(request.app.state.ctx, hazard, region, None, top_n)

    @app.get("/health")
    def health(request: Request) -> dict:
        return {
            "status": "ok",
            "llm_model": settings.llm_model,
            "llm_ready": request.app.state.agent is not None,
            "scoring_version": request.app.state.ctx.book.version,
            "dataset": request.app.state.meta,
        }

    return app


app = build_app()
