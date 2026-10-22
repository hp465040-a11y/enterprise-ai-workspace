"""Persist bounded investigation submissions and verified results.

Revision ID: 0009_investigation_runs
Revises: 0008_order_allocation_evidence
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009_investigation_runs"
down_revision: str | None = "0008_order_allocation_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "investigation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("requested_by_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="RESTRICT")),
        sa.Column("submission_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("executor_instance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("require_knowledge", sa.Boolean(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("error_code", sa.String(64)),
        sa.Column("response", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "requested_by_user_id", "submission_key",
                            name="uq_investigation_runs_org_user_key"),
        sa.CheckConstraint("status IN ('running', 'succeeded', 'failed', 'interrupted')",
                           name="ck_investigation_runs_status"),
        sa.CheckConstraint("(status = 'succeeded' AND response IS NOT NULL) OR "
                           "(status <> 'succeeded' AND response IS NULL)",
                           name="ck_investigation_runs_result"),
    )
    op.create_index("ix_investigation_runs_org_user_created", "investigation_runs",
                    ["organization_id", "requested_by_user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_investigation_runs_org_user_created", table_name="investigation_runs")
    op.drop_table("investigation_runs")
