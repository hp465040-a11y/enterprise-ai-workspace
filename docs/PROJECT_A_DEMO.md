# Project A demo: verified report and authenticated ActionRequest flow

## 从新环境准备隔离演示

三个入口各有独立验收边界；端口仅在对应本地进程启动且预检通过后可用：

| 入口 | 用途 | 模型调用 |
| --- | --- | --- |
| `http://127.0.0.1:3110/login`（8125 API） | 原隔离案件的真实调查与申请审核；2026-10-22 检查时运行的旧 API 对调查历史 GET 返回 405，不用它展示刷新恢复 | 新提交真实调查会调用聊天模型 |
| `http://127.0.0.1:3111/login` | [历史真实结果的 React 保存响应回放](#saved-allocation-report-in-the-actual-react-page)；代理绝不把调查 POST 转给 8125 | 不会 |
| `http://127.0.0.1:3112/login`（8126 API；3113／8127 为第二轮） | [调查刷新恢复验收](PROJECT_A_INVESTIGATION_RUN_ACCEPTANCE.md)使用的受控 Provider；2026-10-22 授权读取确认两份已保存报告。3112 的申请页也通过认证列表读取检查 | 不调用真实聊天模型；录屏只读取既有调查记录 |

录屏只需按[约三分钟分段脚本](PROJECT_A_3MIN_DEMO.md)准备；以下是从新环境复现隔离演示的完整路径，不代表端口现在仍在运行。

This path uses the existing isolated preparation scripts. It does not migrate the business
database or reuse a rolled-back C05 case. From a new checkout, install the existing
backend/frontend dependencies, start this project's PostgreSQL, Redis and Qdrant,
and make the configured Ollama chat and embedding models available:

在仓库根目录检查 `.env`；首次安装才从 `.env.example` 复制，设置本地独有的 `SECRET_KEY` 与 PostgreSQL 配置。不要覆盖已有 `.env`，也不要将凭据提交或录入演示证据。Ollama 是宿主机依赖，不由以下 Compose 命令启动；所配置的聊天与 Embedding 模型须已在本机可用，启动脚本会预检。

```powershell
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
# 首次复制后，在本机设置独有的 SECRET_KEY 与 PostgreSQL 密码；不要提交 .env
py -3.12 -m venv .venv-d4
.\.venv-d4\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
Push-Location frontend; npm ci; Pop-Location
docker compose up -d postgres redis qdrant
```

The guarded test database must be `ragforge_day6_test` on host port 5433; the
scripts refuse another database. If absent, create this **empty isolated test
database once** in the existing Compose PostgreSQL service using its configured
`POSTGRES_USER` (for example, through `docker compose exec postgres psql`). This
is an operator prerequisite, not a migration of the Compose business database.
After confirming the database is absent, the one-time PowerShell command is:

```powershell
'CREATE DATABASE ragforge_day6_test;' |
    docker compose exec -T postgres sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres'
```

From ordinary PowerShell in the repository root, with the existing test database ready:

```powershell
.\scripts\start_investigation_allocation_demo.ps1
```

The launcher reads this project's PostgreSQL container credentials in memory, checks
dependencies and the test database, prepares the existing action-demo identity only
when its state file is absent, then prepares or inspects the allocation fixture. It
adds the existing ActionRequest migrations `0005`–`0007` and run migration `0009`
only in that guarded allocation schema when needed, and starts
the isolated API/page at `127.0.0.1:8125` / `127.0.0.1:3110`. It refuses partially
prepared state and occupied ports. Credentials are restored in the launcher process.
The SQL above goes to `psql` through standard input (`docker compose exec -T`), so
Windows shell argument parsing cannot split the multiword statement.
For the retained allocation case, the same **read-only** standard-input pattern
checks that the case and its order belong to the fixture enterprise. The state
must already be guarded; a result of `ragforge_day6_test|1` was confirmed by the
user in ordinary PowerShell on 2026-10-22:

```powershell
$s = Get-Content -LiteralPath 'scripts/investigation_allocation_demo_state.json' -Raw -Encoding UTF8 | ConvertFrom-Json
if ($s.database -ne 'ragforge_day6_test' -or $s.schema -notmatch '^allocation_demo_[0-9a-f]{32}$' -or
    $s.case_id -ne '7beb2d8e-7ec6-4aef-b48e-3308a8881a21' -or
    $s.organization_id -ne 'd6f90c90-01b5-42de-81f5-5d4e2268aee7') { throw 'Unexpected fixture scope' }
$sql = 'SELECT current_database(), COUNT(*) FROM "' + $s.schema +
       '".exception_cases c JOIN "' + $s.schema +
       '".orders o ON o.id=c.order_id WHERE c.id=''' + $s.case_id +
       '''::uuid AND c.organization_id=''' + $s.organization_id +
       '''::uuid AND o.organization_id=c.organization_id;'
$sql | docker compose exec -T postgres sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" exec psql -XAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d ragforge_day6_test'
if ($LASTEXITCODE -ne 0) { throw 'Read-only case check failed' }
```

For a database-only check before starting the demo, run
`.\scripts\start_investigation_allocation_demo.ps1 -VerifyOnly` in ordinary PowerShell.
It runs the targeted investigation lifecycle tests against random schemas in
`ragforge_day6_test`, checks schema cleanup, and does not call a model or prepare
retained demo data. Stop if the test reports a failure; do not use historical
Graph/API evidence to infer this new persistence path passed.
Read the member/admin email and password locally from the ignored
`scripts/action_request_demo_state.json`; never copy them into evidence. Read the
case ID, workspace ID and exact `as_of` from the ignored
`scripts/investigation_allocation_demo_state.json`. Log in at
`http://127.0.0.1:3110/login`, select the fixture enterprise, open **订单调查**,
enter that case and workspace, enable required SOP retrieval, and submit once.
The page keeps a separate submission key across refreshes, checks the original run,
and offers authorized saved-report history. A connection error is not evidence that
the model stopped: depending on transport cancellation, it may finish and save or
be marked failed, so check the original submission before another run. On the current
single-API-worker deployment, a restarted process marks its old running records
`interrupted` on the next status read; the 690-second deadline also prevents a
permanent running state. If no record was reserved before a connection error, the
page can resend the saved original parameters with the **same** submission key;
it does not silently start a new keyed investigation. A failed report save does
not produce a recoverable success. This is not Graph checkpoint recovery.

On the **same 3110 page and 8125 API**, copy the investigated case ID by hand
into **客户通知申请**, then sign in as the enterprise admin to approve and explicitly
create the in-system notification record. Both actions use the same guarded
allocation schema, so the case ID is valid there; switching to the older
3108/8123 action-demo schema would not find this case. A saved
report does not automatically submit an application or send a message. `delivery_status`
remains `not_sent`. The targeted offline, guarded PostgreSQL and controlled-provider
browser refresh results are separated in the [redacted persistence acceptance summary](PROJECT_A_INVESTIGATION_RUN_ACCEPTANCE.md).
The refresh check used real JWT/API and isolated PostgreSQL with a controlled Provider;
it is not a new real-chat-model investigation pass.

The linked [redacted baseline summary](PROJECT_A_BASELINE_EVIDENCE.md) is commit-safe. Original `scripts/*.json`, `.jsonl` and logs cited by name are local-only and are not included in the repository. Run the evidence commands below from the repository root in PowerShell only when those local archives are available. They display existing results and make no model request or database change. The C05 fixture and ActionRequest test schemas were rolled back, so their IDs are **not** live records.

## Historical real-result replay (current Graph)

From the repository root, use the locally retained 2026-10-19 successful page report:

```powershell
node scripts/investigation_presentation_verify.cjs --preview
Invoke-Item (Join-Path ([System.IO.Path]::GetTempPath()) 'project-a-investigation-saved-report-preview.html')
```

The preview shows the saved summary, Beijing-time comparison, six-part handoff, expandable evidence and copyable request ID. Its source `scripts/investigation_page_run_20261019T150109651854Z_eae597fa.json` is **local-only**, not included in Git. This is a **historical real-result replay**, not a new end-to-end acceptance of the current code or a new model call. The separate authenticated ActionRequest and internal-notification demonstration is described below; the report does not create an application automatically.

## Saved allocation report in the actual React page

With the retained isolated 3110/8125 services and local evidence available, run `node scripts/investigation_allocation_replay_proxy.cjs` once in a separate PowerShell window, then open `http://127.0.0.1:3111/login`. This loopback-only entry proxies the real login, organizations, workspaces and React assets. It requires a valid JWT and visible enterprise/workspace before returning the **saved** HTTP result for request `350b8943-4dcc-493f-b090-11b8076265e4`; it never forwards an investigation POST to 8125. The saved response and credentials live only in ignored local state/evidence files. Logging in at 3111 is necessary even if 3110 is already logged in, because browser storage is origin-specific.

Log in as the existing demo member using the local `scripts/action_request_demo_state.json`, select the demo enterprise and `订单履约调查 SOP 演示` workspace, enter case ID `7beb2d8e-7ec6-4aef-b48e-3308a8881a21`, leave analysis time blank, enable required SOP retrieval and click once. The local relay rejects another case or workspace with 409. The user confirmed the saved response in the actual React page on 2026-10-22: `report_rendered` in about 163 ms in an earlier r4 check, conclusion/evidence visible, expansion working and full request ID copied. The user also confirmed the shortened r6 content and that the r7 submit button returns to “生成只读交接单” after the report displays. The r7 layout leaves the business summary and Beijing-time comparison visible by default; two closed sections reveal short handoff items or source counts, with complete handoff/SOP text, UUIDs and JSON in nested scrollable sections. This is an accepted **React saved-response replay**, not a new model run or live browser-to-model acceptance. Browser automation remains blocked by `CDP timeout: Page.enable`. Stop the relay with Ctrl+C in its own window after the check; do not delete the retained fixture.

## 1. Show the investigation report

```powershell
@'
import json
from pathlib import Path

run = json.loads(Path('scripts/investigation_api_c05_20261018T052738639745Z.json').read_text(encoding='utf-8'))
print({key: run[key] for key in ('passed', 'rollback_verified', 'elapsed_seconds')})
print(' -> '.join(run['tool_path']))
print(json.dumps(run['api_response']['report'], ensure_ascii=False, indent=2))
print(run['api_response']['handoff'])
'@ | .\.venv-d4\Scripts\python.exe -
```

Expected: `passed=True`, tool path `get_exception_case -> analyze_fulfillment -> search_knowledge`, `outcome=observed_delay`, `root_cause=unknown`, four business `evidence_event_ids`, one separate SOP entry in `knowledge_source_ids`, and a six-part handoff. This is a replay of the [single real C05 acceptance run](PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/investigation_api_c05_20261018T052738639745Z.json`，仅本地留存；未包含在仓库中）, not a new live investigation. The independent [C10 result](PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/investigation_api_c10_20261019T055925983902Z.json`，仅本地留存；未包含在仓库中） covers knowledge-source visibility under workspace permissions.

## 2. Show authenticated creation and review

```powershell
$action = Get-Content .\scripts\action_request_20261019T074042047684Z.json -Raw | ConvertFrom-Json
$action | Select-Object passed, tests_run, failures, errors, all_test_schemas_dropped
Select-String .\scripts\action_request_20261019T074042047684Z.log -Pattern 'test_authenticated_creation_and_review_http_chain|test_concurrent_same_key_creates_one_request_and_audit|test_concurrent_reviews_persist_one_decision_and_audit|Ran 14 tests|OK'
```

The new test uses real JWTs and the registered HTTP routes against a random schema in `ragforge_day6_test`. It creates one request and approves it, then creates another and rejects it. A separate database session reads the committed requests and creation/review audits. It also checks unauthenticated creation (401), cross-enterprise membership (403), a foreign case (404), forged scope/applicant/status fields (422), same-content retry (same ID), changed-content retry (409), and ordinary member review (403). The existing Service tests cover two-connection creation and review races.

For a live enterprise member and an existing case owned by that enterprise, creation is:

```http
POST /api/v1/organizations/{organization_id}/action-requests
Authorization: Bearer <member-access-token>
Content-Type: application/json

{"target_case_id":"<case-id>","message":"Please review this delivery update.","idempotency_key":"<enterprise-scoped-key>"}
```

The response contains the request ID, enterprise, applicant, action type, target case, creation time, and `pending_approval` status. Scope and applicant come from the route and JWT, not from request JSON. A same-content retry returns the original request; another body with the same enterprise/key returns 409. The endpoint commits the request and creation audit together and does not send a notification.

An administrator or owner can then review that request:

```http
POST /api/v1/organizations/{organization_id}/action-requests/{request_id}/review
Authorization: Bearer <admin-or-owner-access-token>
Content-Type: application/json

{"decision":"approved"}
```

Use `{"decision":"rejected"}` for a **different pending request**. The response records `status`, `review_decision`, `reviewed_by_user_id`, and `reviewed_at`; a second decision returns 409. Approval means **approved for possible later execution**: it does **not** send the customer notification or set `executed`. A separate, controlled execution step can now create an internal record; no external delivery service is connected.

The C05 evidence case ID cannot be sent to these routes now: its fixture was rolled back. A live demo needs its own valid case and member/admin JWTs. The report does not automatically create an ActionRequest; a person submits the creation request after reviewing it. For an independent replay of the HTTP and Service checks, `.\.venv-d4\Scripts\python.exe scripts\action_request_verify.py` is pinned to `ragforge_day6_test`, creates random schemas, applies migrations `0005/0006` there, and drops them after each test. The earlier 2026-10-19 [15-test evidence](PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/action_request_20261019T080756327731Z.json`，仅本地留存；未包含在仓库中） records successful cleanup. Do not point it at a business database.

## 4. Start the isolated browser demo

The [demo helper](../scripts/action_request_demo.py) pins its database identity to `ragforge_day6_test` on localhost:5433 and creates a random `action_demo_*` schema. It never migrates the business database. The local `scripts/action_request_demo_state.json` holds the test-only logins and password; `.gitignore` excludes it. A prepared schema was retained on 2026-10-19; check its current state with `.\.venv-d4\Scripts\python.exe scripts/action_request_demo.py inspect`. If the state file is absent, run `prepare` once. `prepare` refuses to overwrite existing state.

Start the isolated API in one PowerShell terminal from the repository root:

```powershell
.\.venv-d4\Scripts\python.exe scripts/action_request_demo.py serve
```

Start the built frontend in another terminal. The backend rewrite is embedded during the build, so build with this local address:

```powershell
cd frontend
$env:BACKEND_INTERNAL_URL = 'http://127.0.0.1:8123'
npm run build
node node_modules/next/dist/bin/next start -p 3108
```

Open `http://127.0.0.1:3108/login`. Read the local demo credentials from the ignored state file (`emails.member`, `emails.admin`, `password`) without copying them into evidence. Log in as the member, open **客户通知申请** in the sidebar, use `case_id` from that file, enter a message, and submit. The page shows the application ID and `待人工审核，尚未发送通知`. Create a second application with a different message. Log in as admin, revisit `/action-requests`, approve the first and reject the second. The page should show `已批准，尚未发送通知` and `已拒绝`. The server checks membership and role independently of the buttons.

The retained demo users' original `@example.invalid` addresses made `/auth/me` fail response validation after `/auth/login` succeeded. Their existing user IDs and password were kept; only the email domain in the isolated demo schema and ignored state file was corrected to `@example.com`. Always copy the current `emails.member` or `emails.admin` value from `scripts/action_request_demo_state.json`; an earlier copied email will no longer log in. The one-time repair is available as `scripts/action_request_demo.py repair-emails` and is idempotent for this retained schema. The [frontend-path login check](PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/action_request_demo_login_20261019T092002737272Z.json`，仅本地留存；未包含在仓库中） confirms login, `/auth/me`, organizations and enterprise members all return 200 through port 3108; it records no password or token.

On 2026-10-19 the isolated data was verified through real login, JWT, HTTP and PostgreSQL: [HTTP evidence](PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/action_request_demo_http_20261019T080647172012Z.json`，仅本地留存；未包含在仓库中） shows two committed requests, four audit events, 401/403/404/409/422 responses, and no `executed` state. [Targeted PostgreSQL tests](PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/action_request_20261019T080756327731Z.json`，仅本地留存；未包含在仓库中） cover member-only versus admin enterprise lists and the earlier creation/review races. **Automated browser acceptance is still unverified**: this environment's Chrome and Edge GPU processes failed before CDP could load the page; the [browser attempt](PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/action_request_browser_2026-10-19T08-08-42-020Z/evidence.json`，仅本地留存；未包含在仓库中） records that failure. The frontend passed typecheck, lint, and production build.

When the demonstration is finished, stop the two local servers, then explicitly remove only this test schema and ignored state file:

```powershell
.\.venv-d4\Scripts\python.exe scripts/action_request_demo.py cleanup
```

`cleanup` rechecks the test database identity and confirms the schema is gone. Do not run it while the demo is in use.

### 2026-10-19 browser acceptance follow-up

The 2026-10-19 one-shot headless Chrome attempt used GPU-disabled flags and the retained isolated demo data. It stopped before page interaction: CDP `Page.enable` timed out, with zero browser checks and zero application requests. The [raw evidence](PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/action_request_browser_2026-10-19T08-26-58-871Z/evidence.json`，仅本地留存；未包含在仓库中） records the browser/profile paths; its neighboring `chrome.stderr.log` contains the original startup diagnostics. This run did **not** verify UI creation, duplicate-click protection, approval, rejection, or refreshed labels. A read-only database check after the attempt still found exactly the two earlier requests (`approved` and `rejected`) and four audits. The failure's exact cause is unknown; this attempt's log does not show a fatal GPU-process error.

The isolated API and frontend were left running on `127.0.0.1:8123` and `127.0.0.1:3108` on 2026-10-19; present availability has not been rechecked. After checking or starting both services, open `http://127.0.0.1:3108/login`; from the ignored `scripts/action_request_demo_state.json`, use `emails.member` and `password`, then open **客户通知申请** and enter `case_id` with a new message. Click submit repeatedly while it says `提交中…`: expect one new ID. Create a second request with a different message. Log in with `emails.admin` and the same password, approve the first, reject the second, refresh, and confirm `已批准，尚未发送通知` / `已拒绝`. Run `.\.venv-d4\Scripts\python.exe scripts/action_request_demo.py inspect` to compare IDs/statuses and creation/review audit counts. Keep the schema until the demonstration is finished; use the explicit `cleanup` command above only afterward.

### Controlled internal notification execution

The admin/owner may now click **创建站内通知记录** on an approved application. The authenticated API is `POST /api/v1/organizations/{organization_id}/action-requests/{request_id}/execute`; `GET .../{request_id}/notification` lets its requester or an admin/owner inspect the saved content. A successful result has `delivery_status=not_sent`; the application becomes `executed` only when the internal record and execution audit commit in the same transaction. The UI displays “站内通知记录已创建，未发送；客户收悉未确认”. This records a planned customer message **inside this system**; it does not send email or SMS and provides no proof that the customer saw it. The same request executed twice returns the same record.

The application list now shows creation, review decision/time and internal execution time in Beijing time. An unperformed step says “尚未审核” or “尚未执行”; a missing historical timestamp says “未记录”. Internal execution time is the associated notification record's creation time, not a send or receipt time. Click **查看通知记录** on an executed application to load its own record if needed, scroll to that application's card and briefly highlight/focus it. A failed or mismatched record lookup displays an error rather than showing another application's content. The read-only [retained-demo timeline check](PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/action_request_timeline_20261019T124310482527Z.json`，仅本地留存；未包含在仓库中） verified all four visible application records and the executed timestamp against the notification record through the frontend API proxy. Browser click/scroll remains unverified because the earlier CDP failure was not retried.

The [isolated PostgreSQL result](PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/action_request_20261019T084353824194Z.json`，仅本地留存；未包含在仓库中） passed 21 targeted tests, including approved-only execution, role and enterprise boundaries, duplicate/concurrent calls, the database uniqueness constraint, an audit-failure rollback, and authenticated HTTP readback. Test schemas were dropped. The retained demo schema was upgraded **only inside `ragforge_day6_test`** with `0007_customer_notifications`; `.\.venv-d4\Scripts\python.exe scripts/action_request_demo.py inspect` confirmed its two earlier applications and four audits unchanged and zero internal notifications. The API/frontend were running on ports 8123/3108 on 2026-10-19; check or start them before use. Browser automation remains unverified as recorded above.

### Current LangGraph browser investigation (separate evidence)

**Recovery gate after the first browser attempt:** its retained evidence records `outer_timeout` at the 690-second boundary without a report or persisted tool trace. The Graph has no checkpointer, so this invocation cannot resume. After the computer interruption, PG/Redis/Qdrant were unavailable inside Codex; do not submit again until those existing services and the retained fixture pass read-only checks. The 3109 frontend and 8124 API were restarted without a model request. No new case, workspace or collection was created. See `PROJECT_A_CONTINUATION.md` for the original attempt's limits.

The historical C05 real pass above used the old Core loop and does not establish a pass for the current Graph or the browser page. The action demo was available on 3108/8123 on 2026-10-19; check or start it before use. A separate page/API pair on `http://127.0.0.1:3109/login` and `127.0.0.1:8124` uses the same **isolated** `ragforge_day6_test` demo schema. Its new case, four fulfillment events and SOP workspace have distinct IDs; the SOP vector lives in its own collection. Inspect only these resources with `.\.venv-d4\Scripts\python.exe scripts/investigation_page_demo.py inspect`.

Use the member email and password from the ignored `scripts/action_request_demo_state.json` to log in at port 3109. Select the existing demo enterprise, open **订单调查**, enter case `59db2e27-ac93-4ef0-b939-a72ac2b5113a`, select **订单履约调查 SOP 演示** (workspace `0f676bd4-9f01-447b-b185-227d9df84966`), check **必须检索所选工作区的 SOP**, leave the optional analysis time blank, and submit **once**. Wait for the report or error without retrying. The page exposes the returned outcome, business event IDs, SOP source IDs and six-part handoff. Its request ID helps correlate the browser result. Server-side observation is written to `scripts/investigation_page_graph_evidence.json` only when that case reaches the Core. Run `.\.venv-d4\Scripts\python.exe scripts/investigation_page_demo.py verify` after the response to compare the actual Graph tool trace, report validator, four event citations, SOP citation and six handoff sections; it writes `scripts/investigation_page_acceptance.json`. Preparation and the read-only JWT/workspace check made no chat request.

The report remains separate from ActionRequest: reviewing its recommendation does not automatically create a customer-notification application. The current application requires a separate human submission and approval. This demonstration creates an internal notification record only through the explicit approved execution route; it does not send or prove receipt of a message.

The fixture was retained on 2026-10-19 for browser acceptance; check its current state before cleanup. Once finished and explicitly ready to remove this run's data, stop the 8124/3109 servers, then run `.\.venv-d4\Scripts\python.exe scripts/investigation_page_demo.py cleanup`. This removes only the new case/order/events/workspace and its dedicated collection; it leaves the action demo records alone.

**2026-10-19 readiness update:** PG in `ragforge_day6_test`/`action_demo_e023b320166644acb8429553ae39ad81` still contains the case, order and exactly four expected event IDs. The member retains viewer access to workspace `0f676bd4-9f01-447b-b185-227d9df84966`; its completed SOP chunk and matching Qdrant point remain in collection `project_a_knowledge_test_2958ecc15aef492eac291028c306d64a`. Redis PING, the 3109 login page, the 8124 API and the 3109-to-8124 authenticated route were checked without invoking the investigation. The earlier `scripts/investigation_page_graph_evidence.json` is preserved as historical failure evidence. On a browser submission, the dedicated API creates a unique `scripts/investigation_page_run_*.json` snapshot and fsynced `.jsonl` event stream; `scripts/investigation_page_latest.json` points to the run and records its request ID. The stream records model-request boundaries, tool observations, report rejections, phase changes, final report/error and HTTP status when a response is sent. An interrupted run may have no final result; the last persisted event is the limit of what can be concluded. `verify` now reads the latest snapshot.

**Browser attempt on 2026-10-19:** Do not repeat this model request merely to read its result. Request `288e0c6d-2f2d-40d0-951b-c43ba1e2eec7` completed on the 8124 backend with HTTP 200 after 579.375 s. The [per-run snapshot](PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/investigation_page_run_20261019T143557352050Z_3de46dd5.json`，仅本地留存；未包含在仓库中） and matching `.jsonl` show the exact tool path, two report corrections, validated citations and six-part handoff; [offline acceptance](PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/investigation_page_acceptance.json`，仅本地留存；未包含在仓库中） passed. The browser instead showed an error because its 3109 development proxy logged a socket hang up; browser delivery did not pass. The locally installed Next dev rewrite defaults to a 30 s proxy timeout, now raised to 720 s in the 3109 configuration while the 690 s backend bound remains intact. The proxy correction was first checked with configuration startup and a controlled delay; a later 2026-10-19 browser submission returned a complete current-Graph report through 3109. See the [redacted baseline summary](PROJECT_A_BASELINE_EVIDENCE.md); the original run file `scripts/investigation_page_run_20261019T150109651854Z_eae597fa.json` is local-only and not included in the repository. The transient enterprise-name placeholder now keeps the actual organization ID visible, and cannot be read as evidence that the earlier POST lacked enterprise scope.
