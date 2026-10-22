"""Local-only browser check of investigation persistence; never calls a chat model.

Uses the retained allocation demo's isolated database and real JWT/API. The
synthetic, absent case deliberately produces a validated not_found handoff;
this checks lifecycle recovery, not an allocation-cause business conclusion.
"""

import argparse
import asyncio
import json
from uuid import UUID, uuid4

import action_request_demo as demo  # Pin the guarded test database before app imports.
import investigation_allocation_demo as allocation
import uvicorn
from app.ai.llm.base import LLMToolCall, LLMToolResponse
from app.api.v1.endpoints import investigations
from app.core.exceptions import register_exception_handlers
from app.db.session import get_db
from app.middleware.request_context import RequestContextMiddleware
from app.models.exception_case import ExceptionCase
from app.models.investigation_run import InvestigationRun
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


class ControlledProvider:
    def __init__(self, case_id: UUID, wait_seconds: int) -> None:
        self.case_id = case_id
        self.wait_seconds = wait_seconds
        self.calls = 0

    async def generate_with_tools(self, *, messages, tools, **_kwargs) -> LLMToolResponse:
        self.calls += 1
        if self.calls == 1:
            if "get_exception_case" not in {tool.name for tool in tools}:
                raise RuntimeError("Expected the case read before the report")
            # Gives a person time to refresh while the persisted run is running.
            await asyncio.sleep(self.wait_seconds)
            return LLMToolResponse("", "controlled-local", "tool_use", [
                LLMToolCall("controlled-case-read", "get_exception_case",
                            {"case_id": str(self.case_id)}),
            ])
        if self.calls == 2:
            if not any(message.role == "tool" and message.tool_name == "get_exception_case"
                       and json.loads(message.content).get("status") == "not_found"
                       for message in messages):
                raise RuntimeError("Controlled report requires the real not_found tool result")
            return LLMToolResponse(json.dumps({
                "outcome": "not_found", "evidence_event_ids": [], "root_cause": "unknown",
            }), "controlled-local", "stop")
        raise RuntimeError("Controlled provider budget exceeded")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, choices=(8126, 8127), default=8126)
    parser.add_argument("--wait-seconds", type=int, choices=(20, 90), default=20)
    args = parser.parse_args()
    state = allocation.state_read()
    if not state["prepared"]:
        raise RuntimeError("Retained allocation fixture is not ready")
    retained = demo.load_state()
    if retained["database"] != "ragforge_day6_test":
        raise RuntimeError("Refusing a non-test identity fixture")
    case_id = uuid4()
    organization_id = UUID(state["organization_id"])
    base, scoped = demo.engines(state["schema"])
    provider = ControlledProvider(case_id, args.wait_seconds)

    async def check_database() -> None:
        async with base.connect() as conn:
            await demo.assert_database(conn)
        async with AsyncSession(scoped) as db:
            if await db.scalar(select(ExceptionCase.id).where(ExceptionCase.id == case_id)):
                raise RuntimeError("Controlled case unexpectedly exists")
            # A repeat launch must not silently reuse a previous controlled run.
            if await db.scalar(select(func.count()).select_from(InvestigationRun).where(
                InvestigationRun.organization_id == organization_id,
                InvestigationRun.case_id == case_id,
            )):
                raise RuntimeError("Previous controlled run exists; retain and inspect it")

    asyncio.run(check_database())
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(demo.api_router, prefix="/api/v1")

    async def isolated_db():
        async with AsyncSession(scoped, expire_on_commit=False) as db:
            yield db

    app.dependency_overrides[get_db] = isolated_db
    investigations.get_llm_provider = lambda: provider

    @app.get("/__controlled_refresh_status")
    async def controlled_status():
        async with AsyncSession(scoped) as db:
            rows = (await db.execute(select(InvestigationRun).where(
                InvestigationRun.organization_id == organization_id,
                InvestigationRun.case_id == case_id,
            ))).scalars().all()
        return {"mode": "controlled_provider_isolated_pg", "case_id": str(case_id),
                "provider_calls": provider.calls, "run_count": len(rows),
                "statuses": [row.status for row in rows],
                "saved_reports": sum(row.response is not None for row in rows)}

    print(json.dumps({"mode": "CONTROLLED_PROVIDER_ISOLATED_PG", "case_id": str(case_id),
                      "organization_id": str(organization_id), "api_port": args.port,
                      "wait_seconds": args.wait_seconds}), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
