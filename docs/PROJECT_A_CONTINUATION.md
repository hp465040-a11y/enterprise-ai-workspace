# Project A 持续施工交接

更新：2026-10-13（按用户要求暂停，未完成项见下方）。

## 执行授权

用户已持续授权本项目代码、测试、配置、文档修改，项目虚拟环境依赖安装，项目 Docker 服务构建/启动/重启，单元测试、隔离 PostgreSQL、本地 Ollama 和端到端验证。保留已有改动；每批验证后按已确认计划继续，无需等待学习进度。

非破坏性数据库迁移执行前检查目标、备份与内容，保留业务数据。禁止将清表 fixture 指向业务库。删除数据库/数据卷、破坏性迁移、覆盖用户改动、修改无关项目、强制推送、公开发布及新增未确认预算付费服务不在授权范围。客户端权限限制仍有效。

## 本次核验

- 工作区已有未提交的 D6–D8 模型、迁移、服务、测试和验证脚本，以及 LLM 工具调用、Customer Agent 相关改动；本批未覆盖或提交这些改动。
- `docs/PROGRESS.md` 描述旧版 RAG 施工，不能代表 Project A V2.2 的验收进度。
- 仓库文档、scripts、backend 和 .github 中未检索到 V2.2、D9/D10 或已确认加速安排。已请求用户提供原计划路径或任务与验收标准。不得自行编造日程、声称 D9–D10 完成。

## 真实验证

命令：`.\.venv-d4\Scripts\python.exe -B .\scripts\day8_verify.py`

结果：退出码 0，`Ran 45 tests in 12.351s`，`OK`。

范围：库存单元测试、D8 PostgreSQL 测试、D7 服务、订单查询、履约模型及 D7 PostgreSQL 回归。不是全部后端测试，也不包含本轮 Ollama、端到端或业务库迁移验证。

数据库：`localhost:5433/ragforge_day6_test`。执行前审查脚本和测试生命周期：连接前白名单校验，连接后核验 `current_database()`，随机 schema，事务回滚并验证 schema 消失；未运行全局 pytest 清表 fixture。测试覆盖 ORM 与迁移两种建表方式；迁移 downgrade 仅在隔离测试事务执行。

默认沙箱命令因 `helper_unknown_error: setup refresh had errors` 无法创建进程。本轮只读检查及上述验证通过客户端提权审批执行成功；该错误不等于项目代码失败。

## 独立状态

| 范围 | 代码状态 | 本轮验证 | 本人学习 |
| --- | --- | --- | --- |
| D6 模型/迁移 | 已存在，未重复开发 | 模型及被 D7/D8 使用的迁移路径通过；未单独重跑 D6 全套 | 未确认 |
| D7 查询/履约服务 | 已存在，未重复开发 | 已被上述 45 项覆盖，通过 | 未确认 |
| D8 库存 | 已存在，未重复开发 | 单元与真实 PostgreSQL 通过 | 未确认 |
| D9–D10 及后续 | 原计划缺失，范围待核对 | 未执行 | 未确认 |

## 关键代码与学习交接

- `backend/app/services/inventory_service.py`、`backend/app/models/inventory_record.py`、`backend/alembic/versions/0004_inventory_record.py`：库存快照、组织/SKU 隔离、可用库存及约束。
- `backend/app/services/fulfillment_service.py`、`backend/app/services/exception_service.py`：履约时间线、证据边界和异常查询。
- `backend/tests/commerce/test_day6_postgres.py`：测试库白名单、真实数据库身份验证、随机 schema 与事务回滚。
- `backend/tests/commerce/test_day8_postgres.py`：数量边界、大小写与租户隔离、只读查询、迁移验证。
- 学习重点：缺失库存不等于零；可用库存可为负；履约证据不足应返回 unknown；代码存在、测试通过、本人学习完成分别记录。

以上为首轮核验历史，以下记录后续施工结果。

## D9–D10：2026-10-11

原计划已找到并使用 python-docx 成功读取：`C:\Users\xingk\Downloads\Project_A_V2.2_30天施工与学习计划.docx`。首次中文路径经 PowerShell 管道变为问号，改为限定 Downloads 的 `Project_A_V2.2_30*.docx` 匹配后读取成功，未扫描整盘。

原文 P0：D9「Event数据 → Service → real PG test；不同业务数据产生不同Observation」；D10「四个Tool独立测试；organization_id由服务端绑定，不暴露给LLM」。用户持续授权允许代码前进，学习状态仍单独记录，覆盖原计划按学习逐日等待的节奏要求。

### 文件改动与关键业务代码

- `backend/app/services/fulfillment_service.py`：抽取 `get_fulfillment_events`，复用到已有分析；双重组织/订单过滤；按 occurred_at、created_at、UUID 排序。`as_of` 为包含式 occurred_at 截止，不是历史入库快照；省略时返回全部已记录事件。订单不存在抛 NotFoundError，存在但无事件返回空列表；不推断根因。
- `backend/app/services/exception_service.py`：查询禁用 autoflush，防止挂起 ORM 对象被只读查询意外写入。
- `backend/app/ai/tools/investigation_tools.py`：四个上下文绑定的 StructuredTool，复用 Service；UUID、SKU、带时区时间校验，额外参数禁止；显式案件/事件字段投影，递归序列化 UUID/datetime，拒绝未知对象。
- `backend/tests/unit/test_investigation_tools.py`：逐工具参数、组织注入拒绝、Service 调用、输出与错误边界。
- `backend/tests/commerce/test_day10_postgres.py`：真实 Tool→Service→PG，ORM/迁移两种模式，事件差异、稳定排序、截止、跨组织、缺失记录、负库存、只读事务与 pending 对象保护。
- `scripts/day10_verify.py`：固定隔离库，运行本批与 D6–D8、订单 Tool、Customer Agent、Provider 协议回归。

### 真实验证与限制

`day10_verify.py` 退出码 0：**97 tests / 19.801s / OK**。本轮未执行业务库迁移；用户确认业务库停留 0003，0004 仍仅在隔离库验证。无新模型、写 Tool 或 RAG 改造。

错误约定与 order_tool 一致：schema 错误在执行前抛 Pydantic ValidationError；Service 输入错误返回 invalid_input；记录不存在返回 not_found；数据库/超时/未知异常原样抛给调用方。异常不会伪装成空记录、库存零或履约正常。空事件列表为 found，但不表示履约正常；库存 observed_at 和负可用差额保留，不证明特定订单缺货。

安全重跑（项目根目录）：

```powershell
.\.venv-d4\Scripts\python.exe -B .\scripts\day10_verify.py
```

前提：现有 PostgreSQL `localhost:5433/ragforge_day6_test` 可连接。脚本固定该库；底层验证真实库名、随机 schema、事务回滚，未加载全局 pytest fixture。

代码状态：D9–D10 已实现并通过上述验证；本人学习：未完成/未确认，**不标 CLOSED/PASS**。D8 本人学习仍未完成。

亲手练习：在 `test_day10_postgres.py` 将截止时间改为 `OBSERVED - timedelta(microseconds=1)`，亲手补一个断言验证 events 为空；解释为什么刚好等于 OBSERVED 时返回三条。运行安全重跑命令，记录实际输出，并说明空事件与订单不存在的区别。

后续原文：D11 真实 Provider + PostgreSQL 至少一个 Core Case E2E，只读、不接 RAG/Write；D12 库存/履约事件两条真实 Tool Trace，禁止 case_id 硬编码；D13 Stop/Abstention/Failure 覆盖 C01/C06/C07/C08。先独立完成 D11，不提前声明 D12–D13 验收。

## D11 后续施工与排错

在 D9–D10 的 97 项验证通过后才开始本批。新增 `backend/app/ai/agents/core_agent.py`、`backend/tests/unit/test_core_agent.py`、`scripts/day11_e2e.py`；回归入口纳入 Core Agent 单元测试。循环只注册四个 Read Tool，使用既有 LLMProvider 协议；授权由服务端调用方负责，首查给定案件，后续订单绑定案件返回的 order_id，带时区 cutoff 固定，有工具/模型调用上限，系统异常直接中止。无 API/UI 接入、无新业务模型、无 RAG/Write。

真实排错记录（均保留失败证据，不以 Mock 替代真实验收）：

1. `scripts/day11_evidence.json`：真实 llama3.1:8b 查案件后提前回答，并把案件 open 状态误称订单状态；E2E 失败。修复：成功查到案件后，未取得分析不能直接结束；加入预算内补证据提示和回归；明确案件状态不是订单状态。
2. `scripts/day11_evidence_20261011T093249272924Z.json`：真实模型把 case_id 传给 analyze_fulfillment，schema 正确拒绝，未运行该查询。修复：参数描述明确 case.order_id，并将真实案件返回的 order_id/as_of 加入下一轮提示。没有自动将错误参数改成成功结果。E2E 断言改为只计算 found 的工具结果，避免将失败尝试误当成功分析。

最终回归：**103 tests / 20.801s / OK，退出码 0**。本批新增/修改的 9 个 Python 文件 ruff check 全通过。项目虚拟环境安装了项目已声明开发依赖 ruff 0.17.0；未改全局 Python。`git diff --check` 无空白错误（既有文件提示 LF/CRLF，不构成测试失败）。

真实 E2E 安全重跑：

```powershell
.\.venv-d4\Scripts\python.exe -B .\scripts\day11_e2e.py
```

仅使用 `localhost:11434` 现有 llama3.1:8b 和固定隔离 PG 库；随机 schema 内迁移/准备案件事件，再设事务只读、运行真实模型链路、最终回滚。保存时间戳命名证据，不覆盖此前失败文件。脚本检查真实分析结果为晚发货 3600 秒；自然语言回答仍须与证据对照，不能将链路通过等同完整 Grounding 评测。D12 双路径、D13 完整矩阵仍未验收，本人学习仍未确认。

第三次真实 E2E：退出码 0，证据 `scripts/day11_evidence_20261011T100235914092Z.json`，3 次真实模型请求；路径 get_exception_case → analyze_fulfillment → Final。真实分析判定 late，difference_seconds=3600；回滚验证通过。D11 的真实 Provider→Tool→Service→PG→Provider 链路已验证。

回答人工对照（本次由施工代理检查，不代表本人学习验收）：最终回答正确说明晚发货、未确认根因与预计送达时间未知；08:00 是承诺事件发生时间，实际承诺截止为 10:00，发货为 11:00。回答没有明确说出 10:00 截止或 3600 秒差值，也没有按提示引用 event IDs，仍是 Grounding/表达缺口，不能标完整语义验收通过。此输出保留为后续 D13/评测的真实 Bad Case。

下一批 D12 必要核查结论：可以复用该 Loop 和四工具注册；固定开场查案件/分析之后必须由 Observation 驱动不同路径，不能按 case_id 分支。当前仅有晚发货单 Case 的真实 trace，尚无库存路径与履约事件路径双 Trace 证据；不得据单 Case 声称动态 Agent 验收完成。库存 SKU 必须来自调查证据，不能由模型猜测。优先补固定数据场景、动态双路径验证及引用缺口，再按 D13 测 Stop/Abstention/Failure，不新增业务模型或工具扩充范围。

## D11 收尾、D12–D13 施工（2026-10-11，结果持续补录）

范围沿用原计划：D12 的 C03 库存路径/C04 履约事件路径，D13 的 C01 停止、C06 未知、C07 无记录、C08 系统故障。D11 用 C02 单步证据场景复验。仍不开发 RAG、Write、新模型或新业务工具；本人学习不作为代码施工阻塞条件，也未标学习 PASS。

### 核心改动

- `backend/app/ai/agents/investigation_report.py`：模型提交 outcome、evidence_event_ids、root_cause 的严格结构化结论。仅已成功读到的事件能作为引用；缺少/重复/虚构 ID、矛盾结论、额外因果文案均拒绝。最多一次修正，仍失败则报 ungrounded_final。通用生产渲染器从真实 Service 比较结果输出 expected_at、actual_at、difference_seconds、事件 ID 和库存 observed_at；不是修改演示答案。
- `backend/app/ai/agents/core_agent.py`：模型选择可选 Tool；Python 校验首查案件、订单/cutoff/SKU 来源、标准化参数重复、调用预算、模型/工具超时。故障产生有 trace 的结构化异常，不发送“正常”业务 Observation。最终报告保留模型原文及被拒绝的原文。
- `backend/app/ai/tools/investigation_tools.py`：分析 Tool 只投影时间比较与事件 ID，原始 timeline 保留在 Service；详细事件描述通过 get_fulfillment_events 获取，避免两个工具只是返回同一份完整信息。
- `backend/tests/unit/test_core_agent_boundaries.py`：旧 D11 三个真实坏回答回放、引用/根因边界、原生超时、标准化重复、预算和协议测试；`test_core_agent.py` 更新正式输出/异常契约。
- `backend/tests/commerce/test_day13_postgres.py`：真实 PG 只读保存点回滚、更新反事实测试数据、真实 statement_timeout 取消和恢复。
- `scripts/day13_e2e.py`：真实本地模型/PG 场景。C03/C04 使用相同 case_id/order_id/案件/事件，唯一业务变更是库存量；比较开场结果相同与后续工具不同。完整保留模型请求、提供的工具、Observation、原始响应、验证报告、异常与回滚结果。
- `scripts/day11_e2e.py`：增加引用、截止时间、晚发货差值、unknown 根因断言。`scripts/day10_verify.py` 保留原有回归并纳入本批测试。

### 已运行的代码验证

当前回归 **118 tests / 22.780s / OK，退出码 0**，上述 9 个修改/新增 Python 文件 Ruff 全通过。安全入口仍为 `day10_verify.py`，固定隔离库 ragforge_day6_test，未加载清表 fixture。未迁移业务库、未改变原有业务数据。

### 本批失败历史（保留原文）

1. 运行器首次启动被导入排序破坏 bootstrap 顺序，ModuleNotFoundError；在 PG/模型调用前失败，修复后重跑。
2. `scripts/day13_evidence_20261011T122207627980Z.json`：真实 C03 模型只查案件/分析就结束，忽略 reservation 线索；随后运行器试图直接从 read-only 切回 read-write，PG 拒绝。已修复每轮原调查问题提示（不在代码中指定可选路径），并改用保存点回滚恢复事务设置；真实 PG 回归已通过。此文件仍是失败，不能当 D12 PASS。

### 输出和可靠性边界

当前只读数据不能可靠证明根因，因此 root_cause 明确保留 unknown；这是工程限制，不是已经完成任意因果判断。C01 的 no_observed_delay 仅表示两个可比较时间指标未观察到延迟，整体订单完成仍未知。库存快照不是订单预留事实，负数也不能推断该订单缺货。SKU 来源目前采用已有描述中的显式 `SKU=` 标记，未扩充模型或假称对接 ERP。

模型仍负责可选工具选择；提示描述通用业务调查策略。代码不依据 C01/C03 等场景编号或 case_id 分支。严格证据报告是 LLM 选择 + Python 验证/渲染，不能宣称已验证任意自由文本回答的语义正确性。

真实模型重跑（仅本地 llama3.1:8b 和隔离 PG）：

```powershell
.\.venv-d4\Scripts\python.exe -B .\scripts\day13_e2e.py
# 仅重跑同案件双路径
.\.venv-d4\Scripts\python.exe -B .\scripts\day13_e2e.py --cases C03 C04
```

C08 是明确注入的真实 PG statement_timeout（SELECT pg_sleep 被取消），不是生产故障，也不是用 Mock 假装 PG 不可用；期望 Agent 报 tool_failed、保留失败 trace 且不再调用模型。

后续排错补录：`scripts/day13_evidence_20261011T124127574017Z.json` 中 C03/C04 均提前结束，虽修正了缺失引用，但未通过动态路径断言；事务回滚已正常完成。定位到分析 Tool 摘要丢掉了调查线索，现增加承诺事件的 `promise_notes`，完整流转描述仍仅由事件 Tool 提供。C03/C04 场景调整为承诺事件携带 reservation/backorder 线索，存在 in_transit 记录但缺少 shipped 完成时间；这种数据只能返回 insufficient_evidence，而非虚构晚发货判定。两次场景仍使用完全相同的案件/事件，只改变库存数量。C02 保留晚发货 3600 秒的独立验收。

最新回归 **119 tests / 23.769s / OK**；10 个本批 Python 文件 Ruff 全通过。新增测试确保分析摘要保留 reservation/SKU 线索，而不泄露整份事件详情、不修改原 Service 返回对象。

本人亲手练习：在 `test_core_agent_boundaries.py` 的引用负向测试中添加一个“有效事件 ID + 随机新 UUID”的输入，确认 validate_report 拒绝它；解释为何合法 UUID 不等于有证据支持。随后运行 day10_verify.py，记录实际结果。完成此练习前，代码/验证通过均不代表本人学习完成。

## 2026-10-12 恢复：失败证据核对

用户给出的 `scripts/day13_evidence_20261011T124737394433Z.json` 不存在；实际最后一份是 `scripts/day13_evidence_20261011T124733894433Z.json`。已查看完整 trace、requests/response、rejected_finals；原文件保留，`passed=false`、`counterfactual_pair_verified=false`，不得追改成通过。

| 场景 | 该历史文件的真实状态 | 说明 |
| --- | --- | --- |
| C01 | passed | 案件→分析；最终报告修正后通过 |
| C02 / D11 | passed | 晚发货 3600 秒、10:00 截止、事件 ID、未知根因通过 |
| C03 | failed / ungrounded_final | analysis 传嵌套 case，参数拒绝；未实际查库存 |
| C04 | failed / ungrounded_final | 分析后误报 observed_delay；修正轮输出文本工具 JSON，无原生工具调用；未查库存/事件 |
| C06 | failed / AssertionError | 保留未知，但额外重复查询空事件，停止路径不合格 |
| C07 | passed | not_found；拒绝首轮伪工具文本后修正报告 |
| C08 | passed_expected_failure | 实际 PG statement_timeout；tool_failed 后停止 |

本批七个场景均运行过；C05、C09–C12 不在本批 D11–D13 验收范围，未运行。全部上述场景回滚验证通过。历史通过证据继续保留；共享 Agent 修改后的复验单独记录，不能把旧证据当新代码运行结果。

C04 完整错误语义：CoreAgentError / ungrounded_final（最终证据契约连续失败两次）。第一次原始 JSON outcome=observed_delay，但 shipment.status=unknown、reason=completion_not_observed、actual_at=null；deadline_exceeded 只说明截止已过，不证明实际晚发货。第二次原文是 `{"name":"get_fulfillment_events","parameters":{...}}`，response.tool_calls=[]，且当时 offered_tools=[]；普通文本不等于已执行工具。不能把这个样本标为动态路径通过。

修复涉及 `core_agent.py`：保留原生调用；一次 schema 修复机会不执行错误参数、不自动替模型填参；空事件且无 SKU 时停止无增益读取；调查提示与报告提示分离，模型以 FINISH 自主结束调查，再生成严格报告。四个只读工具在调查阶段全部提供，未按场景编号分支，未指定可选工具执行顺序。报告引用、未知/延迟判定、重复调用和预算断言不放宽。

新增 `test_core_agent_boundaries.py` 回放真实 C04 两次坏输出，并验证 FINISH 转报告不产生额外查询；`day13_e2e.py` 补充安全的 CoreAgentError/断言消息（不记录原始数据库连接异常）。实际执行路径仍必须严格等于原 expected_paths；未执行的 schema 错误独立保留在 trace，最多一次，不能算作成功业务查询。

恢复后的首轮回归：121 tests / 23.247s / OK。新增 C04 回放及 FINISH 测试后的回归、真实模型重跑结果待下文补录，不能据此先标 D12 完成。本人学习仍未完成/未确认。

### 恢复后真实验证（逐次保留）

1. `scripts/day13_evidence_20261012T150722072382Z.json`：C06 passed（案件→分析→未知报告，无额外事件查询）；C03/C04 均 failed / AssertionError，只执行案件→分析，普通文本表达查库存意图而无原生调用。全局 passed=false，反事实双路径未通过，三个场景回滚通过。
2. 针对上述协议问题，调查阶段首次无效文本现在保留所有四个 Tool，提示模型用原生调用或 FINISH；不解析文本成调用、不执行猜测参数。再次无效仍报错，受原模型/工具总预算限制。新增回归证明文本本身不执行查询，随后真实原生请求只执行一次。
3. 中间回归 123 tests / 24.922s / OK；协议修复后 **124 tests / 22.422s / OK**；本次三个 Python 文件 Ruff 通过，git diff --check 退出 0（既有文件只有 LF/CRLF 提示）。真实双路径再次重跑结果待补录。
4. `scripts/day13_evidence_20261012T151458839333Z.json`：C03 真正执行库存查询并读到 -3，随后仍调用事件且 cutoff 不符，scope_violation 拦截；C04 连续输出含说明文字的伪工具调用，ungrounded_final。两者失败、回滚通过，不计入动态双路径通过证据。
5. 对应修复：去掉每轮提示中与负库存停止条件冲突的“未解决线索持续调查”措辞；明确未知根因不要求持续读库、所有时间查询必须使用原调查 cutoff。要求工具调用前后不夹说明文字，防止模型输出的工具 JSON 被当普通 content。现有 `OllamaProvider.generate_with_tools` 增加 temperature=0 以减少采样波动，普通 generate/stream 不改；`test_llm_tool_calling.py` 校验请求参数。**124 tests / 21.429s / OK**，真实验证另行记录，未使用新模型或更换业务样本。
6. `scripts/day13_evidence_20261012T152152880964Z.json`：C03/C04 都查到对应库存，但结束/继续阶段退回普通文本；纠正后重复查询被拦截，仍失败。不得把“查到了库存”当成 D12 验收。
7. 直接读取现有 Ollama `/api/show`，保存原始模板和参数到 `scripts/day13_model_template_20261012T1534215654113Z.json`。模板只在最后一条消息为 user 时通过 `if and $.Tools $last` 展开工具定义；工具结果位于末尾时则要求根据结果回答原问题。这是连续工具决策退化为普通回答的具体配置原因，之前单纯改业务提示没有解决它。
8. 最终协议修复：需要继续决策时，在完整工具结果后追加同一条通用决策提示，使本地模板展开全部工具定义，不根据库存数值筛选工具。加入 `finish_investigation` 内部结束控制（空参数、无 Service/DB、不是第五项业务查询），由模型选择，切换至严格报告阶段。四项业务读 Tool、真实执行路径断言、同案件反事实比较不变。内部控制保留在模型原始 requests/response，业务 trace 只记录实际读工具及参数失败尝试；结束控制不能跳过必需观察，且仍受模型总预算约束。相关回归 124 tests / 22.386s / OK；新增结束控制拒绝绕过的测试待最终回归记录。

静态检查范围说明：core_agent.py、test_core_agent_boundaries.py、day13_e2e.py 通过；扩大到此前已有 test_llm_tool_calling.py 后发现 3 个旧风格告警（SIM117、UP017），与本次 options 断言修改无关，未宣称全仓 Ruff 通过。

9. `scripts/day13_evidence_20261012T153141451266Z.json`：原生调用已恢复，但两场景都查事件后又查同一库存，repeated_call 中止，仍 failed。C03 输入 token 904→2355，`/api/ps` 实际 context_length=4096，未发现截断依据。进一步明确最新真实 Observation 与已完成查询清单，避免旧来源描述“inventory availability unverified”覆盖刚读取的库存结果。该提示对所有数据相同，仅附实际返回值，没有 Python 根据库存正负选择/屏蔽工具。
10. `scripts/day13_evidence_20261012T154034920279Z.json`：通用决策提示过早用于开场，C03/C04 在案件之后先请求库存，missing_analysis 拒绝，均失败。修复将已有必需开场要求保留在案件后的决策提示；取得分析后才使用相同的 Observation 决策提示。可选分支仍由模型决定。回归扩充对应消息顺序/真实 order_id 断言，未调整预期业务路径。
11. `scripts/day13_evidence_20261012T154307056970Z.json`：C03 第三次模型请求发生 Provider 超时，model_failed；C04 自主选择事件 Tool，但 as_of=11:00（案件打开时间），被原 cutoff=12:00 校验拒绝（scope_violation）。两者失败。决策提示现在同时明确列出服务端绑定的 order_id/as_of；不替模型修改提交参数。
12. 验收运行器新增每请求 elapsed_seconds、异常/原因类型，避免只记录 CoreAgentError。脚本内 HTTP 超时设为 190 秒，让 Agent 已有的 180 秒单请求上限负责取消；总请求/工具数和整场 600 秒上限不变，生产配置未改。所有失败仍保留，未作为成功样本复用。

## 2026-10-13 暂停交接（本节为当前状态）

用户明确要求暂停代码修改和 C03/C04 重跑，仅停止后台验证、整理已有证据和更新本记录。本轮不再启动测试，不申请脱离沙箱权限，不标 D12 或本人学习 PASS。以上逐次排错记录属于历史，不能替代本节当前状态。

### 后台运行与核查限制

- 已向已知 `day13_e2e.py --cases C03 C04` 后台会话（执行器 session_id=34040）发送 Ctrl+C；执行器返回 exit_code=1，已知会话已结束。最后回收输出为 C04 第 6、7 次模型请求及事件工具调用，没有成功总结，不能据此推定通过或完整回滚。
- 尝试在沙箱内按精确脚本名/参数检查并停止残留 Python 进程，命令因 `helper_unknown_error: setup refresh had errors` 在进程创建前失败，没有实际执行进程枚举或 Stop-Process。没有申请提权；因此只能确认已知执行会话结束，不能声称已独立核查全系统无残留进程。
- 同一沙箱故障限制了当前文件重新读取、git 状态复核及最后证据文件重新读取。本节依据本轮已经读取的文件和工具实际返回编写；不把未核实内容写成已完成。

### 当前验收矩阵

| 项目 | 已有证据 | 当前结论 |
| --- | --- | --- |
| C01、C02（D11）、C07 | `day13_evidence_20261011T124733894433Z.json` 中 passed | 历史通过保留；最新共享 Agent/Provider 修改后未复验 |
| C08 | 同上 passed_expected_failure，真实 PG statement_timeout 后停止 | 历史通过保留；最新代码后未复验 |
| C06 | `day13_evidence_20261012T150722072382Z.json` 中 passed | 当时修复后的停止路径通过；之后共享代码继续修改，最终版本未复验 |
| C03/C04（D12） | 多份失败文件，见上方逐次记录和下方补录 | **未通过；没有已验收的同案件动态双路径证据** |
| 单元/隔离 PG 回归 | 最后已确认 `125 tests / 23.197s / OK`，退出 0 | 仅覆盖该次运行时版本，不覆盖随后可能落盘的中断补丁 |
| C05、C09–C12 | 本批未运行 | 不在本轮 D11–D13 验收范围，不推定结果 |
| 本人学习 | 未完成/未确认 | 不标 PASS，不由代码测试结果替代 |

原用户文件名 `day13_evidence_20261011T124737394433Z.json` 未找到；实际原始失败文件为 `day13_evidence_20261011T124733894433Z.json`，C04 的 CoreAgentError / ungrounded_final 和 passed=false 保留不变。

### 最后失败补录与更正

- `scripts/day13_evidence_20261012T155043139942Z.json`：已实际读取的 C03 为 model_failed；第 3 次请求 elapsed_seconds=4.922，failure_type=UpstreamProviderError，cause_type=ReadError。**这次是读连接错误，不能称为超时**。前文对更早空错误信息的“超时”描述只是当时推测；没有异常类型支持时，应视为原因未确认。
- 同一运行中的 C04 已观察到案件→分析→事件→库存，并继续请求事件。其顺序已不满足原 expected_paths；最后完整错误、最终文件写入状态及回滚结果在暂停时未重新核实，不标通过。
- 本地 Ollama 日志所读片段有约 1m50s、1m57s 的成功 HTTP 请求，但没有足够信息证明上述 ReadError 的根因；不据此断言模型崩溃、内存不足或上下文截断。
- 模板证据保留在 `scripts/day13_model_template_20261012T1534215654113Z.json`；模板对末尾 user 消息的依赖已实际核查。修复它并不等于业务路径已通过，后续失败全部保留。

### 本轮文件改动清单（保留既有改动）

