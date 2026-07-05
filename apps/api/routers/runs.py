"""Run lifecycle endpoints.

``POST /runs`` implements the fan-out from system-design.md: one run group,
one run per requested provider, one queued runner job each. Cancellation
follows session-design.md: pending and queued runs cancel directly, running
runs get the cooperative Redis flag.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from agent_arena.db.models import Agent, Attempt, Rubric, Run, RunGroup, Task, TraceMetadata
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from apps.api.audit import record_audit
from apps.api.auth import REQUIRE_RUNNER, Principal
from apps.api.db import get_session
from apps.api.ids import uuid7
from apps.api.queue import RunQueue, get_queue
from apps.api.schemas import (
    AttemptOut,
    CancellationOut,
    RunCreateIn,
    RunDetailOut,
    RunGroupOut,
    RunOut,
    TraceMetadataOut,
)

router = APIRouter(prefix="/api/v1", tags=["runs"])


@router.get("/runs", response_model=list[RunOut])
async def list_runs(
    session: AsyncSession = Depends(get_session),
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    run_group_id: uuid.UUID | None = None,
) -> list[Run]:
    statement = select(Run).order_by(Run.queued_at.desc()).limit(limit).offset(offset)
    if status is not None:
        statement = statement.where(Run.status == status)
    if run_group_id is not None:
        statement = statement.where(Run.run_group_id == run_group_id)
    result = await session.execute(statement)
    return list(result.scalars().all())


@router.get("/runs/{run_id}", response_model=RunDetailOut)
async def get_run(run_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> RunDetailOut:
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    attempts = (
        (
            await session.execute(
                select(Attempt).where(Attempt.run_id == run_id).order_by(Attempt.attempt_number)
            )
        )
        .scalars()
        .all()
    )
    traces = (
        (await session.execute(select(TraceMetadata).where(TraceMetadata.run_id == run_id)))
        .scalars()
        .all()
    )
    return RunDetailOut(
        **RunOut.model_validate(run).model_dump(),
        attempts=[AttemptOut.model_validate(a) for a in attempts],
        traces=[TraceMetadataOut.model_validate(t) for t in traces],
    )


@router.post("/runs", response_model=RunGroupOut, status_code=201)
async def create_runs(
    payload: RunCreateIn,
    session: AsyncSession = Depends(get_session),
    queue: RunQueue = Depends(get_queue),
    principal: Principal = Depends(REQUIRE_RUNNER),
) -> RunGroupOut:
    task = await session.get(Task, payload.task_id)
    agent = await session.get(Agent, payload.agent_id)
    rubric = await session.get(Rubric, payload.rubric_id)
    missing = [
        name for name, row in (("task", task), ("agent", agent), ("rubric", rubric)) if row is None
    ]
    if missing:
        raise HTTPException(status_code=422, detail=f"unknown references: {missing}")

    group = RunGroup(name=payload.run_group_name, created_by=principal.user)
    session.add(group)
    await session.flush()

    runs: list[Run] = []
    for entry in payload.providers:
        run = Run(
            id=uuid7(),
            run_group_id=group.id,
            agent_id=payload.agent_id,
            task_id=payload.task_id,
            provider=entry.provider,
            model=entry.model,
            rubric_id=payload.rubric_id,
            status="queued",
            created_by=principal.user,
        )
        session.add(run)
        runs.append(run)
    record_audit(
        session,
        actor=principal.user,
        operation="run.create",
        resource=f"run_group:{group.id}",
        payload={
            "task_id": str(payload.task_id),
            "agent_id": str(payload.agent_id),
            "rubric_id": str(payload.rubric_id),
            "providers": [entry.model_dump() for entry in payload.providers],
        },
    )
    # Commit before enqueueing so a worker can never pick up a job whose row
    # is not yet visible.
    await session.commit()
    for run in runs:
        await run_in_threadpool(queue.enqueue_run, run.id)
    return RunGroupOut(
        run_group_id=group.id,
        runs=[RunOut.model_validate(run) for run in runs],
    )


@router.delete("/runs/{run_id}", response_model=CancellationOut)
async def cancel_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    queue: RunQueue = Depends(get_queue),
    principal: Principal = Depends(REQUIRE_RUNNER),
) -> CancellationOut:
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.status in ("complete", "failed", "cancelled"):
        raise HTTPException(status_code=409, detail=f"run is already {run.status}")

    record_audit(
        session,
        actor=principal.user,
        operation="run.cancel",
        resource=f"run:{run_id}",
        payload={"status_at_request": run.status},
    )
    # The flag is set for every non-terminal status: a pending or queued run
    # that a worker picks up between this read and the commit still sees the
    # flag at its first checkpoint.
    await run_in_threadpool(queue.request_cancellation, run_id)
    if run.status in ("pending", "queued"):
        run.status = "cancelled"
        run.finished_at = datetime.now(UTC)
        await session.commit()
        return CancellationOut(id=run_id, status="cancelled", detail="cancelled before start")
    await session.commit()
    return CancellationOut(
        id=run_id,
        status=run.status,
        detail="cancellation requested; the runner aborts at its next checkpoint",
    )
