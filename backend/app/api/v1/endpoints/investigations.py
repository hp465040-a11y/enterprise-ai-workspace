"""Authenticated, organization-scoped access to the existing read-only Core Agent."""

import asyncio
import json
import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from structlog.contextvars import get_contextvars

from app.ai.agents.core_agent import CoreAgentError, run_core_agent
from app.ai.agents.investigation_report import render_report, validate_report
from app.ai.llm.factory import get_llm_provider
from app.api.deps import CurrentUser, DBSession
from app.core.exceptions import NotFoundError, PermissionDeniedError, ValidationAppError
from app.models.investigation_run import InvestigationRun
from app.models.organization import OrgRole
from app.models.workspace import WorkspaceRole
from app.schemas.investigation import (
    InvestigationRequest,
    InvestigationResponse,
    InvestigationRunRead,
    observations_from_trace,
)
from app.services import investigation_run_service as runs
from app.services import organization_service, workspace_service

router = APIRouter(prefix="/organizations/{organization_id}/investigations", tags=["investigations"])


def _read(run: InvestigationRun) -> InvestigationRunRead:
    return InvestigationRunRead(
        id=run.id, organization_id=run.organization_id, case_id=run.case_id,
        workspace_id=run.workspace_id, as_of=run.as_of, status=run.status,
        deadline_at=run.deadline_at, created_at=run.created_at,
        finished_at=run.finished_at, error_code=run.error_code,
        result=InvestigationResponse.model_validate(run.response) if run.response else None,
    )


@router.get("", response_model=list[InvestigationRunRead])
async def list_runs(organization_id: UUID, current_user: CurrentUser,
                    db: DBSession) -> list[InvestigationRunRead]:
    user_id = current_user.id
    await organization_service.require_role(
        db, organization_id=organization_id, user_id=user_id,
        minimum_role=OrgRole.MEMBER.value)
    await runs.expire(db, organization_id=organization_id, user_id=user_id)
    return [_read(run) for run in await runs.list_authorized(
        db, organization_id=organization_id, user_id=user_id)]


@router.get("/submissions/{submission_key}", response_model=InvestigationRunRead)
async def read_submission(organization_id: UUID, submission_key: str,
                          current_user: CurrentUser, db: DBSession) -> InvestigationRunRead:
    await organization_service.require_role(
        db, organization_id=organization_id, user_id=current_user.id,
        minimum_role=OrgRole.MEMBER.value)
    run_id = (await db.execute(select(InvestigationRun.id).where(
        InvestigationRun.organization_id == organization_id,
        InvestigationRun.requested_by_user_id == current_user.id,
        InvestigationRun.submission_key == submission_key,
    ))).scalar_one_or_none()
    if run_id is None:
        raise NotFoundError("Investigation not found")
    return await read_run(organization_id, run_id, current_user, db)


@router.get("/runs/{run_id}", response_model=InvestigationRunRead)
async def read_run(organization_id: UUID, run_id: UUID, current_user: CurrentUser,
                   db: DBSession) -> InvestigationRunRead:
    user_id = current_user.id
    await runs.authorized_run(db, organization_id=organization_id,
                              user_id=user_id, run_id=run_id)
    await runs.expire(db, run_id=run_id, organization_id=organization_id,
                      user_id=user_id)
    return _read(await runs.authorized_run(db, organization_id=organization_id,
                                            user_id=user_id, run_id=run_id))