| 文件 | 本轮改动/当前风险 |
| --- | --- |
| `backend/app/ai/agents/core_agent.py` | 调查/报告提示分离；参数及普通文本纠正受限；内部 finish_investigation 控制无数据库访问；追加适配本地模板的决策消息；明确绑定的 order_id/as_of、最新观察与停止要求。业务可选工具仍由模型选择，真实动态路径尚未验收。 |
| `backend/app/ai/llm/ollama_provider.py` | 仅工具生成请求增加 temperature=0；保留此前已有 Provider 改动，未重写普通生成/流式接口。 |
| `backend/tests/unit/test_core_agent_boundaries.py` | 加入真实 C04 坏输出回放、参数纠正、文本不执行查询、内部结束控制及消息顺序/作用域提示测试。 |
| `backend/tests/unit/test_llm_tool_calling.py` | 更新工具请求 options 断言，确认 temperature=0。 |
| `scripts/day13_e2e.py` | 增加安全错误消息、请求耗时和异常原因类型；本地运行 HTTP 等待交由 Agent 原有 180 秒上限控制。原业务路径、同案件反事实、引用/未知/回滚验收要求未放宽。 |
| `scripts/day13_evidence_20261012*.json` | 新增带时间戳的真实运行证据；没有覆盖昨日或本轮失败文件。最后文件完整性/回滚状态待后续只读核查。 |
| `scripts/day13_model_template_20261012T1534215654113Z.json` | 本地实际模型模板和参数快照。 |
| `docs/PROJECT_A_CONTINUATION.md` | 持续追加真实失败、验证结果、限制及本次暂停状态。 |

上一轮中断点正在尝试对 core_agent.py 的决策提示补充“无库存快照时不能假定库存量”，并缩小重复附加的 Observation 文本；同时调整对应测试断言。该 apply_patch 调用被用户中断，没有收到完成确认，**是否部分落盘未核实，且未测试**。本次未继续该补丁，也未修改业务代码。恢复时先读取当前两文件，禁止根据本记录猜测其落盘状态。

仓库原有 D6–D13 模型、迁移、Service、Tool、Agent 和测试等未提交改动仍需全部保留；本节是本次增量清单，不是假称刚完成了全仓 git diff 审计。业务库本轮未迁移；没有运行全局清表 fixture，没有删除数据库或 Docker 数据卷。

### 未完成项与恢复入口（现在不执行）

1. 先只读确认无残留本次验证进程；检查最后证据 JSON 是否完整及是否写入 rollback_verified，不把退出码等同回滚成功。
2. 核对中断补丁是否落盘、当前 diff 和最后测试版本；补全最后 C04 的完整原始响应/错误记录。
3. D12 仍缺严格通过的 C03/C04 成对反事实证据。不得放宽 expected_paths、按 case_id 路由、屏蔽工具或用普通文本冒充原生执行。
4. 若后续明确恢复施工并完成必要修复，先跑隔离回归，再复验受影响的真实场景；共享 Agent/Provider 已改变，历史 C01/C02/C06/C07/C08 不能直接标为最终版本已验收。
5. 更新最终矩阵、限制和学习交接；本人学习状态继续单独记录。

已审查的安全重跑入口（仅供后续恢复使用，本次没有执行）：

```powershell
.\.venv-d4\Scripts\python.exe -B .\scripts\day10_verify.py
# 只有恢复施工后才运行：固定隔离 PG + 已有本地模型
.\.venv-d4\Scripts\python.exe -B .\scripts\day13_e2e.py --cases C03 C04
```

关键代码阅读顺序：core_agent.py 的模型决策消息/作用域校验 → investigation_tools.py 的只读 Service 调用 → investigation_report.py 的证据契约 → day13_e2e.py 的原路径与反事实断言。亲手练习继续沿用上文“有效事件 ID + 新 UUID 必须被拒绝”的测试，不要求现在完成，不视为学习 PASS。

## 2026-10-13 最新 C03/C04 单场证据补录

当前代码下，C03 与 C04 各有一次独立真实运行通过；这只证明这两次单场结果，**不代表完整矩阵已通过，也不代表稳定通过率**。两份 evidence 均记录 `rollback_verified=true`。首次报告的 `observed_delay` 均被证据契约以 `invalid_evidence_report` 拒绝；模型随后修正为 `insufficient_evidence`、`root_cause=unknown` 并通过契约。

| 场景 | 最终 evidence | 实际工具路径 | 最终报告 |
| --- | --- | --- | --- |
| C03 | `scripts/day13_evidence_20261013T144156900202Z.json`，`passed=true` | `get_exception_case → analyze_fulfillment → get_inventory_status` | `insufficient_evidence` / `unknown` |
| C04 | `scripts/day13_evidence_20261013T142937791673Z.json`，`passed=true` | `get_exception_case → analyze_fulfillment → get_inventory_status → get_fulfillment_events` | `insufficient_evidence` / `unknown` |

两次分别使用其对应的 JSONL 运行记录；代码路径位于 `backend/app/ai/agents/core_agent.py`，C03 负库存后进入 `final_only`，C04 非负库存后读取事件，事件成功后进入 `final_only`。相关原始证据保留在上述时间戳文件，不以摘要替代。

### 下一项最小未完成任务（本轮不实施）

按 V2.2 D12 的动态双路径目标，下一项是一次**同一案件/订单/事件数据的 C03/C04 成对反事实验收**，只改变库存快照数值。验收条件：两场开场案件与履约分析观察完全相同；C03 路径严格为案件→分析→库存，C04 严格为案件→分析→库存→事件；结果均为 `insufficient_evidence`、根因为 `unknown`，引用包含全部实际观察事件 ID；首次错误报告如出现须被契约拒绝并修正；两场均 `rollback_verified=true`，配对比较通过。单场成功不替代此成对验收，也不据此推定 C01/C02/C06/C07/C08 或完整矩阵通过。

## 2026-10-13 D12 C03/C04 成对验收补录

上节所列的最小成对验收已完成：`scripts/day13_evidence_20261013T155810143158Z.json` 与对应 `.jsonl` 记录本次结果。两场复用同一案件、订单与履约事件，仅库存快照不同；总耗时 **9 分 11 秒**，`counterfactual_pair_verified=true`，两场 `rollback_verified=true`。

- C03：`get_exception_case → analyze_fulfillment → get_inventory_status`；最终 `insufficient_evidence`，`root_cause=unknown`。
- C04：`get_exception_case → analyze_fulfillment → get_inventory_status → get_fulfillment_events`；最终 `insufficient_evidence`，`root_cause=unknown`。

两场首次报告均因错误的 `observed_delay` 被证据契约拒绝，随后修正并通过；引用均覆盖实际观察事件 ID。本次成对验收通过只适用于这次运行，**不代表完整矩阵已通过或稳定通过率**。

## D13 C08 PostgreSQL 故障单场 evidence 核对

已有明确的历史单场通过 evidence，因此本轮未重复运行：`scripts/day13_evidence_20261011T124733894433Z.json` 中 C08 的 case ID 为 `2d4e9240-8d30-4ec5-8a10-282e8f7ac27e`，目标是隔离库 `localhost:5433/ragforge_day6_test`，`fault_injected=true`，case 状态为 `passed_expected_failure`。实际工具路径为 `get_exception_case → analyze_fulfillment`；分析读触发的真实 PostgreSQL `DBAPIError` 被 Core Agent 记为 `execution_failed/tool_failed`，随后停止。

模型仅有两次请求：先读案件，再调用履约分析；数据库故障后没有再次请求模型，因此没有把故障误判为 `not_found` 或“无记录”。`rollback_verified=true`。该 JSON 的全局 `passed=false` 是矩阵整体状态，C08 case 本身为预期故障通过。未找到该时间戳对应的 JSONL。此证据属于 2026-10-11 的代码版本；后续共享 Agent 改动后的 C08 未复验，故不声称当前代码版本已通过 C08。

## 2026-10-14 D13 C08 当前代码单次复验

本轮使用当前代码和现有 runner，仅运行一次 `--cases C08`，外层上限 600 秒；实际耗时 **171.891 秒（约 2 分 52 秒）**，进程退出码为 `0`，退出后确认测试进程 PID `50052` 已不存在。沿用隔离库身份保护，目标为 `localhost:5433/ragforge_day6_test`；故障注入仍为读取履约事件时设置事务内 `statement_timeout='20ms'` 并执行 `pg_sleep(0.2)`，未停止数据库或改动业务代码、验收断言。

- 证据：`scripts/day13_evidence_20261014T094616149065Z.json` 及对应 `.jsonl`；仅含 C08，`passed=true`，case 状态为 `passed_expected_failure`，`error_code=tool_failed`，`fault_injected=true`。case ID：`3874fae7-1787-4a71-9c29-8c2351f09ac4`。
- 实际工具路径：`get_exception_case(found) → analyze_fulfillment(execution_failed/tool_failed)`。JSONL 异常链包含 `DBAPIError` 与 `QueryCanceledError`；数据库故障后立即终止，没有继续调查或生成最终报告，未产生“无记录”“库存为0”“履约正常”等结论；无最终 `outcome/root_cause`。
- 模型仅请求两次，耗时依次为 **94.500 秒、72.984 秒**，两次均为原生工具调用且普通文本为空；最后一条 JSONL 为履约分析的 `tool_failed`。
- `rollback_verified=true`，无 setup/cleanup 失败；现有 fixture 已完成事务回滚并断言隔离 schema 不再存在。本次未超时、未中断、未重试，也未运行其他场景。

本条补足上节历史证据无法覆盖后续 Agent 改动的限制：当前代码下 C08 本次复验通过；不代表完整矩阵通过或稳定通过率。

## 2026-10-14 D13 C07 无匹配记录单次验收

对照原 V2.2 计划、当前 runner 与全部现有 day13 evidence，本轮选择 C07：业务无结果，`not_found` 只能解释为没有对应业务记录。仓库内未找到原计划文件，已读取本记录指向的 Downloads 原始 DOCX；D13 原计划覆盖 C01/C06/C07/C08。C07 仅有 2026-10-11 历史通过，C06 仅有 2026-10-12 历史通过，均不能替代后续共享 Agent 改动后的验收；本轮未重跑已完成的 C03/C04 或 C08。

使用现有 `scripts/day13_e2e.py --cases C07`，仅运行一次，外层上限 720 秒，实际耗时 **124.718 秒（约 2 分 5 秒）**。保持隔离库身份校验、原断言、JSONL 和回滚机制，未修改业务代码、提示词、模型配置或验收标准，未重试。

- 证据：`scripts/day13_evidence_20261014T144608932959Z.json` 及对应 `.jsonl`；`passed=true`、case 状态 `passed`，无 Agent 错误码或 failure_type。case ID：`3d4c598f-1b22-41c6-94dc-ede3a5e72fb3`，由 runner 生成且未插入案件表。
- 实际路径：`get_exception_case(not_found)` → 无工具 `final_only` 报告。工具结果的 `error_code=not_found` 是记录不存在的业务语义，不是执行故障；没有继续分析、查库存或查事件。最终 `outcome=not_found`、`root_cause=unknown`、`evidence_event_ids=[]`，首次报告即通过证据契约，`rejected_finals=[]`；未把无记录解释为履约正常。
- 两次模型请求耗时依次为 **95.641 秒、25.141 秒**；第 2 次 `offered_tools=[]`。目标为 `localhost:5433/ragforge_day6_test`，`rollback_verified=true`，无 setup/cleanup 失败；fixture 已回滚并验证隔离 schema 消失。进程退出码 `0`，退出后确认 PID `46544` 已不存在。

下一项最小任务（本轮不执行）：仅复验当前代码下 C06。其现有样例为案件存在、没有履约事件且无显式 SKU；原断言要求路径严格为 `get_exception_case → analyze_fulfillment`，最终 `insufficient_evidence / unknown`，不额外查询事件或编造根因，并验证回滚与进程退出。C01/C02 仍仅有历史通过证据。当前各单次结果不代表完整矩阵通过或稳定通过率；本人学习仍未确认，不标 PASS。

## 2026-10-14 D13 C06 无履约事件单次复验

本轮完成上节 C06 待办：沿用现有 `scripts/day13_e2e.py --cases C06`，仅运行一次，外层上限 720 秒，实际耗时 **241.265 秒（约 4 分 1 秒）**。样例插入案件但不插入履约事件；保留隔离库保护、原验收断言、证据契约及 JSONL/回滚机制，未修改业务代码、提示词、模型配置或验收标准，未重跑整场或执行其他场景。

- 证据：`scripts/day13_evidence_20261014T145330173273Z.json` 及对应 `.jsonl`；`passed=true`、case 状态 `passed`，无最终 Agent 错误码或 failure_type。case ID：`b1676b6c-3006-4289-b681-80765a4977ab`。
- 实际路径：`get_exception_case(found) → analyze_fulfillment(found) → final_only`。分析的事件引用为空，shipment/delivery 均为 `unknown / missing_promise`，实际时间为空；没有额外库存或事件读取。第 3、4 次模型请求均 `offered_tools=[]`。
- 首次报告的 outcome/root_cause 正确，但编造了两个以订单 ID 拼接 `-shipment-1` / `-delivery-1` 的非法引用，在报告校验阶段被 `invalid_evidence_report` 拒绝；第 4 次请求利用原有一次修正机会提交空引用后通过。最终为 `{"outcome":"insufficient_evidence","evidence_event_ids":[],"root_cause":"unknown"}`。因此本次是纠错后通过，不能表述为模型从未编造引用；最终报告未把无事件记录解释为履约正常或实际未发货。
- 四次模型请求耗时依次为 **88.890、71.188、68.031、9.109 秒**。目标为 `localhost:5433/ragforge_day6_test`；`rollback_verified=true`，无 setup/cleanup 失败，fixture 已回滚并验证隔离 schema 消失。进程退出码 `0`，退出后确认 PID `40680` 已不存在；未超时或强制中断。

下一项最小任务（本轮不执行）：当前代码下仅复验 C01 的停止路径；现有样例包含可比较的发货与送达记录，原断言要求案件→分析后结束、`no_observed_delay / unknown`，引用实际观察事件并验证回滚。这仅表示两个时间指标未观察到延迟，不证明整单履约正常或完成。C01/C02 仍仅有历史版本通过；不宣称完整矩阵或稳定通过率，本人学习仍未确认，不标 PASS。

## 2026-10-14 D13 C01 停止路径单次复验（失败）

仅运行现有 `scripts/day13_e2e.py --cases C01` 一次，外层上限 720 秒，实际耗时 **289.734 秒（约 4 分 50 秒）**。保留原断言、证据契约、隔离测试库身份校验、JSONL 和回滚；未修改业务代码、提示词、模型配置或验收标准，未自动重跑或执行其他场景。

- 证据：`scripts/day13_evidence_20261014T151832279043Z.json` 及对应 `.jsonl`。`passed=false`、case 状态 `failed`、`failure_type=CoreAgentError`、`error_code=scope_violation`；消息为 `SKU must be present as SKU= in observed records`。case ID：`4deb2046-e0e2-4a4c-921c-96f56df614b9`。
- 实际已执行工具：`get_exception_case(found) → analyze_fulfillment(found)`。发货、送达比较均为 `on_time`，时间差分别为 -3600、-1800 秒，分析保留四个真实事件 ID，整单完成状态仍为 `unknown`。
- 第 3 次模型请求仍处于调查阶段，提供案件、分析、库存及 `finish_investigation`；模型未选择结束，而是请求 `get_inventory_status({"sku":"SHIP-A"})`。`SHIP-A` 是已观察到的 tracking_number，并非描述中显式 `SKU=` 来源。Core Agent 在执行前拒绝该请求，库存 Service/查询未执行；虽然没有新增数据库读取，本次未成功完成预期的停止与报告流程。
- 失败定位为**模型调查决策及执行前作用域校验**，不是工具执行故障、报告校验失败或已证实的运行环境故障。没有首次或最终报告，无最终 outcome/root_cause，也未完成报告引用校验；`rejected_finals=[]`，没有报告拒绝或修正。不能把原断言预期的 `no_observed_delay / unknown` 写成本次最终输出。
- 三次模型请求耗时（最终 JSON）为 **87.485、73.359、125.453 秒**；第 2 次 JSONL 返回事件计时为 73.343 秒，与 finally 记录的总耗时略有差异。`rollback_verified=true`，无 setup/cleanup 失败；目标为 `localhost:5433/ragforge_day6_test`，fixture 已回滚并验证隔离 schema 消失。进程退出码 `1`，确认 PID `42652` 已不存在；未超时或强制中断。

下一项最小任务（本轮不实施）：基于本次 evidence 离线回放 C01 的“两个比较 on_time、无显式 SKU，仍请求库存”响应，核对调查停止边界与现有范围校验，形成最小修复候选及针对性验收条件；不先重跑真实模型或放宽原断言。C01 当前版本验收失败，C02 仍仅有历史通过；不宣称完整矩阵通过，本人学习不标 PASS。

## 2026-10-15 C01 scope_violation 离线定位（未实施修复）

只读核对 `scripts/day13_evidence_20261014T151832279043Z.json` 第 3 次请求、对应 JSONL、当前 Core Agent/Tool 和验收断言；未新建或运行测试，未调用模型或连接 PG。

- 实际请求记录：案件问题为 `Investigate shipment timing. Cause unconfirmed.`，承诺备注仅为 `Shipment promise recorded.` / `Shipment fact`，无 reservation/backorder 或显式 `SKU=` 线索。分析顶层 scope 为 order，但 shipment/delivery 比较范围均为 shipment、均 on_time，whole_order_completion=unknown；`SHIP-A` 来自两项比较的 tracking_number。可选工具为案件、分析、库存、finish，无事件工具；system 已明确两项 on_time 时停止、不需库存/事件、不得编造 SKU，无进一步支持的读取则调用 finish。末尾消息保留已完成读取、inventory=null 和停止提示。证据保存了消息/system/工具名称，未保存完整工具 schema 或 Provider 最终网络请求；当前 Tool 描述及 schema 只能作为代码核对，不能冒充当次完整请求快照。
- 当前 `_observed_skus` 仅从成功结果中的案件描述、分析 promise_notes 或事件描述提取显式 SKU 标记；本次来源集合应为空。库存 schema 只校验字符串格式，`SHIP-A` 通过格式校验后在 `core_agent.py:322` 被来源校验以 scope_violation 拒绝，尚未到 `selected.ainvoke`；trace/JSONL 也只有案件和分析的实际工具结果，库存 Tool/Service 未执行。本次确实存在“提供库存工具但无合法 SKU 来源”的状态，但这不足以证明工具可见是失败的唯一原因，或隐藏后一定通过。
- 最小候选属于**工具可选范围**：仅在调查阶段、履约分析已成功且 `_observed_skus(trace)` 为空时，从 offered_tools 移除 get_inventory_status；不自动结束、不自动生成结论、不硬编码场景/标识，保留执行前 SKU 来源、重复调用、预算及报告证据校验。离线边界应覆盖无 SKU 的实际工具列表、跟踪号/错误字段/失败结果不能提供来源、仍伪造调用时 Service 不执行、合法显式 SKU 可选及范围校验、C03/C04 库存正负分支和原报告校验不变。此候选也会隐藏其他已分析但无合法 SKU 的调查库存入口；C03/C04 已有显式 SKU，按规则不应受影响，仍须离线回归确认。它不保证模型一定选择 finish，也不代表两项 on_time 可证明整单正常或所有调查完成。本轮仅提出候选，未实施、未验证；本人学习不标 PASS。

## 2026-10-15 库存工具可选范围最小修复（仅离线验证）

按后续授权实施上述候选：`backend/app/ai/agents/core_agent.py` 仅增加两行过滤，在非 final_only、履约分析成功且现有 `_observed_skus(trace)` 为空时，不向本轮模型请求提供 get_inventory_status。复用原来源规则，保留执行前 scope_violation、重复调用与报告证据校验；不改变 finish 条件、不自动进入报告、不生成结论，不修改真实场景验收断言或其他阶段工具列表。

`backend/tests/unit/test_core_agent_boundaries.py` 新增两项测试：参数化检查无 SKU、仅 tracking_number、案件描述显式 SKU、承诺备注显式 SKU 的实际请求列表，同时验证分析前及报告阶段工具列表、finish 流程未变；另一项验证模型仍提交隐藏的非法库存调用时，scope_violation 在库存 Tool/Service 执行前生效。复用已有负库存停止、非负库存后事件查询、输入/失败语义、重复调用和报告契约测试，未重复增加同义双路径测试。

验证：仅运行 `tests.unit.test_core_agent` 与 `tests.unit.test_core_agent_boundaries`，**48 tests / 0.682s / OK**；两个修改 Python 文件 Ruff 全通过。额度恢复后核对代码和测试内容与该验证版本一致，未重复运行。三个修改文件均相对本轮改前副本检查 diff，无空白错误（文件原为未跟踪，另作 no-index 检查）；交接记录已读回。未调用 Ollama、连接 PG、运行 C01 或完整矩阵，未安装依赖。此次仅证明离线边界符合预期，不能宣称 C01 真实验收通过，也不保证模型下一次会正确结束；库存双路径的真实模型行为亦未重验。下一项最小任务是获得单独授权后仅复验 C01，保持原断言；本人学习不标 PASS。

## 2026-10-15 C01 库存工具过滤修复后单次真实验收

已先确认当前代码包含“调查阶段、分析成功且无合法 SKU 来源时隐藏库存工具”的两行修复，再仅运行现有 `scripts/day13_e2e.py --cases C01` 一次；外层上限 720 秒，实际耗时 **489.594 秒（约 8 分 10 秒）**，未超时或重跑。保留原断言、模型配置、提示词、隔离库保护、JSONL 和回滚机制；未修改业务代码、未运行其他场景，也未重复离线测试。

- 证据：`scripts/day13_evidence_20261015T051730341912Z.json` 及对应 `.jsonl`。`passed=true`、case 状态 `passed`，无最终 Agent 错误码或 failure_type；case ID：`e8da4c44-4f22-46d2-8805-9f78be42ba2a`。
- 过滤实际生效：案件描述和分析承诺备注没有显式 SKU；分析成功后的第 3、4 次请求仅提供 `get_exception_case`、`analyze_fulfillment`、`finish_investigation`，均无库存工具。第 3 次响应仍输出普通文本形式的 get_fulfillment_events 伪调用（tool_calls 为空），未执行查询，被记为调查阶段 `invalid_evidence_report`；第 4 次纠正为原生 finish_investigation。实际数据库工具路径严格为 `get_exception_case → analyze_fulfillment`，无库存/事件实际读取、无重复查询或 repeated_call。
- 第 5、6 次请求均为无工具报告。首次报告错误选择 `observed_delay` 且只引用一个事件，被报告阶段 `invalid_evidence_report` 拒绝；第 6 次在原有一次报告修正机会内改为 `no_observed_delay / unknown`，完整引用分析观察的四个真实事件 ID，通过原证据契约及验收断言。两次拒绝分别属于调查阶段和报告阶段，不能表述为首次响应或首次报告正确。最终仅表示发货/送达两个可比较时间指标未观察到延迟，整单完成仍为 unknown，不证明整单履约正常。
- 六次模型请求耗时（最终 JSON）依次为 **93.359、74.812、128.313、51.688、98.640、38.422 秒**。目标 `localhost:5433/ragforge_day6_test`，`rollback_verified=true`，无 setup/cleanup 失败；fixture 已完成事务回滚并断言隔离 schema 消失。测试进程退出码 `0`，退出后确认 PID `20616` 已不存在。

本条补充当前修复后的 C01 单次通过证据，保留此前失败记录；不代表完整矩阵通过或稳定通过率，也未复验其他路径。本人学习不标 PASS。

## 2026-10-15 产品方向与实施约束

本节按用户最新指示更新后续优先级；原 V2.2 计划从本记录已注明的 `C:\Users\xingk\Downloads\Project_A_V2.2_30天施工与学习计划.docx` 读取，仓库内未找到原文件。保留原计划的工程与求职证据目标、安全要求和未完成验收，不将产品方向调整视为已有功能完成。

1. Project A 继续定位为**订单履约异常调查与受控处置 Agent**，帮助员工集中查询、整理证据、完成调查交接；不扩大成整家企业的 AI 转型平台。
2. 当前业务场景仍是待真实用户验证的假设；不宣称已有客户、上线收益或节省人力比例。
3. 优先将已有调查结果整理成员工可用的交接单：**已确认事实、证据及观察时间、不能确认的事项、缺少的资料、具体下一步建议、处理状态**。工程 trace 不等于员工可用的成品交接单。
4. “进一步核实”必须绑定具体证据缺口，说明需要补什么、用于核实什么；建议不等于执行。通知、分派、暂停恢复尚未接通时，不得写“已安排人员”“已通知”或“系统会自动继续”。未知根因本身不能成为无限读取理由；缺记录不能当作业务未发生。
5. 后续再考虑一种固定格式的数据导入，先复用已有模型、Service 和权限能力；文档上传不等于订单/履约事实导入，不新增完整 ERP、仓库或商品管理系统。
6. 后续评测关注合格交接单完成时间、事实遗漏、引用正确性、无依据归因、人工修改量。先定义合格标准和测量方法，只有实测后才能填写结果；已有 runner 耗时不能直接当作员工完成交接单的时间或人力节省。
7. 保留原计划的服务端企业范围与权限校验、证据契约、HITL、Write Gate、幂等和审计要求；每轮只布置一个可完成的小任务。施工、实际验收和本人学习分别记录，不用代码通过代替学习 PASS。

### 定向核对后的能力状态

本次仅查报告/Agent、异常案件模型与只读 Service、已注册 API、聊天及文档上传入口和对应 UI；“已实现”表示有代码或已有指定证据，不表示本轮做过运行验证。

| 交接单所需能力 | 当前状态 | 依据与缺口 |
| --- | --- | --- |
| 时间比较事实、严格 outcome/事件引用/未知根因校验 | 已实现（后端核心） | `backend/app/ai/agents/investigation_report.py` 的 evidence_contract/validate_report/render_report；CoreAgentResult 保留 report、answer、trace、原始与被拒响应。 |
| 证据和观察时间的员工可读呈现 | 部分实现 | 原输出包含事件 ID、expected_at/actual_at、库存 observed_at；trace 有分析 as_of。尚未统一呈现观察截止、快照时间与业务事件时间，不能互相冒充。 |
| 已确认与不能确认事项分开呈现 | 部分实现 | 有 unknown、comparison reason、整单完成未知和库存非订单缺货证明等边界；缺少统一中文交接栏目。 |
| 缺失资料及逐项对应的下一步建议 | 未实现（交接单层） | reason/null 等可作为整理依据，但当前报告无结构化资料缺口与建议映射；不能用通用“进一步核实”冒充。 |
| 处理状态 | 部分实现 | ExceptionCase 有 open/investigating/closed；当前 Service 仅读取，报告未展示完整处理状态。没有据此完成分派、关闭或更新的流程，调查停止不等于案件关闭。 |
| 人工补充证据、编辑交接单并继续同一 Core 调查 | 未实现（已核对的 Core 链路） | run_core_agent 入口为 case_id/as_of，单次运行；无补充证据/恢复接口。Customer Agent 的 history 和 RAG 聊天追加消息不等于 Core 证据补充及状态恢复。 |
| 员工可访问的 Core API/UI | API 已实现（仅离线验证），UI 未实现 | 2026-10-15 已注册只读调查 API，详情见文末；conversations → chat_service → run_retrieval 仍为文档 RAG。`frontend/src/components/chat/chat-view.tsx`、`use-chat.ts` 尚未接 Core 业务事件/交接单。 |
| 通知、分派、暂停恢复与受控处置 | 未实现（本次核对的 Core 流程） | 当前四个业务 Tool 均只读；finish_investigation 是协议控制，不是任务分派或审批。原计划 ActionRequest/HITL 要求保留待验收，不能用已有聊天权限代替。 |
| 固定格式履约数据导入 | 未实现 | 已有文档上传 API/界面服务于 RAG 入库，不是业务事实导入。此项后置，不在下一任务中开发。 |

### 已有证据与验收阻塞边界

`scripts/day13_evidence_20261015T051730341912Z.json`（及对应 JSONL）确认修复后 **C01 单次纠错后通过**：案件→分析→finish→报告；调查阶段一次文本伪调用被拒，报告阶段首次 observed_delay 且缺引用被拒，最终 no_observed_delay / unknown、四个引用通过，rollback_verified=true。它不证明整单正常、完整矩阵通过或稳定性；本轮只读取，不重跑。

C02 仍只有历史版本通过；C03/C04 成对及 C06/C07/C08 的已通过运行保留各自代码时点，不能自动升级为最新共享修改后的全矩阵通过。原计划 C05、C09–C12 及后续 Core RAG/权限/受控写入、统一评测、Docker/UI 验收仍未完整交付或验证。本次方向调整允许先做已有只读结果的呈现整理，不以“缺完整矩阵”阻塞这一独立小任务；但不得关闭未完成施工单元、宣称可上线或提前开放受控写入。涉及 API/人工证据写入/处置时，权限与租户隔离、证据来源、确认及审计等相应验收是启用前置条件。

### 下一项唯一最小施工任务（本轮不实施）

