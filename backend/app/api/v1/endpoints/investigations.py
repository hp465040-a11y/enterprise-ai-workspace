"""Authenticated, organization-scoped access to the existing read-only Core Agent."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter
from structlog.contextvars import get_contextvars

from app.ai.agents.core_agent import CoreAgentError, run_core_agent
from app.ai.llm.factory import get_llm_provider
from app.api.deps import CurrentUser, DBSession
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models.organization import OrgRole
from app.models.workspace import WorkspaceRole
from app.schemas.investigation import (
    InvestigationRequest,
    InvestigationResponse,
    observations_from_trace,
)
from app.services import organization_service, workspace_service

router = APIRouter(prefix="/organizations/{organization_id}/investigations", tags=["investigations"])


@router.post("", response_model=InvestigationResponse)
async def investigate(
    organization_id: UUID,
    payload: InvestigationRequest,
    current_user: CurrentUser,
    db: DBSession,
) -> InvestigationResponse:
    """Members may investigate cases in their verified organization. No business writes."""
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
    as_of = payload.as_of.astimezone(UTC) if payload.as_of is not None else datetime.now(UTC)
    try:
        result = await run_core_agent(
            get_llm_provider(), db, organization_id=membership.organization_id,
            case_id=payload.case_id, as_of=as_of, **knowledge_context,
        )
    except CoreAgentError as exc:
        if exc.error_code == "knowledge_permission_denied":
            raise PermissionDeniedError("Knowledge scope is no longer accessible") from None
        # Keep the existing failure code, but never publish traces or exception details.
        raise CoreAgentError("Investigation failed; no business conclusion produced",
                             error_code=exc.error_code) from None
    except Exception:  # noqa: BLE001 -- public boundary, including Provider construction failures
        raise CoreAgentError("Investigation failed; no business conclusion produced") from None
    return InvestigationResponse(
        request_id=get_contextvars().get("request_id") or str(uuid4()),
        organization_id=membership.organization_id, case_id=payload.case_id, as_of=as_of,
        report=result.report, handoff=result.answer,
        observations=observations_from_trace(result.trace),
    )
