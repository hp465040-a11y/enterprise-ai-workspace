# Project A｜订单履约异常调查与受控处置 Agent

这是 RAGForge AI 仓库中的 Project A。面向多企业订单履约异常，Agent 只读查询案件和履约事实、检索授权 SOP，并生成带来源引用的调查报告。成员需要处置时另行创建申请；**管理员审核批准后，仍须另行显式执行，系统才创建站内通知记录**。报告不自动触发处置，站内记录不代表邮件、短信已发送或客户已收到。

项目针对的是多来源事实难以核对、模型可能把线索误判为原因、跨企业知识可能越权进入报告，以及处置缺少人工把关与重复执行防线等问题。这里展示的是合成数据与隔离环境中的实现和验收，不声称已有生产用户或量化业务收益。

## 使用流程

`登录／选择企业 → 提交调查 → 等待或刷新找回状态 → 阅读报告与证据 → 手动创建处置申请 → 管理员批准或拒绝 → 对已批准申请显式执行 → 查看站内通知`

调查与处置由人选择案件衔接。批准只改变申请状态，执行才创建系统内通知记录。

## 核心能力与存档结果

以下结果分别属于注明的日期、版本和环境；不跨版本相加为通过率。〔离线〕表示受控 Provider 回放，〔隔离〕表示真实隔离数据库／检索或认证链路，〔真实模型·单次〕表示本机聊天模型的一次运行。

| 能力 | 机制与已验证范围 |
| --- | --- |
| **LangGraph Agent 编排** | 模型决策、工具校验与执行、报告校验是实际 Graph 节点；保留阶段门槛、来源校验、重复调用防线、预算及分阶段纠错。2026-10-19 当时版本的 **11 组受控 Provider 离线回放**与旧循环对照；这不是当前提交的完整等价回归。另一次当前 Graph 的真实页面调查收到 4 条业务事件、1 条独立 SOP 来源及六部分报告〔真实模型·单次〕。[证据](docs/PROJECT_A_BASELINE_EVIDENCE.md) |
| **证据约束的限定归因** | 业务事件和 SOP 来源分别验证，SOP 不能代替订单事实。2026-10-21 合成订单的一次真实 Graph/API 调查引用 6 条业务事件与 1 条 SOP 来源，只限定为“该运单发货延迟与库存分配受阻有关”；整单其他原因及完成情况未知，建议未执行。该次耗时 **490.797 秒**；2026-10-22 的 React 展示验收使用保存响应回放，两者不是同一次实时浏览器到模型链路。[证据](docs/PROJECT_A_BASELINE_EVIDENCE.md) |
| **SOP 检索与权限隔离** | 源码实现 Qdrant 向量检索、工作区内 PG/BM25 稀疏检索及 RRF 名次融合；这些排序机制的效果未做专项运行评测。JWT 用户、企业成员和工作区权限逐层校验，检索候选再经 PG 范围回填。2026-10-19 C10 在真实隔离 PG／Qdrant／Embedding 与受控聊天 Provider 下，核对跨工作区正文、chunk 和来源 ID 均未进入模型上下文，越权请求在读取前被拒绝〔隔离〕。[证据](docs/PROJECT_A_BASELINE_EVIDENCE.md) |
| **审批事务与幂等** | 企业范围幂等键由数据库唯一约束兜底；审核与执行使用行锁，状态及审计处于各自事务边界。2026-10-19 **21 项**隔离 PG 定向测试通过；其中受控双会话同键创建最终为 1 份申请、1 条审计。真实 JWT/HTTP 链路另验证创建、批准和拒绝；批准不等于执行〔隔离〕。[证据](docs/PROJECT_A_BASELINE_EVIDENCE.md) |
| **Celery＋Redis 文档入库** | worker 处理解析、分块、Embedding 与索引，检查 job 状态和 task ID。2026-10-19 隔离 Redis／PG／Qdrant 验证 1 次成功、1 次受控失败、1 次**已完成 job**重复投递；重复后 chunk、vector、usage 计数未增加。失败的 document/job 与 Celery 任务均记录失败；未验证多 worker 竞争或通用 exactly-once〔隔离〕。[证据](docs/PROJECT_A_BASELINE_EVIDENCE.md) |
| **调查记录与刷新恢复** | 提交占位先于长模型调用落库，同键并发去重，报告校验通过才保存；授权历史读取重查企业与工作区。2026-10-22 用户本机隔离 PG 专项 **6 项**通过；两轮受控 Provider＋真实 JWT/API＋隔离 PG 页面验收分别确认运行中刷新找回状态、完成后刷新找回报告。它们不是新增真实聊天模型验收〔隔离〕。[证据](docs/PROJECT_A_INVESTIGATION_RUN_ACCEPTANCE.md) |

## 架构

```mermaid
flowchart LR
    U[成员／管理员浏览器] -->|JWT| F[Next.js 页面]
    F --> A[FastAPI 认证 API]
    A -->|提交键、状态、报告| P[(PostgreSQL)]
    A --> G[LangGraph 调查 Core]
    G --> T[只读案件／履约工具]
    T --> P
    G --> K[授权 SOP 检索]
    K --> P
    K --> Q[(Qdrant)]
    G --> V[事件与 SOP 双来源校验]
    A --> S[ActionRequest 审批 Service]
    S -->|各操作内状态与审计同事务| P
    A --> D[文档入库生产者]
    D --> R[(Redis broker)]
    R --> W[Celery worker]
    W --> P
    W --> Q
```

## 技术栈与演示

主要技术：Python、FastAPI、LangGraph、PostgreSQL、Qdrant、Redis、Celery、Next.js。2026-10-22 核对的本地配置为 **Ollama `llama3.1:8b`** 聊天模型、**`nomic-embed-text`** Embedding（768 维），`RERANK_PROVIDER=none`；本地配置可能与其他部署不同。`docker-compose.yml` 定义 PostgreSQL、Redis、Qdrant、迁移、后端 API、Celery worker、前端、Prometheus 和 Grafana 服务；Ollama 在宿主机运行，不属于该 Compose 服务清单。

从新环境准备隔离数据与启动服务见[演示指南](docs/PROJECT_A_DEMO.md)。无需重新调用模型的[约三分钟分段演示](docs/PROJECT_A_3MIN_DEMO.md)依次展示历史真实结果的 React 回放、受控 Provider 的保存报告刷新读取，以及成员申请→管理员审核→显式执行后的站内记录。这三段使用不同的验证条件，不能合称一次实时浏览器到真实模型再到处置的端到端验收。

## 当前边界与后续计划

**当前边界**

- **耗时**：合成场景的一次真实调查约 491 秒，仅单次样本。
- **执行**：按单 API worker 验收；服务重启后遗留运行标记为“中断”，不续算，历史成功报告可按授权读取。
- **原因归因**：库存分配受阻仅在一次合成场景中验证；证据不足时保持“未知”。
- **通知**：仅创建站内记录，未接入邮件或短信。

**后续计划**

- 根据逐轮计时优化单次调查耗时
- 扩展有订单级关联证据的原因类型
- 建立区分首答与纠错结果的小型评测集

## 说明

原始运行文件仅本地保留，公开仓库提供[脱敏基线摘要](docs/PROJECT_A_BASELINE_EVIDENCE.md)和[调查记录验收摘要](docs/PROJECT_A_INVESTIGATION_RUN_ACCEPTANCE.md)；许可证为 [MIT](LICENSE)。
