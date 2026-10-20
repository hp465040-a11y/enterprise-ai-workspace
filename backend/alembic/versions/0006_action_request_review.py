"""Persist the single manual decision on an ActionRequest.

Revision ID: 0006_action_request_review
Revises: 0005_action_requests
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_action_request_review"
down_revision: str | None = "0005_action_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("action_requests", sa.Column("review_decision", sa.String(16), nullable=True))
    op.add_column("action_requests", sa.Column(
        "reviewed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("action_requests", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_action_requests_reviewed_by_user_id_users", "action_requests", "users",
        ["reviewed_by_user_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_action_requests_review_consistency", "action_requests",
        "(status = 'pending_approval' AND review_decision IS NULL "
        "AND reviewed_by_user_id IS NULL AND reviewed_at IS NULL) OR "
        "(status IN ('approved', 'executed') AND review_decision IS NOT NULL "
        "AND review_decision = 'approved' "
        "AND reviewed_by_user_id IS NOT NULL AND reviewed_at IS NOT NULL) OR "
        "(status = 'rejected' AND review_decision IS NOT NULL "
        "AND review_decision = 'rejected' "
        "AND reviewed_by_user_id IS NOT NULL AND reviewed_at IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_action_requests_review_consistency", "action_requests", type_="check")
    op.drop_constraint("fk_action_requests_reviewed_by_user_id_users", "action_requests", type_="foreignkey")
    op.drop_column("action_requests", "reviewed_at")
    op.drop_column("action_requests", "reviewed_by_user_id")
    op.drop_column("action_requests", "review_decision")
