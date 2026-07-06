"""Trace endpoints: browse metadata, fetch bodies, re-score.

Re-scoring implements the replay path from system-design.md: the stored
body is read from the trace store and the rubric applied as a pure
function, with no LLM calls. A ``(trace_hash, rubric_hash)`` pair uniquely
identifies a score (ADR-0003), so re-scoring is idempotent: an existing
row is returned unchanged. Judge-required rubrics are non-deterministic and
cost money, so they run as a follow-up runner job (issue #19); this
endpoint enqueues the job and returns 202.
"""

from __future__ import annotations

import json
import uuid

from agent_arena.db.models import Rubric, Run, Score, Task, TraceMetadata
from agent_arena.trace_store import TraceNotFoundError, TraceStore
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from apps.api.audit import record_audit
from apps.api.auth import REQUIRE_RUNNER, Principal
from apps.api.db import get_session
from apps.api.queue import RunQueue, get_queue
from apps.api.schemas import RescoreIn, ScoreOut, TraceDetailOut, TraceMetadataOut
from apps.api.trace_store import get_trace_store
from apps.runner.contracts import DefinitionError, RubricDefinition, TaskDefinition
from apps.runner.scoring import ScoringError, score_answer

router = APIRouter(prefix="/api/v1", tags=["traces"])


@router.get("/traces", response_model=list[TraceMetadataOut])
async def list_traces(
    session: AsyncSession = Depends(get_session),
    limit: int = 50,
    offset: int = 0,
    run_id: uuid.UUID | None = None,
) -> list[TraceMetadata]:
    statement = (
        select(TraceMetadata).order_by(TraceMetadata.created_at.desc()).limit(limit).offset(offset)
    )
    if run_id is not None:
        statement = statement.where(TraceMetadata.run_id == run_id)
    result = await session.execute(statement)
    return list(result.scalars().all())


@router.get("/traces/{trace_hash}", response_model=TraceDetailOut)
async def get_trace(
    trace_hash: str, session: AsyncSession = Depends(get_session)
) -> TraceDetailOut:
    trace = await session.get(TraceMetadata, trace_hash)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace not found")
    scores = (
        (await session.execute(select(Score).where(Score.trace_hash == trace_hash))).scalars().all()
    )
    return TraceDetailOut(
        **TraceMetadataOut.model_validate(trace).model_dump(),
        scores=[ScoreOut.model_validate(score) for score in scores],
    )


@router.get("/traces/{trace_hash}/body")
async def get_trace_body(
    trace_hash: str,
    session: AsyncSession = Depends(get_session),
    store: TraceStore = Depends(get_trace_store),
) -> Response:
    trace = await session.get(TraceMetadata, trace_hash)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace not found")
    if trace.body_uri is None:
        raise HTTPException(status_code=409, detail="trace body was not persisted (pre M2 trace)")
    try:
        body = await run_in_threadpool(store.get, trace_hash)
    except TraceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="trace body missing from the store") from exc
    return Response(content=body, media_type="application/json")


@router.post("/traces/{trace_hash}/score", response_model=ScoreOut)
async def rescore_trace(
    trace_hash: str,
    payload: RescoreIn,
    response: Response,
    session: AsyncSession = Depends(get_session),
    store: TraceStore = Depends(get_trace_store),
    queue: RunQueue = Depends(get_queue),
    principal: Principal = Depends(REQUIRE_RUNNER),
) -> Score | JSONResponse:
    trace = await session.get(TraceMetadata, trace_hash)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace not found")
    rubric = await session.get(Rubric, payload.rubric_id)
    if rubric is None:
        raise HTTPException(status_code=422, detail="unknown rubric")

    existing = await session.get(Score, (trace_hash, rubric.definition_hash))
    if existing is not None:
        return existing

    if rubric.judge_required:
        record_audit(
            session,
            actor=principal.user,
            operation="trace.rescore.judge",
            resource=f"trace:{trace_hash}",
            payload={"rubric_id": str(payload.rubric_id)},
        )
        await session.commit()
        await run_in_threadpool(queue.enqueue_judge_score, trace_hash, payload.rubric_id)
        return JSONResponse(
            status_code=202,
            content={
                "status": "queued",
                "detail": "judge scoring runs as a follow-up job; poll the trace detail",
            },
        )

    if trace.body_uri is None:
        raise HTTPException(status_code=409, detail="trace body was not persisted (pre M2 trace)")
    try:
        body = await run_in_threadpool(store.get, trace_hash)
    except TraceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="trace body missing from the store") from exc

    run = await session.get(Run, trace.run_id)
    task = await session.get(Task, run.task_id) if run is not None else None
    if task is None:
        raise HTTPException(status_code=409, detail="the trace's task is no longer available")

    document = json.loads(body)
    try:
        rubric_definition = RubricDefinition.parse(rubric.definition)
        task_definition = TaskDefinition.parse(task.definition)
        result = score_answer(rubric_definition, task_definition, document.get("final_answer"))
    except (DefinitionError, ScoringError) as exc:
        raise HTTPException(status_code=422, detail=f"cannot apply rubric: {exc}") from exc

    score = Score(
        trace_hash=trace_hash,
        rubric_hash=rubric.definition_hash,
        score=result.score,
        is_correct=result.is_correct,
        score_detail=result.detail,
    )
    session.add(score)
    record_audit(
        session,
        actor=principal.user,
        operation="trace.rescore",
        resource=f"trace:{trace_hash}",
        payload={"rubric_id": str(payload.rubric_id), "rubric_hash": rubric.definition_hash},
    )
    try:
        await session.commit()
    except IntegrityError:
        # A concurrent re-score won the race; idempotence means returning it.
        await session.rollback()
        winner = await session.get(Score, (trace_hash, rubric.definition_hash))
        if winner is None:  # pragma: no cover - only on storage failure
            raise HTTPException(status_code=500, detail="score write failed") from None
        return winner
    await session.refresh(score)
    response.status_code = 201
    return score