**将现有已校验报告和 trace 渲染为六部分中文只读交接单。** 属于现有报告输出整理，不增加模型字段、Tool、API、页面、数据库写入或暂停恢复流程；复用原证据契约，保持调查决策及原验收断言不变。

文件范围限定为 `backend/app/ai/agents/investigation_report.py` 的报告呈现、`backend/tests/unit/test_core_agent_boundaries.py` 的现有 ReportTests，以及本交接记录。验收条件：

- 六部分均可辨认；事实和引用来自已成功读取且校验通过的证据，保留原 outcome/root_cause、真实事件 ID 与已有比较数值，来源描述不升级为已确认因果。
- 分开标明 as_of（观察截止）、observed_at（库存快照）与业务时间；未提供的时间明确缺失，不补造“观察于”时间。不能确认的事项保留 unknown，缺记录不等于未发货，no_observed_delay 不等于整单正常。
- 每条建议绑定 trace 中可识别的具体缺口及所需资料，例如缺承诺时间则建议补充对应承诺记录以便比较；不能推断可执行建议时明确“尚无有依据的具体建议”。建议标为待人工核实/未执行，不编造接收人或自动续查承诺；无相应缺口不强造任务。
- 处理状态仅展示案件已读取状态（缺失则注明不可得），另说明本次只读调查输出状态；不声称案件已关闭、交接已送达或已分派。
- 用已有保存结果/离线 fixture 验证有比较事实、证据不足、记录不存在及库存快照等输出边界，并保留原引用/结论拒绝测试；仅相关离线测试、Ruff 和 diff 检查，不重跑已通过真实场景。该任务完成仍不等于 API/UI、人工继续调查或产品效果验收完成。

本轮仅更新文档并读回；未修改业务代码，未运行模型、测试或迁移，未访问数据库。本人学习状态未确认，不标 PASS。

## 2026-10-15 六部分中文只读调查交接单（已实现，离线验证）

按后续授权实施上述唯一任务，仅修改 `backend/app/ai/agents/investigation_report.py`、现有 `backend/tests/unit/test_core_agent_boundaries.py` 的 ReportTests 和本记录，保留全部既有改动。

- `render_report` 将已经过校验的 report/trace 确定性整理为：已确认事实、证据引用及观察时间、不能确认的事项、缺少的资料、逐项对应建议、处理状态。EvidenceReport、evidence_contract、validate_report 未改；未新增模型请求、Tool、API/UI、数据库写入、审批或恢复流程。
- 保留 outcome/root_cause、实际事件 ID 和原比较数值；区分 as_of 观察截止、observed_at 库存快照时间、occurred_at 事件发生时间以及 expected_at/actual_at 业务比较时间。原始字段 null 与中文“未提供”均不表示业务没有发生；跟踪号不转为 SKU，负库存仍只表示组织/SKU 快照差额，不能推断本订单缺货或原因。来源描述独立标为未核实的来源陈述。
- 仅对本次观察的具体字段缺口/无匹配记录/无效输入生成保守建议，用 G 编号与缺口一一对应并标注“建议，尚未执行”；没有具体缺口时不创建任务。只转述案件记录状态，明确未变更、不代表案件关闭或交接送达，本次未通知、未分派、未处置、不会自动继续。
- 新增 5 项 ReportTests，读取已有 C01、C06、C03、C07 保存证据并使用固定离线 trace，覆盖完整时间比较、无事件、库存负差额、无匹配案件、缺失时间/SKU 和来源陈述；校验六分区、缺口建议编号配对、report/trace 不被改写，并用互不相同的三类时间验证不混用。原有伪造/缺失/重复引用、错误根因/结论拒绝断言和库存双路径边界全部保留。
- 最终仅运行 `tests.unit.test_core_agent` 和 `tests.unit.test_core_agent_boundaries`：**53 tests / 1.028s / OK**；两个修改 Python 文件 Ruff 全通过。保存证据仅作为离线固定数据读取，不代表本轮重新通过真实场景。固定 not_found trace 已实际调用纯渲染函数生成“测试样例”；不是客户案例或线上效果数据。

限制：当前完成的是后端只读文本呈现，不是可操作的员工 API/UI；没有人工补充/编辑/继续调查、通知分派、受控写入或自动续查。建议仅覆盖已明确的缺口，不扩展成通用诊断/SOP 系统。未调用 Ollama、未连接数据库、未运行真实矩阵或迁移、未安装依赖；C01 等历史单场证据及原计划待验收项保持各自状态，不宣称完整矩阵或稳定性通过。本人学习不标 PASS。

## 2026-10-15 Core 只读调查 API（HTTP 边界离线验证）

已落盘并核对 `POST /api/v1/organizations/{organization_id}/investigations`。请求正文只接受 `case_id` 和可选的带时区 `as_of`；缺省时间由服务端生成 UTC 时间，显式时间归一到 UTC。成功响应仅含 `request_id`、`organization_id`、`case_id`、`as_of`、已校验的结构化 `report` 和六部分中文 `handoff`，不返回 trace、模型原文、Prompt 或内部异常详情。仍调用现有 Provider 工厂及 `run_core_agent`，没有第二套 Agent、模型配置、业务写入或 UI。

身份链：现有 Bearer access token → `get_current_user` 验证 token 类型及活动用户 → `organization_service.require_role` 以当前用户 ID 和路径企业 ID 查询成员记录并要求至少 MEMBER → 将**成员记录中的** `organization_id` 传给 Core Agent。正文不允许 `organization_id`，token/请求头自称的企业 ID 不取代成员关系。案件无匹配与证据不足沿用已校验报告的 `not_found` / `insufficient_evidence`；Agent 工具或模型故障返回保留错误码的 502，公共消息统一脱敏；成员查询数据库故障由现有全局处理器返回通用 500，不伪装成业务无记录。

仅为本次实现修正 `backend/tests/unit/test_investigation_api.py` 的离线成员查询替身：直接检查 SQLAlchemy 查询条件，不编译需要完整模型映射的 ORM 语句；补充成员查询故障测试。未因测试失败改动业务接口。实际运行该文件及直接相关的 `test_core_agent`、`test_core_agent_boundaries`，**63 tests / 0 failures / 0 errors / 0 skipped**；四个本次 API Python 文件 Ruff 全通过。测试使用真实路由、认证和角色校验代码，但模拟用户查询、成员查询、Provider、Agent 与数据库会话；未连接真实数据库或模型，未执行迁移或完整矩阵。因此实际数据库成员隔离、真实 Provider/Core 串接和部署入口尚需后续隔离环境验收，不能宣称线上可用或稳定通过。施工验证已完成，本人学习不标 PASS。

## 2026-10-15 V2.3 计划接续

已读取用户提供的 `C:\Users\xingk\Downloads\PROJECT_A_PLAN_V2_3.md`，作为后续施工与学习计划；V2.2 和历史施工证据保留。V2.3 将 D 编号保留为任务索引，不再对应自然日；施工与本人掌握程度分别记录，每轮一个明确交付。四个三天周期依次聚焦只读调查入口、企业 SOP 检索、人工审核后的受控处置、统一评测与部署展示。日期是目标窗口，不表示验收已完成；C04 的非负库存不能证明订单没有库存问题，C01 的 on_time 比较不能证明整单正常。

**下一项唯一最小施工任务**：先核查是否已有“真实 JWT 用户及企业成员记录 → HTTP 调查 API → 隔离 PostgreSQL”的现行证据；若缺失，仅补该集成验证，模型使用受控替身。验收未登录、无成员或错误企业不进入 Agent，合法成员仅能读取本企业案件，成员查询故障不返回成功或 not_found；复用既有隔离库身份保护、随机 schema 和回滚。现有 63 项离线测试使用模拟成员查询，不能代替这项验收。本次只同步计划与缺口，未运行该任务、未访问数据库或模型，亦未启动 UI 或其他周期施工；本人学习不标 PASS。

## 2026-10-15 V2.3 周期一：真实 JWT／成员关系／隔离 PG 的调查 API 验证

本轮核对后确认此前只有模拟成员查询的 HTTP 单元测试，无等价真实 PostgreSQL 证据。新增 `backend/tests/commerce/test_investigation_api_postgres.py`，沿用 Day6 测试入口：连接前 URL 必须指向 `postgresql+asyncpg` 的 `ragforge_day6_test`，连接后再检查 `current_database()`；随机私有 schema、事务内建表和数据，退出时回滚并断言 schema 不存在。未加载会创建/删除业务表的全局 pytest fixture，未执行业务库迁移。

测试在隔离 schema 中真实插入用户、两个企业、仅属其中一个企业的成员记录、两企业各一条案件；实际调用 `/auth/login`，由现有认证 Service 核验密码、签发 JWT，调查 API 用真实 JWT 解析、用户读取、成员 SQL 查询及角色检查。受控 Agent 替身仅记录入参，并用真实 `get_exception_case` 只读 Service 核对案件企业范围，返回固定且经过证据契约校验的报告；Provider 工厂被替身取代，未调用 Ollama、完整 Core Loop 或其 Tool 链。

验证结果：未登录 `401`、Agent 未执行；登录后把 URL 改为非成员企业（分别带本企业和目标企业案件 ID）均 `403`、Agent 未执行；合法企业与案件 `200`，Agent 收到从真实成员记录核准的企业 ID；本企业路径请求另一个企业真实存在的案件仅得到 `not_found` 报告，未读到异企业案件。成员查询处注入真实 PostgreSQL 除零错误，HTTP 返回通用 `500/internal_error`，无业务报告，Agent 调用次数不增加。数据库故障注入只覆盖成员查询执行边界，不能代表所有数据库故障。测试结束后 Day6 fixture 的回滚及 schema 消失断言通过；进程正常退出。

最终仅运行新增集成测试及直接相关的 `test_investigation_api` 离线回归：**11 tests / 0 failures / 0 errors / 0 skipped**；相关 API 与测试 Python 文件 Ruff 全通过。先前一次测试发现范围顺带执行 Day6 的 6 项现有测试，均通过，随后已收窄到上述 11 项；没有运行完整矩阵。当前证据支持真实 JWT/用户/成员关系与 HTTP 授权边界，不支持宣称真实模型、Agent/Tool 全链路或生产部署通过。下一项最小任务：定向核对现有前端登录和企业选择后，只补一个调用此 API、展示六部分交接单的只读页面；暂不接人工补充或处置。本人学习不标 PASS。

## 2026-10-15 V2.3 周期一：最小只读调查页面

定向核对后复用已有 dashboard 登录门槛、`useWorkspaceStore.organizationId` 当前企业、`useOrganizations` 成员企业列表、`apiFetch` 和 Card/Input/Button 样式。新增 `/investigations` 页面及侧栏入口：输入案件 UUID、可选本地分析时点（提交为带时区 UTC），只向当前可用企业的调查 API 发起 POST；显示等待状态、请求标识及后端六部分中文交接单。`not_found` 作为成功返回的业务结果单独提示；401、403、422、5xx 和网络错误用固定安全文案区分，不展示 trace、Prompt 或内部异常。等待时禁用输入与按钮，并由请求控制器挡住再次提交；该请求关闭 `apiFetch` 的 401 自动重放，其他 API 保持原有刷新行为。不增加业务写入、审核或人工继续调查。

修改/新增范围：`frontend/src/app/(dashboard)/investigations/page.tsx`、`frontend/src/components/layout/sidebar.tsx`、`frontend/src/lib/api/client.ts`、`frontend/src/lib/api/investigations.ts` 与固定响应测试 `frontend/src/lib/api/investigations.test.ts`。测试覆盖请求路径/正文、等待与重复提交、成功及业务 not_found、401/403/422/502/网络错误分类与脱敏。最初因无 `node_modules`，测试/类型/构建命令均找不到可执行文件；随后仅用现有 `package-lock.json` 安装既定依赖，未改依赖声明或锁文件。第一次 `npm ci` 因全局 npm 缓存写入被系统拒绝；改用临时缓存目录后 `npm ci` 成功。

验证：`npm run typecheck` **退出码 0**；`npm run build` **退出码 0**，构建路由包含 `/investigations`；修改文件 ESLint **退出码 0**。Vitest 因当前 Node 20.14.0 环境缺少锁文件中已有的 `@rolldown/binding-win32-x64-msvc` 原生绑定而启动失败，尝试补装该锁定版本又遭 npm 自身 `edgesOut` 错误；**Vitest 测试文件仍未执行，不能标记其通过**。另用已安装的 TypeScript 编译器转译同一请求模块、固定响应替身执行了独立 Node 检查，覆盖一次 POST、等待/重复提交、成功、业务 not_found、401/403/422/502/网络错误和内部文案不泄露，退出码 0。人工核对页面/API 数据契约，空白字符检查通过；没有浏览器实测或真实模型调用。

下一项最小任务：在支持锁定版 Vitest 的 Node 环境中恢复其原生绑定并运行已写的固定响应测试，再核对页面实际交互；通过前不把前端页面标记为完整验收。本人学习不标 PASS。

## 2026-10-15 /investigations 实际浏览器交互验收（固定 API 响应）

复用已安装 Chrome 及 Next 自带的 WebSocket 组件，通过浏览器调试协议打开现有生产构建 `/investigations`；仅为本轮启动 `127.0.0.1:3107` 前端进程与独立临时浏览器会话。新增可复查脚本 `scripts/investigations_browser_verify.cjs`，在浏览器层拦截所有 API 请求，企业列表、登录态与调查结果均为固定样例。未调用真实后端、数据库或 Ollama，未改页面、Node、依赖声明或锁文件。

- **7 项浏览器断言全部通过，8 次调查 POST 均使用固定响应**。当前选择为列表第二个企业 B，URL 企业 ID 正确；案件 ID 去除首尾空白后提交。浏览器时区固定 Asia/Shanghai，输入 `2026-10-15 20:00` 实际提交 `2026-10-15T12:00:00.000Z`；留空时正文不含 `as_of`。
- 首次点击后等待文案显示、按钮禁用；再连续点击四次，总计只发出一次请求。成功后请求标识显示正确，六部分交接单的 DOM 文本与固定响应逐字一致，并保存全页截图核对。
- 每个错误分支前先展示一份成功报告；后续 `not_found`、403、500 和网络连接失败均显示各自信息，旧请求标识/报告均消失。等待期间也不保留旧报告，403/500 响应中的内部错误样例未展示，未出现自动重试。

证据：`scripts/investigations_browser_2026-10-15T13-20-19-454Z/evidence.json`，包含请求正文、断言、源码哈希、构建 ID、浏览器版本和清理结果；同目录保存 `pending.png`、`success.png`、`not-found.png`、`403.png`、`500.png`、`network.png`。浏览器脚本退出码 0，浏览器正常退出；验收结束后停止本轮前端进程，确认 3107 无监听、浏览器 PID 不存在、临时 profile 已删除，原有 3000 服务未操作。脚本语法及 diff 空白检查通过。

本次完成指定的浏览器交互验收；固定响应不代表真实认证或 Agent/Tool/Service/模型 E2E 通过，亦不替代此前尚未执行的 Vitest 测试文件。下一项仍是单独解决现有 Vitest 环境并运行既有测试，本轮不扩展环境修复。本人学习不标 PASS。

## 2026-10-16 交接：真实调查 API＋C03 单次验收（10 月 15 日运行）

原运行已于 2026-10-15 21:44:53（北京时间）完成，额度恢复后读取原 JSON、JSONL、stdout 并确认进程退出；**没有重跑模型或拼接上下文续跑**。新增的最小入口为 `scripts/investigation_api_c03_once.py`：复用 Day6/Day8 的 `ragforge_day6_test` 双重身份保护、随机 schema、事务回滚，以及 day13 的 C03 样例与原路径/结论/引用/库存断言。ASGI 客户端调用真实登录及调查路由；JWT 解析、用户读取、成员角色校验、Core、Ollama、Tool、Service 和业务 SQL 均使用真实实现，仅将 `get_db` 绑定到隔离事务。未改业务代码、Prompt、模型参数或原验收标准。

- **单次通过：`passed=true`，HTTP `200`，`error_code=null`**。请求标识为 `da61dd58-d14a-4774-bef8-1fa8278ec740`，响应正文与响应头一致；Agent 企业 ID 与真实查验后的成员记录一致。实际执行路径严格为 `get_exception_case(found) → analyze_fulfillment(found) → get_inventory_status(found)`，没有执行事件查询、重复读取或提前 finish。
- 第 3 次模型响应是普通文本伪事件调用，调查阶段以 `invalid_evidence_report` 拒绝，未执行工具；既有纠错后第 4 次正确读取库存。快照可用数量 `-3`，观察时间为 `2026-10-09T12:00:00+00:00`。第 5 次立即进入 `offered_tools=[]` 的报告阶段，但首次报告误报 `observed_delay`，再次被证据契约拒绝；第 6 次仍无工具，修正为 **`insufficient_evidence / unknown`** 后通过。两次拒绝分别属于调查与报告阶段，不能描述为首次输出即正确。
- API 返回已校验结构化报告及完整六部分中文交接单，与 Core 返回一致。引用为 `b847f1d3-c0c0-4dbc-9128-633552a1ddb1`、`b9a731df-7156-4952-b0b4-2ce85526e2dc`；交接单明确负库存仅为组织/SKU 快照差额，不能证明本订单缺货、预留情况或异常根因，建议尚未执行。
- **6 次模型请求**分别耗时 `94.625 / 73.641 / 114.187 / 51.328 / 90.562 / 23.297` 秒；API 请求 `447.859` 秒，含启动及清理总计 **`453.984` 秒（约 7 分 34 秒）**。调查请求限时 600 秒，子进程外层 690 秒并预留清理时间；未超时、无外层重试。
- `rollback_verified=true`；原退出后检查确认 schema 与数据库会话均消失，子进程及外层命令退出码均为 `0`。10 月 16 日再次只读检查同一测试库：`day6_test_f27587507ff34bd787e07afeb94b2687` 不存在、原 PG PID `950142` 不存在；测试父子进程无残留。证据中的源码哈希与当前文件一致。

主证据：`scripts/investigation_api_c03_20261015T133719531091Z.json`；同名 `.jsonl` 为逐次记录，`.log` 为 stdout/stderr；恢复后的只读清理复核为 `scripts/investigation_api_c03_20261015T133719531091Z_cleanup_recheck.json`。旁路 profiler 记录原函数，不替换调用；其中 `requests[].offered_tools` 是实际 Provider 入参，`observed_tools` 是采样缓存，可能落后一轮，不能当成完整请求消息。实际执行顺序以最终 Core trace、原生工具响应及实际工具列表联合核对。

新增包装的 Ruff、语法及 diff 检查通过；本次恢复只收取原结果、核查残留并补文档，未运行其他场景或测试矩阵。这是隔离环境下真实 API 模型链路的 C03 **单次纠错后通过**，不代表完整矩阵、稳定通过率、浏览器真实模型联调或生产部署通过；本人学习不标 PASS。本轮到此停止，既有其他待办不自动启动。

## 2026-10-16 V2.3：独立只读 search_knowledge Tool

新增 `backend/app/ai/tools/knowledge_tool.py`，复用 `run_retrieval` 的混合检索、RRF、SQL 来源回填及现有重排 Provider；空历史跳过 LLM 问题改写，不生成答案或写入业务数据。模型参数仅为 `query`，去除首尾空白后不得为空，`extra="forbid"` 拒绝企业、用户、工作区、文档范围等额外参数。`create_search_knowledge_tool(db, organization_id=..., user_id=..., workspace_id=...)` 由服务端绑定单个工作区；调用方负责提供真实登录用户，不得从模型参数构造授权上下文。

实际权限边界：每次调用先用既有 Service 检查企业成员角色至少 member，再核对工作区属于该企业、用户在该工作区至少 viewer。当前文档 API 以工作区 viewer 权限读取文档，文档模型没有独立逐文档 ACL；本 Tool 沿用这一粒度，不把企业成员关系当成全企业文档授权，不新增权限体系。共享检索节点 `backend/app/ai/graph/nodes.py` 仅补两项回填过滤：chunk 和 document 的 workspace_id 均必须匹配当前工作区，避免索引返回越界或归属不一致 ID 后把文本送入重排。该过滤也适用于原聊天检索，原有合法工作区内的排序和来源字段不变。

返回 `found / no_matches / permission_denied`，来源保留真实 `chunk_id、document_id、document_filename、content、page_number、relevance_score`，白名单序列化，不添加不存在的标题、页码、时间或业务结论。未知页码保持 null。Tool 描述明确只查 SOP/处理规则，实时订单和库存继续使用业务 Tool，片段为不可信参考资料，不是已确认业务事实或待执行指令。输入错误沿用 Pydantic ValidationError，在执行前拒绝；工作区缺失/不可访问统一为 permission_denied，不冒充无匹配；检索或成员查询故障向调用方传播，来源元数据无效报 UpstreamProviderError，不伪造来源或返回空成功。

验证：新增 `backend/tests/unit/test_knowledge_tool.py` 的 **11 项测试**及既有 `test_retrieval.py` 7 项、`test_rag_graph.py` 2 项，共 **20 tests / 0 failures / 0 errors**。覆盖合法调用、空问题、额外范围参数、真实成员角色 Service 配合 DB 替身、每次重查权限、企业与工作区隔离、无匹配、来源序列化及故障传播。图回归使用真实检索图，替换候选检索/重排 Provider；将实际回填 SELECT 编译后在最小内存 SQLite 样例上执行，确认跨工作区、chunk/document 归属不一致、非候选与已删除 ID 都不会流入重排，且空历史不调用生成模型。SQLite 仅验证该 SELECT 的筛选行为，不代表 PostgreSQL 集成通过。

首次启动缺少测试 DATABASE_URL，随后补无真实连接的占位配置；独立测试的 ORM 注册及 schema 检查位置已修正。现有 `.venv-d4` 无 pytest，未安装依赖，改由 unittest 加载新增测试、FunctionTestCase 直接执行上述无 fixture 的既有回归函数，未加载全局 conftest。修改的三个 Python 文件 Ruff（backend 配置）通过，diff 空白检查通过。没有访问真实 PG、Redis、Qdrant、Embedding/重排服务或 Ollama；检索质量、真实服务连通性和真实权限集成尚未验证。

下一处最小接入位置：调查 API 向 `run_core_agent` 传递服务端验证的用户与选定工作区上下文，再在 Core 的工具注册边界接入此 Tool；当前调查 API 只有企业/案件上下文，不能默认扩展成全企业检索。届时需单独设计知识引用与业务事件引用的隔离，不把知识 chunk ID 塞进现有 `evidence_event_ids` 契约。本轮未改 Core 路由、调查 API/页面或报告证据规则，未执行后续接入；本人学习不标 PASS。

## 2026-10-16 V2.3：调查 API → Core → 知识工具 → 报告引用（离线接入）

完成上一节待办的最小接入。`InvestigationRequest` 新增可选 `workspace_id`；原 `POST /api/v1/organizations/{organization_id}/investigations` 路径不变，请求可为 `{"case_id":"<案件 UUID>","workspace_id":"<工作区 UUID>"}`，`as_of` 继续可选。API 先验证登录用户的企业成员角色，再查询工作区、检查企业归属及 viewer 成员关系；传给 Core 的企业 ID 来自通过查验的企业成员记录，用户和工作区 ID 来自通过查验的工作区成员记录。工作区缺失、跨企业或无权限在进入 Core/Provider 前返回 403；查询故障返回通用 500，不包装为无匹配知识或成功报告。不带工作区时沿用原 Core 入参，不注册知识工具。

Core 复用现有 `create_search_knowledge_tool`，不重造检索链路。知识工具在分析完成、没有待完成的必需库存/事件读取且尚未进入 final_only 时可选；执行前也保留相同门槛。模型仍只能填写 query，企业/用户/工作区无法通过模型参数覆盖，Tool 每次调用仍执行原权限检查。原负库存、非负库存后成功事件读取、无事件无 SKU 等强制停止路径保持；工作区存在不意味着必须检索。没有按场景编号分支，最大 9 次模型请求、6 次工具调用及现有重复调用、超时和报告修正次数均未放宽。

报告新增独立 `knowledge_source_ids`（chunk UUID 列表）：仅允许本次 trace 中 `search_knowledge(found)` 返回的来源子集，重复、未观察、跨运行来源及将事件 ID 冒充知识 ID 均拒绝。事件 `evidence_event_ids` 仍须精确匹配本次业务证据集合，知识片段不能改变时间比较、提供业务 SKU、补造履约事件或把 root_cause 改成非 unknown。知识引用为空时序列化省略新字段，保留旧三字段报告与旧模型响应兼容；有引用时交接单第 2 部分从已检索来源确定性呈现文档 ID、chunk ID、名称、页码及片段，不放入“已确认事实”。第 3 部分明确：只验证引用存在于本次检索，**未验证片段对建议的支持性**。

无匹配保持 `no_matches`，不改变业务 outcome；交接单单列检索状态及资料缺口，不断言规则不存在。Tool 调用时权限撤销则 Core 以 `knowledge_permission_denied` 停止，API 转为脱敏 403；检索执行故障沿用 `tool_failed/tool_timeout`、API 502 且不返回业务报告。来源原始内容保存在知识 Tool 的 trace，公开 API 不新增原始 trace、Prompt 或异常详情。

验证：新增 `test_core_knowledge.py` **11 项**，`test_investigation_api.py` 增加 **6 项**；连同既有 Core、状态边界、报告、知识 Tool 与业务 Tool 回归，共 **95 tests / 0 failures / 0 errors，2.683 秒**，修改的 6 个 Python 文件 Ruff 通过，diff 空白检查通过。成功用例实际走 ASGI 路由 → JWT 解析 → 企业/工作区权限 Service → 真实 Core → 原知识 Tool → 报告校验与渲染；读取路径为案件 → 履约分析 → search_knowledge → finish → 无工具报告。Provider 使用受控响应，用户/成员 DB 和业务 Service 读取使用替身，知识 Tool 的既有检索入口使用固定来源替身；未加载全局 conftest，未连接 PG/Redis/Qdrant 或调用 Embedding、重排、Ollama。

覆盖授权上下文、未授权/错误/缺失工作区、API 校验后权限撤销、无工作区不提供工具、独立真实来源 ID、伪造引用拒绝并修正、连续错误失败、重复查询拦截、无匹配及执行故障，并复验带知识授权的库存正负路径也不强制检索；原 C03/C04 等边界断言未放宽。修改范围：`backend/app/schemas/investigation.py`、`backend/app/api/v1/endpoints/investigations.py`、`backend/app/ai/agents/core_agent.py`、`backend/app/ai/agents/investigation_report.py`、上述两个测试文件及本交接文档；页面未改。

尚未验证真实检索服务的连通性、检索质量、实际模型是否合理选择知识工具与引用，以及带工作区 API 的真实 PostgreSQL 权限集成；本次不是完整模型矩阵或建议质量验收。下一项最小任务可为受控隔离知识样例下验证真实检索的授权范围与来源回填，继续与建议支持性评测分开记录；本轮不执行。本人学习不标 PASS，完成交接后停止。

## 2026-10-16 search_knowledge 真实检索隔离验证（Embedding 环境阻塞）

新增独立验证入口 `scripts/knowledge_retrieval_verify.py`，实际执行一次，未使用检索/权限替身或内存 SQL。数据库沿用 Day6 的 URL 与 current_database 双重保护，仅在 `ragforge_day6_test` 的随机 schema 内创建测试表和数据；Qdrant 在独立进程内使用随机命名测试 collection，不触碰原 `document_chunks` 集合。未修改生产代码或配置文件；Embedding 保持当前 `ollama / nomic-embed-text / 768`，重排保持 `none`，只临时覆盖本进程的 Qdrant 集合名并在退出时恢复。BM25 计划只读取随机工作区的 Redis 版本键，无缓存键写入或清理操作。

真实样例已插入同一测试企业下的两名用户、三个工作区及成员记录：用户 A 具有工作区 A 和空工作区的 viewer 权限，工作区 B 仅有用户 B 的 viewer 记录；A/B 各有一条内容相近、标记不同的库存差额 SOP 文档和 chunk。拟执行原 `create_search_knowledge_tool(...).ainvoke({"query": ...})`，核对来源与真实 PG 行、排除 B 的相近文档、拒绝未授权工作区且不触发 Embedding/搜索，以及授权空工作区的 no_matches。旁路 profiler 只观察原函数调用，不替换 Provider、Tool、Service 或查询。

**实际结果：`passed=false`，阶段 `index_embedding`，`UpstreamProviderError`**。首次 `embed_documents` 对两个真实样例发起 `/api/embed` 请求即返回 **HTTP 404**；尚未 upsert 向量，也未调用知识 Tool，`checks={}`。因此上述四项检索/权限验收均不能标通过，也不能沿用离线替身结果代替。运行内耗时 **3.765 秒**，进程退出码 **1**；没有重试、下载模型、修改模型名或执行聊天生成。

