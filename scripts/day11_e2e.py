"""Real local Ollama + isolated PG investigation. No business migrations."""
import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import insert, text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend/tests/commerce"))
values = {**dotenv_values(ROOT / ".env"), **os.environ}
db_password = values.get("POSTGRES_PASSWORD")
if not db_password:
    raise RuntimeError("POSTGRES_PASSWORD is required for the isolated test database")
url = URL.create("postgresql+asyncpg", username=values.get("POSTGRES_USER") or "ragforge",
                 password=db_password,
                 host="localhost", port=5433, database="ragforge_day6_test")
os.environ["DAY6_TEST_DATABASE_URL"] = url.render_as_string(hide_password=False)
os.environ["DATABASE_URL"] = os.environ["DAY6_TEST_DATABASE_URL"]

from app.ai.agents.core_agent import run_core_agent
from app.ai.llm.ollama_provider import OllamaProvider
from app.core.config import settings
from app.models.exception_case import ExceptionCase
from app.models.fulfillment_event import FulfillmentEvent
from test_day8_postgres import OBSERVED, Day8PostgresTests


async def main():
    settings.LLM_MODEL = "llama3.1:8b"
    settings.OLLAMA_BASE_URL = "http://localhost:11434"
    requests = []

    class ObservedProvider(OllamaProvider):
        async def generate_with_tools(self, **kwargs):
            print(f"Real Ollama request {len(requests) + 1}", flush=True)
            response = await super().generate_with_tools(**kwargs)
            requests.append({"model": response.model, "content": response.content,
                             "tools": [{"name": c.name, "arguments": c.arguments} for c in response.tool_calls]})
            print(json.dumps(requests[-1], ensure_ascii=True), flush=True)
            return response

    provider = ObservedProvider()
    evidence = {"target": "localhost:5433/ragforge_day6_test", "provider": "local Ollama",
                "model": settings.LLM_MODEL, "requests": requests, "status": "failed"}
    try:
        async with Day8PostgresTests().database("migration") as (conn, org, order, helper, _):
            case = helper.case(org, order)
            case["problem_description"] = "Investigate late shipment; root cause unconfirmed."
            await conn.execute(insert(ExceptionCase).values(**case))
            for row in (
                helper.event(org, order, event_type="shipment_promised", tracking_number="SHIP-A",
                             occurred_at=OBSERVED - timedelta(hours=4), expected_at=OBSERVED - timedelta(hours=2)),
                helper.event(org, order, event_type="shipped", tracking_number="SHIP-A",
                             occurred_at=OBSERVED - timedelta(hours=1)),
            ):
                await conn.execute(insert(FulfillmentEvent).values(**row))
            await conn.execute(text("SET LOCAL transaction_read_only = on"))
            async with AsyncSession(bind=conn, join_transaction_mode="create_savepoint") as db:
                result = await asyncio.wait_for(run_core_agent(
                    provider, db, organization_id=org, case_id=case["id"], as_of=OBSERVED,
                ), timeout=240)
            evidence.update(answer=result.answer, trace=result.trace, model_requests=result.model_requests,
                            report=result.report, model_final=result.model_final,
                            rejected_finals=result.rejected_finals)
            names = [step["tool"] for step in result.trace if step["result"]["status"] == "found"]
            if "get_exception_case" not in names or "analyze_fulfillment" not in names:
                raise AssertionError("Missing real case/analysis tool round trip")
            analysis = next(s["result"]["analysis"] for s in result.trace if s["tool"] == "analyze_fulfillment")
            if analysis["shipment"]["status"] != "late" or analysis["shipment"]["difference_seconds"] != 3600:
                raise AssertionError("Incorrect real PG observation")
            assert result.report["outcome"] == "observed_delay"
            assert result.report["root_cause"] == "unknown"
            assert set(result.report["evidence_event_ids"]) == set(analysis["evidence_event_ids"])
            assert "2026-10-09T10:00:00+00:00" in result.answer
            assert '"difference_seconds": 3600.0' in result.answer
            evidence["status"] = "passed_evidence_contract"
        evidence["rollback_verified"] = True
    except Exception as exc:
        # Do not persist raw DB exception strings/connection credentials.
        evidence["failure_type"] = type(exc).__name__
        raise
    finally:
        await provider._client.aclose()
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        path = ROOT / f"scripts/day11_evidence_{stamp}.json"
        path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Evidence: {path}; status={evidence['status']}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
