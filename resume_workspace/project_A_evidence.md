# Project A｜项目经历证据库

本文件供求职材料取证，依据 [README 验收表](../README.md)、[脱敏证据摘要](../docs/PROJECT_A_BASELINE_EVIDENCE.md)、[调查持久化验收](../docs/PROJECT_A_INVESTIGATION_RUN_ACCEPTANCE.md) 和 [施工交接](../docs/PROJECT_A_CONTINUATION.md) 整理；只记录已完成的范围，不代表本人已独立掌握。下文 `scripts/` 原始运行文件仅留本地，不随源码基线提交。存档结果属于各自运行日期和实现版本，不能跨版本累加成通过率；早期历史证据与各次 commit 的逐项对应关系仍**需核对**。调查持久化实现已纳入并推送 `07cfe21`。

## 项目业务与实际交付

面向多企业的订单履约异常调查：认证成员选择企业、案件和授权 SOP 工作区，系统只读查询案件／履约事实并检索知识，校验业务事件与 SOP 来源后生成结构化结论及六部分交接单。后续客户通知由成员另行创建申请，经管理员人工批准／拒绝；批准后仍须单独执行，执行仅创建系统内 `not_sent` 通知记录。[调查 API](../backend/app/api/v1/endpoints/investigations.py)、[申请 API](../backend/app/api/v1/endpoints/action_requests.py)、[演示说明](../docs/PROJECT_A_DEMO.md)。调查报告**不会自动**创建申请，系统未发送邮件或短信。

## 已验证能力

