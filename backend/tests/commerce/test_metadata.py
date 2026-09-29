"""Offline mapper, PostgreSQL DDL and migration scope/parity checks."""

import io
import warnings
from decimal import Decimal

import pytest
from sqlalchemy import CheckConstraint, DateTime, Index, MetaData, Numeric, Table, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SAWarning
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db.base import Base
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.product import Product
from app.models.refund import Refund
from app.models.return_request import ReturnRequest

TABLE_NAMES = ("products", "orders", "order_items", "return_requests", "refunds")
DIALECT = postgresql.dialect()


def test_mappers_and_relationships_preserve_transaction_records():
    with warnings.catch_warnings():
        warnings.simplefilter("error", SAWarning)
        configure_mappers()
    for model in (Product, Order, OrderItem, Refund, ReturnRequest):
        for rel in model.__mapper__.relationships:
            assert "delete" not in rel.cascade
            assert "delete-orphan" not in rel.cascade
            if rel.uselist:
                assert rel.passive_deletes == "all"
    assert Order.refunds.property.uselist
    assert OrderItem.__table__.c.product_id.nullable
    assert Refund.__table__.c.return_request_id.nullable


@pytest.mark.parametrize("name", TABLE_NAMES)
def test_organization_owned_types_and_single_column_restrict_foreign_keys(name):
    table = Base.metadata.tables[name]
    assert "workspace_id" not in table.c
    assert not table.c.organization_id.nullable
    assert isinstance(table.c.id.type, postgresql.UUID)
    assert list(table.primary_key.columns.keys()) == ["id"]
    assert table.c.id.default is not None
    for constraint in table.foreign_key_constraints:
        assert len(constraint.elements) == 1
        assert constraint.ondelete == "RESTRICT"
    for column in table.c:
        if isinstance(column.type, Numeric):
            assert (column.type.precision, column.type.scale) == (18, 4)
            assert column.type.python_type is Decimal
        if isinstance(column.type, DateTime):
            assert column.type.timezone
    assert f"CREATE TABLE {name}" in str(CreateTable(table).compile(dialect=DIALECT))


def test_snapshots_and_multiple_refunds_do_not_follow_catalog_changes():
    product = Product(sku="SKU", name="Original", price=Decimal("10.1234"), currency="USD")
    item = OrderItem(product=product, sku=product.sku, product_name=product.name, unit_price=product.price)
    order = Order(items=[item], refunds=[Refund(amount=Decimal("1")), Refund(amount=Decimal("2"))])
    product.name = "New name"
    product.price = Decimal("20")
    assert item.product_name == "Original"
    assert item.unit_price == Decimal("10.1234")
    assert len(order.refunds) == 2
    assert all(refund.order is order for refund in order.refunds)


def _signature(table):
    def default_sql(column):
        return None if column.server_default is None else str(column.server_default.arg)

    return {
        "columns": {
            column.name: (str(column.type.compile(dialect=DIALECT)), column.nullable,
                          column.primary_key, default_sql(column))
            for column in table.c
        },
        "foreign_keys": {
            (tuple(element.parent.name for element in constraint.elements),
             tuple(element.target_fullname for element in constraint.elements), constraint.ondelete)
            for constraint in table.foreign_key_constraints
        },
        "unique": {
            (constraint.name, tuple(constraint.columns.keys()))
            for constraint in table.constraints if isinstance(constraint, UniqueConstraint)
        },
        "checks": {
            (constraint.name, str(constraint.sqltext))
            for constraint in table.constraints if isinstance(constraint, CheckConstraint)
        },
        "indexes": {str(CreateIndex(index).compile(dialect=DIALECT)) for index in table.indexes},
    }


def test_migration_snapshot_matches_models_and_touches_only_five_tables(commerce_migration, monkeypatch):
    metadata = MetaData()
    created = []
    dropped = []

    class CaptureOperations:
        def create_table(self, name, *columns, **kwargs):
            created.append(name)
            return Table(name, metadata, *columns, **kwargs)

        def create_index(self, name, table_name, columns, **kwargs):
            table = metadata.tables[table_name]
            Index(name, *(table.c[column] for column in columns), **kwargs)

        def drop_table(self, name):
            dropped.append(name)

    monkeypatch.setattr(commerce_migration, "op", CaptureOperations())
    assert commerce_migration.revision == "0002_commerce_core"
    assert commerce_migration.down_revision == "0001_initial_schema"
    commerce_migration.upgrade()
    assert created == list(TABLE_NAMES)
    assert set(metadata.tables) == set(TABLE_NAMES)
    for name in TABLE_NAMES:
        assert _signature(metadata.tables[name]) == _signature(Base.metadata.tables[name])
    commerce_migration.downgrade()
    assert dropped == list(reversed(TABLE_NAMES))


def test_migration_renders_postgresql_upgrade_and_downgrade_offline(commerce_migration):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        commerce_migration.upgrade()
        commerce_migration.downgrade()
    sql = output.getvalue()
    assert sql.count("CREATE TABLE ") == 5
    assert sql.count("DROP TABLE ") == 5
    assert "ALTER TABLE" not in sql
    assert "ON DELETE CASCADE" not in sql
    assert "ON DELETE RESTRICT" in sql
    assert "WHERE external_order_id IS NOT NULL" in sql


def test_external_identity_is_scoped_and_optional():
    expected = {
        "orders": ("organization_id", "platform", "store_key", "external_order_id"),
        "order_items": ("organization_id", "order_id", "external_item_id"),
        "refunds": ("organization_id", "order_id", "external_refund_id"),
        "return_requests": ("organization_id", "order_id", "external_return_id", "order_item_id"),
    }
    for name, columns in expected.items():
        indexes = [index for index in Base.metadata.tables[name].indexes if index.unique]
        assert len(indexes) == 1
        assert tuple(indexes[0].columns.keys()) == columns
        assert indexes[0].dialect_options["postgresql"]["where"] is not None
