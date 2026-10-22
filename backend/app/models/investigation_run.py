"""Durable, organization-scoped submission and verified investigation result."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base, TimestampMixin, UUIDPKMixin


class InvestigationRun(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "investigation_runs"
    __table_args__ = (
        UniqueConstraint("organization_id", "requested_by_user_id", "submission_key",
                         name="uq_investigation_runs_org_user_key"),
        CheckConstraint("status IN ('running', 'succeeded', 'failed', 'interrupted')",
                        name="ck_investigation_runs_status"),
        CheckConstraint("(status = 'succeeded' AND response IS NOT NULL) OR "
                        "(status <> 'succeeded' AND response IS NULL)",
                        name="ck_investigation_runs_result"),
        Index("ix_investigation_runs_org_user_created", "organization_id",
              "requested_by_user_id", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"))
    submission_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    executor_instance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    require_knowledge: Mapped[bool] = mapped_column(nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="running")
    error_code: Mapped[str | None] = mapped_column(String(64))
    response: Mapped[dict | None] = mapped_column(JSONB)