| 能力及机制 | 关键代码 | 原始证据、日期与验证条件 |
|---|---|---|
| **LangGraph Agent 编排**：模型决策、工具校验／执行、报告校验为独立节点；共享状态约束阶段、来源、重复调用、预算及纠错。旧循环保留供等价对照。 | [Core Graph](../backend/app/ai/agents/core_graph.py)、[公开入口与旧循环](../backend/app/ai/agents/core_agent.py)、[对照回放](../backend/tests/unit/test_core_graph_parity.py) | 2026-10-19：11 组受控 Provider 离线对照一致，运行结论见[交接](../docs/PROJECT_A_CONTINUATION.md)；90 项相关离线测试的独立原始日志**需核对**。同日[当前 Graph 真实页面运行](../docs/PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/investigation_page_run_20261019T150109651854Z_eae597fa.json`，仅本地留存；未包含在仓库中）经用户确认收到报告，HTTP 200；不是当前版本 C01–C12 全矩阵。 |
| **SOP RAG 与双来源校验**：工作区内 Qdrant 向量＋PG/BM25 稀疏检索，经 RRF 融合；模型只能引用本次观察到的业务事件 ID 和检索到的 SOP chunk ID，两类来源分别校验。 | [知识 Tool](../backend/app/ai/tools/knowledge_tool.py)、[混合检索](../backend/app/ai/retrieval/hybrid_retriever.py)、[报告契约](../backend/app/ai/agents/investigation_report.py) | 2026-10-16 [真实隔离检索](../docs/PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/knowledge_retrieval_20261016T105924977902Z.json`，仅本地留存；未包含在仓库中）通过；2026-10-18 [旧循环真实 C05](../docs/PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/investigation_api_c05_20261018T052738639745Z.json`，仅本地留存；未包含在仓库中）单次通过；2026-10-19 [当前 Graph 页面运行](../docs/PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/investigation_page_run_20261019T150109651854Z_eae597fa.json`，仅本地留存；未包含在仓库中）及[验收核对](../docs/PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/investigation_page_acceptance.json`，仅本地留存；未包含在仓库中）记录四条事件、一条独立 SOP 来源与六部分交接单。已存档本地检索使用 `none` 重排，不能写学习型 Rerank 已验收。 |
| **企业／工作区权限链**：JWT 确认用户，企业成员和工作区 viewer 权限逐层校验；知识工具执行前重查权限，向量候选还经 PG 中 chunk/document 工作区归属回填过滤。 | [JWT 依赖](../backend/app/api/deps.py)、[调查入口](../backend/app/api/v1/endpoints/investigations.py)、[授权回填](../backend/app/ai/graph/nodes.py) | 2026-10-19 [C10](../docs/PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/investigation_api_c10_20261019T055925983902Z.json`，仅本地留存；未包含在仓库中）：真实隔离 PG／Qdrant／Redis／Embedding，**受控聊天 Provider**；授权来源进入模型输入，跨工作区正文、chunk 与来源 ID 均未进入，越权请求在读取前拒绝。非真实聊天模型验收；无单文档 ACL。 |
| **人工审批、事务与幂等**：企业＋幂等键由 PG 唯一约束兜底，同键异内容冲突；创建、审核、内部通知执行各自把状态与审计放在事务边界，审核／执行用行锁防双重决定和重复记录。 | [申请模型约束](../backend/app/models/action_request.py)、[Service](../backend/app/services/action_request_service.py)、[认证 API](../backend/app/api/v1/endpoints/action_requests.py) | 2026-10-19 [最终 21 项隔离 PG 测试](../docs/PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/action_request_20261019T084353824194Z.json`，仅本地留存；未包含在仓库中）全通过；[真实 JWT/HTTP 演示](../docs/PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/action_request_demo_http_20261019T080647172012Z.json`，仅本地留存；未包含在仓库中）覆盖创建→批准及另一申请→拒绝、权限与独立会话持久化。批准不执行；执行后仅有 `not_sent` 站内记录。 |
| **Celery＋Redis 文档入库**：生产者投递文档任务，worker 检查最新 job 状态及 task ID；解析、分块、Embedding 和索引完成后写入业务结果，完成后重复投递跳过业务写入。 | [生产者](../backend/app/services/document_service.py)、[worker](../backend/app/workers/tasks/ingestion_tasks.py)、[Celery 配置](../backend/app/workers/celery_app.py) | 2026-10-19 [隔离真实运行](../docs/PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/ingestion_celery_20261019T061835650013Z.json`，仅本地留存；未包含在仓库中）：Redis broker/worker、PG、Qdrant；一次成功、一次受控解析失败、一次**已完成 job**重复投递。重复后仍是 1 chunk／1 vector／1 usage；受控失败的 document/job 为 `failed` 且 Celery 为 `FAILURE`，重复任务本身为 `SUCCESS`。 |
| **调查提交持久化与刷新恢复**：提交占位先于长模型调用独立落库；企业、用户与参数范围内按提交键去重，报告校验通过才存为成功。授权历史读取重新检查企业与工作区；刷新可找回运行状态或已保存报告。 | [0009 迁移](../backend/alembic/versions/0009_investigation_runs.py)、[生命周期 Service](../backend/app/services/investigation_run_service.py)、[认证 API](../backend/app/api/v1/endpoints/investigations.py)、[调查页](<../frontend/src/app/(dashboard)/investigations/page.tsx>) | 2026-10-22 [脱敏验收](../docs/PROJECT_A_INVESTIGATION_RUN_ACCEPTANCE.md)：用户本机隔离 PG 专项 6 项、11.847 秒、OK；两轮分别用**受控 Provider＋真实 JWT/API＋隔离 PG**，一轮确认完成后刷新恢复报告，另一轮确认运行中刷新找回状态。每轮各有 1 条运行、1 份报告与 2 次 Provider 调用，不能相加为稳定率；不属于新的真实聊天模型验收。 |

## 可引用的小数字与条件

| 数字 | 准确范围与依据 |
|---|---|
| **11 组** | 2026-10-19 当前 Graph 对旧循环的**受控 Provider 离线**回放；[测试代码](../backend/tests/unit/test_core_graph_parity.py)和[交接结果](../docs/PROJECT_A_CONTINUATION.md)。不能写成 11 次真实模型调查。 |
| **21 项** | 2026-10-19 最后一版 ActionRequest 隔离 PG 定向测试，0 failure/error；[结果](../docs/PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/action_request_20261019T084353824194Z.json`，仅本地留存；未包含在仓库中）。不与早期版本的测试数相加。 |
| **2 次并发创建争同一键→1 申请、1 审计** | 一组受控双会话竞争；[测试代码](../backend/tests/commerce/test_action_request_postgres.py)与上述 21 项结果。不是高并发吞吐指标。 |
| **4 条业务事件＋1 条 SOP 来源** | 2026-10-19 当前 Graph 的**一次真实模型／用户浏览器收到报告**；[运行](../docs/PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/investigation_page_run_20261019T150109651854Z_eae597fa.json`，仅本地留存；未包含在仓库中）、[核对](../docs/PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/investigation_page_acceptance.json`，仅本地留存；未包含在仓库中）。不能写成稳定率。 |
| **1 成功＋1 失败＋1 重复投递** | 2026-10-19 一次隔离 Celery 验证；重复后业务结果计数不增。[结果](../docs/PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/ingestion_celery_20261019T061835650013Z.json`，仅本地留存；未包含在仓库中）。多 worker／崩溃重投未覆盖。 |
| **6 项** | 2026-10-22 用户本机隔离 PG 调查生命周期专项，11.847 秒、OK；覆盖占位、同键竞争、授权读取与撤销、报告保存、失败／截止／中断和清理。[脱敏验收](../docs/PROJECT_A_INVESTIGATION_RUN_ACCEPTANCE.md)。与其他版本和环境的测试项不累加。 |
| **490.797 秒** | 2026-10-21 合成订单分配受阻场景一次真实 Graph/API 调查耗时；六条业务事件与独立 SOP 来源，首答引用齐全且未纠错。[脱敏基线](../docs/PROJECT_A_BASELINE_EVIDENCE.md)。单次耗时不代表稳定性能。 |

可用简历短句：**“实现企业范围的调查提交幂等、终态与已校验报告持久化；在隔离 PostgreSQL 专项及受控 Provider 的真实 JWT/API 页面验收中，验证运行中刷新找回状态、完成后刷新找回报告。”** 该句不得改写为真实聊天模型的刷新验收。

## 两个已有 Bad Case

1. **Day11 回答语义缺口（交接中已命名 Bad Case）**：旧循环真实回答识别晚发货及根因未知，但未明确说出 10:00 承诺截止或 3600 秒差值，也未按要求引用事件 ID；运行状态为 `chain_pass_semantic_review_required`，不能改写成完整语义通过。[原始证据](../docs/PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/day11_evidence_20261011T100235914092Z.json`，仅本地留存；未包含在仓库中）、[交接说明](../docs/PROJECT_A_CONTINUATION.md)。
2. **C05 知识读取后的伪工具文本（按存档失败样本整理）**：`search_knowledge` 已返回 `found`，旧循环仍允许继续调查；模型以普通文本输出工具意图，未形成原生工具调用，同阶段再次被拒后 `ungrounded_final`。后来收紧完成必需读取后的 `final_only` 边界；该失败文件保持失败，不用后续成功覆盖。[失败证据](../docs/PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/investigation_api_c05_20261017T142615923918Z.json`，仅本地留存；未包含在仓库中）、[修复后离线证据](../docs/PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/c05_post_knowledge_offline_20261017T144114211062Z.json`，仅本地留存；未包含在仓库中）、[交接说明](../docs/PROJECT_A_CONTINUATION.md)。

## 未完成、未验证与不能写成已实现

- 当前 Graph 没有持久化 checkpointer、人工中断或断点恢复；调查报告与处置申请之间仍需人工操作。[Graph 构建](../backend/app/ai/agents/core_graph.py)、[交接](../docs/PROJECT_A_CONTINUATION.md)。
- C01–C12 **当前 Graph 命名场景**全矩阵未验收。C05 单次真实通过属于旧循环；当前 Graph 页面报告及后来的合成分配受阻 Graph/API 单次通过属于其他运行，不能混写或推导稳定通过率。[README](../README.md)。
- 2026-10-22 用户手工确认了实际 React 页面的**历史成功响应回放**：布局、证据展开、复制与退出加载；它不等于这次由浏览器实时调用真实聊天模型。此前七份处置页浏览器自动化证据均为 `passed=false`，不应覆盖手工验收边界。[脱敏基线](../docs/PROJECT_A_BASELINE_EVIDENCE.md)。
- 未验证通用并发限流、Redis 锁、Celery 多 worker 竞争／worker 崩溃恢复／broker 发布失败补偿；不能写 exactly-once 或性能提升。[Celery 证据](../docs/PROJECT_A_BASELINE_EVIDENCE.md)（原始文件 `scripts/ingestion_celery_20261019T061835650013Z.json`，仅本地留存；未包含在仓库中）。
- 内部通知记录的 `delivery_status=not_sent`；邮件、短信发送及客户收悉均未实现或未证实。[执行 Service](../backend/app/services/action_request_service.py)。
- 旧场景的真实模型报告曾给出 `root_cause=unknown`；后续合成订单级证据场景单次真实 Graph/API 运行只限定为“该运单发货延迟与库存分配受阻有关”，不证明整单唯一根因或其他原因。SOP 引用不证明订单事实，建议未执行。[脱敏基线](../docs/PROJECT_A_BASELINE_EVIDENCE.md)。
- 当前仅按**单 API worker** 验收调查生命周期；服务重启将遗留 `running` 标为 `interrupted`，没有 Graph 断点续算。[持久化验收](../docs/PROJECT_A_INVESTIGATION_RUN_ACCEPTANCE.md)。
- 11 组对照所述 **90 项相关离线测试**仅见交接记录，独立原始运行日志需核对；Prometheus／Grafana 虽有配置，运行验收需核对。不要将不同环境或版本的数字相加。[README](../README.md)。
