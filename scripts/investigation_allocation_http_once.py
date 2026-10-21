"""One guarded, authenticated HTTP acceptance against the retained allocation fixture."""

import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "scripts/investigation_allocation_demo_state.json"
LOGIN = ROOT / "scripts/action_request_demo_state.json"
OUTPUT = ROOT / "scripts/investigation_allocation_run_http_short_refs_20261021.json"
API = "http://127.0.0.1:3110/api/v1"


def save(data: dict) -> None:
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def main() -> None:
    if OUTPUT.exists():
        raise RuntimeError("HTTP attempt evidence exists; refusing a second investigation")
    state = json.loads(STATE.read_text(encoding="utf-8"))
    login_state = json.loads(LOGIN.read_text(encoding="utf-8"))
    if (not state.get("prepared") or state["database"] != "ragforge_day6_test"
            or not state["schema"].startswith("allocation_demo_")
            or state["organization_id"] != login_state["organization_id"]):
        raise RuntimeError("Retained isolated fixture or login scope does not match")
    # The runner's Graph deadline remains 690s. A longer client read timeout
    # merely allows its failure/success response to arrive through the proxy.
    async with httpx.AsyncClient(timeout=httpx.Timeout(735.0, connect=15.0)) as client:
        login = await client.post(f"{API}/auth/login", data={
            "username": login_state["emails"]["member"],
            "password": login_state["password"],
        })
        login.raise_for_status()
        token = login.json().get("access_token")
        if not token:
            raise RuntimeError("Authenticated login did not return a token")
        headers = {"Authorization": f"Bearer {token}"}
        organizations = await client.get(f"{API}/organizations", headers=headers)
        organizations.raise_for_status()
        workspaces = await client.get(
            f"{API}/organizations/{state['organization_id']}/workspaces", headers=headers,
        )
        workspaces.raise_for_status()
        if (state["organization_id"] not in {row["id"] for row in organizations.json()}
                or state["workspace_id"] not in {row["id"] for row in workspaces.json()}):
            raise RuntimeError("Authenticated member cannot see the retained scope")
        data = {
            "status": "started", "started_at": datetime.now(UTC).isoformat(),
            "case_id": state["case_id"], "organization_id": state["organization_id"],
            "workspace_id": state["workspace_id"], "as_of": state["as_of"],
            "require_knowledge": True, "route": "3110 proxy to 8125",
        }
        save(data)  # Fixed-path guard is written before the sole model-triggering POST.
        started = time.monotonic()
        try:
            response = await client.post(
                f"{API}/organizations/{state['organization_id']}/investigations",
                headers=headers, json={
                    "case_id": state["case_id"], "workspace_id": state["workspace_id"],
                    "as_of": state["as_of"], "require_knowledge": True,
                },
            )
            data["http_status"] = response.status_code
            data["request_id_header"] = response.headers.get("x-request-id")
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if response.status_code == 200 and isinstance(payload, dict):
                data["status"] = "completed"
                data["request_id"] = payload.get("request_id")
                data["response"] = payload  # Retain the actual report/handoff; no token.
            else:
                data["status"] = "http_failed"
                data["error_code"] = payload.get("error_code") if isinstance(payload, dict) else None
                data["error_type"] = "HTTPResponse"
        except Exception as exc:  # noqa: BLE001 -- preserve a single attempt; never retry
            data["status"] = "client_failed"
            data["error_type"] = type(exc).__name__
        finally:
            data["client_elapsed_seconds"] = round(time.monotonic() - started, 3)
            data["finished_at"] = datetime.now(UTC).isoformat()
            save(data)
    print(json.dumps({key: data.get(key) for key in (
        "status", "http_status", "request_id", "request_id_header", "error_code",
        "error_type", "client_elapsed_seconds",
    )}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
