"""Organization/SKU inventory snapshots.

Revision ID: 0004_inventory_record
Revises: 0003_fulfillment_investigation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_inventory_record"
down_revision: str | None = "0003_fulfillment_investigation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inventory_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("sku", sa.String(128), nullable=False),
        sa.Column("on_hand_quantity", sa.Integer, nullable=False),
        sa.Column("reserved_quantity", sa.Integer, nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "sku", name="uq_inventory_records_org_sku"),
        sa.CheckConstraint(
            "btrim(sku) <> '' AND sku !~ '^[[:space:]]|[[:space:]]$'",
            name="ck_inventory_records_sku",
        ),
        sa.CheckConstraint(
            "on_hand_quantity >= 0 AND reserved_quantity >= 0",
            name="ck_inventory_records_quantities_nonnegative",
        ),
    )


def downgrade() -> None:
    op.drop_table("inventory_records")
