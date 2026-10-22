# Project A 最小调查评测集（设计与单次结果）

本清单只复用已有合成场景和存档证据，不把历史结果算作本次运行。评测对象是当前 Graph 的调查报告；每次运行仍由原 `evidence_contract`、`validate_report` 和 `render_report` 判定，不用关键字匹配代替校验。案例 ID 只标识隔离演示数据，不是生产案例。原始运行 JSON/JSONL 仅本地留存；公开依据见[基线脱敏摘要](PROJECT_A_BASELINE_EVIDENCE.md)和[调查记录验收摘要](PROJECT_A_INVESTIGATION_RUN_ACCEPTANCE.md)。

| 案例与输入 | 预期结论、必需引用和禁止结论 | 通过条件 | 已有证据与当前可用性 |
| --- | --- | --- | --- |
| **A：有订单级关联证据。** 已保存隔离状态 `scripts/investigation_allocation_demo_state.json`：案件 `7beb2d8e-7ec6-4aef-b48e-3308a8881a21`、工作区 `61730353-ee16-470b-916e-7c3b5117875f`、`as_of=2026-10-20T18:37:15.004234+00:00`，`require_knowledge=true`；企业 ID 从同一状态文件读取，不从请求正文伪造。 | `observed_delay / inventory_allocation_blocked`，只限**该运单发货延迟与分配受阻有关**。必须引用本次分析已观察的全部业务事件及独立检索到的 SOP 来源；历史样本分别为六条与一条，重跑时以当次观察为准。禁止称整单完成、唯一根因、通知已发送或建议已执行。 | 案件→履约分析→授权 SOP 检索的工具轨迹正确；分配失败和延迟关联符合企业、订单、运单、来源、时间及唯一关联约束；报告通过原校验器，六部分交接单完整。 | 2026-10-21 当前 Graph/API **真实模型单次通过**，首份报告合格、无报告纠错，HTTP 200、490.797 秒；保存响应的 React 回放另验。本轮 HTTP 确认页面/API、授权组织/工作区、SOP collection 与点可见；隔离 PG 案件/事件仍待独立只读核实。 |
| **B：观察到延迟，但无充分原因关联。** 已保存隔离状态 `scripts/investigation_page_demo_state.json`：案件 `59db2e27-ac93-4ef0-b939-a72ac2b5113a`、工作区 `0f676bd4-9f01-447b-b185-227d9df84966`，`require_knowledge=true`；历史运行的 `as_of=2026-10-19T15:01:09.364109+00:00`，后续比较必须固定同一分析时点。 | `observed_delay / unknown`。必须引用本次分析已观察的全部业务事件及独立检索到的 SOP 来源；历史样本分别为四条与一条，重跑时以当次观察为准。禁止凭时间差、库存快照或 SOP 推断具体根因，也不能把运单送达提前写成整单完成。 | 案件、履约分析和授权 SOP 均实际读取；原校验器接受事件与知识两类引用，六部分交接单保留未知事项、未执行状态。 | 2026-10-19 当前 Graph 的**真实模型＋浏览器提交单次通过**，报告纠错后合格；另有旧循环 C05 成功，不能替代当前 Graph 结果。本轮 HTTP 确认页面/API、授权组织/工作区、SOP collection 与点可见；隔离 PG 案件/事件仍待独立只读核实。 |
| **C：案件不存在。** 固定合成案件 ID `c0ffee00-0000-4000-8000-00000000c003`；企业、成员、工作区和 `as_of` 复用 A 的有效隔离输入，`require_knowledge=false`。预检必须在 `ragforge_day6_test` 的 A schema 确认此 ID 不存在。 | `not_found / unknown`，业务事件引用为空；未实际检索 SOP 时知识来源引用也为空。禁止把它写成履约正常、已完成或权限拒绝；401/403 与授权范围内的业务 `not_found` 分开统计。 | 真实案件工具返回 `not_found`，模型报告经原校验器接受，HTTP 200 与六部分只读交接单成立；若工具/模型故障则记最终失败，不能充当 `not_found`。 | 2026-10-23 当前评测 **真实模型＋真实 JWT/ASGI API＋隔离 PG 单次首答通过**；预检确认固定 ID 不存在，详细结果见下文。此前另有 2026-10-22 受控 Provider 刷新恢复验收，两者不是同一次运行。 |

## 本轮单次结果索引

