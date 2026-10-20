"""Organization-scoped customer-notification approval requests.

Revision ID: 0005_action_requests
Revises: 0004_inventory_record
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_action_requests"
down_revision: str | None = "0004_inventory_record"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "action_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("requested_by_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("action_type", sa.String(64), nullable=False),
        sa.Column("target_case_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("exception_cases.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("parameters", postgresql.JSONB, nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending_approval", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_action_requests_org_key"),
        sa.CheckConstraint("action_type = 'notify_case_customer'", name="ck_action_requests_type"),
        sa.CheckConstraint(
            "status IN ('pending_approval', 'approved', 'rejected', 'executed')",
            name="ck_action_requests_status",
        ),
        sa.CheckConstraint(
            "btrim(idempotency_key) <> '' AND idempotency_key = btrim(idempotency_key)",
            name="ck_action_requests_key",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(parameters) = 'object' AND jsonb_typeof(parameters->'message') = 'string' "
            "AND btrim(parameters->>'message') <> ''",
            name="ck_action_requests_parameters",
        ),
    )
    op.create_index("ix_action_requests_organization_id", "action_requests", ["organization_id"])


def downgrade() -> None:
    op.drop_table("action_requests")
