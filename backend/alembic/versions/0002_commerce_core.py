"""Organization-owned products, orders, order items, returns and refunds.

Revision ID: 0002_commerce_core
Revises: 0001_initial_schema

V1 uses single-column entity foreign keys. Organization and order consistency
across references must be enforced by future services, not by this migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_commerce_core"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _common_columns() -> list[sa.Column]:
    # UUID generation matches UUIDPKMixin (application-side uuid4).
    # Keep this schema snapshot independent of application model imports.
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "organization_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "products",
        *_common_columns(),
        sa.Column("sku", sa.String(128), nullable=False),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("status", sa.String(32), server_default="active", nullable=False),
        sa.Column("price", sa.Numeric(18, 4), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("attributes", postgresql.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.UniqueConstraint("organization_id", "sku", name="uq_products_org_sku"),
        sa.CheckConstraint("btrim(sku) <> ''", name="ck_products_sku_nonempty"),
        sa.CheckConstraint("price >= 0", name="ck_products_price_nonnegative"),
        sa.CheckConstraint(
            "(price IS NULL AND currency IS NULL) OR (price IS NOT NULL AND currency IS NOT NULL)",
            name="ck_products_price_currency_pair",
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_products_currency"),
        sa.CheckConstraint("status IN ('active', 'inactive', 'archived')", name="ck_products_status"),
    )
    op.create_index("ix_products_org_status", "products", ["organization_id", "status"])

    op.create_table(
        "orders",
        *_common_columns(),
        sa.Column("platform", sa.String(64), nullable=False),
        sa.Column("store_key", sa.String(128), nullable=False),
        sa.Column("external_order_id", sa.String(255), nullable=True),
        sa.Column("order_number", sa.String(128), nullable=False),
        sa.Column("customer_email", sa.String(320), nullable=True),
        sa.Column("customer_name", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), server_default="unknown", nullable=False),
        sa.Column("payment_status", sa.String(32), server_default="unknown", nullable=False),
        sa.Column("fulfillment_status", sa.String(32), server_default="unknown", nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("subtotal_amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("discount_amount", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("shipping_amount", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("tax_amount", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("total_amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("shipping_address", postgresql.JSONB, nullable=True),
        sa.Column("ordered_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("btrim(platform) <> ''", name="ck_orders_platform_nonempty"),
        sa.CheckConstraint("btrim(store_key) <> ''", name="ck_orders_store_key_nonempty"),
        sa.CheckConstraint("btrim(order_number) <> ''", name="ck_orders_number_nonempty"),
        sa.CheckConstraint("btrim(external_order_id) <> ''", name="ck_orders_external_id_nonempty"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_orders_currency"),
        sa.CheckConstraint(
            "subtotal_amount >= 0 AND discount_amount >= 0 AND shipping_amount >= 0 "
            "AND tax_amount >= 0 AND total_amount >= 0", name="ck_orders_amounts_nonnegative",
        ),
        sa.CheckConstraint(
            "status IN ('unknown', 'pending', 'confirmed', 'completed', 'cancelled')",
            name="ck_orders_status",
        ),
        sa.CheckConstraint(
            "payment_status IN ('unknown', 'unpaid', 'partially_paid', 'paid', "
            "'partially_refunded', 'refunded', 'failed')", name="ck_orders_payment_status",
        ),
        sa.CheckConstraint(
            "fulfillment_status IN ('unknown', 'unfulfilled', 'partially_fulfilled', "
            "'fulfilled', 'cancelled')", name="ck_orders_fulfillment_status",
        ),
    )
    op.create_index(
        "uq_orders_external_id", "orders",
        ["organization_id", "platform", "store_key", "external_order_id"],
        unique=True, postgresql_where=sa.text("external_order_id IS NOT NULL"),
    )
    op.create_index("ix_orders_org_number", "orders", ["organization_id", "order_number"])
    op.create_index("ix_orders_org_ordered_at", "orders", ["organization_id", "ordered_at"])
    op.create_index("ix_orders_org_customer_email", "orders", ["organization_id", "customer_email"])

    op.create_table(
        "order_items",
        *_common_columns(),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("line_number", sa.Integer, nullable=False),
        sa.Column("external_item_id", sa.String(255), nullable=True),
        sa.Column("sku", sa.String(128), nullable=True),
        sa.Column("product_name", sa.String(512), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("discount_amount", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("tax_amount", sa.Numeric(18, 4), server_default="0", nullable=False),
        sa.Column("total_amount", sa.Numeric(18, 4), nullable=False),
        sa.UniqueConstraint("organization_id", "order_id", "line_number", name="uq_order_items_line"),
        sa.CheckConstraint("line_number > 0", name="ck_order_items_line_positive"),
        sa.CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
        sa.CheckConstraint("btrim(external_item_id) <> ''", name="ck_order_items_external_id_nonempty"),
        sa.CheckConstraint(
            "unit_price >= 0 AND discount_amount >= 0 AND tax_amount >= 0 AND total_amount >= 0",
            name="ck_order_items_amounts_nonnegative",
        ),
    )
    op.create_index(
        "uq_order_items_external_id", "order_items",
        ["organization_id", "order_id", "external_item_id"], unique=True,
        postgresql_where=sa.text("external_item_id IS NOT NULL"),
    )
    op.create_index("ix_order_items_org_product", "order_items", ["organization_id", "product_id"])
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_index("ix_order_items_product_id", "order_items", ["product_id"])

    op.create_table(
        "return_requests",
        *_common_columns(),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("order_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("order_items.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("external_return_id", sa.String(255), nullable=True),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("status", sa.String(32), server_default="requested", nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("return_carrier", sa.String(128), nullable=True),
        sa.Column("return_tracking_number", sa.String(255), nullable=True),
        sa.CheckConstraint("quantity > 0", name="ck_return_requests_quantity_positive"),
        sa.CheckConstraint("btrim(external_return_id) <> ''", name="ck_return_requests_external_id_nonempty"),
        sa.CheckConstraint(
            "status IN ('requested', 'approved', 'rejected', 'in_transit', 'received', 'completed', 'cancelled')",
            name="ck_return_requests_status",
        ),
    )
    op.create_index(
        "uq_return_requests_external_item", "return_requests",
        ["organization_id", "order_id", "external_return_id", "order_item_id"], unique=True,
        postgresql_where=sa.text("external_return_id IS NOT NULL"),
    )
    op.create_index("ix_return_requests_org_status_requested", "return_requests", ["organization_id", "status", "requested_at"])
    op.create_index("ix_return_requests_org_order_item", "return_requests", ["organization_id", "order_id", "order_item_id"])
    op.create_index("ix_return_requests_order_id", "return_requests", ["order_id"])
    op.create_index("ix_return_requests_order_item_id", "return_requests", ["order_item_id"])

    op.create_table(
        "refunds",
        *_common_columns(),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("return_request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("return_requests.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("external_refund_id", sa.String(255), nullable=True),
        sa.Column("amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount > 0", name="ck_refunds_amount_positive"),
        sa.CheckConstraint("btrim(external_refund_id) <> ''", name="ck_refunds_external_id_nonempty"),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'succeeded', 'failed', 'cancelled')",
            name="ck_refunds_status",
        ),
    )
    op.create_index(
        "uq_refunds_external_id", "refunds", ["organization_id", "order_id", "external_refund_id"],
        unique=True, postgresql_where=sa.text("external_refund_id IS NOT NULL"),
    )
    op.create_index("ix_refunds_org_status_requested", "refunds", ["organization_id", "status", "requested_at"])
    op.create_index("ix_refunds_org_order_return", "refunds", ["organization_id", "order_id", "return_request_id"])
    op.create_index("ix_refunds_order_id", "refunds", ["order_id"])
    op.create_index("ix_refunds_return_request_id", "refunds", ["return_request_id"])


def downgrade() -> None:
    op.drop_table("refunds")
    op.drop_table("return_requests")
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("products")
