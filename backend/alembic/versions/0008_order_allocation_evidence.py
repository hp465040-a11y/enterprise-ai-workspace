"""Add typed order allocation and explicit shipment-delay attribution events.

Revision ID: 0008_order_allocation_evidence
Revises: 0007_customer_notifications
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008_order_allocation_evidence"
down_revision: str | None = "0007_customer_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_TYPES = (
    "event_type IN ('shipment_promised', 'delivery_promised', 'shipped', "
    "'in_transit', 'delivered', 'delivery_failed')"
)
NEW_TYPES = (
    "event_type IN ('shipment_promised', 'delivery_promised', 'shipped', "
    "'in_transit', 'delivered', 'delivery_failed', 'inventory_allocation_failed', "
    "'shipment_delay_attributed')"
)


def upgrade() -> None:
    op.add_column("fulfillment_events", sa.Column(
        "caused_by_event_id", postgresql.UUID(as_uuid=True), nullable=True,
    ))
    op.create_foreign_key(
        "fk_fulfillment_events_causal_reference", "fulfillment_events", "fulfillment_events",
        ["caused_by_event_id"], ["id"], ondelete="RESTRICT",
    )
    op.drop_constraint("ck_fulfillment_events_type", "fulfillment_events", type_="check")
    op.create_check_constraint("ck_fulfillment_events_type", "fulfillment_events", NEW_TYPES)
    op.create_check_constraint(
        "ck_fulfillment_events_causal_reference", "fulfillment_events",
        "(event_type = 'shipment_delay_attributed' AND caused_by_event_id IS NOT NULL) "
        "OR (event_type <> 'shipment_delay_attributed' AND caused_by_event_id IS NULL)",
    )
    op.create_check_constraint(
        "ck_fulfillment_events_allocation_provenance", "fulfillment_events",
        "event_type NOT IN ('inventory_allocation_failed', 'shipment_delay_attributed') "
        "OR (external_event_id IS NOT NULL AND tracking_number IS NOT NULL "
        "AND btrim(tracking_number) <> '')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_fulfillment_events_allocation_provenance", "fulfillment_events", type_="check")
    op.drop_constraint("ck_fulfillment_events_causal_reference", "fulfillment_events", type_="check")
    op.drop_constraint("ck_fulfillment_events_type", "fulfillment_events", type_="check")
    op.create_check_constraint("ck_fulfillment_events_type", "fulfillment_events", OLD_TYPES)
    op.drop_constraint("fk_fulfillment_events_causal_reference", "fulfillment_events", type_="foreignkey")
    op.drop_column("fulfillment_events", "caused_by_event_id")
