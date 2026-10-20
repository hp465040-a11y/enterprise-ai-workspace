"""Offline contract for the C03/C04 shared counterfactual fixture."""
import ast
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID


class InsertStatement:
    def __init__(self, model):
        self.model = model

    def values(self, **values):
        return self.model, values


class CaptureConnection:
    def __init__(self):
        self.rows = []

    async def execute(self, statement):
        self.rows.append(statement)


class FixtureHelper:
    def __init__(self):
        self.event_id = 2

    def case(self, organization_id, order_id):
        return {"id": UUID(int=1), "organization_id": organization_id, "order_id": order_id}

    def event(self, organization_id, order_id, **fields):
        event_id = UUID(int=self.event_id)
        self.event_id += 1
        return {"id": event_id, "organization_id": organization_id, "order_id": order_id, **fields}


class Day13FixtureContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_c03_c04_share_case_events_and_analysis_cutoff(self):
        script = Path(__file__).resolve().parents[3] / "scripts/day13_e2e.py"
        tree = ast.parse(script.read_text(encoding="utf-8"))
        seed_node = next(node for node in tree.body
                         if isinstance(node, ast.AsyncFunctionDef) and node.name == "seed")
        cutoff_node = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "agent"
            and any(keyword.arg == "as_of" and isinstance(keyword.value, ast.Name)
                    and keyword.value.id == "OBSERVED" for keyword in node.keywords)
        )
        self.assertIsNotNone(cutoff_node)

        observed = datetime(2026, 10, 9, 12, tzinfo=UTC)
        organization_id, order_id = UUID(int=10), UUID(int=11)
        case_model, event_model, inventory_model = object(), object(), object()
        captured = {}
        for scenario in ("C03", "C04"):
            connection = CaptureConnection()
            namespace = {
                "OBSERVED": observed, "timedelta": timedelta,
                "uuid4": lambda: UUID(int=12), "insert": InsertStatement,
                "ExceptionCase": case_model, "FulfillmentEvent": event_model,
                "InventoryRecord": inventory_model,
                "Day8PostgresTests": lambda: SimpleNamespace(record=lambda org, **values: {
                    "organization_id": org, "sku": "Sku-A", "observed_at": observed,
                    **values,
                }),
            }
            exec(compile(ast.Module(body=[seed_node], type_ignores=[]), str(script), "exec"), namespace)
            await namespace["seed"](connection, organization_id, order_id, FixtureHelper(), scenario)
            captured[scenario] = connection.rows

        c03, c04 = captured["C03"], captured["C04"]
        self.assertEqual(len(c03), 4)
        self.assertEqual(len(c04), 4)
        self.assertEqual(c03[:3], c04[:3])
        self.assertEqual([row[0] for row in c03[:3]], [
            case_model, event_model, event_model,
        ])
        c03_inventory, c04_inventory = c03[3][1], c04[3][1]
        self.assertEqual({k: v for k, v in c03_inventory.items() if k not in {
            "on_hand_quantity", "reserved_quantity",
        }}, {k: v for k, v in c04_inventory.items() if k not in {
            "on_hand_quantity", "reserved_quantity",
        }})
        self.assertEqual((c03_inventory["on_hand_quantity"], c03_inventory["reserved_quantity"]), (2, 5))
        self.assertEqual((c04_inventory["on_hand_quantity"], c04_inventory["reserved_quantity"]), (10, 3))