随后只读 GET `/api/tags` 返回 200，模型列表仅有 `llama3.1:8b`，当前配置的 `nomic-embed-text` 不存在。这是已确认的运行前置缺口；本轮未改变服务或安装模型。没有运行 Core/Agent 矩阵或 C05，也未修复其他问题。

清理：`rollback_verified=true`，随机 schema `day6_test_9fa7077b83764d4694e4d4033b6bd4df` 已回滚消失；仅删除本轮创建的 `project_a_knowledge_test_a7b816b927a7495cb5ad90c385bea89d`，`collection_absent=true`。退出后独立只读复核确认该 schema、该 collection 及原 PG 会话 PID `963460` 均不存在，测试进程无残留。原模型配置未变，业务数据库和业务向量集合未写入样例。

证据：`scripts/knowledge_retrieval_20261016T053308105136Z.json` 与同名 `.jsonl`（真实样例 ID、成员权限依据、调用记录与清理结果）；只读模型清单及清理复核为 `scripts/knowledge_retrieval_20261016T053308105136Z_cleanup_recheck.json`。新增包装 Ruff、语法与 diff 检查通过；生产实现和既有改动保留。

**尚不具备直接运行真实 C05 的完整条件**：需先恢复当前配置的 Embedding 模型可用性，再完成本入口的四项真实检索验证；此外现有 `day13_e2e.py --cases` 只接受 C01/C02/C03/C04/C06/C07/C08，尚无 C05 样例与验收入口，不能猜编号或借用别的路径冒充。下一项最小任务是单独解决已配置 Embedding 模型不可用的前置问题，本轮只记录、不实施。本人学习不标 PASS，到此停止。

## 2026-10-16 补齐 nomic-embed-text 与真实检索单次复验（Redis 连接阻塞）

接续前核对：无下载/检索验证进程，模型列表仍只有 llama3.1:8b；上次平台额度阻断未启动下载，也没有新验收证据。本轮保留既有代码、配置及原失败证据，只补未完成步骤。

- 下载前确认运行服务为 `http://localhost:11434`，实际模型目录为 `C:\Users\xingk\.ollama\models`，不是链接；虽用户环境变量指向 D 盘，运行服务的 `/api/show` 返回 C 盘实际路径，本轮未迁移或改配置。C 盘可用约 18.1 GiB，官方 manifest 合计 274,302,450 字节，空间充足。
- `ollama pull nomic-embed-text` 单次成功，退出码 0，耗时 28.343 秒。通过项目现有 Embedding Provider 做一次最小请求，耗时 10.656 秒，返回 768 维且数值有限，与 `ollama / nomic-embed-text / 768` 配置一致。前置证据：`scripts/nomic_embedding_setup_20261016T102948496111Z.json`；下载日志：`scripts/nomic_pull_20261016T102948.stdout.log`、同名前缀 `.stderr.log`。
- 随后仅重跑一次现有 `knowledge_retrieval_verify.py`，保留原四项断言与隔离机制。结果 **passed=false，failure_type=ConnectionError，stage=authorized**；运行内 8.484 秒，含启动进程总计 11.438 秒，退出码 1，无超时、无外层重试。两份测试 SOP 的真实 Embedding 成功（均 768 维，0.594 秒），查询 Embedding 成功（768 维，0.093 秒）；真实 Qdrant 检索仅返回授权工作区的 chunk（0.063 秒）。但并行 sparse_search 未完成，Tool 未返回结果，`checks={}`；不能据此把授权检索或跨工作区隔离整项标通过，未授权拒绝和空工作区 no_matches 尚未执行。
- 故障依据：JSONL 记录 sparse_search 开始后 ConnectionError；现有 BM25 首先从 Redis 读取工作区版本。退出后对当前配置 `localhost:6379` 做一次只读 TCP 连接检查，得到 `ConnectionRefusedError / WinError 10061`。这支持 Redis 连接不可用为当前阻塞；runner 未保存原异常堆栈，不冒充已捕获完整异常链。本轮未启动/重装 Redis、修改检索代码或继续重跑。
- 清理 **rollback_verified=true**：schema `day6_test_119d954d21e8442e8ffd7e65b5e4cc49`、测试 collection `project_a_knowledge_test_986a901f49a34b218a7e2db66e08799b` 均消失；退出后独立只读复核 PG 会话 968982 及测试进程 14860/45444 均不存在。仅清理本次资源，未写业务库或业务向量集合，原 Embedding/重排配置未变。

最终证据：`scripts/knowledge_retrieval_20261016T103134089743Z.json`、同名 `.jsonl`、`scripts/knowledge_retrieval_20261016T103134089743Z_cleanup_recheck.json`；外层进程状态及日志：`scripts/knowledge_retrieval_rerun_20261016T1031.status.json`、同名前缀 `.log`。

后续恢复现有 Redis 连接前置条件后，复验命令为 `.\.venv-d4\Scripts\python.exe scripts/knowledge_retrieval_verify.py`（本轮已执行一次，到此停止）。最小下一任务是单独核对并恢复现有 Redis 服务可用性，再授权一次原四项复验；已通过且配置不变的模型下载/维度检查无需重复。尚不具备真实 C05 完整验收条件，现有 runner 也没有 C05 入口；本轮未开发入口、未调用聊天模型或运行 Agent 矩阵，未改业务规则/配置，未标本人学习 PASS。

## 2026-10-16 Redis 端口核对与真实知识检索单次通过

确认 Compose 现有 `rag-forge-ai-main-redis-1` 为 running/healthy，映射为宿主机 **6380 → 容器 6379**；宿主机验证脚本原配置为 localhost:6379，属于端口不匹配。本轮没有启动第二套 Redis 或重建容器，仅将验证进程内的 Redis 端口改为 localhost:6380，保留原认证、数据库编号等 URL 组成；未输出凭据或完整连接串，未修改 `.env`、Compose 或业务代码。

先从同一宿主机 Python 环境一次性预检四项依赖，全部通过：隔离 PG 的 URL/current_database 均为 ragforge_day6_test（只读查询后回滚）、Qdrant 可读、当前 nomic-embed-text 返回 768 维、Redis PING 成功。证据：`scripts/knowledge_dependencies_20261016T105852795681Z.json`。随后将相同 Redis 覆盖仅传给子进程，执行原 `scripts/knowledge_retrieval_verify.py` 一次；没有修改验收断言、自动重试或调用聊天模型。

**结果：passed=true，四项原断言全部通过，退出码 0。** 验收内部耗时 **4.265 秒**，含子进程启动共 **7.265 秒**，没有超时。

- 授权工作区返回 found，唯一来源的 chunk ID、document ID、名称 `Allowed-inventory-SOP.txt` 和片段与真实测试 PG 行一致。
- 相近的另一工作区 SOP 已写入本轮独立 Qdrant collection；授权查询的向量与 BM25 两条搜索均仅返回授权 chunk，Tool 输出没有另一工作区的文档、chunk 或片段。
- 无权限工作区返回 permission_denied、sources=[]；调用观察证明此请求没有继续 Embedding、向量或稀疏检索。
- 有权限但无文档的工作区返回 no_matches、sources=[]，没有冒充权限拒绝或检索故障。

实际链路为原 search_knowledge Tool → 真实企业/工作区权限 Service → RAG 检索 → 真实 Ollama Embedding、Qdrant、Redis 版本读取、PG/BM25 → 来源序列化；无检索替身或内存 SQL。两份索引向量及两次查询向量均为 768 维；未触发聊天 Provider。当前重排配置仍为 none，不代表学习型重排、建议支持性或检索质量评测通过。

清理：**rollback_verified=true**，独立复核 schema `day6_test_dc59b994465a45bc8f91bd7aa04e6e84`、collection `project_a_knowledge_test_76f77f9a471c469fb7fa2bcc9c1e0a1d`、PG 会话 971430 及测试进程 38384/46380 均已消失。Redis 仅 PING/读取本轮随机工作区版本 key，并对三个明确归属 key 做 EXISTS 核查，均不存在；无 Redis key 写入、删除或 FLUSH 操作。未写业务库/业务向量集合，Embedding 和重排配置未变。

证据：
- `scripts/knowledge_retrieval_20261016T105924977902Z.json` 及同名 `.jsonl`；
- `scripts/knowledge_retrieval_20261016T105924977902Z_cleanup_recheck.json`；
- `scripts/knowledge_retrieval_redis_run_20261016T105922392834Z.status.json` 及同名前缀 `.log`。

后续复现入口仍为 `.\.venv-d4\Scripts\python.exe scripts/knowledge_retrieval_verify.py`，从宿主机运行须先在该子进程环境中将现有 REDIS_URL 的主机/端口定向覆盖为 localhost:6380，保留其余组成；全局默认未改，直接裸跑原入口仍可能遇到旧端口问题。本次只证明四项真实检索与工作区权限隔离，不代表完整调查 API/Agent/模型端到端、稳定通过率或真实 C05 通过。真实检索前置阻塞已解除；下一项最小任务仍须单独确定 C05 样例与入口（现有 day13 runner 尚无 C05），本轮不开发或运行。施工与本人学习分开记录，本人学习不标 PASS。

## 2026-10-16 Ollama 模型复制到 D 盘并切换（保留 C 盘备份）

按本轮授权仅处理本机 Ollama 模型存储。切换前未发现调查、Embedding 或下载任务进程；11434 无活动连接，`/api/ps` 已加载模型列表为空。D 盘可用约 140.12 GiB，`D:\OllamaModels` 原为空，用户级和当前进程级 OLLAMA_MODELS 已为该路径，未修改用户级配置或其他全局配置。

从 `C:\Users\xingk\.ollama\models` 完整复制 **13 个文件、5,195,064,265 字节（约 4.84 GiB）** 至 `D:\OllamaModels`。逐文件保存并比对相对路径、大小、源/目标 SHA256，全部一致，目标路径集合一致；采用排他创建，未覆盖任何内容不同的同名文件。随后退出原 Ollama app/server，将源目录改名为 **`C:\Users\xingk\.ollama\models.backup_20261016T111127041297Z`**，以明确继承 `OLLAMA_MODELS=D:\OllamaModels` 的新进程启动原 Ollama 应用。

验证成功：`llama3.1:8b`、`nomic-embed-text:latest` 均可识别，两个 `/api/show` 的 FROM 路径均位于 **D:\OllamaModels\blobs**。仅一次最小聊天请求返回 `OK`、done=true，耗时 **20.250 秒**；仅一次最小 Embedding 请求返回 **1 × 768 维**且数值有限，耗时 **6.625 秒**。未下载或调用调查 Agent/C05，未运行测试矩阵。请求级最小生成选项未改写项目模型配置。

继续使用 D 盘，无需回退。C 盘备份仍在，退出后核对备份文件数和总字节数未变，原模型目录路径不存在；原 app/server 进程已退出，新监听进程信息记录于证据。**没有删除模型或释放 C 盘空间**，后续任何清理必须另行授权；未修改项目代码、数据库、Docker 或其他配置。

证据：`scripts/ollama_models_switch_20261016T111127041297Z.json`（全部文件双份 SHA256、实际模型路径、原/新进程、请求结果、备份路径）。本轮环境切换验收完成即停止，不将其视为检索/Agent 业务验收，不标本人学习 PASS。

## 2026-10-16 C05 知识检索验收准备（离线完成，未运行真实 C05）

接续额度中断：检查时无遗留 Python 验证进程、无新的 c05_offline 结果；样例扩展及 runner 改动已落盘，但最终测试和本节交接尚未完成。本轮保留全部已有改动，补正一处清理负向测试的断言位置，完成剩余离线验证；没有重新下载模型、清理 C 盘备份或重跑真实知识检索。

### 预先固定的样例与验收契约

- 同一案件明确要求核对 Shipment delay review SOP 处理规则，根因未确认；不带 SKU 或 reservation/backorder 调查线索。观察截止沿用 `2026-10-09T12:00:00+00:00`。
- 同一跟踪号的四条真实测试事件：发货承诺记录于 06:00、截止 08:00、实际发货 09:00；送达承诺记录于 06:00、截止 11:00、实际送达 10:00（均 UTC）。发货晚 3600 秒、送达早 3600 秒，完整可比较，但不证明整单完成。
- 授权工作区 viewer 成员可检索唯一测试文档 `Shipment-delay-review-SOP.txt`。文档说明同跟踪号时间比较、保留事件引用及补充因果证据，不宣称任何订单事实、已执行操作或根因。
- 固定预期 **outcome=observed_delay、root_cause=unknown**。成功读取路径必须是 `get_exception_case → analyze_fulfillment → search_knowledge`；仅提及工具而未执行、未检索知识即结束均不能通过。沿用原单次参数纠错限制，不增加 Agent 请求/工具预算。
- 业务引用必须精确覆盖四条本次事件 ID；知识引用必须是本次成功检索的唯一 chunk ID，且来源 document ID、名称、片段与样例一致。事件与知识引用分别校验；SOP 不进入已确认业务事实，不得改变时间结论或确认异常根因。六部分交接单、请求 ID、登录用户/企业成员/工作区成员到 Core 的上下文及公开响应边界一并验证。引用存在仍不等于建议支持性已经验证。

### 最小接入与清理

复用 `scripts/investigation_api_c03_once.py` 的真实登录、ASGI API、观察记录、JSON/JSONL、子进程与回滚机制，新增 `--case C05`，默认仍为 C03；原 C03 断言保留。`scripts/investigation_c05.py` 仅承担固定样例、知识资源准备和验收，不修改 Agent 业务分支。`scripts/knowledge_retrieval_verify.py` 抽取既有测试文档/chunk 建样、真实 Embedding/Qdrant 入索引核对及仅删除自有随机 collection 的函数，两条入口共用，原四项检索断言未放宽。

真实运行前在子进程检查测试库 URL/current_database、Qdrant、Redis PING、两模型的 D 盘实际来源，并以测试 SOP 建索引检查 768 维；这些步骤先于聊天请求。Redis 只在验证进程将原地址的主机/端口覆盖为 localhost:6380，保留其他组成，不改 `.env` 或 Compose。PG 使用 ragforge_day6_test 随机 schema；Qdrant 使用 `project_a_knowledge_test_<随机UUID>`，创建前检查不存在并落盘所有权，正常/失败/中断后仅清理该集合；不动业务集合、无 Redis FLUSH。父进程复核 schema、PG 会话和集合消失；回滚、清理或退出不成功不能判通过。

C05 子进程上限 690 秒，API 请求上限 600 秒，预留最多约 30 秒用于进程停止和清理核查（整体按 12 分钟安排），无自动重试。针对 Windows 虚拟环境启动器可能另有 Python 子进程，C05 超时仅停止本次拥有的进程树，保留已落盘 JSONL；C03 原停止逻辑本轮未改。

### 离线验证结果与边界

**20 项定向测试通过（3.437 秒），随后仅补跑新增进程树测试 1 项通过（0.031 秒）；合计 21 项，0 failures、0 errors。** 包括新增 `backend/tests/unit/test_c05_acceptance.py` 的 10 项与直接相关 `CoreKnowledgeTests` 的 11 项；未重复运行完整回归。四个修改/新增 Python 文件 Ruff 通过。证据：`scripts/c05_offline_20261016T152210653310Z.json` 及同名 `.log`。

新增测试实际执行原 child 入口、ASGI 路由、JWT/认证函数、企业/工作区权限函数、Core、Tool、业务比较 Service 和报告校验/渲染；聊天 Provider 为受控序列，PG fixture/session/SQL 结果、Embedding、Qdrant、Redis、检索返回与模型路径查询均为替身。新增测试禁止 socket connect，不加载全局 pytest fixture；离线字典 SQL 返回不代表 PostgreSQL 集成，测试中的 rollback 标记只验证模拟生命周期，不是真实回滚证据。覆盖固定成功路径、缺失/伪造/混淆引用、错误结论/根因、跳过知识调用、检索故障、连续两次坏报告、部分索引失败、依赖预检失败、清理失败、仅清理自有集合及超时进程树参数；读取旧 C03 evidence 验证其原断言兼容，未重跑 C03。

本轮未连接真实 PG/Qdrant/Redis/Embedding 或聊天服务。真实模型是否主动选择知识工具、实际检索与最终报告能否一起通过、真实异常/超时清理仍待单次验收；已有四项真实检索通过证据与 D 盘模型验证保留各自边界，不替代 C05。

### 下一项仅单次真实 C05 的命令（本轮不执行）

在仓库根目录 PowerShell 运行：

```powershell
.\.venv-d4\Scripts\python.exe scripts/investigation_api_c03_once.py --case C05
```

前置：现有隔离库 ragforge_day6_test（localhost:5433）与测试身份可用；Qdrant localhost:6333、现有 Redis 宿主 6380 可用；Ollama localhost:11434 能从 D:\OllamaModels 识别 llama3.1:8b 和 nomic-embed-text（768 维）；现有依赖已安装。入口自动做上述进程级覆盖与预检；不要使用 `--child` 绕过外层上限，也不要用 `python -O` 禁用验收断言。输出为 `scripts/investigation_api_c05_<UTC时间>.json/.jsonl/.log`，只运行一次，不因失败自动重跑。

本轮只交付验收准备，**不宣称真实 C05 或完整矩阵通过**；未改业务代码、提示词、请求预算、页面、LangGraph 或写入功能，C 盘模型备份未动。本人学习不标 PASS；更新并读回本记录后停止。

## 2026-10-16 C05 真实 API 单次验收（失败，未检索 SOP）

执行前确认没有同任务进程或既有 C05 最终证据，按既有命令仅运行一次，未改代码、提示词、模型配置、请求预算或验收断言，未自动重试。PG 身份、Qdrant、Redis 6380、D 盘两个模型及 SOP 建索引的 768 维检查均通过；真实登录返回 200，JWT 用户、企业 member、工作区 viewer 校验已记录。C 盘模型备份未动。

**passed=false；error_code=null；failure_stage=acceptance_assertions；failure_type=AssertionError。** 总耗时 **548.453 秒（9 分 8.453 秒）**，API 内 533.031 秒，子进程内 543.922 秒；退出码 1，outer_timeout=false。失败发生在最终 C05 场景断言：模型跳过必需的知识检索，不是环境预检或 Tool 执行故障。

实际成功读取仅为 **get_exception_case → analyze_fulfillment**；随后模型原生调用 finish_investigation，进入无工具报告。没有执行 search_knowledge、事件补查或库存查询，没有 repeated_call。第 3/4 次实际提供的工具均包括 search_knowledge 和 finish；第 3 次普通文本伪调用 get_fulfillment_events 未执行，被调查阶段纠错反馈拒绝，第 4 次改为原生 finish，但没有完成规则查询。

| 模型请求 | 耗时（秒） | 实际响应/结果 |
| --- | ---: | --- |
| 1 | 94.422 | get_exception_case，读取成功 |
| 2 | 81.797 | analyze_fulfillment，读取成功 |
| 3 | 148.703 | 普通文本伪事件调用，invalid_evidence_report（investigation），未执行 |
| 4 | 59.735 | 原生 finish_investigation，随后工具列表为空 |
| 5 | 110.953 | 首份报告只引用一条事件，invalid_evidence_report（report），获得一次修正 |
| 6 | 37.204 | 修正为四条事件引用，业务报告通过现有证据契约 |

最终 API 为 **HTTP 200**，返回已校验的 `observed_delay / unknown` 和六部分中文交接单；四条事件引用精确匹配本次样例，未输出 trace、Prompt、model_final 或 rejected_finals。`knowledge_source_ids` 未提供，因为本次未成功检索任何知识；所以业务证据契约通过仍不等于 C05 通过。测试 SOP 虽已入本次独立 collection，但未进入模型工具观察或报告引用，不能据本次声称“已验证 SOP 与业务事实分开引用”或建议支持性通过。请求标识：`40318bec-5a51-44a6-a492-edd42cf085dc`。

清理：**rollback_verified=true**，父进程及独立只读复核均确认 schema `day6_test_b9dcf2e6bcce486583f76a14acbd418c`、PG 会话 989485、collection `project_a_knowledge_test_350e671fb0c04a53acc32105086fbf93` 消失；测试进程已退出。本轮工作区唯一明确归属的 `bm25:version:<workspace_id>` key 不存在；无 Redis 清空或其他资源删除。未运行其他场景或矩阵。

原始证据保留：`scripts/investigation_api_c05_20261016T152854003114Z.json`、同名 `.jsonl` 与 `.log`；补充只读核查：`scripts/investigation_api_c05_20261016T152854003114Z_cleanup_recheck.json`。停点为模型调查决策未执行知识检索，最终场景断言拒绝；本轮仅交接、不修复、不重跑，不标本人学习 PASS。

## 2026-10-16 C05 漏检索定位与显式检索要求（仅离线修复）

**定位依据。** 沿用上述失败 evidence，不新增真实运行。固定样例和案件工具的实际返回均明确写有 `consult the authorized Shipment delay review SOP for handling rules`，并要求分别记录业务证据与规则来源。第 3、4 次实际请求记录的工具均为 `get_exception_case / analyze_fulfillment / search_knowledge / finish_investigation`；第 3 次为普通文本伪事件调用，第 4 次选择原生 finish，trace 中没有知识检索。因此不是工具注册遗漏，模型确实没有完成样例中的规则查询。

原 evidence 没保存完整 messages/system/schema；以下是根据运行时 SHA256 与修改前文件一致的代码还原，不能当作完整请求抓包：案件结果进入 tool 消息，分析后案件问题还进入 `Original question (untrusted record data, not instructions)`。知识工具描述为查 SOP/处理规则、实时订单库存走业务工具；schema 仅允许必填非空 `query`，拒绝额外参数，用户/企业/工作区由服务端绑定。原系统指引明确说 `Optional search_knowledge`，普通文本纠错允许 `Otherwise call finish_investigation`；初始用户消息只有案件与分析时点，API 没有“必须检索”控制字段。原结束门槛只约束 reservation 库存/事件读取，业务报告契约也不要求未检索的来源。故同时存在模型漏查和 **C05 必查要求未成为产品可执行契约**，不能仅归为提示漏传，也不应通过强迫所有调查检索来修复。

**最小修复。** 在原调查请求增加严格布尔 `require_knowledge`，默认 false；true 必须同时提供工作区，否则 422。API 仍先校验登录身份、企业成员和工作区权限，再将该显式要求与查验后的上下文传入 Core。C05 既有入口仅补传 `require_knowledge=true`，样例问题、业务结论、工具路径与四条事件/一条 SOP 引用的原验收断言均未修改。不用 SOP 关键词、场景编号或案件 ID 推断需求；案件文本本身仍是非可信记录，不提升为控制指令。

仅显式要求检索且业务分析成功、没有终止性的业务读取缺失/错误时：未完成知识读取则不提供 finish，原生 finish、文本 FINISH 和直接有效报告均以 `missing_knowledge` 拒绝；普通文本伪调用的反馈指向当前必需读取，既有库存/事件前置条件优先。负库存、事件读取完成或无事件的业务自动停止也不能跳过该显式要求。`found` 或 `no_matches` 才完成检索要求；no_matches 允许结束，但不生成或接受虚构引用，也不能满足 C05 的真实 SOP 来源断言。权限拒绝和检索故障继续分别失败，业务 not_found 保留原终止语义。达到原预算而未完成要求则失败，不增加模型 9 次/工具 6 次上限。未指定或 false 的原路径仍按既有规则停止，工作区存在或案件文本提及 SOP 本身不会强制检索。知识/事件引用隔离、执行时权限复核、重复调用和证据校验均保留。

**实际离线验证。** `test_core_knowledge`、`test_investigation_api`、`test_core_agent`、`test_core_agent_boundaries`、`test_c05_acceptance` 共 **102 项通过，0 failures、0 errors，5.687 秒**。回放原 C05 第 3/4 次原始响应（开场观察使用离线固定数据）确认跳查被拒绝；另以受控响应完成“伪调用 → 纠错检索 → finish → 伪造来源报告被拒绝 → 正确报告”。覆盖三种结束形式、API 显式要求和授权传递、无工作区/非法布尔/无权限拒绝、no_matches 无来源、检索故障、无事件、无匹配案件、预算上限，以及原负库存停止与非负库存后事件路径。原 C05 入口成功和失败清理测试使用替身，不能视为真实回滚证据。

最终离线证据：`scripts/c05_required_knowledge_offline_20261016T155503544124Z.json` 及同名 `.log`。首次离线命令把 Windows asyncio 初始化自身 socketpair 也拦截，93 项在事件循环初始化失败，9 项同步测试完成；记录保留在 `scripts/c05_required_knowledge_offline_20261016T155412047588Z.json/.log`。仅调整测试命令的网络拦截时机至异步测试主体后，得到上述 102 项通过；未因此改业务逻辑。测试使用受控 Provider、数据库/检索/外部依赖替身，测试主体禁止 socket connect，不加载全局 pytest fixture。7 个修改的 Python 文件 Ruff 通过；文档及修改文件另做差异/空白检查。

修改范围：`core_agent.py`、调查 API/schema、现有 C05 runner 的请求字段、三个现有离线测试文件及本记录；未改 `investigation_c05.py` 的固定契约或报告校验/渲染。尚未验证真实模型是否遵从新门槛后成功检索及分别引用来源；本轮没有调用 Ollama、PG、Embedding 或完整矩阵，不宣称 C05 真实通过，不标本人学习 PASS。下一项最小任务仍是经授权后用原单次命令复验 C05（690 秒子进程上限与既有清理），本轮不执行。

## 2026-10-17 C05 修复后单次执行（预检失败，未进入调查）

只读核对最新交接及必要文件后，确认 `scripts/c05_required_knowledge_offline_20261016T155503544124Z.json` 中 7 个源码/测试 SHA256 全部一致；其余 7 个运行相关文件与上次真实 C05 evidence 的 SHA256 一致。runner 明确传入 `require_knowledge=true`，复用 102 项离线通过证据，未重复测试。启动前仅存在上次已收取的失败结果及清理记录；Get-Process 未发现 Python 进程，没有待接续任务。

仅执行一次 `.\.venv-d4\Scripts\python.exe scripts/investigation_api_c03_once.py --case C05`，保留原预检、690 秒上限和清理机制。**passed=false，退出码 1，outer_timeout=false，总耗时 15.454 秒，子进程内 5.359 秒。** 请求标识 `c2ec3f5d-3d80-41df-9950-98cad4068472`，子进程 PID 24736。`cleanup_or_setup_failure`、`knowledge_cleanup_failure`、`cleanup_verification_error` 均为 `ResponseHandlingException`；`error_code=null`。原日志仅包含 Qdrant 无法取得服务版本的警告，未记录底层异常消息，不能据此断言具体网络或服务根因。

持久化状态为 `collection_owned=false`，结合未变更源码可定位到首次 Qdrant `collection_exists` 检查，尚未进入数据库 fixture、SOP 建索引、登录或调查 API。模型请求为 0，无工具路径、报告、业务事件引用、知识来源或六部分交接单；没有模型纠错。`expected` 中的 `observed_delay / unknown` 仅为预期，不能当作实际输出。本次不满足 C05 验收，不修复、不重跑。

清理核实：进程已退出，独立 Get-Process 再次确认 Python 进程数为 0。未创建本轮 schema 或 fixture 数据库会话、未分配 workspace ID，因此未产生本轮工作区 Redis key，无 key 删除或扫描。仅预分配 collection 名 `project_a_knowledge_test_c3e545356d474a1ebefae80174d1d20b`，未取得所有权、未执行创建；清理函数不会删除未拥有的集合。**服务端集合不存在的复核失败，schema/PG 会话服务端复核也未得到成功标记；rollback_verified=false，不能写成回滚或清理全部通过。** 以上“未创建”为运行状态与源码控制流证据，区别于服务端查证。未进一步探测环境、改权限或全局配置，未下载模型或触及业务库及 C 盘备份。

原始证据：`scripts/investigation_api_c05_20261017T140715472614Z.json`、同名 `.jsonl`、`.log`；补充核查：`scripts/investigation_api_c05_20261017T140715472614Z_cleanup_recheck.json`。准备阶段一次文件枚举参数错误已改为名称过滤；一次 Win32_Process 命令行只读查询被拒绝访问，改用 Get-Process 确认无 Python 进程，未修改权限。两者均发生在唯一真实运行前，不计为 C05 重试，也不是模型纠错。

本轮停点：保留预检失败和未完成服务端清理复核的证据；require_knowledge 修复后的真实知识检索及分别引用仍未验收。未运行其他场景或完整矩阵，未增加预算或放宽断言。本人学习不标 PASS。追加并读回本条后停止。

