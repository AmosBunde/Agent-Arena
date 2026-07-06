"""Request and response models for the v1 API."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TaskIn(BaseModel):
    slug: str = Field(min_length=1)
    version: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    definition: dict[str, Any]
    capabilities_required: list[str] = Field(default_factory=list)


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    version: str
    domain: str
    definition: dict[str, Any]
    capabilities_required: list[str]
    created_at: datetime
    deprecated_at: datetime | None
    contamination: dict[str, Any] | None = None


class RubricIn(BaseModel):
    slug: str = Field(min_length=1)
    version: str = Field(min_length=1)
    definition: dict[str, Any]
    judge_required: bool = False


class RubricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    version: str
    definition_hash: str
    definition: dict[str, Any]
    judge_required: bool
    created_at: datetime


class AgentIn(BaseModel):
    slug: str = Field(min_length=1)
    version: str = Field(min_length=1)
    definition: dict[str, Any]


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    version: str
    definition: dict[str, Any]
    created_at: datetime


class ProviderModel(BaseModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)


class RunCreateIn(BaseModel):
    agent_id: uuid.UUID
    task_id: uuid.UUID
    rubric_id: uuid.UUID
    providers: list[ProviderModel] = Field(min_length=1)
    run_group_name: str | None = None


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_group_id: uuid.UUID | None
    agent_id: uuid.UUID
    task_id: uuid.UUID
    provider: str
    model: str
    rubric_id: uuid.UUID
    status: str
    failure_reason: str | None
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    created_by: str


class RunGroupOut(BaseModel):
    run_group_id: uuid.UUID
    runs: list[RunOut]


class AttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    attempt_number: int
    adapter_version: str
    started_at: datetime
    finished_at: datetime | None
    outcome: str


class TraceMetadataOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    hash: str
    run_id: uuid.UUID
    attempt_id: uuid.UUID
    body_uri: str | None
    body_size_bytes: int
    total_input_tokens: int
    total_output_tokens: int
    total_cached_tokens: int
    estimated_cost_usd: Decimal
    latency_ms: int
    tool_call_count: int
    created_at: datetime


class ScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trace_hash: str
    rubric_hash: str
    score: Decimal
    is_correct: bool
    score_detail: dict[str, Any]
    judge_model: str | None
    scored_at: datetime


class TraceDetailOut(TraceMetadataOut):
    scores: list[ScoreOut]


class RescoreIn(BaseModel):
    rubric_id: uuid.UUID


class RunDetailOut(RunOut):
    attempts: list[AttemptOut]
    traces: list[TraceMetadataOut]


class CancellationOut(BaseModel):
    id: uuid.UUID
    status: str
    detail: str


class TokenIn(BaseModel):
    name: str = Field(min_length=1)
    role: str
    expires_at: datetime | None = None


class TokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    prefix: str
    role: str
    created_by: str
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None


class TokenCreatedOut(TokenOut):
    # The plaintext value; present only in the creation response.
    token: str


class ParetoRowOut(BaseModel):
    agent_id: uuid.UUID
    task_id: uuid.UUID
    provider: str
    model: str
    rubric_hash: str
    correct_count: int
    total_count: int
    accuracy: Decimal
    mean_cost_usd: Decimal
    cost_per_correct_usd: Decimal | None
    on_front: bool


class LeaderboardRowOut(BaseModel):
    agent_id: uuid.UUID
    task_id: uuid.UUID
    provider: str
    model: str
    rubric_hash: str
    correct_count: int
    total_count: int
    mean_score: Decimal
    total_cost_usd: Decimal
    cost_per_correct_usd: Decimal | None
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    # 95 percent percentile bootstrap intervals (issue #23); None until the
    # scheduled job has computed the cell.
    accuracy_ci_low: Decimal | None = None
    accuracy_ci_high: Decimal | None = None
    cpca_ci_low_usd: Decimal | None = None
    cpca_ci_high_usd: Decimal | None = None
    ci_resamples: int | None = None
