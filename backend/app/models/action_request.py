"""Approval request for one concrete action: notify a case's customer."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base, TimestampMixin, UUIDPKMixin


class ActionRequestStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"


class ActionRequest(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "action_requests"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_action_requests_org_key"),
        CheckConstraint("action_type = 'notify_case_customer'", name="ck_action_requests_type"),
        CheckConstraint(
            "status IN ('pending_approval', 'approved', 'rejected', 'executed')",
            name="ck_action_requests_status",
        ),
        CheckConstraint(
            "(status = 'pending_approval' AND review_decision IS NULL "
            "AND reviewed_by_user_id IS NULL AND reviewed_at IS NULL) OR "
            "(status IN ('approved', 'executed') AND review_decision IS NOT NULL "
            "AND review_decision = 'approved' "
            "AND reviewed_by_user_id IS NOT NULL AND reviewed_at IS NOT NULL) OR "
            "(status = 'rejected' AND review_decision IS NOT NULL "
            "AND review_decision = 'rejected' "
            "AND reviewed_by_user_id IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_action_requests_review_consistency",
        ),
        CheckConstraint(
            "btrim(idempotency_key) <> '' AND idempotency_key = btrim(idempotency_key)",
            name="ck_action_requests_key",
        ),
        CheckConstraint(
            "jsonb_typeof(parameters) = 'object' AND jsonb_typeof(parameters->'message') = 'string' "
            "AND btrim(parameters->>'message') <> ''",
            name="ck_action_requests_parameters",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exception_cases.id", ondelete="RESTRICT"), nullable=False
    )
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ActionRequestStatus.PENDING_APPROVAL.value,
        server_default=ActionRequestStatus.PENDING_APPROVAL.value,
    )
    review_decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
