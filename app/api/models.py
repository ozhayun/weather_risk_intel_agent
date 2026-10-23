"""HTTP request/response models."""

from typing import Annotated

from pydantic import BaseModel, Field

from app.agent.schemas import Answer, QueryPlan
from app.domain.hubs import Region
from app.domain.results import Result
from app.domain.scoring import Hazard, Label


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=1000)


class ChatResponse(BaseModel):
    session_id: str
    answer: Answer
    plan: QueryPlan | None
    result: Annotated[Result, Field(discriminator="kind")] | None


class HubSummary(BaseModel):
    hub_id: str
    name: str
    state: str
    region: Region
    composite: float
    label: Label
    peak_hazard: Hazard
    overall_rank: int