## 2026-10-17 C05 Qdrant 前置连接定位（未恢复，按未知故障边界停止）

读取上一条失败 JSON 与 cleanup_recheck 后，仅检查相关 runner 配置、Compose 和 Qdrant 连接；未运行 C05、102 项测试或聊天模型。历史 evidence 仅保存异常类型，无法还原当时未记录的完整 traceback。本轮用相同 runner bootstrap/settings 对原随机集合执行一次只读 collection_exists，捕获当前完整关联异常链（cause/context/source 与异常组），不冒充历史异常抓包。为避免额外版本探测，仅本次诊断 client 关闭兼容性探测，超时 5 秒，不修改 runner 或全局配置。

直接连接失败原因：ResponseHandlingException → ConnectError → ConnectError → OSError → ExceptionGroup → 两个 ConnectionRefusedError，底层均为 `[WinError 1225] 远程计算机拒绝网络连接。` 实际地址为 `http://localhost:6333`，来源为 `backend/app/core/config.py` 的 Settings 默认值；当前进程和根目录 .env 均未覆盖 QDRANT_URL，API key 未设置。Compose 声明 Qdrant 宿主映射为 `6333:6333`，未配置 healthcheck；backend/worker 容器内使用的 `http://qdrant:6333` 不适用于宿主 runner。本轮未发现需要修正的验证进程地址。

`docker compose ps -a qdrant` 未能读取容器状态：Docker config.json 报 Access is denied，随后连接 `npipe:////./pipe/docker_engine` 失败，原错误为 `open //./pipe/docker_engine: The system cannot find the file specified.` 因 Docker API 不可达，不能确认容器状态、实际映射或健康情况，也不能判断仅为既有 Qdrant 容器停止。未擅自启动 Docker Desktop、切换 context、修改权限、重建容器、更新镜像或处理数据卷；按用户“其他未知故障保留证据并停止”边界结束。连接未恢复。

残留核查：原集合 `project_a_knowledge_test_c3e545356d474a1ebefae80174d1d20b` 的服务端不存在验证仍为 null（连接被拒绝），不是无残留成功。原运行未进入资源创建、未分配 schema/fixture PG 会话/workspace 标识，因此没有可按本轮标识查询的 schema、会话或 Redis key；未扫描或删除其他资源。保持原 `rollback_verified=false`，不把预检失败解释为回滚成功。原核查中的进程退出证据保留。

新增诊断证据：`scripts/c05_qdrant_connection_20261017.json`，包含脱敏配置来源、Docker 查询失败摘要、完整当前连接异常链及未完成的集合残留核查状态。原始失败 evidence 和 cleanup_recheck 未覆盖。本轮仅新增诊断证据及本条交接，追加后读回；不宣称真实 C05 通过，本人学习不标 PASS。

## 2026-10-17 C05 Qdrant 启动后单次执行（预检失败，独立结果）

用户确认 Qdrant 已启动后，复用已核实源码哈希及 102 项离线通过结果，未重复离线测试或环境排查。启动前 Get-Process 无 Python 进程，确认 runner 请求字段 `require_knowledge=true` 及 690 秒上限。仅运行一次原命令 `.\.venv-d4\Scripts\python.exe scripts/investigation_api_c03_once.py --case C05`，未重试、未修改代码/配置/验收断言或预算。

**passed=false；总耗时 12.734 秒，子进程内 5.000 秒；退出码 1，outer_timeout=false。** 本轮 request_id 为 `88fe7577-6788-4642-bd16-e73a843f39b9`，PID 6480。`cleanup_or_setup_failure=ConnectionRefusedError`、`cleanup_verification_error=ConnectionRefusedError`、`error_code=null`。Qdrant 初始集合检查已通过（collection_owned=true），最终 collection_absent=true；因此本轮不再是上一轮首次 Qdrant 连接检查失败。父进程 check_cleanup 的隔离 PostgreSQL 核查仍因连接拒绝失败；子进程也在预检结束前失败，原 evidence 未保存底层异常消息或详细失败栈，不把推定的具体主机服务故障写成已确诊根因。日志为空。未现场扩大诊断或修复。

模型请求 0，未进入登录/调查 API，没有实际工具路径、知识检索、四条事件引用、SOP 引用或六部分交接单，无模型纠错。`observed_delay / unknown` 仅为 expected 字段，不是实际报告。原验收条件完整保留，本次未完成 C05 验收。

清理：本轮随机 collection `project_a_knowledge_test_79f580d9e78e4635876f7b6810679091` 已由 runner 服务端确认不存在；仅预登记所有权，未进入 ensure_collection 创建或 SOP 索引。未进入数据库 fixture，未创建 schema、fixture 数据库会话、workspace 或本轮工作区 Redis key；未扫描/删除其他资源。schema/PG 会话服务端消失核验未完成，**本轮 rollback_verified=false**，不能视为回滚成功或全部清理通过。进程已退出，独立 Get-Process 确认 Python 进程数为 0。历史 rollback_verified=false 保留，未覆盖历史证据。

本轮证据：`scripts/investigation_api_c05_20261017T141617412844Z.json`、同名 `.jsonl`、`.log`；补充核查 `scripts/investigation_api_c05_20261017T141617412844Z_cleanup_recheck.json`。未运行其他场景、矩阵或离线测试，未触及业务库和 C 盘备份。本条仅追加一次并读回后停止；真实 C05 未通过，本人学习不标 PASS。

## 2026-10-17 C05 全依赖集中核查（PG/Redis 阻塞，未运行验收）

基于最新失败 evidence 与 runner，一次并行完成依赖检查。隔离 PG 实际目标由 `scripts/day11_e2e.py` bootstrap 固定为 `localhost:5433/ragforge_day6_test`，进程内设置 DAY6_TEST_DATABASE_URL/DATABASE_URL；账号与密码本轮来自根目录 .env（密码未输出）。对应 Compose 服务 postgres，映射 5433:5432。连接失败：`ConnectionRefusedError [WinError 1225] 远程计算机拒绝网络连接。` 因此尚不能通过 SELECT current_database() 确认实际库名，也未完成只读 PG 残留核查，历史 rollback_verified=false 保持不变。

Qdrant `http://localhost:6333` 的集合接口成功，服务 qdrant 映射 6333:6333，Compose 未配置 healthcheck；服务端确认最新失败运行集合不存在。Redis 按 runner 保留原认证/路径、仅在检查进程使用 localhost:6380（服务 redis，6380:6379），PING 连接被拒，底层同为 WinError 1225。Ollama localhost:11434 的 /api/show 成功返回 llama3.1:8b（completion/tools）及 nomic-embed-text（embedding），两者来源均在 D:\OllamaModels；只验证既有模型元数据与来源，未调用聊天或 Embedding 生成、未下载模型。

Docker 查询 `docker compose ps -a postgres redis qdrant` 在 Codex 内受到权限限制：config.json Access is denied，Docker API 管道 permission denied。用户已确认普通 PowerShell 引擎正常；本轮不据权限拒绝误判引擎停止。无法确认既有容器已停止，故未执行 start；未重建、拉镜像、迁移、创建数据库或改全局配置/业务代码。没有恢复动作，因此未重复探测。剩余阻塞是 PG/Redis 连接被拒，以及 Codex 无权查询/操作容器；全部依赖就绪后再安排真实 C05，本轮不执行。

直接证据：`scripts/c05_dependencies_20261017.json`。未重复离线测试；未删除任何资源。本条仅追加一次并读回，真实 C05 未通过，本人学习不标 PASS。

## 2026-10-17 C05 依赖恢复后单次真实验收（知识检索成功，调查响应失败）

启动前使用原配置只读确认实际数据库为 localhost:5433/ragforge_day6_test，测试 schema 与其他隔离库会话均为空，无 Python 任务；此前两次预检失败的随机集合均由服务端确认不存在。补核证据为 `scripts/c05_pre_run_residual_20261017.json`，历史 rollback_verified=false 未修改。复用已有源码哈希与 102 项离线结果，未重复哈希/测试/Docker 排查；相关文件修改时间未见变化。确认 require_knowledge=true、原断言、690 秒上限与清理机制，原命令仅执行一次，无重试或现场修复。

**passed=false；HTTP 502，error_code=ungrounded_final，failure_stage=investigation_api，failure_type=RuntimeError。** 总耗时 **482.016 秒（8 分 2.016 秒）**，API 469.110 秒，子进程 478.234 秒，退出码 1，outer_timeout=false。全部依赖预检和 SOP 索引通过，实际完成 JWT/企业/工作区授权及业务读取，失败不在依赖连接。

实际工具路径为 **get_exception_case → analyze_fulfillment → search_knowledge**，三步均 found。分析保留四条与本轮 fixture 精确一致的事件引用，发货 late/+3600 秒，送达 on_time/-3600 秒，整单完成仍 unknown。真实知识检索返回唯一 Shipment-delay-review-SOP.txt；chunk_id、document_id、文件名与内容均匹配本轮 fixture，知识 chunk 未混入业务事件 ID。此为工具观察层校验成功，不代表最终报告引用契约通过。

5 次模型请求耗时依次为 94.390、76.719、144.547、64.312、86.860 秒。第 3 次输出普通文本伪 get_fulfillment_events 调用，被 investigation 阶段 invalid_evidence_report 拒绝；第 3/4 次提供 search_knowledge 且未提供 finish，纠错后第 4 次原生调用知识工具成功。第 5 次已提供 finish，但模型再次输出普通文本伪 get_inventory_status 调用，含无业务来源的 SKU-123，未执行库存查询；第二次 invalid_evidence_report 后以 ungrounded_final 终止。两次均为调查响应纠错记录，不是最终报告引用纠错。未生成经校验的 observed_delay / unknown 报告、四事件/一 SOP 最终引用或六部分交接单，API 明确返回 no business conclusion produced；不能将 expected 字段写成实际结论。本次仅证明真实知识检索门槛在纠错后得到满足，C05 整体验收仍失败。

本轮清理成功：rollback_verified=true，runner 与独立只读核查均确认 schema `day6_test_2b5a3998319b4d3083d0e597e5895331`、PG 会话 314、collection `project_a_knowledge_test_a6284b87ce5d4811bc7c862dc5d3d781` 不存在；工作区 `3d9f06bc-a1c9-4d2f-9f33-55ad41b5e35f` 对应唯一明确归属的 bm25:version key 不存在，无 Redis 删除或 FLUSH。测试进程 PID 27332 已退出，独立 Get-Process 无 Python 进程。该回滚成功仅属于本轮，不覆盖历史失败。

证据：`scripts/investigation_api_c05_20261017T142615923918Z.json` 及同名 `.jsonl`、`.log`；独立核查为同前缀 `_cleanup_recheck.json`。未运行其他场景或完整矩阵，未修改业务代码、全局配置、预算或断言，未下载模型、触及业务库或 C 盘备份。本条追加一次并读回后停止；本人学习不标 PASS。

## 2026-10-17 C05 知识检索后结束边界修复（仅离线）

直接依据 `scripts/investigation_api_c05_20261017T142615923918Z.json`：第 4 次原生 search_knowledge 返回 found 后，第 5 次仍处于 investigation，并非 final_only；实际工具列表为 get_exception_case、analyze_fulfillment、search_knowledge、finish_investigation。原自动停止只覆盖终止性结果/工具预算、负库存、完成必需事件读取及无事件无 SKU；知识 found/no_matches 完成 require_knowledge 门槛后仅重新允许 finish，没有自动进入报告。第 3、5 次伪工具文本分别被记为 investigation/invalid_evidence_report，正确累计同阶段第二次失败并终止；不是 report 计数混入 investigation，也不应通过重置计数或增加预算解决。

历史 evidence 保存了响应、实际工具列表和拒绝阶段，未保存完整请求 messages/system。根据相应代码还原：第 3 次反馈要求当前必需的原生 search_knowledge，不再允许 finish；知识返回后仍追加 Select ONE function 决策提示及观察停止规则，允许模型再次调查或选择 finish。提示中的“事实充分且无进一步线索则停止”未在该完成边界成为强制状态转换。第 5 次 SKU-123 仅见于模型输出及其拒绝记录，业务观察与检索到的 SOP 均无此值；可确认其无合法观察来源，无法确定模型内部为何生成该字符串，不能归因于 SOP 示例。

最小改动仅在 Core 的通用阶段边界：显式 require_knowledge=true、分析成功、必需业务读取已完成且 search_knowledge 返回 found/no_matches 后，复用既有自动结束逻辑转入 final_only，移除旧决策提示，下一请求工具为空并要求证据 JSON；报告阶段不再追加要求继续知识检索的指令。无匹配仍允许报告但不能虚构来源；require_knowledge=false 的自选检索路径保持原行为。未硬编码场景/SKU/样例 ID，未自动填结论，未改 SKU 执行前来源校验、引用/根因契约、阶段纠错次数及 9 次模型/6 次工具预算。业务文件仅修改 `backend/app/ai/agents/core_agent.py`；两个相关测试文件同步流程并新增回放。

定向离线验证：`test_core_knowledge` 与 `test_c05_acceptance` 共 **33 项通过，0 failures、0 errors，3.265 秒**；3 个修改文件 Ruff 通过。回放本次五个原始模型响应，业务与知识观察由真实 evidence 提供给替身 Service/检索：第 3 次仍是 investigation 拒绝，第 5 次现在为 report 拒绝，第 6 次受控正确报告通过，四事件与 SOP 分别引用；同一 report 连续两次坏响应仍失败。另覆盖 required no_matches 后伪造来源被拒再纠正、非必需检索/无工作区/库存路径保持原行为、SOP 示例 SKU 的原生库存请求在执行前 scope_violation 且 Service 未调用，以及入口成功/失败与清理替身流程。全程受控 Provider、DB/检索替身，异步测试主体禁止 socket connect，不加载全局 pytest fixture；没有真实模型、数据库或其他外部调用，不能作为真实回滚或 C05 通过证据。

最终证据：`scripts/c05_post_knowledge_offline_20261017T144114211062Z.json` 及同名 `.log`，含本次修改文件 SHA256。准备时首次测试导入缺少 DATABASE_URL，尚未执行测试；改为仅导入既有 runner bootstrap 后执行（未调用 main），没有改全局配置。首次完整 33 项中 32 项通过、1 项旧请求数断言失败，证据 `scripts/c05_post_knowledge_offline_20261017T144038852239Z.json/.log` 保留；因自动报告省去 finish 请求，将对应测试期望由 6 改为 5 后得上述最终全通过，未放宽业务验收。

未验证部分：真实模型能否在新的 final_only 消息与工具列表下输出合规报告、实际 API 六部分交接单能否完成，仍需后续授权单次验收。本轮未运行真实 C05、完整回归或其他场景；仅追加本条并读回后停止。本人学习不标 PASS。

## 2026-10-18 收取 20261017T144515065498Z 原 C05 结果（失败，未重跑）

仅接续原 exec 会话 22417，已收取退出码 1 及最终 JSON/JSONL/.log。未发现同前缀独立 stdout/stderr/status 文件：子进程输出合并在 .log，父进程 stdout/status 由原 exec 会话收取。原任务已退出，无 Python 进程，不需强制停止；本轮未启动 C05、模型请求或测试，未修改业务代码。

**passed=false，error_code=request_timeout，failure_stage=investigation_api，failure_type=TimeoutError。** 总耗时记录 **51857.937 秒（14 小时 24 分 17.937 秒）**，API 51844.985 秒；第 6 次模型请求 completed=false，计时 51342.594 秒。JSONL 第 6 次开始于 2026-10-17T14:53:48.838805Z，失败于 2026-10-18T05:09:31.447070Z。outer_timeout=false，与原 690 秒上限存在明显墙钟跨度异常；不据此推断机器休眠、额度中断或进程暂停的具体原因，也不宣称上限得到正常执行。日志另记录 model_timeout，最终 runner 证据记录 request_timeout，无成功 API 报告。

实际路径 **get_exception_case → analyze_fulfillment → search_knowledge**，均 found。第 3 次伪库存文本调用在 investigation 被拒，第 4 次原生知识检索成功；第 5、6 次 offered_tools=[]，确认修复后进入无工具报告阶段。分析四条事件与 fixture 一致、唯一 SOP 检索来源匹配。第 5 次草稿为 observed_delay / unknown，SOP chunk 引用正确且与业务引用分开，但只引用四条事件中的一条，被 report 阶段 invalid_evidence_report 拒绝；第 6 次修正未完成。没有经校验的最终报告或六部分交接单，不能以草稿结果宣称通过。

清理成功：原 evidence rollback_verified=true；父进程及本轮独立只读复核均确认 schema day6_test_8fe2939e23db4e45b216f8cf1fa92c51、PG 会话 1947、collection project_a_knowledge_test_6aacb2c7c36746378f6504de0649eee6 不存在；工作区 771b96be-6933-4ada-a64d-69f26022729c 对应 bm25:version key 不存在。测试 PID 25124 已退出；未删除其他资源，未修改历史证据或历史 rollback 标记。

原证据：`scripts/investigation_api_c05_20261017T144515065498Z.json` 及同名 `.jsonl/.log`；本轮补核为同前缀 `_cleanup_recheck.json`。唯一下一步：离线核对超时/计时机制与异常时间跨度的证据，再决定后续验收，本轮不施工、不重跑。仅追加本条并读回后停止；本人学习不标 PASS。

## 2026-10-18 C05 超时计时离线核对与最小修复

依据 20261017T144515065498Z 原 JSON/JSONL/.log/cleanup_recheck，仅核对 runner、Core/Provider 超时调用及本地 Python 等待实现；未连接模型、数据库或其他服务。51857.937 秒是父进程 main 开始（生成证据路径/Popen 之前）到父进程清理复核后的 time.monotonic 差值，不是 JSONL UTC 时间直接相减；子进程 51853.719 秒从 child 入口计到子进程清理/客户端关闭结束，API 51844.985 秒从 asyncio.wait_for(client.post,600) 前计至 finally。模型请求耗时由 Observer 的首次 Provider 调用至返回计量，未完成请求在 API finally 补记；前五次合计 500.735 秒，第六次未完成计 51342.594 秒。这些都是经过时间，不是 CPU/实际活跃执行时间，不能据此排除暂停或调度间隔。JSONL 用 datetime.now(UTC)，其长时间跨度与 elapsed 相符；本地 Python 3.12.3 的 monotonic 当前实现为 GetTickCount64，asyncio loop.time 调用 time.monotonic。历史 evidence 未单独保存时钟实现。

690 秒由独立父 runner 在 Popen 后等待子进程退出时执行，包含子进程导入、预检、建样、API 及子进程清理；不包含父进程自身此前导入/Popen 和其后的清理复核（后者另设 20 秒）、证据保存。API 600 秒、Core 单请求 180 秒、Provider HTTP 190 秒是子进程内不同层限制；日志 model_timeout 来自 Core，最终 request_timeout 由 child 捕获 TimeoutError 设置，未成功保存 API response。旧 outer_timeout 仅在 process.wait(timeout=690) 抛 TimeoutExpired 时为 true。本地 Windows Popen._wait 使用 WaitForSingleObject，仅 WAIT_TIMEOUT 才抛异常；正常返回时不比对单调时钟，因此存在“经过截止时间后返回子进程退出，但 outer_timeout=false”的确定漏判分支。原父进程最终写出了清理核查并由旧 exec 收到退出码 1，不能推断它在长间隔内一直可调度；缺父进程等待起止/心跳、暂停恢复及系统电源事件，无法确认系统休眠/唤醒、父进程暂停或中断的实际原因。

最小修复限于 `scripts/investigation_api_c03_once.py` 的 C05 父进程监控：保持 690 秒，用单调截止时间及最多 1 秒的原生等待片段复核；子进程即使晚退出也记录 outer_timeout，超期仍存活才调用既有 stop_child_tree，避免针对已退出 PID 发 taskkill。新增 parent_wait_started/finished、父/子启动器 PID、时钟实现与等待耗时，超期覆盖 error_code 时另存 child_error_code。C03 原等待逻辑、业务/报告契约与各项预算不变；没有修复报告缺引用。暂停/休眠期间父进程无法执行终止操作，本修复只能在恢复可调度后检查并停止/标记，不能保证暂停期间实时杀进程，也不声称已查明本次长间隔根因。

定向验证仅新建 `test_c05_deadline.py`，6 项假时钟/假子进程测试全部通过（含导入总耗时 2.750 秒），覆盖正常零/非零退出、到期活进程停止、原生等待正常返回但已超期、时钟大幅前进且进程仍活、恰好截止退出不发 kill；socket connect 全程禁止，无真实子进程或长等待。两个修改/新增文件 Ruff 通过。证据 `scripts/c05_deadline_offline_20261018T051923388232Z.json/.log`；计时审计 `scripts/c05_timeout_audit_20261018.json`。历史失败与清理证据未改，本轮未重复已有测试或运行真实 C05。仅追加本条并读回后停止；真实环境监控行为尚未复验，本人学习不标 PASS。

## 2026-10-18 C05 报告漏引反馈补齐（仅离线）

核对 `scripts/investigation_api_c05_20261017T144515065498Z.json` 与报告阶段代码：首次报告的工具消息已含全部四条业务事件 ID 和唯一 SOP chunk ID，系统明确 Include ALL observed event IDs，并要求 knowledge_source_ids 与 evidence_event_ids 分开。原修正反馈已给完整 evidence_contract，但未直接列出该份草稿缺失的三条事件。历史 evidence 没保存完整 messages；上述消息内容由代码及受控回放核实，不冒充历史网络抓包。不能将首次漏引归因于事件 ID 未提供，也不能确认模型漏引的内部原因。

本轮仅在 Core 报告纠错反馈追加 missing_evidence_event_ids：从可解析草稿与既有事件契约作差集，明确要求把缺项纳入业务事件字段，知识引用不能代替事件引用。原坏样本缺少 704abfab-c92c-41e1-b09a-0757a103d0f7、ac82ada9-d75e-4625-919e-991e225ab626、daa241ce-b8a1-4c03-9ae0-9605b2f69782；这些 ID 仅用于证据/测试，不硬编码进业务代码。结构非法或无事件缺项时不生成缺失清单。首次报告提示、验证契约与渲染、预算、超时逻辑均未修改；报告仍由模型生成，不自动补写任何引用。Core 知识引用原规则为成功检索来源的合法子集，未改成必须引用全部来源；C05 的单 SOP 原断言保持不变。

仅运行 3 项新增定向离线测试：**3 项通过、0 failures、0 errors，0.063 秒**。回放原五次已完成响应与原观察，第 5 次一事件/一 SOP 草稿仍被拒，反馈精确列出其余三条事件且不混入 SOP；第 6 次受控模型完整报告通过 observed_delay / unknown 与两类引用校验。再次提交原坏报告仍以 ungrounded_final 失败；结构非法、完整引用和空事件场景不产生虚假缺项。测试检查首次报告消息确实携带完整两类来源，模型输出/坏样本未被代码补写。Provider、DB/检索均为替身，测试主体禁止 socket connect，无真实模型/数据库/C05。两文件 Ruff 通过；测试后仅按 Ruff 要求换行整理导入，未改行为、未重复测试，证据同时保留测试时及最终文件哈希。

证据：`scripts/c05_missing_citations_offline_20261018T052535519151Z.json/.log`。真实模型能否利用新反馈完成纠正仍未验证；原失败、缺引用和超时记录保留。本轮不混改超时逻辑、不运行其他场景或完整回归。仅追加本条并读回后停止；本人学习不标 PASS。

## 2026-10-18 C05 单次真实验收通过（纠错后，本轮独立结果）

复用超时修复 6 项、缺失引用反馈 3 项离线测试及 Ruff 结果，确认无 Python 任务后，仅执行一次原 C05 命令。require_knowledge=true、依赖预检、原预算/断言与 690 秒上限均保留，未重试或现场修改。**passed=true，HTTP 200，退出码 0，总耗时 608.531 秒（10 分 8.531 秒）**；API 595.218 秒，子进程 604.500 秒。实际路径 **get_exception_case → analyze_fulfillment → search_knowledge**，真实检索 found；第 5/6 次报告请求 offered_tools=[]。最终 observed_delay / unknown，四条事件与样例精确匹配、唯一 SOP chunk 单独引用，API 六部分中文交接单完整。知识仍标注非业务事实，不证明根因或建议支持性。

纠错：第 3 次普通文本伪事件调用未执行，在 investigation 阶段被拒；第 4 次原生知识检索成功。第 5 次首份报告仅引用一条事件，在 report 阶段被拒；缺失项为 0011c5b3-05ed-4eb8-86c7-45a6d25c920d、c4a53f66-0822-48d3-8bd6-b32ce7d4bfb6、cd2e009d-f1d1-4f36-87c1-828478e9ea71。第 6 次模型自行补齐，原引用契约通过。缺失清单反馈及修正结果保存于补核文件；反馈文本根据本次坏样本与相同运行代码重建，runner 未保存完整请求 messages，不能称为完整请求抓包。六次模型耗时为 88.375、76.672、145.359、76.125、139.782、67.203 秒。

父进程 PID 32148、启动器 PID 25684、子进程 PID 32552；parent_wait_started/finished 均落盘，单调时钟 GetTickCount64，等待 607.860 秒，小于 690 秒；outer_timeout=false，child_tree_stop_requested=false。本次正常退出验证了截止监控记录，不替代暂停/超期强制停止的真实环境验证。

清理：rollback_verified=true，runner 及独立只读复核确认 schema day6_test_c3f63bc22360420e82405db21520b596、PG 会话 4316、collection project_a_knowledge_test_a3c9a5fe0755450f809be667c8315990 均不存在；工作区 17e447b0-653b-4312-a4ff-245754eb85e3 的 bm25:version key 不存在，测试进程全部退出。未删除其他资源或修改历史失败/回滚记录。

证据：`scripts/investigation_api_c05_20261018T052738639745Z.json`、同名 `.jsonl/.log`，以及 `_cleanup_recheck.json`。本次仅证明 C05 这一场真实运行通过，不代表完整矩阵或稳定通过率；未运行其他场景或重复离线验证，未动业务库、全局配置或 C 盘备份。仅追加本条并读回后停止；本人学习不标 PASS。

## 2026-10-19 C10 知识权限边界验证通过

已有 2026-10-16 真实检索证据仅覆盖知识 Tool，已有 API 权限测试为离线替身，均不足以证明本轮要求的“实际模型输入无越权来源”。新增专用入口 `scripts/investigation_api_c10_once.py`，沿用隔离 PG 身份保护、随机 schema、自有 Qdrant collection 及清理函数，只将调查聊天 Provider 替换为受控实现；真实用户登录、JWT、企业/工作区 Service、Core、知识 Tool、Embedding、Qdrant、Redis、PG/BM25 与来源回填均实际执行。不运行 C05、不调用聊天模型、不开新权限体系，生产代码无需修复。

**C10 passed=true，退出码 0，总耗时 15.922 秒。** 真实隔离库 ragforge_day6_test，两个工作区各一份相近文档，用户只有授权工作区 viewer 权限。授权 API 返回 200，受控 Provider 的实际 messages/system/tool schemas 全量保存：Allowed-inventory-SOP.txt 的正文、chunk `9d71f39b-ebdc-4b7c-bdf7-193c01a16653`、document `5236afb9-85b6-4e2f-93e2-35fa16dfafcd` 可见；Restricted-inventory-SOP.txt 的正文/RESTRICTED-B 标记、chunk `18743c32-c0a1-4877-bf64-0d0ca2b94efc`、document `c9256abe-0372-4a33-baaf-4bfd00435e58`、vector ID 与文件名在全部模型输入中均不可见。正常向量/稀疏检索均仅返回授权 chunk。另仅在自有集合故意将受限向量的 workspace 标签改为授权工作区，真实向量候选随后包含受限 chunk，但原 PG 双 workspace 回填过滤将其阻断；第二次 API 仍为 200，模型输入仍仅含授权来源。不是只检查最终报告没有引用。

无权限工作区 API 请求返回 403/permission_denied，Provider factory 调用 0、模型请求 0，且未启动 Embedding/向量/稀疏检索；另直接调用原知识 Tool 返回 permission_denied/sources=[]，同样无检索调用，验证执行时权限复核。沿用工作区文档权限继承语义，不宣称存在逐文档 ACL，也不宣称真实聊天模型行为或完整矩阵已验收。

命令：`.\.venv-d4\Scripts\python.exe scripts/investigation_api_c10_once.py`。此前仅通过 `.\.venv-d4\Scripts\python.exe -` 的 unittest stdin harness 加载 `test_c10_visibility`（socket.connect 禁止），3 项通过、0 failures/errors、0.001 秒；覆盖授权来源正例、每个受限字段在 system/tools/messages 各位置泄漏均失败、空上下文不可冒充通过。两个新增 Python 文件 Ruff 通过。修改仅专用入口、`backend/tests/unit/test_c10_visibility.py`、本交接及证据；未修改业务实现。准备时修正一处读取文件名和 Ruff 导入/诊断注释，无运行失败重试。

