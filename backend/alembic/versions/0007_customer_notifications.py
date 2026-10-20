"""Create internal customer notification records without external delivery.

Revision ID: 0007_customer_notifications
Revises: 0006_action_request_review
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_customer_notifications"
down_revision: str | None = "0006_action_request_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customer_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("action_request_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("action_requests.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("target_case_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("exception_cases.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("delivery_status", sa.String(16), server_default="not_sent", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("action_request_id", name="uq_customer_notifications_action_request"),
        sa.CheckConstraint("delivery_status = 'not_sent'", name="ck_customer_notifications_not_sent"),
    )
    op.create_index("ix_customer_notifications_organization_id", "customer_notifications", ["organization_id"])


def downgrade() -> None:
    op.drop_table("customer_notifications")
