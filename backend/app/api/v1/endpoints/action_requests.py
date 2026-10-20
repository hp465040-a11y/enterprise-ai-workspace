"""Authenticated creation and manual review of organization-owned ActionRequests."""

from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.action_request import ActionRequest
from app.models.customer_notification import CustomerNotification
from app.models.organization import OrgRole
from app.schemas.action_request import (
    ActionCreateInput,
    ActionCreateResult,
    ActionReviewInput,
    ActionReviewResult,
    CustomerNotificationRead,
)
from app.services.action_request_service import (
    create_notification_request,
    execute_approved_notification,
    get_internal_notification,
    review_action_request,
)
from app.services.organization_service import require_membership

router = APIRouter(prefix="/organizations/{organization_id}/action-requests", tags=["action-requests"])


@router.get("", response_model=list[ActionCreateResult])
async def list_requests(
    organization_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> list[ActionCreateResult]:
    membership = await require_membership(
        db, organization_id=organization_id, user_id=current_user.id,
    )
    query = select(ActionRequest, CustomerNotification.created_at).outerjoin(
        CustomerNotification,
        (CustomerNotification.action_request_id == ActionRequest.id)
        & (CustomerNotification.organization_id == ActionRequest.organization_id),
    ).where(ActionRequest.organization_id == organization_id)
    if membership.role not in (OrgRole.ADMIN.value, OrgRole.OWNER.value):
        query = query.where(ActionRequest.requested_by_user_id == current_user.id)
    rows = (await db.execute(query.order_by(ActionRequest.created_at.desc()).limit(50))).all()
    return [ActionCreateResult.model_validate(request).model_copy(update={"executed_at": executed_at})
            for request, executed_at in rows]


@router.post("", response_model=ActionCreateResult)
async def create_request(
    organization_id: UUID,
    payload: ActionCreateInput,
    current_user: CurrentUser,
    db: DBSession,
) -> ActionCreateResult:
    request = await create_notification_request(
        db,
        organization_id=organization_id,
        requested_by_user_id=current_user.id,
        target_case_id=payload.target_case_id,
        message=payload.message,
        idempotency_key=payload.idempotency_key,
    )
    result = ActionCreateResult.model_validate(request)
    await db.commit()
    return result


@router.post("/{request_id}/review", response_model=ActionReviewResult)
async def review_request(
    organization_id: UUID,
    request_id: UUID,
    payload: ActionReviewInput,
    current_user: CurrentUser,
    db: DBSession,
) -> ActionReviewResult:
    request = await review_action_request(
        db,
        organization_id=organization_id,
        request_id=request_id,
        reviewer_user_id=current_user.id,
        decision=payload.decision,
    )
    result = ActionReviewResult.model_validate(request)
    await db.commit()
    return result


@router.post("/{request_id}/execute", response_model=CustomerNotificationRead)
async def execute_request(
    organization_id: UUID,
    request_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> CustomerNotificationRead:
    notification = await execute_approved_notification(
        db,
        organization_id=organization_id,
        request_id=request_id,
        executor_user_id=current_user.id,
    )
    result = CustomerNotificationRead.model_validate(notification)
    await db.commit()
    return result


@router.get("/{request_id}/notification", response_model=CustomerNotificationRead)
async def read_notification(
    organization_id: UUID,
    request_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> CustomerNotificationRead:
    notification = await get_internal_notification(
        db,
        organization_id=organization_id,
        request_id=request_id,
        viewer_user_id=current_user.id,
    )
    return CustomerNotificationRead.model_validate(notification)