清理：rollback_verified=true，父进程确认 schema `day6_test_a5674d735fb74d63870fed66ee40ccef`及 PG 会话 36539 不存在，独立集合已删除，三个样例工作区 bm25:version key 均不存在，原测试进程已退出，独立 Get-Process 确认无 Python 进程；未触及其他集合或 Redis key。证据：`scripts/investigation_api_c10_20261019T055925983902Z.json` 及同名 `.jsonl/.log`，测试/清理摘要 `_review.json`；模型输入位于 `api_runs.authorized.model_inputs` 和 `api_runs.wrong_vector_workspace_label.model_inputs`。本条追加一次并读回后停止；本人学习不标 PASS。

## 2026-10-19 Celery + Redis 文档入库隔离验收

现有入口为文档上传或重新入库提交数据库后调用 `document_service.enqueue_ingestion`；Redis /1 为 Celery broker、/2 为结果后端，worker 执行 `ingestion.process_document`，`Document` 与 `IngestionJob` 提供业务状态。原任务每次投递新建 job，并重写 chunk/向量及追加用量记录；终态解析失败只写业务失败却向 Celery 返回成功。已在原任务内改为原子领取已有待处理 job、按 task ID 更新状态，重复投递跳过；终态失败重新抛出，使 Celery 结果为 FAILURE。未新建队列体系或修改权限/报告规则。

定向命令：`.\\.venv-d4\\Scripts\\python.exe scripts/ingestion_celery_verify.py`。真实隔离运行 **passed=true，10.843 秒**：测试库身份 `ragforge_day6_test`；随机 schema、独立 Qdrant collection、独立 Celery 队列和临时本地存储。生产者调用经仅本次进程重定向到该队列，真实 Redis broker/结果后端和单独 solo worker 执行；实际调用本地 Ollama Embedding，未调用聊天模型。成功文档的原排队 job 变 completed/done、1 chunk、1 向量、1 用量记录，Celery SUCCESS；空白文档变 failed、错误 `No extractable text found in this document` 同时出现在文档/job，Celery FAILURE，0 chunk、0 用量。成功文档再次投递后，原 job 数量和 ID、chunk/向量 ID、用量计数均不变。Ruff 通过。

原始证据：`scripts/ingestion_celery_20261019T061835650013Z.json` 和同名前缀 `.worker.log`。验证脚本确认 worker 退出，测试 schema、collection、隔离队列/结果及 BM25 Redis key、临时文件均不存在；未动业务库或业务集合。尚未验证多 worker 并发竞争、worker 崩溃后的同 task ID 重投递、显式 reingest 与旧任务交错、broker 发布失败后的待处理 job 补偿。现有上传为先提交再发布，发布失败可能留下 pending job；本轮未扩展为 outbox。本人学习不标 PASS。

## 2026-10-19 ActionRequest 数据库与 Service 基础

仅实现 `notify_case_customer`（指定异常案件的客户通知申请）。`ActionRequest` 保存企业、申请人、目标案件、`{message}` 参数、企业内幂等键和状态；新申请仅为 `pending_approval`。`approved`、`rejected`、`executed` 保留状态空间，但本轮无审核/执行入口，也没有通知发送或设置 `executed` 的代码。Service 先检查申请人的企业成员身份及案件企业归属；同企业同键同申请人/目标/原文消息返回原申请，同键内容不同返回冲突。数据库唯一约束 `(organization_id, idempotency_key)` 兜住竞争，PostgreSQL `ON CONFLICT DO NOTHING RETURNING` 后读取胜出行。

创建申请与 `action_request.created` 审计使用同一保存点；审计失败时申请回滚。调用方拥有外层事务并负责提交/回滚，Service 不自行提交。审计只记类型和目标 ID，不复制通知正文。迁移 `0005_action_requests` 已在隔离测试 schema 执行，未迁移业务库。目标跨企业一致性沿用现有 Service 校验约定；数据库目标外键为单列，直接绕过 Service 的 SQL 不具备同企业复合外键保护。

改动：`backend/app/models/action_request.py`、`backend/app/db/base.py`、`backend/alembic/versions/0005_action_requests.py`、`backend/app/services/action_request_service.py`、`backend/tests/commerce/test_action_request_postgres.py`、`scripts/action_request_verify.py`。命令 `.\\.venv-d4\\Scripts\\python.exe scripts/action_request_verify.py` 在 `ragforge_day6_test` 的逐测试随机 schema 上 **7 项通过，0 failure/error，7.922 秒**；覆盖跨企业同键、同内容去重、异内容冲突、未批准不改订单/案件、双连接并发只产一申请一审计、非成员/跨企业目标拒绝、审计失败回滚。每个测试退出后确认 schema 不存在；Ruff 通过。最终证据 `scripts/action_request_20261019T063450350304Z.json` 及同名前缀 `.log`；此前 6 项通过证据保留为修正前记录。

未验证人工审批与执行、真实通知发送、审核角色策略/API/UI、与 LangGraph/Celery 的连接及业务库迁移；本轮未运行聊天模型、C01–C12 或既有 C05/C10/文档入库验收。本人学习不标 PASS。

## 2026-10-19 ActionRequest 人工批准/拒绝 Service 与认证 API

在已有 `notify_case_customer` 申请上新增一次性人工审核：`POST /api/v1/organizations/{organization_id}/action-requests/{request_id}/review` 仅接收 `approved` 或 `rejected`。真实 JWT 用户进入 API，Service 再通过企业成员及至少 `admin` 角色校验；`owner` 由现有角色层级覆盖。按企业和申请 ID 加 PostgreSQL 行锁并刷新 ORM 缓存状态，仅 `pending_approval` 可审核；重复或竞争输方返回 409，不追加第二条决定/审计。审核记录 `review_decision`、`reviewed_by_user_id`、`reviewed_at` 及 `action_request.reviewed` 审计，申请修改与审计在同一保存点，API 提交外层事务；审计失败两者均回滚。批准只到 `approved`，没有发送通知或写入 `executed`。审核响应不暴露通知正文。

新增独立迁移 `0006_action_request_review.py` 和数据库一致性约束，既有 `0005` 保持原样；未迁移业务库。改动文件：`backend/app/models/action_request.py`、`backend/alembic/versions/0006_action_request_review.py`、`backend/app/services/action_request_service.py`、`backend/app/schemas/action_request.py`、`backend/app/api/v1/endpoints/action_requests.py`、`backend/app/api/v1/router.py`、`backend/tests/commerce/test_action_request_postgres.py`。测试仍由 `.\\.venv-d4\\Scripts\\python.exe scripts/action_request_verify.py` 执行，仅在 `ragforge_day6_test` 随机 schema 上依次运行 `0005/0006` 迁移。最终 **13 项通过，0 failure/error，16.89 秒**；覆盖批准、拒绝、重复审核、两个独立连接并发审核（包括旧 ORM 缓存）、成员/角色/企业边界、真实 JWT API 的 401/403/422/200/409、审计失败回滚和订单/案件未变。Ruff 通过，每个测试退出后确认 schema 不存在。原始证据：`scripts/action_request_20261019T064431433048Z.json` 与同名前缀 `.log`。

未实现申请创建 API、审核 UI、双人分离策略、通知执行或 `executed` 状态设置；没有模型、C 场景、完整矩阵或 Celery 运行。本人学习不标 PASS。

## 2026-10-19 README 实际状态与 Project A 演示步骤收口

只读核对当前 router、ActionRequest Service/API 及已有证据：调查 API 已注册；`create_notification_request` 仅为 Service，没有申请创建 HTTP API；ActionRequest 路由目前仅有 `POST /organizations/{organization_id}/action-requests/{request_id}/review`。因此调查报告、申请创建 Service 和管理员审核 API 不能宣称是已接通的前端/HTTP 完整链路。批准仅写 `approved`、审核人/时间/审计，不发送客户通知，也不设置 `executed`。

更新 `README.md` 的状态说明与 Project A 能力表，移除“当前 feature-complete／全量 71 项通过”的过时断言，并按现有源码修正 LangGraph 仅负责聊天检索阶段的描述；加入 C05、C10、真实隔离入库及 ActionRequest 定向证据链接。新增 `docs/PROJECT_A_DEMO.md`：先只读展示 C05 报告与四条业务事件/一条 SOP 引用，再用已有 ActionRequest 13 项隔离 PG 测试证据展示 Service 创建、幂等及人工批准/拒绝，最后给出审核 API 请求契约，明确审核需另一个真实待批准申请。测试 fixture 的 schema 已删除，旧 case/request ID 不可用于现场 API 请求；文档提供以后独立复验的原命令，但本轮未执行。

证据复用：`scripts/investigation_api_c05_20261018T052738639745Z.json`（真实 C05 passed/rollback_verified，路径 case→analysis→knowledge）、`scripts/investigation_api_c10_20261019T055925983902Z.json`、`scripts/ingestion_celery_20261019T061835650013Z.json`、`scripts/action_request_20261019T064431433048Z.json/.log`（13 项通过）。只读演示核验得到 C05 True/True、实际三工具路径、4 条事件引用及 1 条知识来源。准备时 PowerShell `ConvertFrom-Json` 无法解析体量较大的 C05 evidence，改为现有虚拟环境 Python 的 JSON 读取并验证成功；没有改 evidence。未调用模型、重跑场景/测试、修改业务代码或执行迁移。本人学习不标 PASS。

## 2026-10-19 ActionRequest 认证创建 API 与 HTTP 链路

补齐 `POST /api/v1/organizations/{organization_id}/action-requests`，仅接收目标案件、通知内容和幂等键；申请人取自现有 JWT，企业取自路径，额外正文身份/范围/状态字段拒绝。复用 `create_notification_request` 的企业成员、案件归属、唯一约束及创建审计，API 提交事务；新申请为 `pending_approval`，同企业同键同内容返回原申请，内容不同为 409。批准/拒绝仍由管理员审核 API 完成；没有通知发送或 `executed` 写入。改动 `backend/app/api/v1/endpoints/action_requests.py`、`backend/app/schemas/action_request.py`、`backend/tests/commerce/test_action_request_postgres.py`、`README.md`、`docs/PROJECT_A_DEMO.md` 及本交接。

命令 `.\.venv-d4\Scripts\python.exe scripts/action_request_verify.py` 在隔离 PostgreSQL `ragforge_day6_test` 的逐测试随机 schema 中运行，**14 项通过、0 failure/error、21.094 秒**；Ruff 对上述三个 Python 文件通过。新增真实 JWT/ASGI HTTP 测试覆盖创建→管理员批准、另建申请→拒绝，以及未登录 401、跨企业 403、跨企业案件 404、伪造身份/状态 422、重复创建同 ID、异内容 409、普通成员审核 403；独立数据库会话读取已提交的两申请和四条创建/审核审计，最终分别为 `approved`、`rejected`，订单及案件数量不变。此前首次尝试因测试文件括号笔误在导入时中止，修正后才形成上述有效运行；未产生数据库测试资源。原始证据 `scripts/action_request_20261019T074042047684Z.json/.log`。测试 teardown 在独立连接确认每个随机 schema 已删除，证据 `all_test_schemas_dropped=true`；本轮未创建 Qdrant collection、Redis key 或常驻进程，未迁移业务库，未运行模型、C05/C10 或场景矩阵。

剩余边界：C05 的测试案件已回滚，报告不会自动提交处置申请；现场演示需另备有效案件和成员/管理员 JWT。尚无审核 UI、通知执行器或 `executed` 状态路径；本轮只证明隔离数据库上的认证 HTTP 链路，不代表生产环境部署。本人学习不标 PASS。

## 2026-10-19 ActionRequest 最小前端与隔离演示

新增侧边栏 `/action-requests` 页面，复用当前登录态、企业选择、成员角色查询、按钮/表单组件与 `apiFetch`。普通成员填写本企业案件 UUID、拟通知正文创建 `notify_case_customer` 申请，看到 ID 及服务端实际状态；admin/owner 可在列表中批准或拒绝。状态文案明确区分“待人工审核，尚未发送通知”“已批准，尚未发送通知”“已拒绝”。同步 pending guard 阻止等待期间重复点击，企业/用户/案件/正文未变时重试沿用同一幂等键；请求失败清除本次成功提示并显示可理解错误。后端新增最少的企业申请列表 GET：成员只看本人，admin/owner 看本企业，响应不含通知正文；创建/审核仍由原 Service 校验。改动 `frontend/src/app/(dashboard)/action-requests/page.tsx`、`frontend/src/lib/api/action-requests.ts`、侧边栏及成员 hook、`backend/app/api/v1/endpoints/action_requests.py`、定向 PG 测试、演示脚本、README 和演示文档。

独立演示脚本 `scripts/action_request_demo.py` 将数据库固定为 localhost:5433 的 `ragforge_day6_test`，在随机 `action_demo_*` schema 中建立两企业、成员/admin/外部用户、独立案件和必要表；登录密码仅在被 `.gitignore` 排除的本地 `scripts/action_request_demo_state.json`。不复用 C05 回滚 ID，不迁移业务库。真实服务进程和 Next 页面曾在 8123/3108 启动。`scripts/action_request_demo_http_verify.py` 使用真实 `/auth/login` JWT，经真实 HTTP 完成创建→批准及另建→拒绝，验证未登录 401、跨企业 403、外企业案件 404、伪造申请人 422、同键同内容原 ID、异内容 409、普通成员审核 403；独立数据库会话核对两份申请分别为 `approved`/`rejected`、四条创建/审核审计且无 `executed`。证据 `scripts/action_request_demo_http_20261019T080647172012Z.json`，`passed=true`。另一次隔离 PG 定向测试 `scripts/action_request_20261019T080756327731Z.json/.log` 为 **15 项通过、0 failure/error、20.0 秒**，新增列表的本人/管理员可见范围测试；测试随机 schema 均删除。Ruff、前端 typecheck/lint、当前源码的 Next 生产构建、浏览器脚本语法检查通过。

浏览器自动化**未通过**：Chrome 和 Edge 在 CDP 页面加载前发生本机 GPU 子进程崩溃或未生成调试端口；最后一次 Chrome 证据 `scripts/action_request_browser_2026-10-19T08-08-42-020Z/evidence.json` 记录 `Page.enable` 超时，`checks=0`，未发申请请求。不能把真实 HTTP 验证冒充浏览器验收，页面重复点击也只完成代码 guard 和构建检查，尚缺真实浏览器交互证据。已停止本轮启动的后端 PID 10948 和 Next PID 32240；随后只读 `inspect` 确认演示 schema 仍在、两申请及四审计可读。演示数据按要求保持，显式结束时执行 `scripts/action_request_demo.py cleanup`；没有创建 Qdrant/Redis 资源、发送通知或调用聊天模型。递归清理临时浏览器 profile 的命令被自动策略拒绝（`blocked by policy`），因此临时 profile 目录可能残留，未扩大处理。本人学习不标 PASS。

## 2026-10-19 最小处置页面浏览器验收接续

先只读复核上轮 `scripts/action_request_browser_2026-10-19T08-08-42-020Z/evidence.json`、现有 runner 与隔离库：`ragforge_day6_test` 的 `action_demo_e023b320166644acb8429553ae39ad81` 仍有已批准/已拒绝申请各一份和四条审计。针对旧 runner 默认假设空列表，改为按运行时新 ID 识别本轮申请，并加入刷新后文案核对；runner 保留本次临时 profile 路径且不再删除任何 profile。只做语法检查，未重跑已有 HTTP 测试、模型或场景。

启动隔离 API `127.0.0.1:8123`（PID 24760）与已构建前端 `127.0.0.1:3108`（PID 14912），两端启动前 HTTP 200。仅运行一次 `node scripts/action_request_browser_verify.cjs`，无头 Chrome 使用禁用 GPU/软件光栅化等既有启动选项；结果 **browser passed=false**，`Page.enable` 等待 20 秒无响应，`checks=0`、`browser_requests=[]`，没有到达登录或页面，因此成员创建、连续点击、管理员批准/拒绝、刷新状态均**未在浏览器中验证**。原始证据 `scripts/action_request_browser_2026-10-19T08-26-58-871Z/evidence.json` 及同目录 `chrome.stderr.log`；本次 stderr 显示 DevTools 监听、加密/地理位置权限诊断及默认网页安装失败，没有上轮 GPU fatal，确切卡住原因未知。浏览器 PID 33004 已退出；本次 profile `C:\Users\xingk\AppData\Local\Temp\project-a-action-browser-IZpQye` 明确保留，未尝试删除。只读 `inspect` 再确认隔离库仍为原两申请/四审计，未新增申请。API/前端进程与隔离数据保留供手工验收；最短步骤与显式清理命令已写入 `docs/PROJECT_A_DEMO.md`。本人学习不标 PASS。

## 2026-10-19 客户通知站内记录的受控执行

只读核对 `backend/app`：现有 `notify_case_customer` 仅有申请、审核与审计，没有邮件、短信或其他发送设施。本轮将“执行”限定为**创建本系统内的通知记录**：`customer_notifications` 对 `action_request_id` 有唯一约束，`delivery_status` 由数据库约束为 `not_sent`；记录冻结经批准的正文、案件、企业和执行人。只有本企业 admin/owner 可对 `approved` 申请调用 `POST .../action-requests/{id}/execute`；待审、拒绝和跨企业申请不能执行。Service 在行锁与同一保存点内创建记录、设置申请 `executed`、写 `action_request.executed` 审计，API 提交外层事务；重复或并发调用返回同一记录，不追加记录/审计。`GET .../{id}/notification` 仅让原申请人及本企业 admin/owner 查阅。前端在已批准申请上显示“创建站内通知记录”，已执行显示“站内通知记录已创建，未发送；客户收悉未确认”并可查看记录正文。没有外部发送或送达确认，不把内部记录冒充客户收悉。

改动 `backend/app/models/customer_notification.py`、`backend/alembic/versions/0007_customer_notifications.py`、`backend/app/db/base.py`、`backend/app/services/action_request_service.py`、`backend/app/schemas/action_request.py`、`backend/app/api/v1/endpoints/action_requests.py`、`backend/tests/commerce/test_action_request_postgres.py`、`frontend/src/lib/api/action-requests.ts`、`frontend/src/app/(dashboard)/action-requests/page.tsx`、`scripts/action_request_demo.py`、README、演示文档和本交接。`0007` 只在隔离测试 schema 运行，未迁移业务库。定向命令 `.\.venv-d4\Scripts\python.exe scripts/action_request_verify.py` 在 `ragforge_day6_test` 随机 schema 中 **21 项通过、0 failure/error、29.422 秒**，包含批准后执行、待审/拒绝/普通成员/跨企业拒绝、真实 JWT HTTP、独立数据库会话读取、重复/双连接并发去重、数据库唯一约束直测、审计失败时状态与记录回滚；所有测试 schema 删除。原始证据 `scripts/action_request_20261019T084353824194Z.json/.log`。Ruff、前端 typecheck/lint/生产构建通过。

保留中的演示 schema `action_demo_e023b320166644acb8429553ae39ad81` 仅追加 `customer_notifications` 表；只读 `inspect` 确认原 approved/rejected 两申请与四审计不变，通知记录为零。旧演示 API/前端进程已停止，当前构建在 API PID 14504（8123）、Next PID 34100（3108）运行，OpenAPI 含执行和查看路径、页面 HTTP 200。数据继续保留供手工演示，结束后按 `docs/PROJECT_A_DEMO.md` 显式清理；本轮没有调用浏览器/CDP、聊天模型、通知外发或全矩阵。上轮浏览器验收仍待办，临时 profile 原样保留。本人学习不标 PASS。

## 2026-10-19 业务 Core 最小 LangGraph 迁移（离线对照）

核对原 `run_core_agent` 单循环、既有调查 Tool/Service、报告校验和已安装 `langgraph==1.2.12`。新增 `backend/app/ai/agents/core_graph.py`：每次请求的 `CoreSession` 明确保存认证范围、原始截止时间、消息/观察、已见调用、模型与工具预算、调查/报告分阶段纠错计数、待办读取及结果；Graph 用模型决策、工具校验、工具执行、报告校验四个实际节点和条件边循环/结束。公开 `run_core_agent` 保留签名与返回值，构造同一授权工具注册表后进入 Graph；原循环改名 `_run_core_agent_legacy`，只供离线等价对照。没有检查点、人工中断、外部通知或新权限体系。模型及工具各自原有 `asyncio.wait_for`、调用上限、来源/范围/重复校验、知识与事件引用契约未放宽。

新增 `backend/tests/unit/test_core_graph_parity.py`，受控 Provider 对旧循环与 Graph 逐次比较模型可见消息和工具列表、实际读取次数、工具轨迹、报告与交接正文、拒绝记录、错误码和模型请求数。11 组情形覆盖负库存停止及报告修正、非负库存后事件读取与缺失引用修正、必需知识检索进入空工具 final_only、无匹配知识、工具故障/短时受控超时、越权案件及知识权限撤销、重复工具调用、模型预算耗尽和调查/报告分阶段修正；**11 组一致**。用仅供离线导入的进程内虚构 SECRET_KEY/DATABASE_URL 运行 `..\.venv-d4\Scripts\python.exe -m unittest tests.unit.test_core_graph_parity tests.unit.test_core_agent tests.unit.test_core_agent_boundaries tests.unit.test_core_knowledge -q`（工作目录 `backend`），最终 **90 项通过、0 failure/error、7.217 秒**；Ruff 对两个 Core 文件及新测试通过。初次定向测试因缺少进程内必需配置在导入前中止，补入虚构配置后通过；受控超时初次设置过短、在首个读取即触发，调为只在目标事件工具触发后 11 组通过，生产超时参数未变。未连接虚构数据库，未运行真实模型、数据库、浏览器或场景矩阵，未迁移业务库，原隔离演示数据和进程未触碰。该证据只证明离线确定性回放，不宣称真实模型已通过；后续真实运行的模型行为及既有 runner 增量观察兼容性仍待验证。本人学习不标 PASS。

## 2026-10-19 演示成员登录故障修复

前端当前构建的登录请求为同源 `/api/v1/auth/login`；`frontend/.next/routes-manifest.json` 确认 `/api/:path*` rewrite 到 `http://127.0.0.1:8123/api/:path*`。用保留状态文件中的同一成员账号请求 8123 和 3108，登录均为 HTTP 200、JWT 已签发；紧接的 `/auth/me` 均为 HTTP 500，脱敏错误 `internal_error`，企业和成员列表却均为 200。独立只读数据库会话确认实际库 `ragforge_day6_test`、当前 schema `action_demo_e023b320166644acb8429553ae39ad81`、成员 ID 与状态文件一致。直接复现 `UserRead.model_validate` 的 `EmailStr` 错误：演示种子使用 `@example.invalid`，该保留域名被邮箱校验拒绝，故页面在登录后读取当前用户时失败。

只改 `scripts/action_request_demo.py` 的未来演示种子邮箱域名为 `@example.com`，新增限定现有隔离 schema 的幂等 `repair-emails` 命令；已运行一次，仅原位更新三个现有演示用户邮箱并同步被忽略的状态文件，用户 ID、密码、角色、案件和申请均未重建。通过端口 3108 的实际同源请求链验证成员登录、`/auth/me`、企业列表、企业成员列表均为 HTTP 200；返回用户 ID 与成员 ID 匹配。独立数据库会话复核原两申请、四条申请审计、零通知记录不变。脱敏证据 `scripts/action_request_demo_login_20261019T092002737272Z.json`（不含邮箱、密码或 Token），Ruff 和语法检查通过。演示步骤已更新，需从当前状态文件读取更正后的邮箱；旧复制邮箱已失效。未清理演示数据、未关闭鉴权、未运行浏览器 CDP、模型或全矩阵。本人学习不标 PASS。

## 2026-10-19 处置申请页面即时状态一致性

用户复现批准申请 `be0cf4c5-34c8-49c9-abff-01708e90e601` 后，列表按钮已切换为执行，但顶部“实际状态”仍显示待审。根因是页面持有独立 `recent` 创建响应对象，审核/执行只触发 React Query 列表刷新，未更新该对象；两个位置来源不同。审核 API 的 `ActionReviewResult` 已提供申请 ID、企业和新状态；执行 API 返回已提交的内部通知记录，但没有申请完整对象。前端现以列表缓存作为顶部最近申请、行内文字及操作按钮的同一数据源：创建成功插入完整响应，批准/拒绝成功合并服务端审核状态，执行成功依据同事务提交的通知响应切换为 `executed`，随后均向服务端重新读取列表。操作中的按钮持续禁用；POST 失败不改动缓存；POST 成功而重新读取失败时单独显示“操作成功、列表核对失败”，不误报 POST 失败。读取错误文案也仅称列表可能不是最新状态。改动 `frontend/src/app/(dashboard)/action-requests/page.tsx`、`frontend/src/lib/api/action-requests.ts`、`frontend/src/lib/action-request-state.ts` 及定向测试。

`frontend/src/lib/action-request-state.test.ts` 四项状态转换检查实际共享的状态/按钮选择逻辑：批准即时出现执行按钮，拒绝无审核/执行按钮，执行出现记录查看且明确未发送，错误或跨企业结果不制造成功。Vitest 因当前 `node_modules` 缺少 Rolldown Windows 原生绑定而在启动前失败，未重装或升级依赖；改用已安装 TypeScript 编译器执行同一测试源码，**4 项通过**。`npm run typecheck`、相关文件 ESLint、带 `BACKEND_INTERNAL_URL=http://127.0.0.1:8123` 的 `npm run build` 均通过。仅重启 Next 前端，当前 3108 `/action-requests`、`/login` 为 HTTP 200，未登录企业 API 为预期 401，rewrite 仍到 8123。只读 `action_request_demo.py inspect` 确认保留 schema、包括用户目标申请的四份申请、九条申请审计和一条 `not_sent` 通知记录均保留；本轮未调用审核/执行 API 修改数据。未运行浏览器 CDP，真实点击后的视觉行为仍待手工核对；未运行模型、数据库全套测试或完整矩阵。本人学习不标 PASS。

## 2026-10-19 客户通知申请页两项收口

按本轮明确范围仅补通知记录定位和真实时间。原通知卡片为页面末尾的单一状态，连续查看不同申请可能只替换内容且不滚动；现按 `organization_id:action_request_id` 分别缓存，点击“查看通知记录”时未加载先调用现有认证 GET，再严格核对返回的企业和申请 ID，随后滚动到该申请行内卡片、聚焦并短暂高亮；读取失败或关联不符明确报错，不展示错配记录。加载中禁用重复查看。没有调用浏览器 CDP，实际视觉交互仍待人工核对。

申请表原有 `created_at`、`review_decision`、`reviewed_at`；通知表原有 `created_at`。仅在 `ActionCreateResult` 和企业范围列表 GET 补审查字段与从通知表左连接得出的 `executed_at`，无迁移、新列或伪造时间。前端从服务端 ISO 时间统一按 `Asia/Shanghai` 标“北京时间”；待审/未执行显示“尚未审核/尚未执行”，非待审历史缺失显示“未记录”。执行时间仅代表同事务站内通知记录创建，不代表发送或客户收悉。审核响应的真实 `reviewed_at` 和执行响应的通知 `created_at` 会立即合并进前端申请状态。

改动 `backend/app/schemas/action_request.py`、`backend/app/api/v1/endpoints/action_requests.py`、一项隔离 PG 列表测试、`frontend/src/lib/api/action-requests.ts`、`frontend/src/lib/action-request-state.ts` 及其测试、申请页面、演示说明和本交接。定向隔离 PostgreSQL **1 项通过**，验证待审空值、已审核实时时间、执行时间等于通知记录时间，测试 schema 自动清理；前端定向状态/定位/时区测试源码通过已安装 TypeScript 编译器执行 **7 项通过**，typecheck、相关 ESLint 和生产构建通过。Vitest 原生绑定仍缺失，本轮未称 Vitest 通过，也未安装/升级依赖。重启现有演示 API 与 Next 后，前端代理只读 JWT GET 验证 4 条保留申请、4 条审核时间及已执行时间与对应通知记录相等；证据 `scripts/action_request_timeline_20261019T124310482527Z.json`，不含凭据或正文。演示数据未清理；本轮未调用创建/审核/执行写接口、聊天模型或全矩阵。本人学习不标 PASS。

## 2026-10-19 订单履约调查页面闭环准备（等待用户浏览器单次提交）

