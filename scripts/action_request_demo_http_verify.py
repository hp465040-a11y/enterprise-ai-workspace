"""Real HTTP/JWT/PostgreSQL verification for the persistent demo schema."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
from action_request_demo import ActionRequest, AuditLog, engines, load_state
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ROOT = Path(__file__).resolve().parents[1]


async def run():
    state = load_state()
    if state["database"] != "ragforge_day6_test":
        raise RuntimeError("Refusing a non-test database")
    output = ROOT / "scripts" / (
        "action_request_demo_http_" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + ".json"
    )
    evidence = {"database": state["database"], "schema": state["schema"],
                "started_at": datetime.now(UTC).isoformat(), "checks": {}, "passed": False}
    base, scoped = engines(state["schema"])
    try:
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8123", timeout=15) as client:
            async def login(role):
                response = await client.post("/api/v1/auth/login", data={
                    "username": state["emails"][role], "password": state["password"],
                })
                assert response.status_code == 200, response.text
                return {"Authorization": "Bearer " + response.json()["access_token"]}

            member = await login("member")
            admin = await login("admin")
            outsider = await login("outsider")
            evidence["checks"]["real_login_jwt"] = True
            url = f"/api/v1/organizations/{state['organization_id']}/action-requests"
            other_url = f"/api/v1/organizations/{state['other_organization_id']}/action-requests"
            body = {"target_case_id": state["case_id"], "message": "Demo approval notification",
                    "idempotency_key": "demo-approval"}
            assert (await client.get(url)).status_code == 401
            assert (await client.get(other_url, headers=member)).status_code == 403
            assert (await client.get(url, headers=outsider)).status_code == 403
            assert (await client.post(url, headers=member, json={**body,
                "target_case_id": state["other_case_id"]})).status_code == 404
            assert (await client.post(url, headers=member, json={**body,
                "requested_by_user_id": state["admin_id"]})).status_code == 422
            evidence["checks"]["authentication_organization_and_case_boundaries"] = True
            created = await client.post(url, headers=member, json=body)
            assert created.status_code == 200, created.text
            first = created.json()
            assert first["status"] == "pending_approval"
            assert first["requested_by_user_id"] == state["member_id"]
            assert first["organization_id"] == state["organization_id"]
            duplicate = await client.post(url, headers=member, json=body)
            assert duplicate.status_code == 200 and duplicate.json()["id"] == first["id"]
            assert (await client.post(url, headers=member, json={**body,
                "message": "changed"})).status_code == 409
            assert (await client.post(url + f"/{first['id']}/review", headers=member,
                                      json={"decision": "approved"})).status_code == 403
            evidence["checks"]["idempotency_and_member_review_forbidden"] = True
            second_body = {**body, "message": "Demo rejection notification",
                           "idempotency_key": "demo-rejection"}
            second_response = await client.post(url, headers=member, json=second_body)
            assert second_response.status_code == 200, second_response.text
            second = second_response.json()
            member_list = await client.get(url, headers=member)
            assert member_list.status_code == 200
            assert {item["id"] for item in member_list.json()} == {first["id"], second["id"]}
            admin_list = await client.get(url, headers=admin)
            assert admin_list.status_code == 200
            assert {item["id"] for item in admin_list.json()} == {first["id"], second["id"]}
            approved = await client.post(url + f"/{first['id']}/review", headers=admin,
                                         json={"decision": "approved"})
            rejected = await client.post(url + f"/{second['id']}/review", headers=admin,
                                         json={"decision": "rejected"})
            assert approved.status_code == 200 and approved.json()["status"] == "approved"
            assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
            assert (await client.post(url + f"/{first['id']}/review", headers=admin,
                                      json={"decision": "rejected"})).status_code == 409
            evidence["checks"]["real_http_create_approve_and_create_reject"] = True
        async with AsyncSession(scoped) as db:
            requests = (await db.execute(select(ActionRequest))).scalars().all()
            audits = (await db.execute(select(AuditLog).where(
                AuditLog.resource_type == "action_request"))).scalars().all()
            assert {str(item.id): item.status for item in requests} == {
                first["id"]: "approved", second["id"]: "rejected",
            }
            assert sorted(item.action for item in audits) == [
                "action_request.created", "action_request.created",
                "action_request.reviewed", "action_request.reviewed",
            ]
            evidence["checks"]["independent_session_two_requests_four_audits_no_executed"] = True
        evidence["request_ids"] = {"approved": first["id"], "rejected": second["id"]}
        evidence["passed"] = True
    except BaseException as error:
        evidence["failure"] = {"type": type(error).__name__, "message": str(error)[:500]}
        raise
    finally:
        await scoped.dispose()
        await base.dispose()
        evidence["finished_at"] = datetime.now(UTC).isoformat()
        output.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(output)


if __name__ == "__main__":
    asyncio.run(run())
