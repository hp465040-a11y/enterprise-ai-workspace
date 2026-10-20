"""Create a customer-notification request; approval and execution are separate work."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AlreadyExistsError, NotFoundError, ValidationAppError
from app.models.action_request import ActionRequest, ActionRequestStatus
from app.models.customer_notification import CustomerNotification
from app.models.organization import OrgRole
from app.services.audit_service import record_audit_event
from app.services.exception_service import get_exception_case
from app.services.organization_service import require_membership, require_role

ACTION_TYPE = "notify_case_customer"


async def create_notification_request(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    requested_by_user_id: uuid.UUID,
    target_case_id: uuid.UUID,
    message: str,
    idempotency_key: str,
) -> ActionRequest:
    """Write request and audit atomically inside the caller's transaction.

    The caller commits or rolls back. This function never approves, sends, or
    marks a notification executed. The savepoint prevents a partial request if
    audit insertion fails and keeps unrelated caller work outside that boundary.
    """
    if not isinstance(idempotency_key, str) or not idempotency_key or (
        idempotency_key != idempotency_key.strip() or len(idempotency_key) > 128
    ):
        raise ValidationAppError("Idempotency key must be 1-128 non-whitespace-edge characters")
    if not isinstance(message, str) or not message.strip() or len(message) > 1000:
        raise ValidationAppError("Notification message must contain 1-1000 characters")

    await require_membership(db, organization_id=organization_id, user_id=requested_by_user_id)
    await get_exception_case(db, organization_id=organization_id, case_id=target_case_id)
    parameters = {"message": message}
    request_id = uuid.uuid4()

    async with db.begin_nested():
        inserted_id = (
            await db.execute(
                insert(ActionRequest)
                .values(
                    id=request_id,
                    organization_id=organization_id,
                    requested_by_user_id=requested_by_user_id,
                    action_type=ACTION_TYPE,
                    target_case_id=target_case_id,
                    parameters=parameters,
                    idempotency_key=idempotency_key,
                    status=ActionRequestStatus.PENDING_APPROVAL.value,
                )
                .on_conflict_do_nothing(constraint="uq_action_requests_org_key")
                .returning(ActionRequest.id)
            )
        ).scalar_one_or_none()
        if inserted_id is None:
            existing = (
                await db.execute(
                    select(ActionRequest).where(
                        ActionRequest.organization_id == organization_id,
                        ActionRequest.idempotency_key == idempotency_key,
                    )
                )
            ).scalar_one()
            if (
                existing.requested_by_user_id != requested_by_user_id
                or existing.action_type != ACTION_TYPE
                or existing.target_case_id != target_case_id
                or existing.parameters != parameters
            ):
                raise AlreadyExistsError("Idempotency key already belongs to a different request")
            return existing

        await record_audit_event(
            db,
            action="action_request.created",
            resource_type="action_request",
            actor_user_id=requested_by_user_id,
            organization_id=organization_id,
            resource_id=inserted_id,
            metadata={"action_type": ACTION_TYPE, "target_case_id": str(target_case_id)},
        )
        return (await db.execute(select(ActionRequest).where(ActionRequest.id == inserted_id))).scalar_one()


async def review_action_request(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    reviewer_user_id: uuid.UUID,
    decision: str,
) -> ActionRequest:
    """Record one admin/owner decision and audit it in the caller's transaction."""
    if decision not in (ActionRequestStatus.APPROVED.value, ActionRequestStatus.REJECTED.value):
        raise ValidationAppError("Review decision must be approved or rejected")
    await require_role(
        db, organization_id=organization_id, user_id=reviewer_user_id,
        minimum_role=OrgRole.ADMIN.value,
    )

    async with db.begin_nested():
        request = (
            await db.execute(
                select(ActionRequest)
                .where(ActionRequest.organization_id == organization_id, ActionRequest.id == request_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if request is None:
            raise NotFoundError("Action request not found")
        if request.status != ActionRequestStatus.PENDING_APPROVAL.value:
            raise AlreadyExistsError("Action request has already been reviewed")

        request.status = decision
        request.review_decision = decision
        request.reviewed_by_user_id = reviewer_user_id
        request.reviewed_at = datetime.now(UTC)
        await db.flush()
        await record_audit_event(
            db,
            action="action_request.reviewed",
            resource_type="action_request",
            actor_user_id=reviewer_user_id,
            organization_id=organization_id,
            resource_id=request.id,
            metadata={"decision": decision},
        )
        return request


async def execute_approved_notification(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    executor_user_id: uuid.UUID,
) -> CustomerNotification:
    """Create one internal record atomically; no email/SMS or delivery claim."""
    await require_role(
        db, organization_id=organization_id, user_id=executor_user_id,
        minimum_role=OrgRole.ADMIN.value,
    )
    async with db.begin_nested():
        request = (
            await db.execute(
                select(ActionRequest)
                .where(ActionRequest.organization_id == organization_id, ActionRequest.id == request_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if request is None:
            raise NotFoundError("Action request not found")
        if request.status == ActionRequestStatus.EXECUTED.value:
            notification = (
                await db.execute(select(CustomerNotification).where(
                    CustomerNotification.action_request_id == request.id,
                    CustomerNotification.organization_id == organization_id,
                ))
            ).scalar_one_or_none()
            if notification is None:
                raise ValidationAppError("Executed request has no notification record")
            return notification
        if request.status != ActionRequestStatus.APPROVED.value:
            raise ValidationAppError("Only approved requests may create a notification record")
        message = request.parameters.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ValidationAppError("Approved request has no notification content")

        notification = CustomerNotification(
            organization_id=organization_id,
            action_request_id=request.id,
            target_case_id=request.target_case_id,
            created_by_user_id=executor_user_id,
            content=message,
            delivery_status="not_sent",
        )
        db.add(notification)
        await db.flush()
        request.status = ActionRequestStatus.EXECUTED.value
        await db.flush()
        await record_audit_event(
            db,
            action="action_request.executed",
            resource_type="action_request",
            actor_user_id=executor_user_id,
            organization_id=organization_id,
            resource_id=request.id,
            metadata={"notification_id": str(notification.id), "delivery_status": "not_sent"},
        )
        return notification


async def get_internal_notification(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    viewer_user_id: uuid.UUID,
) -> CustomerNotification:
    """Members see their own records; admins/owners see their organization's."""
    membership = await require_membership(db, organization_id=organization_id, user_id=viewer_user_id)
    request = (
        await db.execute(select(ActionRequest).where(
            ActionRequest.organization_id == organization_id,
            ActionRequest.id == request_id,
        ))
    ).scalar_one_or_none()
    if request is None or (
        membership.role not in (OrgRole.ADMIN.value, OrgRole.OWNER.value)
        and request.requested_by_user_id != viewer_user_id
    ):
        raise NotFoundError("Notification record not found")
    notification = (
        await db.execute(select(CustomerNotification).where(
            CustomerNotification.organization_id == organization_id,
            CustomerNotification.action_request_id == request_id,
        ))
    ).scalar_one_or_none()
    if notification is None:
        raise NotFoundError("Notification record not found")
    return notification