| 记录 | 结果 | 模型调用／耗时 | 验证范围与本地原始证据 |
| --- | --- | --- | --- |
| A | `final_failure`：调查阶段异常输出被拒，纠错轮 `model_timeout` | 4 次／519.406 秒 | 完整 Graph/认证 ASGI；`scripts/investigation_minieval_A_once.json` 及同名 JSONL。 |
| 原 B | `final_failure`：旧隔离 schema 缺列导致 `tool_failed`；环境失败，不计模型质量 | 2 次／173.984 秒 | 完整 Graph/认证 ASGI；`scripts/investigation_minieval_B_once.json` 及同名 JSONL。 |
| B2 | `final_failure`：完整调查已取得业务与 SOP 观察，但报告首答及纠错均漏引并错误归因 | 5 次／441.484 秒 | 0008 修复后的完整 Graph/认证 ASGI；`scripts/investigation_minieval_B2_once.json` 及同名 JSONL。 |
| C | `first_answer_pass`：`not_found / unknown`，HTTP 200 | 2 次／124.203 秒 | 完整 Graph/认证 ASGI；`scripts/investigation_minieval_C_once.json` 及同名 JSONL。 |
| B2 报告阶段修复后 | `first_answer_pass`：E1–E4、K1 齐全，根因 `unknown` | 1 次／162.173 秒 | 仅复用 B2 保存的完整观察生成报告；`scripts/investigation_minieval_B2_report_once.json` 及同名 JSONL。**不算完整 Graph/API 通过**。 |

以上原始 JSON/JSONL 仅本地留存，不纳入仓库；每行均为独立单次结果，不计算稳定率，也不覆盖历史成功或失败记录。

## 统一结果记录

每次尝试单独保存一条记录，至少包含：`case_key`、代码 commit、环境/Provider 类型、输入范围（企业/案件/工作区、`as_of`、`require_knowledge`）、请求与提交键、开始/结束时间、HTTP 状态、工具序列及状态、报告候选与原校验器的拒绝差异、最终报告/六部分交接单、`model_call_count`、逐次模型调用阶段及耗时、总耗时、错误码/异常类型和证据路径。凭据、完整 Token、原始 Prompt 与完整观察不放入公开摘要；无法取得的时长或计数记 `null`，不能推算。

已结束尝试的 `result_class` 只能是 `first_answer_pass`、`corrected_pass` 或 `final_failure`；未启动的案例另记 `not_run`。如果快照已建立但无结束事件，保持未定并人工核对原提交，不凭文件末尾猜测终态。这里的“首答”是**首次报告候选**，不是首次工具决策；首份报告经原校验器通过且引用完整才记首答通过。首份被拒、按原预算纠错后通过才记纠错后通过；报告引用遗漏/伪造、原因越界、工具或模型超时、HTTP/保存失败、权限拒绝、中断等均记最终失败，并同时保存实际 `error_code`、失败阶段和简短原因。HTTP 200、工具检索成功或页面显示文字单独都不构成通过。不得自动补引用、放宽合同或重试整场。

## 离线核对与真实模型执行前提

2026-10-22 定向离线复核四个既有方法通过（`Ran 4 tests ... OK`）：有明确分配关联、只有分配失败但因果未知、缺失事件的 `not_found` 终态，以及 API 对 `not_found`/`insufficient_evidence` 的成功响应。运行时仅向测试进程提供虚构 `SECRET_KEY`/`DATABASE_URL`；测试未连接数据库或调用模型。另将 A/B 两份已保存真实运行的 `report` 和 `trace` 原样交给当前 `validate_report`，分别得到 `observed_delay / inventory_allocation_blocked` 与 `observed_delay / unknown`，未重新生成报告。以上只验证合同和保存结果，不是三例当前真实模型评测。

统一入口最初另有 3 项定向离线测试通过：预检 CLI 不分派运行、同一案例的本地证据文件不能覆盖、原校验器对 `not_found` 首答/纠错分类及错误原因拒绝。Python 语法、Ruff、PowerShell 解析及文档链接检查通过；**截至该次离线检查**尚未执行隔离 PG 预检或真实模型请求。后续 A 单次尝试另见下文，不并入离线通过数。

真实模型前须只读确认隔离 PG 身份与 schema、A/B 案件及事件、工作区成员权限、SOP chunk/vector、Redis/Qdrant/Ollama；C 的固定 ID 须在 A schema 查为不存在。独立入口 `scripts/investigation_minieval.ps1` 从本项目 postgres 容器读取现有凭据到进程内，调用 `scripts/investigation_minieval_once.py`：默认只读预检；`-Run` 才经真实 JWT 与现有 ASGI API 提交一例。每例固定的本地快照/JSONL 以独占创建防重，不覆盖历史运行；三个案例各有独立提交键和输出，另以本地活动标记禁止同时启动。逐轮候选、引用差异、工具轨迹和计时只留本地；原报告校验器不变。此入口**不启动浏览器，也不把离线 ASGI 提交称为页面验收**。现有旧 runner 的固定输出路径仍受保护。

