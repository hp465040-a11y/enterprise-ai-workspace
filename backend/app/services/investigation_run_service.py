"""Short transactions for investigation reservations, results and authorized reads."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import case, null, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AlreadyExistsError, NotFoundError, PermissionDeniedError
from app.models.investigation_run import InvestigationRun
from app.models.organization import OrgRole
from app.models.workspace import WorkspaceRole
from app.services import organization_service, workspace_service

OUTER_TIMEOUT_SECONDS = 690
INSTANCE_ID = uuid4()  # Single API worker in the current Compose/local deployment.


def request_hash(*, case_id: UUID, as_of: datetime | None, workspace_id: UUID | None,
                 require_knowledge: bool) -> str:
    """Hash submitted parameters, including whether analysis time was omitted."""
    value = {"case_id": str(case_id), "as_of": as_of.astimezone(UTC).isoformat() if as_of else None,
             "workspace_id": str(workspace_id) if workspace_id else None,
             "require_knowledge": require_knowledge}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def reserve(db: AsyncSession, *, organization_id: UUID, user_id: UUID, submission_key: str,
                  case_id: UUID, as_of: datetime | None, workspace_id: UUID | None,
                  require_knowledge: bool) -> tuple[InvestigationRun, bool]:
    """A database uniqueness constraint elects exactly one executor per scoped key."""
    now = datetime.now(UTC)
    fingerprint = request_hash(case_id=case_id, as_of=as_of, workspace_id=workspace_id,
                               require_knowledge=require_knowledge)
    run_id = uuid4()
    statement = insert(InvestigationRun).values(
        id=run_id, organization_id=organization_id, requested_by_user_id=user_id,
        submission_key=submission_key, request_hash=fingerprint, case_id=case_id,
        executor_instance_id=INSTANCE_ID,
        workspace_id=workspace_id, require_knowledge=require_knowledge,
        as_of=as_of.astimezone(UTC) if as_of else now,
        deadline_at=now + timedelta(seconds=OUTER_TIMEOUT_SECONDS), status="running",
    ).on_conflict_do_nothing(constraint="uq_investigation_runs_org_user_key").returning(InvestigationRun.id)
    created = (await db.execute(statement)).scalar_one_or_none() is not None
    await db.commit()  # Occupancy is visible before the long model call.
    run = (await db.execute(select(InvestigationRun).where(
        InvestigationRun.organization_id == organization_id,
        InvestigationRun.requested_by_user_id == user_id,
        InvestigationRun.submission_key == submission_key,
    ))).scalar_one()
    if run.request_hash != fingerprint:
        raise AlreadyExistsError("Submission key already has different investigation parameters")
    return run, created


async def finish(db: AsyncSession, run_id: UUID, *, response: dict | None = None,
                 error_code: str | None = None) -> bool:
    """Only a still-live run may publish a result; saving failure is not success."""
    now = datetime.now(UTC)
    statement = update(InvestigationRun).where(
        InvestigationRun.id == run_id, InvestigationRun.status == "running",
        InvestigationRun.executor_instance_id == INSTANCE_ID,
    )
    if response is not None:
        # A validated report cannot become a saved success after the deadline.
        statement = statement.where(InvestigationRun.deadline_at > now).values(
            status="succeeded", response=response, error_code=None, finished_at=now)
    else:
        # A failed call still needs a terminal record if its deadline has passed.
        statement = statement.values(
            status=case((InvestigationRun.deadline_at <= now, "interrupted"),
                        else_="failed"),
            response=null(),  # JSONB Python None would bind JSON null, violating IS NULL.
            error_code=case((InvestigationRun.deadline_at <= now, "deadline_exceeded"),
                            else_=error_code), finished_at=now)
    changed = (await db.execute(statement.returning(InvestigationRun.id))).scalar_one_or_none()
    await db.commit()
    return changed is not None


async def expire(db: AsyncSession, *, run_id: UUID | None = None,
                 organization_id: UUID | None = None, user_id: UUID | None = None) -> None:
    now = datetime.now(UTC)
    statement = update(InvestigationRun).where(
        InvestigationRun.status == "running",
        or_(InvestigationRun.deadline_at <= now,
            InvestigationRun.executor_instance_id != INSTANCE_ID),
    )
    if run_id is not None:
        statement = statement.where(InvestigationRun.id == run_id)
    if organization_id is not None:
        statement = statement.where(InvestigationRun.organization_id == organization_id)
    if user_id is not None:
        statement = statement.where(InvestigationRun.requested_by_user_id == user_id)
    await db.execute(statement.values(
        status="interrupted",
        error_code=case((InvestigationRun.deadline_at <= now, "deadline_exceeded"),
                        else_="service_restarted"),
        finished_at=now))
    await db.commit()


async def authorized_run(db: AsyncSession, *, organization_id: UUID, user_id: UUID,
                         run_id: UUID) -> InvestigationRun:
    await organization_service.require_role(db, organization_id=organization_id, user_id=user_id,
                                            minimum_role=OrgRole.MEMBER.value)
    run = (await db.execute(select(InvestigationRun).where(
        InvestigationRun.id == run_id, InvestigationRun.organization_id == organization_id,
        InvestigationRun.requested_by_user_id == user_id,
    ))).scalar_one_or_none()
    if run is None:
        raise NotFoundError("Investigation not found")
    if run.workspace_id is not None:
        try:
            workspace = await workspace_service.get_workspace(db, run.workspace_id)
            if workspace.organization_id != organization_id:
                raise PermissionDeniedError("Knowledge scope is no longer accessible")
            await workspace_service.require_workspace_role(
                db, workspace_id=run.workspace_id, user_id=user_id,
                minimum_role=WorkspaceRole.VIEWER.value)
        except NotFoundError:
            raise PermissionDeniedError("Knowledge scope is no longer accessible") from None
    return run


async def list_authorized(db: AsyncSession, *, organization_id: UUID,
                          user_id: UUID) -> list[InvestigationRun]:
    await organization_service.require_role(db, organization_id=organization_id, user_id=user_id,
                                            minimum_role=OrgRole.MEMBER.value)
    rows = (await db.execute(select(InvestigationRun).where(
        InvestigationRun.organization_id == organization_id,
        InvestigationRun.requested_by_user_id == user_id,
    ).order_by(InvestigationRun.created_at.desc()).limit(50))).scalars().all()
    visible = []
    for row in rows:
        if row.workspace_id is not None:
            try:
                workspace = await workspace_service.get_workspace(db, row.workspace_id)
                if workspace.organization_id != organization_id:
                    continue
                await workspace_service.require_workspace_role(
                    db, workspace_id=row.workspace_id, user_id=user_id,
                    minimum_role=WorkspaceRole.VIEWER.value)
            except (NotFoundError, PermissionDeniedError):
                continue
        visible.append(row)
    return visible
