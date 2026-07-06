"""Catalog resources: tasks, rubrics, agents.

CRUD-ish per issue #9: list, fetch, create. Creation requires the admin role
(session-design.md, Authorisation model). Rubric creation computes the
definition hash the scoring pipeline keys on.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from agent_arena.db.models import Agent, Rubric, Task
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.audit import record_audit
from apps.api.auth import REQUIRE_ADMIN, Principal
from apps.api.db import get_session
from apps.api.schemas import AgentIn, AgentOut, RubricIn, RubricOut, TaskIn, TaskOut

router = APIRouter(prefix="/api/v1", tags=["catalog"])


def rubric_definition_hash(definition: dict[str, Any]) -> str:
    """Deterministic hash of a rubric definition (sorted keys, compact)."""
    body = json.dumps(definition, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(
    session: AsyncSession = Depends(get_session),
    limit: int = 100,
    offset: int = 0,
) -> list[Task]:
    result = await session.execute(
        select(Task).order_by(Task.created_at.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all())


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task(task_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Task:
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@router.post("/tasks", response_model=TaskOut, status_code=201)
async def create_task(
    payload: TaskIn,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(REQUIRE_ADMIN),
) -> Task:
    task = Task(
        slug=payload.slug,
        version=payload.version,
        domain=payload.domain,
        definition=payload.definition,
        capabilities_required=payload.capabilities_required,
    )
    session.add(task)
    record_audit(
        session,
        actor=principal.user,
        operation="task.create",
        resource=f"task:{payload.slug}@{payload.version}",
        payload={"domain": payload.domain},
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="task slug and version already exist") from exc
    await session.refresh(task)
    return task


@router.get("/rubrics", response_model=list[RubricOut])
async def list_rubrics(
    session: AsyncSession = Depends(get_session),
    limit: int = 100,
    offset: int = 0,
) -> list[Rubric]:
    result = await session.execute(
        select(Rubric).order_by(Rubric.created_at.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all())


@router.get("/rubrics/{rubric_id}", response_model=RubricOut)
async def get_rubric(rubric_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Rubric:
    rubric = await session.get(Rubric, rubric_id)
    if rubric is None:
        raise HTTPException(status_code=404, detail="rubric not found")
    return rubric


@router.post("/rubrics", response_model=RubricOut, status_code=201)
async def create_rubric(
    payload: RubricIn,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(REQUIRE_ADMIN),
) -> Rubric:
    rubric = Rubric(
        slug=payload.slug,
        version=payload.version,
        definition=payload.definition,
        definition_hash=rubric_definition_hash(payload.definition),
        judge_required=payload.judge_required,
    )
    session.add(rubric)
    record_audit(
        session,
        actor=principal.user,
        operation="rubric.create",
        resource=f"rubric:{payload.slug}@{payload.version}",
        payload={"judge_required": payload.judge_required},
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="rubric slug and version, or an identical definition, already exist",
        ) from exc
    await session.refresh(rubric)
    return rubric


@router.get("/agents", response_model=list[AgentOut])
async def list_agents(
    session: AsyncSession = Depends(get_session),
    limit: int = 100,
    offset: int = 0,
) -> list[Agent]:
    result = await session.execute(
        select(Agent).order_by(Agent.created_at.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all())


@router.get("/agents/{agent_id}", response_model=AgentOut)
async def get_agent(agent_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> Agent:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return agent


@router.post("/agents", response_model=AgentOut, status_code=201)
async def create_agent(
    payload: AgentIn,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(REQUIRE_ADMIN),
) -> Agent:
    agent = Agent(slug=payload.slug, version=payload.version, definition=payload.definition)
    session.add(agent)
    record_audit(
        session,
        actor=principal.user,
        operation="agent.create",
        resource=f"agent:{payload.slug}@{payload.version}",
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="agent slug and version already exist") from exc
    await session.refresh(agent)
    return agent