2026-10-22 首次普通 PowerShell 预检：A 通过；B 因保留 schema 缺少 `investigation_runs` 表而停止；C 尚未检查。此失败记录保留，不改写为通过。B 专用 `-UpgradeB` 先强制核对 `ragforge_day6_test`、明确的 B schema、案件/事件/SOP 身份，再仅应用现有 `0009_investigation_runs` 迁移建立调查记录表、约束和索引；若已有表或部分迁移则停止。成功后同一入口依次只读预检 A、B、C，**不会运行 `-Run` 或调用模型**。该修复仅适用于保留的隔离评测 schema，不是业务库迁移。

2026-10-23 A 单次真实模型评测（本地原始证据仅留 `scripts/investigation_minieval_A_once.json` 及同名 `.jsonl`）：`final_failure`，HTTP 502 / `model_timeout`，request_id `2521adf9-50cd-433b-9965-e50783c81545`，4 次模型调用，519.406 秒。两项业务工具依次返回案件、履约分析；第 3 次调查阶段输出被拒（`invalid_evidence_report`），第 4 次调查阶段纠错调用在 180.016 秒取消。未进入报告阶段，未检索 SOP，未形成合格报告。此结果不覆盖 2026-10-21 当前 Graph/API 的历史单次成功；两次运行分别记录，不能合成稳定率。快照和 JSONL 有结束事件且活动标记已不存在；隔离数据库的终态尚未通过独立只读查询确认，不能仅凭 HTTP 502 声称已落库。

2026-10-23 B 单次真实模型评测（本地原始证据仅留 `scripts/investigation_minieval_B_once.json` 及同名 `.jsonl`）：原始结果保持 `final_failure`，HTTP 502 / `tool_failed`，request_id `9f9e2923-20d9-45a8-9174-89444277d38b`，2 次模型调用，173.984 秒。`get_exception_case` 成功；`analyze_fulfillment` 按该案件返回的订单 ID 和固定 `as_of` 调用时，在 0.016 秒内抛出 `ProgrammingError`。尚未产生履约分析、SOP 检索或报告，也没有报告纠错。用户普通 PowerShell **只读 PG 查询**随后确认：数据库 `ragforge_day6_test`，唯一调查记录 `failed / tool_failed`、响应为 SQL NULL、完成时间已写入；B 隔离 schema 的 `caused_by_event_id` 列不存在，显式列查询得到 PostgreSQL 缺列错误。故评测归因为**环境结构失败，不计入模型质量统计**；保留原始 HTTP/模型调用证据及 B 历史成功记录，不将修复后状态回填为本次通过。

B 专用兼容修复入口 `-RepairB` 仅在库、明确 schema、原案件/事件/SOP 和失败调查记录吻合时，检查当前事件表全部模型列、基线及 0008 约束、现有索引；仅对完整的旧 0008 前结构调用现有 `0008_order_allocation_evidence.py`，遇到部分迁移停止。修复后使用当前 `FulfillmentEvent` ORM 只读 SELECT 和结构检查预检 A/B/C。用户普通 PowerShell 已确认 0008 修复和 A/B/C 三例预检通过；这只证明环境就绪，不改写 B 原始 `final_failure`。

随后普通 PowerShell `-RepairB` 曾在迁移前的 `Fulfillment event baseline checks are incomplete` 处停止；该次入口没有执行 DDL，也没有由此产生部分迁移。用户再次以只读事务核对 `ragforge_day6_test` 中明确的 B schema：旧模型全部 11 列、五个具名基线 CHECK、组织/订单外键及三个业务索引均存在；缺少的是 0008 新增的 `caused_by_event_id` 列、对应外键/两个 CHECK 与扩展后的事件类型。故旧表结构符合完整的 0008 前版本；误停来自检查入口直接比较 `pg_constraint.contype` 内部字符值与 Python 字符串。入口改为 SQL 显式 `contype::text` 后再比较，保留原检查和部分迁移拒绝。用户随后报告修复和三例预检通过；原 B 失败与 PG 终态保持原样。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\investigation_minieval.ps1 -RepairB
```

本执行器 Docker 命名管道被权限拒绝，不能直接执行修复及独立 PG 复核；用户普通 PowerShell 已核实 B 的失败终态和缺列。上方 `-RepairB` 成功后会自动依次执行 A/B/C 只读预检；若需单独复核，可用以下命令，任一例失败即停：

```powershell
Set-Location -LiteralPath 'D:\rjcs-projects\Rag-forge-ai-main'
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\investigation_minieval.ps1 -PreflightAll
```

原始 A/B 单次尝试已结束且证据文件防重保留，**不得再次执行 A/B 的 `-Run`**。B 修复后的独立尝试命名为 `B2`：复用 B 的案件、工作区、固定 `as_of`、必需 SOP 和原校验器；使用新生成的 `minieval-b2-*` 提交键、独立的 `investigation_minieval_B2_once.json/.jsonl` 与 `investigation_minieval_B2_once.active` 标记，同时保留全局活动标记。命令内还会做 B2 预检；它不覆盖 B 原失败文件，不自动重试。以下是已执行的历史命令，**不得再次运行**：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\investigation_minieval.ps1 -Case B2 -Run
```