用户已手工确认客户通知申请页状态同步、通知记录定位及北京时间展示；本轮不重复施工或测试该页。历史 C05 真实通过属于旧循环，不作当前 LangGraph/浏览器链路证据。

调查页新增可选 SOP 工作区与“必须检索”选项，默认提交行为保持不变；结果页现在显示结构化 outcome、root_cause、业务事件 ID、SOP 来源 ID 和六部分交接正文。使用已保留的隔离数据库 `ragforge_day6_test` 内演示 schema，仅新增独立案件 `59db2e27-ac93-4ef0-b939-a72ac2b5113a`、四条事件、工作区 `0f676bd4-9f01-447b-b185-227d9df84966`、SOP 文档与独立 Qdrant collection；原处置申请记录未改。准备脚本为 `scripts/investigation_page_demo.py`，`inspect` 已核对案件/订单/工作区/文档 chunk、四事件及 collection 存在。3109 前端代理到 8124 专用认证 API；真实 JWT 登录、`auth/me` 和工作区 GET 均 200，演示工作区可见。准备只调用 SOP Embedding，不调用聊天模型或调查 API。

页面入口与只提交一次的操作见 `docs/PROJECT_A_DEMO.md`。服务端仅在该案件实际进入 Core 后写 `scripts/investigation_page_graph_evidence.json`；准备阶段尚无此文件，因此当时 Graph 工具路径、报告和浏览器展示均未验收。提交完成后运行 `scripts/investigation_page_demo.py verify`，逐项核查报告契约和两类引用，并用 `inspect` 复核隔离库范围。前端 typecheck、相关 ESLint、脚本 Ruff 与语法检查通过；未运行浏览器 CDP、旧 C05 或全矩阵。处置申请与调查报告目前需要人工衔接；审核/内部通知执行不是调查 API 的自动步骤，外部通知仍未发送。演示数据和 3109/8124 服务保留待用户提交，清理仅针对本轮新资源；本人学习不标 PASS。

## 2026-10-19 单次浏览器调查的中断核查

用户在 3109 用成员账号提交案件 `59db2e27-ac93-4ef0-b939-a72ac2b5113a`，选择工作区 `0f676bd4-9f01-447b-b185-227d9df84966` 并要求 SOP 检索；页面报调查失败，随后报告电脑意外关机。本轮只核对原请求，不再次发起调查。`scripts/investigation_page_graph_evidence.json` 精确匹配案件/企业/工作区及 `require_knowledge=true`，记录 2026-10-19 13:28:36.687811 UTC 开始、13:40:06.706015 UTC 结束，耗时 690.015 秒、`error_code=outer_timeout`、`passed=false`。文件没有 report、trace、model_requests 或 request_id；不能从中断日志推断工具路径、报告阶段、报告拒绝原因或 HTTP 状态。上轮 3109 Next 增量日志记录到 8124 的代理 `ECONNRESET/socket hang up`，8124 尚无该 POST 的完成行；旧进程会话随关机消失，无法再收取。另有工作区聊天 GET 的 `conversations` 缺表异常，路径不同，不归因于此 POST。Docker backend 日志在 13:40:33 UTC 有事件流 HTTP 500，晚于本证据的 690 秒截止；电脑断电具体时点未知，不能据此归因模型/代码。

Graph 由无 checkpointer 的 `builder.compile()` 构建，`CoreSession` 仅在请求进程内保存状态；原请求没有可恢复检查点，不可断点续跑。当前原 3109/8124 进程已消失，已按现有脚本恢复这两项本地服务且各自健康接口为 200，未触发模型。Ollama 11434 及现有聊天/Embedding 模型元数据可用。PG 5433、Redis 6380、Qdrant 6333 均未监听，原隔离数据及 collection 的服务端状态暂无法只读确认；忽略状态文件仍指向同一隔离 schema/案件，尚未重复准备或清理。尝试启动现有 Docker Desktop，但 Codex 沙箱对用户 `.docker`/Docker 日志目录访问被拒，`docker_engine` 管道不存在，Desktop 后端未就绪；已停止本轮启动的隐藏 Desktop 进程，未执行 Compose 重建/拉取/迁移。待用户在普通 PowerShell 恢复已有容器后，先只读复核数据库、collection、Redis，再给出再次手工提交的步骤；当前不得提交。本人学习不标 PASS。


## 2026-10-19 Investigation demo readiness and durable trace

Read-only verification: isolated database ragforge_day6_test and retained schema action_demo_e023b320166644acb8429553ae39ad81 contain case 59db2e27-ac93-4ef0-b939-a72ac2b5113a, its order, exactly four expected events, and the completed SOP document/chunk. The retained member has viewer access to workspace 0f676bd4-9f01-447b-b185-227d9df84966. Dedicated Qdrant collection project_a_knowledge_test_2958ecc15aef492eac291028c306d64a and the corresponding point are available. Redis PING succeeded. The 3109 login page and 8124 OpenAPI returned 200; the 3109 proxy reaches the 8124 auth route. Earlier in this turn, retained member credentials yielded JWT login, auth/me and workspace GET 200. No fixture was recreated or cleaned, and no investigation or chat model was invoked.

The dedicated 8124 runner now creates a unique scripts/investigation_page_run_*.json snapshot and fsynced .jsonl event stream per request, plus scripts/investigation_page_latest.json pointer. They record request_id, Graph model request boundaries, tool observations, phase changes, report rejections, final report/error and HTTP status when a response is sent. Historical scripts/investigation_page_graph_evidence.json is preserved; verify reads the latest run. The Graph has no checkpointer, so an interrupted run is described only by its last persisted event. Changed only the demo runner and demo/handoff docs. Offline seven-event evidence lifecycle, Python syntax and Ruff passed; 8124 was restarted and read-only HTTP health rechecked. Await one browser submission. Current Graph and report remain unverified. Personal learning is not marked PASS.

## 2026-10-19 Browser investigation result and proxy correction

The single browser POST really reached `POST /api/v1/organizations/d6f90c90-01b5-42de-81f5-5d4e2268aee7/investigations` with request_id 288e0c6d-2f2d-40d0-951b-c43ba1e2eec7. The dedicated Graph ran six model requests, observed get_exception_case -> analyze_fulfillment -> search_knowledge, entered final_only, rejected one investigation response and one report response, then returned backend HTTP 200 after 579.375 s. Final report: observed_delay/unknown, all four event IDs and the distinct SOP chunk ID; all six handoff sections. Offline `verify` passed every retained check. Source: scripts/investigation_page_run_20261019T143557352050Z_3de46dd5.json and .jsonl; acceptance: scripts/investigation_page_acceptance.json. Backend error_code is absent. The 3109 Next proxy logged ECONNRESET/socket hang up and the browser displayed a failure, so browser delivery is NOT accepted as passed. Existing Next 15 dev rewrite code has a 30 s default proxyTimeout, shorter than the 690 s Core deadline; the log does not separately prove whether the browser disconnected.

Minimal correction: frontend/next.config.ts sets dev proxyTimeout to 720000 ms so it can carry a bounded 690 s API response; Next restarted and acknowledged the setting. The investigation page now shows the retained organization ID while its name is unavailable, rather than claiming no organization was selected. Submit permission checks are unchanged. The demo verifier now names the actual latest snapshot, preserving the historical failure evidence. Frontend typecheck and targeted ESLint, runner syntax and Ruff, and offline verifier passed; 3109 login and 8124 OpenAPI returned 200 after restart. No new model request, fixture write, or investigation POST was made during diagnosis. Long-running browser response delivery after the config change remains unverified.

## 2026-10-19 Controlled 3109 proxy delay check

Before any second browser model request, a temporary read-only/no-model endpoint on the existing isolated 8124 demo API delayed exactly 40 s. One actual GET through 3109 returned HTTP 200 and the sentinel JSON after 40.179 s; backend logged request_id 02a4cc1c-6edd-4b14-813a-3863bcca7621, HTTP 200, duration 40057.54 ms. This exceeds the old 30 s Next dev-proxy default. The running Next process acknowledged experimental proxyTimeout 720000 ms. The probe was removed, 8124 restarted, the probe now returns 404, and 3109 login/8124 OpenAPI both return 200. Evidence: scripts/investigation_page_proxy_probe_20261019T1457Z.json. This is a controlled 40 s delivery check, not a full 720 s wait or a second Graph/browser acceptance. The latest Graph pointer still names request 288e0c6d-2f2d-40d0-951b-c43ba1e2eec7. Await exactly one user-initiated browser submit for final report-display acceptance; no model or database resource was touched by the probe.

## 2026-10-19 Browser report acceptance and concise presentation

User confirmed the 3109 browser displayed the complete report for request_id 422fec17-c22c-410d-bee3-ec746132f58d and case 59db2e27-ac93-4ef0-b939-a72ac2b5113a, including four business event citations, one separate SOP source and the six-part handoff. The retained per-run JSON/JSONL independently show Graph path get_exception_case -> analyze_fulfillment -> search_knowledge, final_only after retrieval, six model requests, two rejected drafts, backend HTTP 200, no error_code and elapsed 558.157 s. Offline verifier passed every retained check. Source: scripts/investigation_page_run_20261019T150109651854Z_eae597fa.json and .jsonl; verification: scripts/investigation_page_acceptance.json. This accepts the user's observed report delivery, not unobserved browser interactions. No model request was repeated.

For presentation, the authenticated API now adds optional read-only `observations` copied from the successful analysis trace: shipment/delivery status, promised/actual times, difference seconds, scope, tracking, reason and whole-order completion. Original validated `report` and complete `handoff` remain unchanged. The page derives Chinese timing text from these fields, shows Beijing time, root cause/whole-order limits and the precise gap that the late-shipment reason field is not provided. It displays a concise six-part handoff by default and places the complete original six-part text, raw report JSON, full event/SOP IDs and source text in expandable evidence details; request ID has a copy control. It does not invent a cause, action execution or automatic follow-up. The phrases '????' and '?????' are absent from retained raw response, renderer and frontend source; browser translation or another display layer is unconfirmed, so no speculative wording change was made.

Changed backend/app/schemas/investigation.py, backend/app/api/v1/endpoints/investigations.py, frontend/src/lib/api/investigations.ts, frontend/src/lib/investigation-presentation.ts, frontend/src/app/(dashboard)/investigations/page.tsx and added scripts/investigation_presentation_verify.cjs. Offline fixed-response replay, direct endpoint composition with controlled provider and no DB/model, frontend typecheck and targeted ESLint, backend syntax/Ruff all passed. 8124 restarted; its OpenAPI exposes optional observations and 3109 investigations page returns 200. The new visual layout, expand/copy interactions and long-request delivery of the NEW response have not been manually browser-tested. Existing demo resources were retained; no migration or business write. Personal learning is not marked PASS.

## 2026-10-20 Resume V2.0 evidence handoff

The only resume baseline reviewed was the user-designated V2.0 one-page file dated 10.18 under D:/1.[personal folder]/jianli; no resume file was modified or exported. The five proposed Project A bullets cover current LangGraph Core orchestration, authorized SOP retrieval with separate event/source citations, enterprise/workspace permissions, ActionRequest approval/idempotent transactions, and scoped Celery document ingestion. Keep the existing project title/date and one-sentence business overview; personal information and employment content were untouched. Delete unsupported resume claims of a Redis lock or a general concurrency limiter; describe the actual PostgreSQL unique key, row locks, task deadlines and bounded Agent requests instead. Keep internal notification records distinct from external delivery.

README's Project A section now separates 2026-10-19 controlled Graph parity (11 scenarios; 90 related offline tests recorded in the prior handoff), the 2026-10-18 legacy-loop real C05, 2026-10-19 current-Graph real browser report, C10 isolated retrieval with controlled chat Provider, 21 targeted isolated PostgreSQL ActionRequest tests plus JWT HTTP evidence, and one real isolated Celery success/failure/duplicate run. Counts from different methods or versions are not combined. New report-layout visual/expand/copy behavior, full scenario matrix, persistent Graph recovery, and external notification delivery remain unverified or absent. No model, database, test suite or migration was run for this resume/documentation turn.

## 2026-10-20 订单库存分配受阻调查最小闭环（未提交）

当前基线 7c9e736 已由用户推送；保留原有未提交的 frontend/next-env.d.ts、frontend/tsconfig.json 及演示数据。本轮没有调用聊天模型、运行场景矩阵、改动业务库或提交推送。旧报告契约只允许 root_cause=unknown；库存快照仅属组织/SKU 线索，不能证明某订单缺货或造成延迟。现新增订单关联的 `inventory_allocation_failed` 事件，以及明确引用该失败事件的 `shipment_delay_attributed` 事件；两者有发生时间、来源记录号、运单和既有订单/企业范围。只有发货确实晚于承诺，且关联事件与失败事件同来源、同运单、同订单/企业、符合承诺/发货时间边界并且关联唯一时，Service 才标为 `linked_to_shipment_delay`，报告契约才允许 `inventory_allocation_blocked`；仅有失败记录时只确认“分配受阻已记录”，延迟原因仍为 unknown。负库存不归因规则保留；不宣称具体欠货数量、送达或整单根因。固定事件均为合成验收数据，不是生产案例。

变更范围：`backend/app/models/fulfillment_event.py`、`backend/alembic/versions/0008_order_allocation_evidence.py`、`backend/app/services/fulfillment_service.py`、`backend/app/ai/agents/{investigation_report,core_agent,core_graph}.py`、`backend/app/schemas/investigation.py`，以及调查页的 API 类型、展示、回放脚本和直接相关测试。原 API 输入、预算、阶段边界和知识引用契约未放宽；报告保留六部分交接单，把失败事实、引用与时间、未确认的因果、对应建议（尚未执行）分开显示。展示使用结构化 `observations.allocation`，不解析中文报告；旧响应仍可显示。0008 只在隔离随机 schema 测试，未迁移业务库；在已有旧 schema 上部署新 ORM 前必须按正常变更流程应用 0008，受保护演示库本轮不变。

验证：2026-10-20 定向离线单测先有 99 项通过（含受控 Provider 的 Graph/旧循环新场景、来源与时间边界、负库存旧规则）；新增 HTTP 投影用例单独 1 项通过；最后收紧关联时间边界后再跑直接相关 42 项，全部通过。隔离 PostgreSQL `ragforge_day6_test` 测试在收紧时间边界前通过 1 方法、模型建表/0008 迁移两个子场景，真实查询验证早于关联时点不归因、同订单关联可用及跨企业/订单引用不归因；测试辅助器回滚后确认随机 schema 不存在。收紧边界后的再次 PG 连接被拒（现有 `.env` 凭据认证失败，未创建 schema），故该最终微调只有离线验证，不把先前 PG 通过说成最终源码的完整 PG 验收。固定响应前端回放、typecheck、定向 ESLint、Ruff、`git diff --check` 通过。回放与数据库测试均非真实模型/浏览器验收；新根因场景尚无真实模型或页面手工验收，也没有生产来源事件接入。本轮不标记个人学习 PASS。

## 2026-10-20 分配受阻调查收口：隔离 PG 认证阻塞

本轮未改源码、测试、报告契约或演示数据。定向核对 `scripts/day6_verify.py`、`scripts/action_request_verify.py`、`backend/tests/commerce/test_day6_postgres.py` 和 Compose：目标固定为宿主 `localhost:5433`、库 `ragforge_day6_test`、用户 `ragforge`；配置由根 `.env` 读取，再由同名进程环境变量覆盖，本轮进程无 `POSTGRES_USER`/`POSTGRES_PASSWORD` 覆盖。使用当前 `.env` 值的最终版定向 PG 复核在认证前被服务拒绝，原始异常为 `password authentication failed for user "ragforge"`；未进入建 schema 或迁移阶段，不能据此断言最终版 PG 通过。Codex 内 Docker 只读查询被 `C:\Users\xingk\.docker\config.json: Access is denied` 和 Docker API named pipe `permission denied` 阻断，不能核对容器当前凭据；不误判 Docker 引擎停止，也不推断密码为什么变化。不重试、不重置密码、不改 `.env`。本轮未创建临时 schema/collection/Redis key/进程；此前隔离 PG 通过轮次的随机 schema 已由测试辅助器核实回滚。报告及页面只把分配失败列为订单事实，明确关联才说该运单发货延迟有关，整单/其他原因仍未确认，建议标注尚未执行；措辞检查无须修改。剩余：用有效的隔离 PG 凭据完成最终源码的单项定向 PG 复核；真实模型、浏览器及生产来源事件接入仍未验收。未 commit/push，本人学习不标 PASS。

## 2026-10-20 用户本机完成最终版隔离 PG 复核

用户在普通 PowerShell 用本项目现有 postgres 容器凭据运行 `test_order_allocation_postgres.OrderAllocationPostgresTests.test_model_and_migration_support_real_scoped_causal_read`，反馈原始终端结果 `Ran 1 test in 1.536s`、`OK`、退出码 0；本轮 Codex 未重跑，也没有单独归档终端日志。源码核对：1 个 unittest 方法内部含 `models` 和 `migration` 两个 subTest，后者在临时 schema 对旧 0002/0003 结构应用 0008；两者均在 `ragforge_day6_test` 中写入合成承诺、发货、分配失败和明确延迟关联事件，验证关联事件尚未进入观察时点时因果未知、进入后同订单运单延迟可关联，并用另一企业/订单引用原企业失败事件验证不能跨范围归因。共享 Day6 测试辅助器先校验数据库名，在随机 `day6_test_*` schema 内运行，finally 回滚事务、查询 `pg_namespace` 断言 schema 已不存在，并 dispose engine；由于整个方法 OK，两轮均通过这些清理断言。未额外执行独立的运行后残留普查。

相对已推送基线 7c9e736，本轮未提交源码新增了订单级分配失败/延迟关联事件及 0008、保守的履约 Service 归因、Graph/旧循环报告契约与六部分交接单措辞、只读 API 观察字段及调查页展示，并有离线与隔离 PG 定向测试。仅记录“该运单发货延迟有明确关联”，不称整单或唯一根因；仅有失败事件、库存快照或 SOP 仍不能归因。原受保护演示库和业务库未迁移。剩余验收：将真实来源事件接入后验证数据真实性，在已按正常流程应用 0008 的隔离页面环境进行真实模型/浏览器路径验收；本轮不执行这些步骤，不运行全矩阵，不 commit/push。本人学习不标 PASS。

## 2026-10-21 分配调查单轮性能收口

原页面请求 `e4430dbb-e536-480d-a1a9-401431997ccf` 的前两轮模型分别用 100.187、106.281 秒，第三轮在 Graph 的 180 秒截止；工具合计仅 0.078 秒。历史响应未存 Ollama token/加载/输入处理/生成计数，Provider 原先丢弃服务端时长。现已让 Ollama Tool Response 保留白名单性能计数并由隔离 runner 记录；历史证据不补写。原第三轮单轮探针 `scripts/investigation_allocation_latency_probe_e4430dbb.json` 在 180.312 秒截止。

优化仅移除已成功读取且固定范围不可重复的案件/分析工具定义，Graph 与旧循环保持一致；完整业务观察、必需 SOP 工具、权限/预算/报告校验不变。离线重建第三轮由 3 工具降为仅 `search_knowledge`，请求体 12321→11207 字节；本机 GGUF tokenizer 加 Ollama 模板估算提示约 3569 token，运行上下文 4096、输出上限 700，完整预留输出时输入预算 3396，故不能声称 700 token 输出余量充足。无 SKU 及待办库存/事件读取，SOP 仍待检索。直接相关的 Graph/知识/Provider 47 项、边界 47 项及更新断言 2 项离线通过；这不等于真实提速。

本轮唯一优化后第三轮单轮探针 `scripts/investigation_allocation_optimized_probe_e4430dbb.json` 使用同一模型/参数/180 秒截止，在 180.281 秒再次截止，未返回工具调用或服务端性能计数；与原探针相差 0.031 秒，不能据单次截止比较认定改善。探针期间 Ollama 显示 `llama3.1:8b` Q4_K_M、4096 上下文、约 15% CPU/85% GPU，GTX 1650 Ti 一次采样 99% 利用率；历史请求当时的设备分配未知。未调用调查 API、业务工具或数据库，未动隔离演示数据，也未重跑完整场景。停止同配置探针；下一候选是仅对调查决策阶段评估较低 `num_predict`，以释放 4096 上下文的输出余量，代价是可能截断合法工具参数，须在后续受控验证中核对；最终报告上限和验收规则不变。本轮未实施该候选，不下载模型、不提高超时，不标个人学习 PASS。

## 2026-10-21 调查决策轮 256-token 单次探针

Provider 的 `max_tokens` 会传至 Ollama `options.num_predict`；此前 Core 两阶段均未单独传值。本轮只让调查决策轮显式传 256，报告轮仍使用原默认上限；Graph 与旧循环一致，180 秒截止、工具/引用/权限/预算规则不变。离线重建第三轮仍有完整 7 条消息和必需 `search_knowledge`，代表性合法原生调用为 147 ASCII 字节（仅证明该短调用有输出空间，非服务端 token 实测；任意长查询不作保证）。定向 Graph/Provider 检查分别运行 4 项与 14 项，均通过；截断响应在执行知识工具前拒绝。生产代码、Graph 回放和探针脚本 Ruff/语法检查通过；Provider 测试文件全量 Ruff 仍有 3 条既存、与本轮新增用例无关的样式提示。

唯一探针证据 `scripts/investigation_allocation_decision_256_probe_e4430dbb.json`：同一 `llama3.1:8b`、7 消息、只提供 SOP 工具，`num_predict=256`、180 秒截止，180.265 秒超时；无模型响应、工具调用或服务端 token/耗时计数。先前 700-token 优化探针为 180.281 秒超时，两次均被相同截止截断，不能判定提速或原因；本轮不具备单次完整场景验收条件。未发起调查 API、检索或数据库访问，演示数据未改。停止同配置探针。下一候选是定向压缩第三轮重复的决策说明文本（保留全部观察、SOP 权限和证据规则），为 4096 上下文留输入余量；代价是需要离线对照防止改变模型决策，且没有服务端阶段计数前不能保证提速。未实施该候选，未提高超时、换模型或重跑完整调查；本人学习不标 PASS。

## 2026-10-21 第三轮决策上下文精简与单次探针

先前最小工具对照 `scripts/investigation_allocation_run_minimal_tool_probe_e4430dbb.json` 用同 Provider/模型/256 输出上限，以 207 输入、29 输出 token 在 27.547 秒返回合法原生 `search_knowledge`；服务端输入处理 13.541 秒。本轮仅对干净的“案件读取→履约分析→必需 SOP 待检索”第三轮建立临时精简请求：保留完整原始 trace 和报告阶段历史，模型本轮收到系统规则及一条明确标记为不可信工具数据的用户消息，内含企业/案件/订单/分析时点、原请求和两项未删字段的观察；跳过已有原生调用外壳与重复决策说明。Graph 和旧循环共用构造，检索工具、服务端权限及报告校验不变。真实失败样本离线逐字段比对两项观察完全一致，6 个业务事件 ID、分配关联/运单/时间均保留；消息合法，且只提供 `search_knowledge`。Graph/旧循环 14 项、边界 47 项及最后两项定向断言通过；恶意观察文本仍为数据，模拟跳过必需检索被服务端拒绝。替身不能证明真实模型行为等价。

唯一精简探针 `scripts/investigation_allocation_compact_probe_e4430dbb.json` 未执行真实工具：请求由 7 条消息、11207 字节降为 2 条、7483 字节；同一 `llama3.1:8b`、`num_predict=256`、180 秒截止，146.859 秒返回可解析的原生 `search_knowledge`，服务端计数为输入 2187、输出 29 token；总时长 146.596 秒，其中加载 10.442、输入处理 130.631、生成 5.514 秒。此前第三轮两次均在约 180 秒截止且无服务端计数，不能用单次结果推断稳定提速。返回查询针对运单延迟，但没有点明库存分配失败；真实知识命中、引用与最终报告尚未验证。可安排一次完整验收尝试，先做常规依赖/隔离数据预检，不保证结果通过；本轮未调用调查 API、检索、数据库或完整场景，未改演示数据，也未提交推送。本人学习不标 PASS。
当前 8125 隔离 API 于本次源码变更前启动，serve() 未开启 reload；后续真实页面验收前须先按现有方式重启该隔离 API 并核对服务加载新版代码。本轮未重启。

## 2026-10-21 单次完整验收预检阻断
已核对保存状态中的 allocation_demo 案件、工作区、collection 标识与旧失败记录；受 PG 凭据限制，本轮尚未完成在线资源预检。8125/3110 仍在运行，未见本任务活跃调查或 Ollama 请求。新版第三轮上下文尚未加载到旧 8125。Codex 沙箱执行本项目 Docker 查询返回 config.json Access is denied 和 docker_engine named pipe permission denied；本进程无隔离 PG 凭据，因此未停止旧 API、未重复试失效 .env，也未发起调查。新增 scripts/restart_investigation_allocation_api.ps1：普通 PowerShell 中只读容器身份/端口/隔离依赖/保留数据后仅重启本轮 8125，保留 3110 与演示数据；语法通过。新增 scripts/investigation_allocation_http_once.py：服务就绪后用现有成员认证、保存状态及 3110 代理仅提交一次，POST 前写固定路径防重复标记；语法/Ruff 通过但尚未运行。需用户在普通 PowerShell 执行重启脚本并返回 READY，之后 Codex 执行该唯一 HTTP 提交、读取 runner 轨迹和验收；当前没有本轮模型/数据库写入，未宣称通过，不标个人学习 PASS。

## 2026-10-21 订单分配受阻场景单次真实 Graph/API 验收
用户在普通 PowerShell 启动脚本确认 8125 READY（新 PID 35060），3110 保留；隔离 PG、Redis、Qdrant、原案件/6 条事件/SOP collection 预检通过。提交前本轮防重标记不存在、无活跃同任务请求。随后仅运行一次 `scripts/investigation_allocation_http_once.py`，使用保存状态中的 case_id `7beb2d8e-7ec6-4aef-b48e-3308a8881a21`、workspace_id `61730353-ee16-470b-916e-7c3b5117875f`、as_of `2026-10-20T18:37:15.004234+00:00`、`require_knowledge=true`，经 3110 代理进入当前 Graph；防重标记和客户端响应保存于 `scripts/investigation_allocation_run_http_client_20261021.json`。

结果 **未通过**：request_id `2b4100f8-8fc2-41f5-ac77-35695c4ae23e`，HTTP 502、`error_code=model_timeout`，Graph 耗时 513.282 秒（客户端 514.125 秒）。工具路径 `get_exception_case(found) → analyze_fulfillment(found) → search_knowledge(found)`；报告阶段 `final_only` 已进入，但第 4 次模型请求在单轮 180.016 秒截止时取消，未返回报告；690 秒总截止未触发。无报告拒绝记录，也无六部分交接单或可供无模型回放的成功报告。逐轮模型耗时 90.609、112.453、127.062、180.016 秒；前三轮有服务端计数，第四轮没有。原始证据 `scripts/investigation_allocation_run_20261020T200910720967Z_e78899e0.json` 及同名 `.jsonl`；直接验收 `scripts/investigation_allocation_acceptance.json` 为 `passed=false`，业务/知识路径、知识命中、阶段及订单分配关联检查通过，报告/引用/限定措辞检查因报告缺失未通过。

分析工具返回同一运单发货晚 3600 秒、送达早 3600 秒，订单级分配失败事件与明确延迟关联事件均在六条业务证据内；其 `causal_status=linked_to_shipment_delay` 仅支持该运单发货延迟关联，不代表整单或唯一根因。SOP 单独以授权 chunk 命中，但没有最终报告，故业务事件与 SOP 来源的报告引用无法验收。该调查轨迹只有只读工具，未执行处置或发送通知。本轮未新建或清理隔离演示资源，保留原数据、服务及全部失败证据；没有自动重试、修复、提交或推送。API 验收失败，浏览器展示未验收；本人学习不标 PASS。

## 2026-10-21 报告轮上下文精简与唯一探针
针对 request_id `2b4100f8-8fc2-41f5-ac77-35695c4ae23e`，仅复用 `scripts/investigation_allocation_run_20261020T200910720967Z_e78899e0.json` 的三项真实工具结果，不重查数据库/检索、不运行调查前三轮。原证据记录第 4 轮进入 report 后 180.016 秒取消，但未持久化第 4 轮完整模型请求、其输入 token 或服务端计数；历史精确输入不可恢复。当前源码推导的干净报告轮带原始 user/assistant/tool 调用外壳及重复提示。仅在三项读取均成功、消息角色/工具顺序匹配、没有报告纠错的分支，改为一条含完整 scope、原请求和三项原样观察的 user 数据消息；系统仍保留原报告契约，报告工具列表为空、原 4096 输出上限及 180 秒外层截止不变。修改 `backend/app/ai/agents/core_agent.py`、`backend/app/ai/agents/core_graph.py`；新增 `scripts/investigation_allocation_report_probe.py`。

