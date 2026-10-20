"""Order lookup tests using mocked sessions; no database or app fixtures."""

import unittest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.core.exceptions import NotFoundError, ValidationAppError
from app.db.base import Base  # noqa: F401 -- register all related models for SQL compilation
from app.models.order import Order
from app.services.order_service import get_order


class GetOrderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.organization_id = uuid4()
        self.db = MagicMock()
        self.result = MagicMock()
        self.db.execute = AsyncMock(return_value=self.result)

    def matches(self, orders):
        self.result.scalars.return_value.all.return_value = orders

    async def test_missing_order(self):
        self.matches([])
        with self.assertRaises(NotFoundError) as caught:
            await get_order(self.db, organization_id=self.organization_id, order_number="123")
        self.assertEqual(caught.exception.error_code, "not_found")

    async def test_single_order_and_tenant_filter(self):
        order = MagicMock(spec=Order)
        self.matches([order])
        actual = await get_order(
            self.db, organization_id=self.organization_id, order_number=" 123 "
        )
        self.assertIs(actual, order)
        query = self.db.execute.call_args.args[0]
        compiled = query.compile(dialect=postgresql.dialect())
        self.assertEqual(
            compiled.params,
            {"organization_id_1": self.organization_id, "order_number_1": "123"},
        )
        sql = str(compiled)
        self.assertIn("orders.organization_id =", sql)
        self.assertIn(" AND orders.order_number =", sql)
        self.assertNotIn(" JOIN ", sql)
        self.db.commit.assert_not_called()
        self.db.flush.assert_not_called()

    async def test_ambiguous_order(self):
        self.matches([MagicMock(spec=Order), MagicMock(spec=Order)])
        with self.assertRaises(ValidationAppError) as caught:
            await get_order(self.db, organization_id=self.organization_id, order_number="123")
        self.assertEqual(caught.exception.error_code, "ambiguous_order")
        self.assertIn("platform", caught.exception.message)
        self.assertIn("store", caught.exception.message)

    async def test_optional_filters_are_independent_and_use_none(self):
        self.matches([MagicMock(spec=Order)])
        for platform, store_key in (
            (None, None),
            ("shopify", None),
            (None, "store-a"),
            ("shopify", "store-a"),
        ):
            with self.subTest(platform=platform, store_key=store_key):
                await get_order(
                    self.db, organization_id=self.organization_id, order_number="123",
                    platform=platform, store_key=store_key,
                )
                query = self.db.execute.call_args.args[0]
                compiled = query.compile(dialect=postgresql.dialect())
                self.assertEqual(compiled.params["organization_id_1"], self.organization_id)
                self.assertEqual(compiled.params["order_number_1"], "123")
                self.assertEqual("platform_1" in compiled.params, platform is not None)
                self.assertEqual("store_key_1" in compiled.params, store_key is not None)
                if platform is not None:
                    self.assertEqual(compiled.params["platform_1"], platform)
                if store_key is not None:
                    self.assertEqual(compiled.params["store_key_1"], store_key)

    async def test_platform_is_trimmed(self):
        order = MagicMock(spec=Order)
        self.matches([order])
        actual = await get_order(
            self.db, organization_id=self.organization_id, order_number="123",
            platform="  shopify  ",
        )
        self.assertIs(actual, order)
        compiled = self.db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
        self.assertEqual(compiled.params["platform_1"], "shopify")

    async def test_store_key_is_trimmed(self):
        order = MagicMock(spec=Order)
        self.matches([order])
        actual = await get_order(
            self.db, organization_id=self.organization_id, order_number="123",
            store_key="  store-a  ",
        )
        self.assertIs(actual, order)
        compiled = self.db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
        self.assertEqual(compiled.params["store_key_1"], "store-a")

    async def test_blank_platform_does_not_query(self):
        for value in ("", "   "):
            with self.subTest(value=value):
                with self.assertRaises(ValidationAppError) as caught:
                    await get_order(
                        self.db, organization_id=self.organization_id, order_number="123",
                        platform=value,
                    )
                self.assertEqual(caught.exception.message, "Platform must not be empty")
        self.db.execute.assert_not_awaited()

    async def test_blank_store_key_does_not_query(self):
        for value in ("", "   "):
            with self.subTest(value=value):
                with self.assertRaises(ValidationAppError) as caught:
                    await get_order(
                        self.db, organization_id=self.organization_id, order_number="123",
                        store_key=value,
                    )
                self.assertEqual(caught.exception.message, "Store key must not be empty")
        self.db.execute.assert_not_awaited()

    async def test_blank_order_number_does_not_query(self):
        for value in ("", " \t\n "):
            with self.subTest(value=value):
                with self.assertRaises(ValidationAppError):
                    await get_order(
                        self.db, organization_id=self.organization_id, order_number=value
                    )
        self.db.execute.assert_not_awaited()

    async def test_database_error_propagates(self):
        error = RuntimeError("Database unavailable")
        self.db.execute.side_effect = error
        with self.assertRaises(RuntimeError) as caught:
            await get_order(self.db, organization_id=self.organization_id, order_number="123")
        self.assertIs(caught.exception, error)


if __name__ == "__main__":
    unittest.main()
