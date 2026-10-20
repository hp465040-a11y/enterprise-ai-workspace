"""Order exception cases and fulfillment facts.

Revision ID: 0003_fulfillment_investigation
Revises: 0002_commerce_core

Single-column foreign keys follow commerce V1. Services must validate tenant
consistency and evidence_event_ids. No application models are imported here.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_fulfillment_investigation"
down_revision: str | None = "0002_commerce_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _common_columns() -> list[sa.Column]:
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "exception_cases",
        *_common_columns(),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("exception_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), server_default="open", nullable=False),
        sa.Column("problem_description", sa.Text, nullable=False),
        sa.Column("conclusion", sa.Text, nullable=True),
        sa.Column("evidence_event_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
                  server_default=sa.text("'{}'::uuid[]"), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "exception_type IN ('shipment_delay', 'delivery_delay', 'delivery_failed', 'other')",
            name="ck_exception_cases_type",
        ),
        sa.CheckConstraint("status IN ('open', 'investigating', 'closed')", name="ck_exception_cases_status"),
        sa.CheckConstraint("btrim(problem_description) <> ''", name="ck_exception_cases_problem_nonempty"),
        sa.CheckConstraint(
            "status <> 'closed' OR (closed_at IS NOT NULL AND conclusion IS NOT NULL "
            "AND btrim(conclusion) <> '')", name="ck_exception_cases_closed_details",
        ),
    )
    op.create_index("ix_exception_cases_org_order", "exception_cases", ["organization_id", "order_id"])
    op.create_index("ix_exception_cases_org_status_opened", "exception_cases", ["organization_id", "status", "opened_at"])
    op.create_index("ix_exception_cases_order_id", "exception_cases", ["order_id"])

    op.create_table(
        "fulfillment_events",
        *_common_columns(),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(128), nullable=False),
        sa.Column("external_event_id", sa.String(255), nullable=True),
        sa.Column("tracking_number", sa.String(255), nullable=True),
        sa.Column("description", sa.Text, nullable=False),
        sa.CheckConstraint(
            "event_type IN ('shipment_promised', 'delivery_promised', 'shipped', "
            "'in_transit', 'delivered', 'delivery_failed')", name="ck_fulfillment_events_type",
        ),
        sa.CheckConstraint(
            "(event_type IN ('shipment_promised', 'delivery_promised') AND expected_at IS NOT NULL) "
            "OR (event_type NOT IN ('shipment_promised', 'delivery_promised') AND expected_at IS NULL)",
            name="ck_fulfillment_events_expected_at",
        ),
        sa.CheckConstraint("btrim(source) <> ''", name="ck_fulfillment_events_source_nonempty"),
        sa.CheckConstraint("btrim(description) <> ''", name="ck_fulfillment_events_description_nonempty"),
        sa.CheckConstraint("btrim(external_event_id) <> ''", name="ck_fulfillment_events_external_id_nonempty"),
    )
    op.create_index(
        "uq_fulfillment_events_external_id", "fulfillment_events",
        ["organization_id", "order_id", "source", "external_event_id"], unique=True,
        postgresql_where=sa.text("external_event_id IS NOT NULL"),
    )
    op.create_index("ix_fulfillment_events_org_order_occurred", "fulfillment_events",
                    ["organization_id", "order_id", "occurred_at"])
    op.create_index("ix_fulfillment_events_order_id", "fulfillment_events", ["order_id"])


def downgrade() -> None:
    op.drop_table("fulfillment_events")
    op.drop_table("exception_cases")