离线检查 `scripts/investigation_allocation_report_compaction_check_20261021.json` 通过：当前源码重建的线缆消息 9→2 条、UTF-8 JSON 7510→5971 字节（不是历史真实 token 计数）；三项完整观察、六条业务事件 ID 与一条独立 SOP chunk ID 均保留。直接调用 Graph 决策节点的受控 Provider 检查确认走精简报告分支、无工具、max_tokens=None（由当前配置映射为 4096）。原校验器对完整预期结构通过，对漏掉业务引用、伪造 SOP 来源和错误根因均拒绝；Ruff 与语法检查通过。

唯一模型探针 `scripts/investigation_allocation_report_probe_20261021.json`：`llama3.1:8b`、输入线缆 5971 字节、外层 180 秒、无工具；本地 Provider 的 `LLM_REQUEST_TIMEOUT_SECONDS=120`；120.29 秒返回 `UpstreamProviderError`，与该 HTTP 截止吻合，但底层 HTTP 异常子类未保存，未取得报告或服务端 token/耗时计数，不能判定 180 秒内模型是否会返回。探针证据原样保存，不再试跑、未放宽校验或预算、未调用调查 API/业务工具、未改演示数据。此项未通过保存观察的报告轮验证，更非完整 E2E 或浏览器验收；下次试验前须先核对探针与实际 API 的 Provider HTTP 截止是否一致，并确认服务端该请求是否仍在执行，不据此推断模型性能。未 commit/push，本人学习不标 PASS。

## 2026-10-21 报告轮探针配置对齐与单次结果
定向确认配置来源：`scripts/investigation_allocation_demo.py:serve` 调用 `configure`，进而复用 `scripts/investigation_page_demo.py:configure`，在创建 OllamaProvider 前将 `LLM_REQUEST_TIMEOUT_SECONDS=190`、`LLM_MAX_TOKENS=700` 写入进程内 settings；Provider 构造在 `backend/app/ai/llm/ollama_provider.py` 从该 settings 创建 HTTP client，并把报告轮的 `max_tokens=None` 映射为 700。此前独立探针绕过演示 configure，使用 `.env`/默认 120 秒与 4096；旧证据仅保存 `UpstreamProviderError`，底层异常子类未保存，不能仅凭 120.29 秒定论。Graph 单轮 180 秒及演示 runner 总 690 秒未改。本轮无法读取已运行 8125 进程环境（CIM Access denied），但启动代码路径和真实前三轮 127 秒返回与 190 配置一致；不宣称已直接读取运行进程的内存参数。

修订 `scripts/investigation_allocation_report_probe.py`，在独立进程复用同一演示 configure、记录有效 HTTP/输出参数和异常链类型；不连接业务库或检索。离线对齐检查 `scripts/investigation_allocation_report_aligned_check_20261021.json` 通过：保存的三项完整真实观察、六条业务事件 ID 与一条 SOP chunk ID 不丢；报告线缆 2 条/5971 字节（字节数非 token）；当前配置为 190/700、Graph 单轮 180。唯一对齐模型探针 `scripts/investigation_allocation_report_aligned_probe_20261021.json`：`llama3.1:8b` 返回，耗时 178.007 秒，未超时、无工具调用、stop_reason=stop；服务端输入 1908、输出 126 token，总 177.716 秒，其中加载 22.015、输入处理 129.254、生成 26.397 秒。模型调用无异常链；原 `validate_report` 抛 `ValueError: Missing, duplicate or invented event citations`，状态 `report_rejected`。报告未校验通过，也未生成六部分交接单。探针当时未保存被拒候选 JSON，故无法确定具体缺失/重复/伪造的 ID；随后仅修正探针今后的响应留存和独立 SOP/六部分检查，未再调用模型。脱敏复核见 `scripts/investigation_allocation_report_aligned_review_20261021.json`，Ruff/语法检查通过。

本轮只验证保存观察的报告轮，未重查 PG/Qdrant、未运行完整调查、未改原演示数据或其他模型配置。报告轮仍未通过；下一次完整 Graph/API 及浏览器验收均待有效报告后另行进行，不能把本探针称作 E2E。未 commit/push，本人学习不标 PASS。

## 2026-10-21 保存观察的报告阶段引用纠错单次验证
仅复用 `scripts/investigation_allocation_run_20261020T200910720967Z_e78899e0.json` 中的案件、履约分析和成功 SOP 检索三项原始观察；未连接 PG/Qdrant、未重跑调查前三轮。原报告精简消息包含完整观察，却未单列六条必引业务事件 ID 和独立 SOP chunk ID；原 Graph 报告反馈只明确漏引事件，未分列重复、未观察 ID 与 SOP 差异。本轮在 `backend/app/ai/agents/core_agent.py` 的报告数据消息中加入从原 `evidence_contract(trace)` 计算的 `required_report_citations`，不补写模型输出；报告纠错反馈列出候选的 missing/duplicate/unobserved 两类引用差异，并保持原契约与缺完成时间提示。`backend/app/ai/agents/core_graph.py` 复用该反馈，未放宽校验、预算、权限或因果边界。

`scripts/investigation_allocation_report_probe.py` 新增直接调用当前 Graph 报告决策/校验节点的受控报告阶段入口：每轮先落盘原始模型响应，再解析候选 JSON 和调用原 `validate_report`，保存差异、反馈、耗时及异常链类型；最多首答加一次纠错，单轮 180 秒、阶段 690 秒，实际 Provider 190 秒、报告 num_predict 700。原三项读取后的模型预算计数从 3 起，最多两轮，不越过原 9 次上限。原始候选文件用 `.gitignore` 中精确规则只留本地，不含凭据；不覆盖历史失败证据。离线检查 `scripts/investigation_allocation_report_stage_check_20261021.json` 通过：必引 6+1 列表精确、完整观察不丢，漏引/重复/未观察和 SOP 差异反馈准确；受控替身回放证实 Graph 漏引→一次纠错→合格报告，Ruff/语法通过。

唯一真实报告阶段验证 `scripts/investigation_allocation_report_stage_probe_20261021.json`：首轮 167.580 秒服务端总耗时，输入 2100/输出 126 token；候选为 `observed_delay`、`inventory_allocation_blocked`，引用一条 SOP 来源，但仅引用六条必需业务事件中的两条。原校验器拒绝，准确差异为缺少 4 条业务事件、无重复或未观察 ID。原始响应、解析候选及包含 4 个缺失 ID 的反馈均已保存。第二轮仅一次纠错请求，因 Graph 180 秒单轮截止返回 `model_timeout`，异常链类型 `CoreAgentError → TimeoutError → CancelledError`；没有第二份模型响应或服务端计数。第二轮按现有 Graph 纠错路径发送了 10 条消息、9164 UTF-8 字节（包含历史工具调用外壳），这是本次已记录的后续耗时线索，不能断言唯一原因。报告阶段合计 347.907 秒，未触及 690 秒上限，无合格报告或六部分交接单、无可用回放。未追加模型调用、未修改演示数据、未 commit/push；完整 Graph/API 与浏览器验收仍待完成，本人学习不标 PASS。

## 2026-10-21 报告纠错上下文一致化与实验状态
仅修改 `backend/app/ai/agents/core_agent.py`、`backend/app/ai/agents/core_graph.py` 的当前 Graph 报告纠错消息选择：在三项成功且结构匹配的保存观察路径中，首答仍用一条完整、标注为不可信工具数据的精简消息；一次报告拒绝后复用同一观察消息，只追加被拒候选和原校验差异反馈。若历史结构或反馈不匹配则退回原路径，不删除证据、不补写引用、不修改原 validator、权限、9 次请求预算、180 秒单轮或 690 秒总截止。测试入口 `scripts/investigation_allocation_report_probe.py stage-compaction-check` 使用保存的三项真实观察与受控 Provider，验证首答消息角色 `user`、纠错角色 `user/assistant/user`、两轮同一完整观察、6 条业务与 1 条 SOP 来源均保留；错误首答被拒，纠正后完整报告通过，连续错误报告仍为 `ungrounded_final`。证据 `scripts/investigation_allocation_report_stage_compaction_check_20261021.json`；Ruff/语法检查通过。未调用模型、数据库或检索，未重跑完整调查。

`README.md` 将新增“订单库存分配受阻调查”单独标为 **Experimental / 实验中**：合成数据上的 Service/隔离 PG 与离线验证已通过，真实授权 SOP 检索成功，但最终报告引用校验和完整 Graph/API、浏览器验收未通过。原有已通过调查主线及全部失败证据保持原样。要形成可演示的新场景，仍需未来一次真实报告通过原业务与 SOP 引用校验并生成六部分交接单，再完成单次完整 Graph/API 和页面展示验收；本轮没有宣称模型行为等价或 E2E 通过。未 commit/push，本人学习不标 PASS。

## 2026-10-21 当前版本收尾：离线回归与演示边界

订单库存分配受阻仍为实验中：合成订单级证据的 Service、隔离 PG 与离线契约已有通过记录，真实 SOP 检索成功；最终报告引用校验、完整 Graph/API 和浏览器验收未通过。本轮没有调用模型、运行完整场景或改变原始失败证据。

公共 Core/Graph 定向离线回归首轮运行 93 项，其中 83 项通过、10 项因旧测试固定要求历史消息外壳或旧反馈文字而失败；测试断言改为保留结果、工具序列、预算、拒绝记录及权限边界校验，同时允许当前已验证的精简消息结构。仅复核受影响的 40 项：先通过 39 项，修正一项对历史回退路径的预期后单独通过该项；这是分次定向结果，不称一次 93 项全绿。另有调查 API/Provider 相关 40 项通过，覆盖认证与工作区边界、响应脱敏及工具协议。此前 `scripts/investigation_allocation_report_stage_compaction_check_20261021.json` 的离线报告纠错检查复用，未重跑。相关 Ruff、`git diff --check` 和 README/演示/交接的相对链接检查通过。

`docs/PROJECT_A_DEMO.md` 增加“历史真实结果回放”入口：使用本地保存的 2026-10-19 当前 Graph 成功报告，经 `node scripts/investigation_presentation_verify.cjs --preview` 生成无 API/模型/数据库访问的本地 HTML；源 JSON 仅本地留存。申请创建、管理员审核和站内通知记录的独立演示步骤继续保留，站内记录不代表外部发送或客户收悉。回放不算当前代码新增 E2E。提交范围应只取本轮源码、迁移、直接相关测试、演示脚本与文档；排除原始 JSON/JSONL/日志、凭据、演示状态、虚拟环境及 Next 生成的 `frontend/next-env.d.ts`/`frontend/tsconfig.json`，另有 `backend/tests/commerce/test_day6_postgres.py` 仅换行变化，不纳入。未 commit/push，本人学习不标 PASS。

## 2026-10-21 保存观察的报告阶段单次复验（纠错后仍失败）

复用 request_id `2b4100f8-8fc2-41f5-ac77-35695c4ae23e` 的三项真实观察、既有离线通过证据 `scripts/investigation_allocation_report_stage_compaction_check_20261021.json` 与原 `validate_report`；未重查业务库或 SOP、未重跑离线测试或完整调查。预检未见连接 Ollama 的活跃客户端，`/api/ps` 无已加载模型。探针将本次证据另存为仅本地的 `scripts/investigation_allocation_report_stage_post_compaction_20261021.json`，没有覆盖上次失败。为使异常轮也有耗时记录，探针仅补 `finally` 计时；Ruff 通过。实际 Provider `llama3.1:8b`、HTTP 190 秒、报告输出上限 700，Graph 单轮 180 秒、报告阶段 690 秒，首答前已有 3 次模型请求；本阶段最多两次，没有自动重启。

首答使用一条精简的 `user` 消息、无工具，163.407 秒返回；服务端输入/输出 2100/126 token。候选 `observed_delay / inventory_allocation_blocked`，六条必需业务事件仅引两条，独立 SOP 引用正确；原校验器拒绝，四条缺失 ID 和反馈已保存。唯一纠错轮使用 `user/assistant/user`，其中复用原完整观察、附被拒候选与准确差异；77.820 秒返回，服务端输入/输出 2691/181 token。候选仍为相同限定结论、独立 SOP 引用正确，但仅引四条业务事件，仍缺两条；无重复或伪造 ID。原校验器最终返回 `ungrounded_final`，异常链 `CoreAgentError → ValueError`。阶段耗时 241.257 秒，两轮均未触发 180 秒超时，原始响应、解析候选、差异和服务端计数均在新证据中。失败属于**引用遗漏且一次纠错未补全**，不是本次生成超时；没有合格报告、六部分交接单或新场景回放，完整 Graph/API、浏览器仍未验收。未追加模型调用、放宽校验、自动补引用、commit/push；本人学习不标 PASS。

## 2026-10-21 报告阶段短编号引用验证（仅保存观察）

对照本地两份失败候选：六条必引事件均在完整分析观察中，分别对应发货、送达、分配失败及延迟关联；首答引 2/6，纠错引 4/6，漏引并非输入缺少事件。仅在当前 Graph 的精简报告阶段为已观察业务事件建立 E1…En、检索来源建立独立 K1…Kn；消息保留完整原观察、企业/订单/运单范围、来源、时间和关联，在映射旁标明事件摘要。模型仅提交短编号，服务端严格检查缺失、未知、重复、类型混用或直接提交 UUID，再还原为 UUID 交原 `validate_report`；不自动补引用、不改变 API 报告或归因契约。首答与一次纠错复用同一确定性映射，原始候选与映射只在本地探针证据中保存。调查工具、权限、预算和截止未改。

新增离线检查 `scripts/investigation_allocation_report_short_refs_check_20261021.json` 通过：6 个 E、1 个 K 的有效映射经原校验器和六部分渲染通过；漏事件、漏 SOP、未知编号、重复、业务/SOP 混用及直接 UUID 共 9 类坏候选均拒绝；受控 Graph 首答拒绝→一次纠错使用同一映射并通过。随后直接相关 Graph/知识离线回归 40 项通过，映射来源元数据微调后复核相关单项通过；Ruff 与差异格式检查通过。未重跑旧离线检查。

唯一真实报告阶段验证复用 request_id `2b4100f8-8fc2-41f5-ac77-35695c4ae23e` 已保存的三项真实观察，不重读 PG/Qdrant、不重跑完整调查。新本地证据 `scripts/investigation_allocation_report_stage_short_refs_20261021.json` 记录首轮无工具、E1–E6/K1 原始候选、映射、空引用差异、UUID 还原后的合格报告及六部分交接单；首答即通过，未用纠错。结果 `observed_delay / inventory_allocation_blocked`，限定为该运单发货延迟与分配受阻有关，整单其他原因未确认，建议未执行。实际模型请求 1 次、耗时 178.352 秒（接近 Graph 单轮 180 秒），服务端输入/输出 2299/64 token；该单次通过不证明稳定性。仅标“保存观察的报告阶段通过”，完整 Graph/API 与浏览器验收仍待完成；未 commit/push，本人学习不标 PASS。
## 2026-10-21 库存分配受阻完整验收预备与环境阻断

读取 `scripts/investigation_allocation_report_stage_short_refs_20261021.json`：保存观察的报告阶段首答通过，UUID 报告含六条业务事件与独立 SOP 来源，六部分交接单限定为该运单发货延迟关联、整单其他原因未确认、建议未执行；这仍非完整 Graph/API 结果。用当前 `investigationPresentation` 和该保存报告、原分析观察运行 `node scripts/investigation_presentation_verify.cjs --preview --allocation-stage-preview`，通过摘要（发货晚 1 小时、送达早 1 小时）、限定归因及六部分渲染检查，生成本地 `project-a-allocation-saved-report-preview.html`；这是 Node/HTML 无模型回放，不是浏览器交互验收。短编号 Graph 首答和纠错共用映射的既有受控检查继续有效，严格还原后仍由原 `validate_report` 验证。

为下一次唯一完整验收，隔离 runner 新增报告轮原始候选、解析 JSON、引用差异的本地 JSONL/快照记录，保留逐轮与工具耗时；客户端防重复证据改用新文件名，避免覆盖前次失败。受控 Provider 记录检查通过，Ruff 与差异检查通过。8125/3110 页面和 API 端口可用，保存的隔离状态仍指向 `ragforge_day6_test`、原案件/工作区；但 8125 进程早于短编号源码改动，尚不能用于新版完整验收。Codex 内 `docker compose ps -q postgres` 被本机 Docker config 及 named pipe `Access is denied / permission denied` 拒绝，不能按现有安全脚本读取本项目 PG 凭据并重启 8125；不误判 Docker 引擎停止，不修改权限或凭据。已请用户在普通 PowerShell 运行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\restart_investigation_allocation_api.ps1` 并回复 READY 或原始错误。当前新防重复文件不存在，**没有发起新的完整调查或模型请求**；完整 Graph/API 与浏览器展示待新版 API READY 后再按唯一一次原则执行。未 commit/push。

## 2026-10-21 库存分配受阻完整 Graph/API 单次验收

用户在普通 PowerShell 重启隔离 8125 后报告 READY（PID 10464），3110 保留。新进程启动晚于 core_agent.py/core_graph.py 的短编号改动；本次报告模型实际返回 E1–E6/K1，服务端还原为六条事件 UUID 与独立 SOP chunk UUID，确认新逻辑生效。只运行一次 scripts/investigation_allocation_http_once.py，使用保留的隔离案件、工作区、准确 as_of 和 require_knowledge=true；HTTP 200，request_id 350b8943-4dcc-493f-b090-11b8076265e4，客户端耗时 490.797 秒，无自动重试。原始本地证据：scripts/investigation_allocation_run_http_short_refs_20261021.json、scripts/investigation_allocation_run_20261021T131249224570Z_b4543abf.json 及同名 JSONL；验收摘要：scripts/investigation_allocation_run_acceptance_short_refs_20261021.json。原始轨迹与候选仅本地保留，不作为公开仓库链接。

实际 Graph 工具路径为 get_exception_case → analyze_fulfillment → search_knowledge，均 found；成功检索后进入 final_only 报告阶段。四轮模型耗时分别为 90.719、113.516、118.875、163.594 秒；工具耗时分别为 0.032、0.031、3.093 秒；本次无报告拒绝或纠错，引用差异全空。分析观察包含同企业订单/运单的分配失败来源及时间、独立的延迟关联事件，限定结论为该运单发货延迟与库存分配受阻有关；发货晚 1 小时、送达早 1 小时，整单其他原因及完成情况未知。原校验器通过 observed_delay / inventory_allocation_blocked、六条业务事件和一条独立 SOP 引用；六部分交接单完整，工具轨迹无处置或通知执行。单次通过不代表稳定率，也不是生产案例。

investigation_allocation_demo.py verify 初次仅因脚本中第五部分标题少“逐项”而误报；只将验收脚本标题对齐现有渲染器后，重读同一结果的全部 13 项检查通过，没有重新调用模型。node scripts/investigation_presentation_verify.cjs --preview --allocation-api-preview 复用这份 HTTP 响应通过当前前端展示逻辑的摘要、时间、限定归因、六部分及证据折叠检查，生成本地 file:///C:/Users/xingk/AppData/Local/Temp/project-a-allocation-saved-report-preview.html；这是无模型静态回放，浏览器实际交互尚待人工查看，不能标为浏览器端到端通过。原演示数据保留，未 commit/push；本人学习不标 PASS。

## 2026-10-21 分配受阻页面回放与提交范围复核

复用 request_id 350b8943-4dcc-493f-b090-11b8076265e4 的完整 HTTP 响应，没有调用模型或重新调查。原有静态 HTML 回放只验证共享展示映射，不是 React 页面。为手工验收新增本地回环入口 scripts/investigation_allocation_replay_proxy.cjs（3111 → 现有 3110）：真实登录/JWT、企业和工作区读取照常进行；仅匹配保留案件、工作区、必需 SOP 的调查 POST 在认证后返回保存结果，其他案件返回 409，未登录返回 403，绝不转发调查 POST。定向 HTTP 核对 login=200、matching replay=200、unauth=403、wrong case=409，回放页 GET=200；未输出凭据。浏览器自动化唯一一次 CDP 检查再次在 Page.enable 超时，保留临时 profile，不继续排障。故当前只能记“React 页面回放入口就绪、实际交互待人工验收”，不能把静态预览或代理 HTTP 检查记成 React 展示通过；具体手工步骤在 docs/PROJECT_A_DEMO.md。

README 验收表和 docs/PROJECT_A_BASELINE_EVIDENCE.md 新增 2026-10-21 后基线条目，注明完整 Graph/API 单次 HTTP 200、490.797 秒、首答 E1–E6/K1 引用齐全且无纠错、合成隔离数据、无稳定率及浏览器通过结论。相对已推送 7c9e736，必要变更为 0008 迁移、事件模型/履约 Service/公开观察、Core/Graph/Provider 与原校验规则、前端限定展示、直接相关测试、隔离 runner/启动与本地回放脚本、上述文档和本地证据忽略规则；依赖的 action_request_demo.py、investigation_page_demo.py、knowledge_retrieval_verify.py、0007 迁移均已在基线跟踪。排除 .venv-d4、原始 JSON/JSONL/log、演示状态、CDP profile、frontend/next-env.d.ts、frontend/tsconfig.json 和仅有换行差异的 test_day6_postgres.py。复用此前 40 项离线、42 项订单级离线及用户本机 1 项隔离 PG 结果；本轮新增本地入口 Node 语法/HTTP 守卫检查和相关前端 typecheck、定向 ESLint 均通过；34 个候选文件的定向密钥模式扫描无命中，差异格式检查通过，未跑全矩阵。React 展开/复制/时间视觉仍待手工验收；在文档准确保留此限制且白名单检查通过时，源码可作为单次 Graph/API 结果提交。不 commit/push，本人学习不标 PASS。

## 2026-10-21 3111 回放页面停在调查中：定向核查与本地代理修正

用户报告在 3111 提交保存报告回放后页面长时间显示“调查中”。只读核查：本地代理旧会话曾记录 saved_response_served，说明至少一次请求通过认证和案件/工作区匹配；但旧日志没有时间及 response finish，无法把该记录无歧义地归给用户点击，也不能确认旧响应已送达浏览器。8125 最近日志仅有 21:20:59 完成的原 Graph 调查 POST（request_id 350b8943-4dcc-493f-b090-11b8076265e4），没有新增调查 POST；latest 仍指向该已完成结果，相关端口无活跃等待连接。没有新模型请求或待停真实调查。前端源码请求相对 /api/v1，3110 演示启动配置 NEXT_PUBLIC_API_URL 为空；原浏览器网络细节因 CDP 故障未能直接采集。现有证据排除新 8125 模型运行，旧停点只能限定在代理响应送达或浏览器状态更新，不能武断归因。

仅修 scripts/investigation_allocation_replay_proxy.cjs：保存响应设置明确 Content-Length；对经 3111 的所有 investigation POST 设本地拦截边界，未知路径直接 409、不转发；记录脱敏的 host/path、HTTP 状态、完成耗时及未完成断开，不记录 JWT 或正文。确认原 3111 无活跃连接后只重启本地代理，未动 3110/8125。新入口 http://127.0.0.1:3111/investigations，代理 PID 15012。真实 JWT 定向 HTTP 回放在 420 ms 返回 200、5427 字节、原 request_id 和六条事件；新代理 finish 记录 host=127.0.0.1:3111、path 为企业调查 POST、耗时 414 ms。8125 latest 和调查 POST 日志保持不变。另用保存响应对前端 createInvestigationRunner 做无 API 的受控状态回放，pending → success 通过。上述不等于用户浏览器交互通过；须在 3111 刷新后手工再看页面，CDP 不再重试，本人学习不标 PASS。

## 2026-10-22 React 保存响应回放确认与展示收尾

用户手工确认 3111 的 r4 实际 React 页：保存响应 request_id `350b8943-4dcc-493f-b090-11b8076265e4` 到达 `report_rendered` 约 163 ms；调查结论和证据可见，证据能展开，完整请求标识复制正确。此项记为**实际 React 页的保存响应回放通过**，与 2026-10-21 的单次真实 Graph/API HTTP 200、490.797 s 分开；未发生新的浏览器到模型实时 E2E。随后 r5 仅调整布局：默认展示由结构化观察计算的发货晚 1 小时、送达早 1 小时、该运单延迟与分配受阻关联、整单完成及其他原因未知、未执行处置；原六部分交接单和技术证据分别折叠，原文区域 `translate=no`，完整引用与复制保留。保存响应及源码中均无“发送到达”“库存配置失败”“可疑交接单”或弯引号；浏览器翻译来源未证实，不改历史证据。具体资料缺口未列出时明确“不表示资料齐全”，页面不自动生成建议。

`node scripts/investigation_presentation_verify.cjs --preview --allocation-api-preview` 的保存响应/React 布局契约检查、前端 `npm run typecheck`、页面与展示映射定向 ESLint 均退出码 0；静态 HTML 只作回放辅助，不作为 React 浏览器证据。r5 新折叠布局的视觉确认仍待用户查看；r4 已确认的展开与复制不需重验。原始 JSON/JSONL、演示状态和凭据继续仅本地保留；本轮未调用模型、迁移业务库、commit/push，本人学习不标 PASS。

## 2026-10-22 调查报告 r6 末次展示精简

r5 的两个外层 `<details>` 源码均无 `open`，默认收起；用户反馈展开后原文仍使页面过长。r6 继续只改展示：默认仅留业务摘要和北京时间对比；展开六部分交接单先见六条由结构化报告/观察生成的短节，完整原文在第二层；展开技术证据先见六条业务事件、一条 SOP 来源和业务观察类型概览，完整 ID、JSON 及含 SOP 内容的原交接单在第二层。全文区限制高度并内部滚动，保留 `translate=no`、请求 ID 复制及原文逐字内容；未解析原文补造建议，未知事项和未执行状态仍明确展示。API、调查、权限和校验器未改。

保存的同一 HTTP 响应通过 `node scripts/investigation_presentation_verify.cjs --preview --allocation-api-preview`，检查四个详情均默认关闭、六短节/来源概览/完整内容位置、无默认 UUID 及滚动样式；前端 typecheck 和页面/展示映射定向 ESLint 均退出码 0。静态预览不算实际 React 浏览器通过；r6 视觉只待一次人工确认，r4 已验展开与复制不重验。上轮 34 个明确文件白名单仍覆盖本次所有修改，尚未执行暂存、commit/push；未调用模型，本人学习不标 PASS。

## 2026-10-22 r6 报告可见但提交按钮仍显示调查中

用户确认同一次 3111 保存响应回放已到 `state_committed_success` 和 `report_rendered`，随后没有新的 `submit_started` 或 `pending`；残留“调查中”的是提交按钮，不是报告状态。源码核对：按钮文字与 `disabled`、报告区域都读同一个 `view.status`；共享 Button 组件仅透传原生 button 属性，没有单独状态或缓存。因而可确认浏览器按钮 DOM 与已提交的 React 状态脱节；是否由浏览器翻译或开发热更新引起仍未知，不能据此归咎模型或代理。只在状态切换时用 key 重建提交按钮，并给按钮设置 `translate=no`；本地面板在成功提交后追加 `submit_button_ready` / `submit_button_mismatch`，不记录正文或凭据。r6 的报告层级和调查 API/校验器未改，页面脚本标记 r7。

复用同一保存响应运行 `node scripts/investigation_presentation_verify.cjs --preview --allocation-api-preview`：实际页面组件离线渲染验证 pending 按钮禁用、success/error 按钮恢复并可点击，success 同时有报告且无等待提示；原 runner 完成后再等待，状态仍为 success、按钮仍可点击。前端 typecheck、页面/诊断定向 ESLint 及差异空白检查通过；这些是离线检查，r7 实际浏览器按钮尚待确认。未调用模型、重试 CDP、暂存、commit/push，本人学习不标 PASS。

## 2026-10-22 Project A 本轮功能冻结与页面最终验收

用户已手工确认 3111 的 r7 保存响应回放：报告出现后按钮恢复“生成只读交接单”；连同先前确认的报告展示、r6 精简布局、证据展开和完整请求标识复制，保存响应的实际 React 页面交互验收完成，等待状态能退出。此结果仅是已有 HTTP 结果的浏览器回放；真实 Graph/API 仍只对应 2026-10-21 的一次 HTTP 200、490.797 秒、六条业务事件及独立 SOP 引用的合成隔离场景，不合并成新增实时浏览器到模型 E2E 或稳定率。页面布局与功能至此冻结；原始运行证据和演示状态仍只留本地，本人学习不标 PASS。