2026-10-23 B2 隔离 schema 修复后的完整调查单次真实模型评测（本地原始证据仅留 `scripts/investigation_minieval_B2_once.json` 及同名 `.jsonl`）：`final_failure`，HTTP 502 / `ungrounded_final`，request_id `11ddcf04-820f-42b7-80d2-0e7141df21af`，5 次模型调用，441.484 秒。前 3 轮依次成功读取案件（99.562 秒）、履约分析（82.407 秒）、授权 SOP（97.609 秒），随后进入报告阶段。首份报告（132.047 秒）和唯一纠错报告（25.031 秒）内容相同：`observed_delay`、业务引用 `[E3,E4]`、知识引用 `[K1]`、`root_cause=inventory_allocation_blocked`。两次均缺少本次已观察事件 `E1,E2`，无重复、伪造或类型混用的引用；校验器按引用检查顺序先以 `invalid_evidence_report` 拒绝。另据履约分析 `allocation.status=not_observed`、`causal_status=unknown`，候选的分配受阻归因也与原证据契约矛盾，不能因为引用补齐就接受。没有合格最终报告。快照标记 `finished`、JSONL 有 `attempt_finished`，本地活动标记已清除；未独立查询本次 PG 终态。此为 **B2 模型报告质量失败**，与 B 原 `tool_failed` 环境结构失败分开记录，不覆盖历史成功记录。

2026-10-23 C 单次真实模型评测（本地原始证据仅留 `scripts/investigation_minieval_C_once.json` 及同名 `.jsonl`）：`first_answer_pass`，HTTP 200，request_id `c0ab5db9-32cf-4ddd-843d-ab7dcc325011`，2 次模型调用，124.203 秒。预检确认固定案件 ID 在隔离 schema 中不存在、成员及工作区授权有效；真实案件工具返回 `not_found`（0.078 秒），没有履约分析或知识检索，符合本例 `require_knowledge=false`。模型首次报告候选为 `not_found / unknown`、业务事件与知识来源引用均为空；引用差异全空，没有报告拒绝或纠错。保存响应包含六部分只读交接单，明确说明建议尚未执行、本次未通知、未执行处置；不将 `not_found` 误写成履约正常。JSONL 有 HTTP 200 和 `attempt_finished`，本地活动标记已清除。此为隔离 PG＋真实 JWT/ASGI API＋真实 Ollama 的单次验收，不是浏览器验收或稳定率。

2026-10-23 B2 报告阶段修复后单次真实模型验证：只读取 `scripts/investigation_minieval_B2_once.json` 的三项完整保存观察，通过当前 Graph 报告首答消息路径和原校验器，不读取数据库、不执行工具或检索。实际请求使用 `llama3.1:8b`、报告上限 700、Provider HTTP 190 秒、Graph 单轮 180 秒、总截止 690 秒。`first_answer_pass`，1 次模型调用，总耗时 162.173 秒；模型首答 `observed_delay / unknown`，E1–E4 与 K1 齐全，短编号还原后引用及根因差异均为空，六部分交接单完整。输入、候选及服务端计数仅本地留存于 `scripts/investigation_minieval_B2_report_once.json` 及同名 `.jsonl`。该一次性入口还依赖本地保留的 B2 原始证据和既有隔离演示状态；公开仓库不含这些数据，不能在新克隆中直接执行。提交的离线测试使用内嵌脱敏等价观察，不依赖原始证据。**此结果仅证实保存观察的报告阶段，不证明修复后的完整 Graph/API 或浏览器链路通过，也不能推断稳定率。**

不得删除已有快照重试；A、B、B2、C 的单次入口及 B2 保存观察的报告阶段入口均已用过。历史 A/B 成功结果和本轮各次失败、成功记录分别保留，不合并为通过率。

预算按当前 Core 上限每例最多 9 次模型调用、单次 180 秒、整场 690 秒；三例理论上限 27 次请求，实际数量依路径和纠错而变。此次 A 失败调用 4 次；此次 B 环境结构失败调用 2 次，**不纳入模型质量统计**；修复后 B2 报告失败调用 5 次；C 首答通过调用 2 次。各次分别记录，不跨版本相加或推算稳定率。B 历史成功运行的 6 次调用属于另一版本/运行，不能合并；修复轮未发模型请求。