@router.post("", response_model=InvestigationResponse | InvestigationRunRead)
async def investigate(
    organization_id: UUID,
    payload: InvestigationRequest,
    current_user: CurrentUser,
    db: DBSession,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> InvestigationResponse | InvestigationRunRead | JSONResponse:
    """Members may investigate cases; only submission/report records are written."""
    membership = await organization_service.require_role(
        db, organization_id=organization_id, user_id=current_user.id,
        minimum_role=OrgRole.MEMBER.value,
    )
    knowledge_context = {}
    if payload.workspace_id is not None:
        try:
            workspace = await workspace_service.get_workspace(db, payload.workspace_id)
        except NotFoundError:
            raise PermissionDeniedError("Knowledge scope is not accessible") from None
        if workspace.organization_id != membership.organization_id:
            raise PermissionDeniedError("Knowledge scope is not accessible")
        workspace_member = await workspace_service.require_workspace_role(
            db, workspace_id=workspace.id, user_id=current_user.id,
            minimum_role=WorkspaceRole.VIEWER.value,
        )
        knowledge_context = {"user_id": workspace_member.user_id,
                             "workspace_id": workspace_member.workspace_id}
        if payload.require_knowledge:
            knowledge_context["require_knowledge"] = True
    if idempotency_key is not None and not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", idempotency_key):
        raise ValidationAppError("Invalid investigation submission key")
    verified_org_id = membership.organization_id
    verified_user_id = current_user.id
    # Release the authentication read transaction before reserving or running the model.
    session_factory = async_sessionmaker(bind=db.bind, expire_on_commit=False)
    await db.rollback()
    async with session_factory() as reservation_db:
        run, created = await runs.reserve(
            reservation_db, organization_id=verified_org_id, user_id=verified_user_id,
            submission_key=idempotency_key or str(uuid4()), case_id=payload.case_id,
            as_of=payload.as_of, workspace_id=payload.workspace_id,
            require_knowledge=payload.require_knowledge)
    if not created:
        async with session_factory() as read_db:
            await runs.expire(read_db, run_id=run.id,
                              organization_id=verified_org_id, user_id=verified_user_id)
            run = await runs.authorized_run(read_db, organization_id=verified_org_id,
                                            user_id=verified_user_id, run_id=run.id)
            if run.status == "succeeded" and run.response is not None:
                return InvestigationResponse.model_validate(run.response)
            read = _read(run)
            return JSONResponse(status_code=202 if run.status == "running" else 200,
                                content=read.model_dump(mode="json"))
    as_of = run.as_of.astimezone(UTC)
    try:
        async with session_factory() as agent_db:
            remaining = max(0, (run.deadline_at - datetime.now(UTC)).total_seconds())
            result = await asyncio.wait_for(run_core_agent(
                get_llm_provider(), agent_db, organization_id=verified_org_id,
                case_id=payload.case_id, as_of=as_of, **knowledge_context,
            ), timeout=remaining)
        verified_report = validate_report(json.dumps(result.report), result.trace)
        if render_report(verified_report, result.trace) != result.answer:
            raise ValueError("Core handoff differs from its verified report")
        response = InvestigationResponse(
            run_id=run.id, request_id=get_contextvars().get("request_id") or str(uuid4()),
            organization_id=verified_org_id, case_id=payload.case_id, as_of=as_of,
            report=verified_report, handoff=result.answer,
            observations=observations_from_trace(result.trace),
        )
        async with session_factory() as finish_db:
            saved = await runs.finish(finish_db, run.id, response=response.model_dump(mode="json"))
        if not saved:
            raise CoreAgentError("Investigation deadline elapsed before the report was saved",
                                 error_code="outer_timeout")
        return response
    except CoreAgentError as exc:
        async with session_factory() as finish_db:
            terminal = await runs.finish(finish_db, run.id, error_code=exc.error_code)
        if not terminal:
            async with session_factory() as reconcile_db:
                await runs.expire(reconcile_db, run_id=run.id,
                                  organization_id=verified_org_id, user_id=verified_user_id)
        if exc.error_code == "knowledge_permission_denied":
            raise PermissionDeniedError("Knowledge scope is no longer accessible") from None
        # Keep the existing failure code, but never publish traces or exception details.
        raise CoreAgentError("Investigation failed; no business conclusion produced",
                             error_code=exc.error_code) from None
    except asyncio.CancelledError:
        # A disconnected client may cancel this coroutine. If this write is also
        # cancelled, the persisted deadline still makes the run terminal on read.
        async def mark_cancelled() -> None:
            async with session_factory() as finish_db:
                await runs.finish(finish_db, run.id, error_code="request_cancelled")
        try:
            await asyncio.shield(mark_cancelled())
        finally:
            raise
    except TimeoutError:
        async with session_factory() as finish_db:
            await runs.expire(finish_db, run_id=run.id,
                              organization_id=verified_org_id, user_id=verified_user_id)
        raise CoreAgentError("Investigation deadline exceeded", error_code="outer_timeout") from None
    except Exception:  # noqa: BLE001 -- public boundary, including Provider construction failures
        try:
            async with session_factory() as finish_db:
                terminal = await runs.finish(finish_db, run.id, error_code="investigation_failed")
            if not terminal:
                async with session_factory() as reconcile_db:
                    await runs.expire(reconcile_db, run_id=run.id,
                                      organization_id=verified_org_id, user_id=verified_user_id)
        except Exception:  # noqa: BLE001 -- a failed save must never yield success
            pass
        raise CoreAgentError("Investigation failed; no business conclusion produced") from None
