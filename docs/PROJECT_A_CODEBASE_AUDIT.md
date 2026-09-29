# Project A 代码库体检报告

审计对象：`Rag-forge-ai-main`  
整理日期：2026-09-29  
方法：目录清点、全局代码检索、核心调用链及配置和测试源码静态审阅。

## 1. 结论与证据边界

当前项目是一个已有实质实现的多租户文档 RAG 应用：前端页面、FastAPI API、PostgreSQL 数据模型、Celery 异步入库、Qdrant 向量检索、BM25、流式问答和管理后台均有代码。它可以作为 Enterprise AI Workspace 的基础，但当前没有业务 Agent、Tool Calling 执行循环或跨境电商系统连接器。

本文只整理前一轮实际代码审阅已确认的信息，不把 README、代码注释中的完成声明当作运行证据。文中的“已实现”表示存在实现及调用关系，不表示已在当前环境运行成功。

- 前一轮目录清点识别到 263 个文件；该数量是新增本文档前的快照。
- 未启动应用、连接数据库进行验证、调用模型、运行测试、构建镜像或执行迁移。
- 没有确认当前数据库结构、容器健康、模型可用性、依赖安装版本或线上性能。
- 当前目录未识别到 Git 仓库元数据，不能提供提交 SHA 或核验历史变更。
- 本次唯一新增文件为本文档；不修改业务代码、配置、数据库或依赖。
- 相对文件链接均以本文档所在的 `docs/` 为基准。

## 2. 当前目录与整体架构

```text
Rag-forge-ai-main/
├── frontend/
│   ├── src/app/                  Next.js 页面、布局、登录和工作台
│   ├── src/components/           UI、聊天、引用、文档、图表和后台组件
│   ├── src/hooks/                查询、变更、文档轮询、聊天流处理
│   ├── src/lib/api/              HTTP/SSE 客户端
│   ├── src/store/                认证、工作区选择、通知
│   ├── package.json
│   ├── package-lock.json
│   └── Dockerfile
├── backend/
│   ├── app/main.py               FastAPI 入口
│   ├── app/api/                  路由及身份/权限依赖
│   ├── app/services/             业务服务
│   ├── app/models/               SQLAlchemy 数据模型
│   ├── app/schemas/              Pydantic 请求/响应结构
│   ├── app/db/                   API 与 Worker 数据库会话
│   ├── app/core/                 配置、安全、Redis、异常、日志
│   ├── app/middleware/           请求上下文、限流
│   ├── app/storage/              本地及 S3 存储适配
│   ├── app/workers/              Celery、文档入库任务
│   ├── app/ai/
│   │   ├── parsers/              文档解析、PDF OCR
│   │   ├── chunking/             递归字符切块
│   │   ├── embeddings/           Voyage/OpenAI/Ollama
│   │   ├── vectorstore/          Qdrant
│   │   ├── retrieval/            BM25、混合检索、RRF
│   │   ├── reranking/            Voyage、直通实现
│   │   ├── graph/                LangGraph 检索图
│   │   ├── llm/                  Anthropic/Ollama
│   │   ├── prompts/              改写和回答提示词
│   │   └── evaluation/           离线评测指标与模拟检索器
│   ├── alembic/                  迁移
│   ├── tests/                    单元和接口集成测试
│   └── Dockerfile
├── docker-compose.yml
├── infra/                        Prometheus、Grafana
├── scripts/run_retrieval_eval.py
├── .github/workflows/ci.yml
└── docs/
```

系统是前后端分离、后端模块化分层、Celery Worker 独立进程执行的应用。没有证据表明业务服务已经拆分为独立微服务。

```text
浏览器：Next.js / React
  ├── HTTP JSON：认证、工作区、文档、统计、管理
  └── HTTP POST + SSE：聊天
                  ↓
FastAPI：请求上下文 / Redis 限流 / JWT / 工作区权限
                  ↓
API 路由 → Service
  ├── PostgreSQL：关系数据、切块正文、消息、引用、用量、审计
  ├── 文件存储：local；可选 S3
  ├── Redis → Celery Worker：文档入库
  └── RAG 检索图 → LLM：问答生成
          ├── Qdrant：向量检索
          └── PostgreSQL 切块 → 进程内 BM25
```

证据：[应用入口](../backend/app/main.py)、[路由注册](../backend/app/api/v1/router.py)、[聊天服务](../backend/app/services/chat_service.py)、[入库任务](../backend/app/workers/tasks/ingestion_tasks.py)。

## 3. 当前真实技术栈与可确认版本

版本必须区分锁文件、声明范围和镜像标签；以下均不是当前运行环境已安装版本的证明。

| 层次           | 实际技术                                                                | 可确认版本或范围                              | 证据类型                     |
| ------------ | ------------------------------------------------------------------- | ------------------------------------- | ------------------------ |
| 后端语言         | Python                                                              | 项目要求 >=3.12；镜像 `python:3.12-slim`     | pyproject、Dockerfile     |
| API          | FastAPI、Uvicorn                                                     | FastAPI >=0.115.0；Uvicorn >=0.32.0    | 依赖范围及代码导入                |
| 数据校验         | Pydantic、pydantic-settings                                          | >=2.9.0、>=2.5.0                       | 依赖范围及代码                  |
| ORM/驱动/迁移    | SQLAlchemy、asyncpg、Alembic                                          | >=2.0.35、>=0.30.0、>=1.13.3            | 依赖范围及代码                  |
| 关系数据库        | PostgreSQL                                                          | `postgres:16-alpine`                  | Compose 标签               |
| Redis        | Redis 服务、Python redis 客户端                                           | 服务 `redis:7-alpine`；客户端 >=5.1.0       | Compose、依赖范围             |
| 后台任务         | Celery                                                              | >=5.4.0                               | 依赖范围及任务代码                |
| 向量数据库        | Qdrant                                                              | 服务 `latest`，无法确认具体版本；客户端 >=1.11.0     | Compose、依赖范围             |
| 前端框架         | Next.js                                                             | 锁文件 15.5.20；package.json 为 ^15.1.0    | 锁文件及实际页面代码               |
| 前端 UI 运行库    | React                                                               | 锁文件 19.2.7；声明 ^19.0.0                 | 锁文件                      |
| 前端语言         | TypeScript                                                          | 锁文件 5.9.3；声明 ^5.7.2                   | 锁文件                      |
| Node.js      | Node                                                                | 镜像 `node:22-slim`                     | Dockerfile 标签            |
| 样式与组件        | Tailwind CSS、Radix UI、Lucide、本地 UI 组件                               | Tailwind 声明 ^3.4.17                   | package.json、组件代码        |
| 状态与数据查询      | Zustand、TanStack Query                                              | 声明 ^5.0.2、^5.62.0                     | package.json、hooks/store |
| 表单           | React Hook Form、Zod                                                 | 声明 ^7.54.0、^3.24.1                    | package.json、表单代码        |
| LLM          | Anthropic SDK、Ollama HTTP API                                       | Anthropic SDK >=0.68.0；Ollama 服务版本未确认 | provider 代码              |
| Embedding/重排 | Voyage；可选 OpenAI Embedding；Ollama Embedding                         | Voyage SDK >=0.3.0                    | provider 代码              |
| 编排与切块        | LangGraph、langchain-text-splitters                                  | >=0.2.0、>=0.3.0                       | 依赖范围及代码                  |
| 稀疏检索         | rank-bm25                                                           | >=0.2.2                               | 依赖范围及代码                  |
| 解析/OCR       | pdfplumber、python-docx、BeautifulSoup、Markdown、pytesseract、pdf2image | 不额外推断安装版本                             | parser 代码、Dockerfile     |
| 安全           | bcrypt、PyJWT                                                        | 声明 >=4.1.0、>=2.9.0                    | security 代码              |
| 可观测性         | structlog、Prometheus instrumentator、Grafana                         | 监控服务使用 latest；未确认运行版本                 | main、infra、Compose       |

后端 requirements 的注释写“Pinned”，但内容主要是 `>=` 下界约束，并非精确锁定。前端存在 `package-lock.json`。

证据：[后端依赖](../backend/requirements.txt)、[项目元数据](../backend/pyproject.toml)、[前端依赖](../frontend/package.json)、[前端锁文件](../frontend/package-lock.json)。

### 3.1 当前本地配置选择

前次审阅只提取根目录 `.env` 中与技术选择有关的非敏感字段：

```text
APP_ENV=development
LLM_PROVIDER=ollama
LLM_MODEL=llama3.1:8b
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSIONS=768
RERANK_PROVIDER=none
STORAGE_BACKEND=local
```

这证明配置选择，不证明 Ollama 已安装、模型已下载或服务可访问。模型名称是配置字符串，不是服务端模型可用性的认证。模型选择是应用级配置，没有按 Agent/租户动态选择模型的实现。

## 4. 前端当前实现情况

- Next.js App Router 提供登录、注册、工作台、工作区聊天、文档列表和详情、统计、成员设置、账户设置、组织设置及超级管理员页面。
- 登录注册采用 React Hook Form/Zod；API 客户端处理 Bearer Token、刷新令牌和错误响应。
- Zustand 保存认证信息与工作区选择，并使用默认 persist 存储到 localStorage。
- TanStack Query 负责接口查询和变更后的失效；处理中的文档每 3 秒轮询状态。
- 聊天用 POST `fetch()` 读取 SSE，解析 token/done/error 事件；支持增量显示、历史消息和引用提示。
- 引用组件展示文件名、页码和片段；消息主体主要是文本加引用标记，没有完整 Markdown 渲染器。
- 统计图表是本地 SVG 组件，数据来自后端用量接口；它们显示 AI 使用数据，不是电商广告或经营指标。
- 文档上传、成员添加等界面已连接实际 API，但按钮可见性并未全面按角色限制，最终权限由后端判断。
- 根布局配置 `force-dynamic`；Next.js 配置 standalone 构建和 `/api/*` 转发。

证据：[API 客户端](../frontend/src/lib/api/client.ts)、[聊天客户端](../frontend/src/lib/api/chat.ts)、[聊天 hook](../frontend/src/hooks/use-chat.ts)、[文档 hooks](../frontend/src/hooks/use-documents.ts)、[认证 store](../frontend/src/store/auth-store.ts)、[图表组件](../frontend/src/components/charts/)、[Next 配置](../frontend/next.config.ts)。

## 5. 后端当前实现情况

- FastAPI 在 `/api/v1` 下注册认证、用户、组织、工作区、文档、会话、分析和管理员接口。
- API 使用依赖注入获得数据库会话、当前用户和工作区最低角色检查。
- JWT Access Token 配合 PostgreSQL 中保存哈希的 opaque Refresh Token；实现刷新轮换和撤销。
- 注册创建用户和组织及 owner 成员关系；没有自动创建工作区的调用。
- 组织角色为 owner/admin/member；工作区角色为 owner/editor/viewer。
- 工作区支持创建、列表、详情、更新及成员添加/移除；组织有列表、详情、成员列表和移除接口。
- 文档接口负责上传、状态、详情、切块、重入库和删除。上传/重入库提交事务后投递 Celery。
- 聊天生成器自主管理数据库会话，保存用户消息后执行检索和生成，成功后保存助手消息与引用。
- 超级管理员可查看组织/用户、修改套餐字段、停用用户、修改超级管理员权限、查看平台用量和审计日志。
- 统一异常响应、请求 ID、结构化日志和限流中间件已有实现。

证据：[权限依赖](../backend/app/api/deps.py)、[认证服务](../backend/app/services/auth_service.py)、[接口目录](../backend/app/api/v1/endpoints/)、[服务目录](../backend/app/services/)。

## 6. PostgreSQL / Redis / Qdrant 当前实现情况

### 6.1 PostgreSQL

使用 SQLAlchemy 异步会话和 asyncpg。API 会话有连接池；Worker 会话使用 NullPool。数据库模型使用原生 UUID、JSONB、外键、唯一约束及索引。

初始迁移定义 15 张应用表：

| 领域    | 表                                                                                             |
| ----- | --------------------------------------------------------------------------------------------- |
| 身份及租户 | users、organizations、organization_members、workspaces、workspace_members、refresh_tokens、api_keys |
| 知识入库  | documents、document_chunks、ingestion_jobs                                                      |
| 对话    | conversations、messages、message_citations                                                      |
| 记录    | usage_records、audit_logs                                                                      |

切块正文在 PostgreSQL，向量在 Qdrant；未发现 pgvector 实现。仅发现一个初始迁移文件。没有发现 PostgreSQL RLS 策略，隔离依赖应用权限与查询条件。未核验任何现存数据库是否应用了迁移。

证据：[模型](../backend/app/models/)、[API 会话](../backend/app/db/session.py)、[Worker 会话](../backend/app/db/worker_session.py)、[初始迁移](../backend/alembic/versions/0001_initial_schema.py)。

### 6.2 Redis

Compose 将 Redis 分别配置为：应用状态 DB 0、Celery Broker DB 1、Celery 结果后端 DB 2。

实际用途：

- 固定分钟窗口计数限流。
- Celery 任务传输和结果后端。
- 工作区 BM25 版本计数，协调 API 与 Worker 的缓存失效。

BM25 索引本体缓存在 API 进程内，不存储在 Redis。未发现 Redis 登录会话缓存或回答缓存实现；Refresh Token 存储在 PostgreSQL。

证据：[Redis 客户端](../backend/app/core/redis_client.py)、[限流](../backend/app/middleware/rate_limit.py)、[Celery 配置](../backend/app/workers/celery_app.py)、[BM25](../backend/app/ai/retrieval/bm25_index.py)。

### 6.3 Qdrant

- AsyncQdrantClient 实现 collection 初始化、upsert、query_points、按文档删除。
- 使用 cosine 距离；维度取自全局 `EMBEDDING_DIMENSIONS`。
- payload 包含 chunk_id、document_id、workspace_id、organization_id。
- 搜索显式按 workspace_id 过滤；建有 workspace_id/document_id payload 索引。
- collection 已存在时没有校验其维度与当前 Embedding 配置是否一致。
- FastAPI 启动尝试初始化 collection，失败记录 warning 并继续启动；不是完整运行期降级策略。

证据：[Qdrant 实现](../backend/app/ai/vectorstore/qdrant_store.py)、[启动生命周期](../backend/app/main.py)。

## 7. RAG 当前实现情况

### 7.1 文档入库

```text
上传 → 保存原文件 → PostgreSQL Document/Pending Job → 提交事务
  → Redis/Celery
  → 解析（PDF 必要时 OCR）
  → 按页递归字符切块
  → Embedding
  → 删除旧 Qdrant 向量并写新向量
  → PostgreSQL 替换切块并更新状态、记录用量
  → Redis 增加 BM25 版本号
```

支持 PDF、DOCX、HTML、Markdown、TXT；没有发现 CSV/XLSX 解析、网页抓取或企业数据源同步接口。HTML 解析是上传文件内容处理，不是爬虫。

默认切块 2000 字符、重叠 200 字符；Token 数通过约 4 字符/Token 估算。PDF 按页处理；DOCX 被视为单逻辑页。OCR 为 best-effort，失败时记录 warning；没有配置中文 OCR 语言选择。

Celery 对 `UpstreamProviderError` 配置退避重试，最多 3 次；有终态失败记录。顺序重跑会替换旧数据，但没有因此证明并发幂等或跨存储原子性。

证据：[解析器](../backend/app/ai/parsers/)、[切块](../backend/app/ai/chunking/recursive_chunker.py)、[入库任务](../backend/app/workers/tasks/ingestion_tasks.py)。

### 7.2 检索与回答

```text
问题 + 最近历史
  → LangGraph：rewrite_query → hybrid_retrieve → rerank
      ├── 查询 Embedding → Qdrant Dense
      └── PostgreSQL 切块 → 内存 BM25 Sparse
                         ↓
                        RRF
  → chat_service 组装提示词
  → LLM stream → SSE
  → 保存回答、引用和用量
```

- 没有历史时跳过模型改写；有历史时使用最近窗口改写独立检索问题。
- 默认 Dense 50、Sparse 50、融合后 30、最终上下文最多 8 个片段。
- 生成读取最近 20 条历史消息，改写窗口配置为最近 6 条历史条目。
- 重排可使用 Voyage 或 NoOp；当前 `.env` 为 none，NoOp 只保持顺序并生成用于展示的递减分数。
- LLM 支持 Anthropic 和 Ollama；OpenAI 适配只用于 Embedding。
- 提示词要求只依据提供文档回答，缺少依据时说明无法回答。
- 引用通过正则提取 `[n]` 并检查范围，保存到 message_citations；没有事实一致性核验器。
- 检索和回答属于同一后端应用的内部模块，没有独立 Shared RAG 服务 API 边界。

证据：[检索图](../backend/app/ai/graph/rag_graph.py)、[节点](../backend/app/ai/graph/nodes.py)、[混合检索](../backend/app/ai/retrieval/hybrid_retriever.py)、[聊天服务](../backend/app/services/chat_service.py)、[提示词](../backend/app/ai/prompts/rag_prompts.py)。

## 8. Agent / Tool Calling 当前实现情况

LangGraph 被实际使用，但图仅有 rewrite_query、hybrid_retrieve、rerank 三个线性节点。生成和持久化在图外，没有 checkpointer。

在已扫描的应用代码中，未发现：

- Router、Customer、Operation、Supply Chain Agent。
- 工具注册表、ToolNode、工具调用执行循环或 Agent handoff。
- 向 LLM provider 传递 tools/schema、解析 tool calls、回传 tool results 的实现。
- 任务规划、人工批准、暂停恢复、持久化 Agent 执行状态。
- 订单、退换货、广告、库存、ERP/WMS 等连接器。

LLM 接口目前主要接受 user/assistant 文本消息，返回文本、模型信息和 Token 用量。因此“存在 LangGraph”不能被理解为“已实现 Agent 平台”。

证据：[LLM 接口](../backend/app/ai/llm/base.py)、[Anthropic provider](../backend/app/ai/llm/anthropic_provider.py)、[Ollama provider](../backend/app/ai/llm/ollama_provider.py)、[检索图](../backend/app/ai/graph/rag_graph.py)。

## 9. Docker / 部署 / 监控当前情况

Compose 定义 postgres、redis、qdrant、migrate、backend、worker、frontend、prometheus、grafana 九个服务。

| 服务         | 宿主机映射或职责                         |
| ---------- | -------------------------------- |
| PostgreSQL | 5433 → 5432                      |
| Redis      | 6380 → 6379                      |
| Qdrant     | 6333 → 6333                      |
| Backend    | 8000 → 8000                      |
| Frontend   | 3000 → 3000                      |
| Prometheus | 9090 → 9090                      |
| Grafana    | 3002 → 3000                      |
| migrate    | 执行 `alembic upgrade head` 的一次性服务 |
| worker     | Celery 文档入库                      |

- 后端与 Worker 共享构建镜像和本地存储卷；镜像安装 OCR 系统工具并使用非 root 用户。
- 前端使用 Node 22 多阶段构建、npm ci、Next standalone 和非 root node 用户。
- Ollama 在宿主机，Compose 中的 API/Worker 指向 `host.docker.internal:11434`。
- PostgreSQL、Redis 有健康检查；Worker 显式关闭继承的 HTTP 健康检查；Qdrant 没有 Compose 健康检查。
- `/health` 仅表示 API 活着；`/health/ready` 只执行数据库 SELECT 1。
- `/metrics` 暴露 HTTP 指标，Grafana 配置请求率、5xx 比率、延迟分位数、处理中请求数等面板。
- 未发现完整 RAG 节点追踪、任务队列监控、LLM 调用指标和生产告警闭环。
- `SENTRY_DSN` 存在，但未发现 Sentry 初始化。
- Compose 默认数据库凭据、Grafana admin 密码及匿名 Viewer 设置属于开发部署配置；数据库/队列端口直接映射到宿主机。
- 未发现 Kubernetes、高可用部署、备份恢复自动化或正式发布流水线；CI 镜像构建配置 `push: false`。

证据：[Compose](../docker-compose.yml)、[后端 Dockerfile](../backend/Dockerfile)、[前端 Dockerfile](../frontend/Dockerfile)、[健康接口](../backend/app/api/v1/endpoints/health.py)、[监控配置](../infra/)、[CI](../.github/workflows/ci.yml)。

## 10. 测试与评估体系当前情况

### 10.1 测试

静态清点发现 18 个后端测试文件、86 个 `test_` 函数定义；这不是执行后的用例数或通过数。前端有两个 `.test.ts` 文件，主要测试图表数据转换和格式化。

- 单元测试涉及安全、配置、解析、切块、存储、Provider 辅助逻辑、提示词、图结构、检索融合、引用提取、费用计算和评测指标。
- 接口集成测试覆盖认证、工作区、文档、聊天、分析和管理。
- 后端集成测试使用真实 PostgreSQL；fixture 执行 ORM create_all/drop_all，不是迁移测试。
- 聊天测试用 Fake LLM/Embedding/Rerank 和替换后的向量检索测试主要流程，不能证明真实模型回答质量。
- 文档接口测试替换 Celery 投递，没有在这些测试中完成真实 Worker 入库。
- 未发现独立覆盖真实 Worker 完整入库及连续任务生命周期的测试，也未发现前端浏览器端到端测试。
- CI 配置后端 Ruff/mypy/pytest，前端 lint/typecheck/test/build，以及 Docker 镜像构建；存在配置不代表当前检查通过。

**测试执行边界：** `backend/tests/conftest.py` 会创建和删除配置数据库中的表，不能把该测试命令当作只读检查，也不能在未确认隔离测试数据库时执行。

证据：[测试目录](../backend/tests/)、[fixture](../backend/tests/conftest.py)、[聊天测试](../backend/tests/integration/test_chat_endpoints.py)、[文档测试](../backend/tests/integration/test_document_endpoints.py)、[前端图表测试](../frontend/src/components/charts/)、[CI](../.github/workflows/ci.yml)。

### 10.2 评估

有 Recall@K、Precision@K、MRR@K、Hit Rate@K、DCG/IDCG/NDCG 的实际计算代码，以及离线 benchmark 和 CLI。

必须注意生产链路与评测链路不同：

- `DeterministicDenseScorer` 实际使用词集合 Jaccard 相似度，未调用真实 Embedding 或 Qdrant。
- `cross_encoder_rerank` 使用词重合和匹配奖励，未运行真实 Cross-Encoder。
- 评测 BM25 是独立参考实现，不是直接调用生产 `sparse_search`。
- 因此该评测可以用于指标计算和模拟流程验证，不能作为真实生产 RAG 效果、延迟或成本的证明。
- benchmark 包含其他领域示例，没有形成跨境电商业务验收集。

证据：[评测实现](../backend/app/ai/evaluation/evaluator.py)、[指标](../backend/app/ai/evaluation/metrics.py)、[数据集](../backend/app/ai/evaluation/benchmark_dataset.py)、[CLI](../scripts/run_retrieval_eval.py)。

## 11. 已真正实现的功能清单

| 功能            | 代码支持及边界                                             |
| ------------- | --------------------------------------------------- |
| 用户注册、登录、刷新、退出 | 有接口、服务、令牌存储和前端接线                                    |
| 账户资料及密码修改     | 有前后端实现                                              |
| 多租户组织/工作区基础   | 有模型、角色、权限依赖；撤权闭环仍有缺口                                |
| 工作区成员管理       | 已有账户可按邮箱加入；不等于组织邀请体系                                |
| 文档上传与管理       | 上传、查询、删除、重入库、状态、切块查看                                |
| 异步入库          | Celery 任务实际调用解析、切块、Embedding、Qdrant 和数据库            |
| 混合检索          | Dense + BM25 + RRF；可选 Voyage 重排                     |
| 流式文档问答        | SSE、历史、引用及持久化                                       |
| 多 Provider 接口 | Anthropic/Ollama LLM，Voyage/OpenAI/Ollama Embedding |
| 本地与 S3 存储适配   | 均有实现，S3 默认依赖不齐                                      |
| 使用量分析         | 从 usage_records 聚合；不是完整账单                           |
| 管理员后台         | 组织、用户、套餐字段、权限及部分审计                                  |
| 工程基础          | 日志、HTTP 指标、容器和 CI 配置                                |

## 12. 未完成、占位或仅有框架的功能

| 功能                         | 当前边界                                  | 证据                                                 |
| -------------------------- | ------------------------------------- | -------------------------------------------------- |
| API Key 访问                 | 有模型和生成函数，无管理及认证调用链                    | models/api_key.py、core/security.py、api/deps.py     |
| 组织邀请                       | 有 Invite schema，无发出/接受流程              | schemas/organization.py、endpoints/organizations.py |
| 邮箱验证                       | 有 email_verified 字段，无验证流程             | models/user.py、认证接口                                |
| 套餐/计费                      | 只可修改套餐字段，无配额、支付和账单                    | admin_service.py、usage_service.py                  |
| 完整用量计量                     | 实际调用主要记录回答和入库；改写、查询 Embedding、重排未完整记录 | chat_service.py、ingestion_tasks.py                 |
| 完整审计                       | 只发现三个管理员修改操作写审计                       | endpoints/admin.py                                 |
| 细粒度入库进度                    | 有 stage 枚举，主要写 parsing/done           | models/ingestion_job.py、ingestion_tasks.py         |
| 非流式聊天                      | schema 有 stream 字段，路由始终 SSE           | schemas/chat.py、endpoints/conversations.py         |
| 事实核验                       | 仅提取并校验引用序号范围                          | chat_service.py                                    |
| Sentry                     | 配置字段存在，无初始化代码                         | core/config.py                                     |
| OpenAI Embedding / S3 开箱即用 | 适配真实存在，默认依赖没有 openai/boto3            | provider/storage、requirements.txt                  |
| 业务 Agent 和 Tool Calling    | 未发现实现                                 | ai/graph、ai/llm 接口及全局检索                            |

## 13. 重要技术债、风险和代码问题

以下优先级是本次审阅判断。已确认的控制流与尚需运行复现的风险分开描述，不把静态推断写成已发生事故。

### 13.1 高优先级：权限和会话边界

**组织移除不撤销工作区访问（代码行为已确认）。** 组织成员删除只删除 OrganizationMember，工作区授权只检查 WorkspaceMember；工作区成员关系仍在时，移出组织不等于撤销工作区访问。新增工作区成员也不要求所属组织成员资格。

**Owner 保护与组织路径核验不足（代码行为已确认）。** 成员删除接口没有完整的最后 owner 保护；组织管理员删除成员时没有额外保护 owner。部分工作区成员接口未核对路径 organization_id 与 workspace 归属。这不等于已证明任意跨租户访问，但层级约束不完整。

**会话按工作区共享（代码行为已确认）。** 列表、读取和继续对话不按 Conversation.user_id 隔离；viewer 可以读取和继续工作区会话，editor 可删除。未来接入客户订单和个人信息时必须明确这一产品边界。

证据：[组织接口](../backend/app/api/v1/endpoints/organizations.py)、[工作区接口](../backend/app/api/v1/endpoints/workspaces.py)、[工作区授权](../backend/app/services/workspace_service.py)、[会话服务](../backend/app/services/conversation_service.py)、[聊天服务](../backend/app/services/chat_service.py)。

### 13.2 高优先级：入库可靠性与数据一致性

**跨存储写入没有原子保证（控制流已确认，故障后果未复现）。** 入库先替换 Qdrant，再提交 PostgreSQL 切块；数据库失败可能留下不匹配向量。上传先提交数据库再投递任务，投递失败可能留下 pending 文档。没有发现 outbox、补偿或文档级并发锁。

**Job 生命周期不统一（代码行为已确认）。** API 建 pending Job，Worker 另建 running Job，完成时查询最新 Job。上传返回的 Job ID 不一定是最终完成记录；并发重入库时“最新记录”不等于当前任务。

**缓存失效时序（风险待复现）。** 删除文档在数据库 commit 前增加 BM25 版本号，其他请求可能以新版本读到旧数据并缓存。

**异步客户端跨事件循环复用（风险待验证）。** Celery 每次 asyncio.run 创建新循环，数据库已用 NullPool；Redis、Embedding、Qdrant 工厂仍缓存异步客户端，需验证同一 Worker 连续任务的连接生命周期。

证据：[文档接口](../backend/app/api/v1/endpoints/documents.py)、[文档服务](../backend/app/services/document_service.py)、[入库任务](../backend/app/workers/tasks/ingestion_tasks.py)、[Worker 会话](../backend/app/db/worker_session.py)、[Redis 工厂](../backend/app/core/redis_client.py)、[Embedding 工厂](../backend/app/ai/embeddings/factory.py)、[向量工厂](../backend/app/ai/vectorstore/factory.py)。

### 13.3 高优先级：多语言检索与效果证据

**BM25 不识别中文（代码行为已确认）。** 分词正则为 `[A-Za-z0-9]+`，中文不进入索引。零分候选仍返回并参与 RRF；完全无有效词项的语料是否触发库初始化错误需运行验证。

**生产效果未由现有评测证明（代码事实）。** 离线 Dense 和 rerank 是模拟器；真实检索质量、中文知识问答和跨境电商任务准确性未由这些分数证明。

证据：[BM25](../backend/app/ai/retrieval/bm25_index.py)、[评测器](../backend/app/ai/evaluation/evaluator.py)。

### 13.4 中优先级：引用、知识版本和检索规模

- 重入库删除旧切块；message_citations 到切块的外键是 CASCADE。历史引用记录会随旧切块删除，消息中的 `[n]` 文本仍保留。这不是稳定的历史证据快照。
- BM25 缓存失效时读取工作区全部切块，在进程内创建索引并排序；缓存最多 32 个工作区，没有容量或负载验证依据。
- Qdrant 已有 collection 不校验维度；修改模型/维度不能被理解为自动迁移旧向量。
- 没有语义事实核验、文档级访问控制、文档版本或有效期治理。
- 检索依赖的 Redis、Embedding、Qdrant 任一失败可能导致整个问答失败；当前没有完整的检索支路降级。

证据：[引用模型](../backend/app/models/message.py)、[入库](../backend/app/workers/tasks/ingestion_tasks.py)、[BM25](../backend/app/ai/retrieval/bm25_index.py)、[Qdrant](../backend/app/ai/vectorstore/qdrant_store.py)、[混合检索](../backend/app/ai/retrieval/hybrid_retriever.py)。

### 13.5 中优先级：登录态、缓存、限流和上传

- Token 持久化在 localStorage；不是 HttpOnly Cookie 方案。
- 登出只清理认证 store，没有清理工作区选择与 QueryClient 缓存；同浏览器换账号存在陈旧状态/数据显示风险，未运行复现。
- 修改密码未撤销现有 Refresh Token；刷新轮换没有 token family 重放撤销闭环。
- 限流优先信任未认证的 X-API-Key 头作为计数桶标识，改变头值可切换桶；不是严格用户预算控制。Bearer 分桶还使用 Python 进程 hash，不是稳定用户标识。
- 文件先完整读取再检查大小，且 MIME 类型由上传方提供；不能等同于流式大小限制或内容嗅探。

证据：[认证 store](../frontend/src/store/auth-store.ts)、[退出组件](../frontend/src/components/layout/user-menu.tsx)、[Providers](../frontend/src/components/providers.tsx)、[用户接口](../backend/app/api/v1/endpoints/users.py)、[认证服务](../backend/app/services/auth_service.py)、[限流](../backend/app/middleware/rate_limit.py)、[上传接口](../backend/app/api/v1/endpoints/documents.py)。

### 13.6 中优先级：计量、部署和工程验证

- 费用是硬编码模型单价估算；未知模型成本回落为 0，未完整处理缓存定价，入库费用默认 0。不能用于正式账单。
- 审计只覆盖有限管理员操作，没有完整的企业业务操作审计。
- 后端依赖下界约束和基础设施 latest 标签导致构建不可精确复现。
- Worker 没有配置有效健康检查，readiness 不检查 Redis/Qdrant/模型。
- 本地文件卷用于 API/Worker 共享，不代表多节点存储方案已经完成；S3 默认镜像缺依赖。
- 测试创建 ORM schema，不覆盖迁移升级；真实模型、完整 Worker 和浏览器流程验证存在缺口。

证据：[用量服务](../backend/app/services/usage_service.py)、[管理员接口](../backend/app/api/v1/endpoints/admin.py)、[依赖](../backend/requirements.txt)、[Compose](../docker-compose.yml)、[S3](../backend/app/storage/s3_storage.py)、[测试 fixture](../backend/tests/conftest.py)。

### 13.7 文档与代码不一致

以下只用于说明文档可信度，事实判断仍以实现为准：

- README 的图描述包含 Generate/Verify & Cite，但实际 LangGraph 只有三个检索节点。
- README 提到 Redis session cache，应用实际令牌存储在 PostgreSQL，没有发现对应缓存调用链。
- 技术债文档写入库仍需迁往 Celery，但当前 Celery 入库已有实现。
- README 的历史测试通过声明不是当前快照的执行结果。

后续开发不应从这些文档声明推断已有功能或测试通过。

## 14. 当前可以直接保留的模块

“保留”指保留职责和已有代码资产，不等于不需要测试或企业安全验收。

| 模块                              | 保留价值              |
| ------------------------------- | ----------------- |
| FastAPI 路由、Pydantic、异常响应        | API 基础清晰          |
| SQLAlchemy、asyncpg、Alembic      | 关系数据访问与演进基础       |
| UI 组件、布局、表单和通知                  | 工作台界面基础           |
| HTTP/SSE 客户端、引用组件               | 对话交互基础            |
| 文档 parser 和递归 chunker           | 常用企业文档入库基础；多语言需评估 |
| LLM/Embedding/Rerank/Storage 抽象 | 已有替换边界，可继续扩展      |
| HTTP 日志、监控和 CI 配置               | 工程起点              |

## 15. 建议改造复用的模块

| 现有模块                        | 可复用方向          | 主要需补齐内容                  |
| --------------------------- | -------------- | ------------------------ |
| Organization/Workspace/RBAC | 企业与团队权限底座      | 身份生命周期、撤权、细粒度授权          |
| app/ai 与入库任务                | Shared RAG 的主体 | 多语言、知识版本、ACL、一致性、真实评测    |
| chat_service                | 统一交互入口         | 意图分流、工具结果、任务状态；不再固定仅文档问答 |
| LangGraph 检索图               | 编排基础           | 业务分支、状态持久化、人工介入          |
| Conversation/Message        | 对话记录基础         | Agent/工具执行记录及明确共享/私有边界   |
| Celery                      | 后台任务执行基础       | 并发幂等、状态一致性、补偿、健康指标       |
| Usage/Audit/Admin           | 管理工作台          | 完整计量、预算、操作审计             |
| Compose                     | 开发与集成环境        | 可重复部署及运行健康验证             |

以上为复用判断，不是已经实施的架构改造。

## 16. Enterprise AI Workspace 目标下需要新增的模块

下列为目标需求缺口，不是当前代码已有能力：

- Router Agent：意图识别、领域分派、跨业务协调。
- Customer Agent：订单读取、退换货处理、售前售后流程与人工交接。
- Operation Agent：Listing 任务、广告数据分析、运营报告。
- Supply Chain Agent：库存读取、补货建议和 ERP/WMS 工具。
- 业务系统连接器：电商平台、订单系统、广告平台、ERP、WMS。
- Tool Calling 执行层：工具契约、鉴权、权限、执行记录、幂等及写操作审批。
- Agent 运行记录：任务状态、工具结果、恢复和追踪。
- 企业身份及治理：SSO、组织成员生命周期、统一撤权和敏感数据访问策略。
- 知识治理：数据源同步、版本、有效期、来源及文档级权限。
- 业务评测体系：真实检索、模型回答、工具正确性、越权和电商场景回归。

Shared RAG 不是完全从零新增：已有核心实现，需要形成可供多个业务调用方复用的明确边界。

## 17. 与 Project A 目标架构的差距

目标是 Router Agent、Customer Agent、Operation Agent、Supply Chain Agent 与 Shared RAG Service 的协作体系。当前主体是“工作区文档 → 检索 → 回答”，两者不能只通过重命名模块等同起来。

| 目标组件               | 当前可利用资产                        | 目标差距                             |
| ------------------ | ------------------------------ | -------------------------------- |
| Router Agent       | 聊天入口、历史、LangGraph 基础           | 没有意图分类、Agent 分派或工具选择             |
| Customer Agent     | 文档问答、流式交互                      | 没有订单 API、退换货状态机、客户身份关联或人工转接      |
| Operation Agent    | LLM 接口、工作台、通用图表                | 没有 Listing 专用任务、广告数据接入、指标计算和报告流程 |
| Supply Chain Agent | API/数据库/异步任务基础                 | 没有库存领域模型、ERP/WMS 接口和补货逻辑         |
| Shared RAG Service | 解析、切块、Embedding、Qdrant、BM25、引用 | 内部模块尚未形成共享服务边界；缺 ACL、版本和真实多语言评测  |

业务范围对应关系：

| 场景                   | 当前可做的代码能力        | 当前不能由已有代码完成的部分           |
| -------------------- | ---------------- | ------------------------ |
| 客服：订单查询、退换货、售前售后     | 对上传政策/产品资料进行问答   | 实时订单查询、订单操作、退款退货执行       |
| 运营：Listing、广告分析、运营报告 | 文档检索和一般文本生成接口    | Listing 流程、广告数据分析、真实经营报告 |
| 供应链：库存、补货、ERP/WMS    | 上传相关说明文件后检索      | 实时库存、补货计算、ERP/WMS 查询     |
| 企业知识：SOP、产品、平台规则     | 文档入库、工作区检索、带引用回答 | 多数据源同步、知识版本、细粒度授权和可靠效果验证 |

其中企业知识问答最接近现有实现。当前统计页面仅用于 AI 用量，不能视为运营分析；向 RAG 上传订单说明也不能视为具备实时订单查询能力。

## 18. 给后续开发者/AI的交接摘要

1. 这是 Next.js/React 前端 + Python/FastAPI 后端 + Celery Worker 的多租户文档 RAG 项目，有实质业务代码，不是空模板。
2. PostgreSQL 存关系数据和切块正文；Qdrant 存向量；Redis 用于 Celery、限流和 BM25 版本协调。BM25 索引本身在进程内。
3. 优先阅读 `backend/app/services/chat_service.py`、`app/ai/graph/rag_graph.py`、`app/workers/tasks/ingestion_tasks.py`、`app/api/deps.py` 和 `docker-compose.yml`。
4. LangGraph 只有“问题改写 → 混合检索 → 重排”；生成在图外。没有 Router/业务 Agent、Tool Calling 或电商系统连接器。
5. 审计时本地配置为 Ollama llama3.1:8b + nomic-embed-text/768 维 + rerank none + local 存储。配置不代表服务可用。
6. 首要关注组织撤权不联动工作区、工作区共享会话、中文 BM25、入库跨存储一致性、Job 跟踪及 Worker 客户端生命周期。
7. 重入库会删除旧切块及关联引用；费用与审计不完整；API Key、邮箱验证和组织邀请没有业务闭环。
8. 离线 Dense/rerank 是模拟打分，不是真实生产效果评测；本次没有运行任何测试。测试 fixture 会 create_all/drop_all，执行前必须确认隔离测试数据库。
9. 最有复用价值的是 RAG 核心、工作区基础、Provider 抽象及 UI。业务 Agent、工具执行、连接器和企业治理仍需新增或补齐。
10. 本文是静态审计快照，不是生产验收或后续实施方案；修改代码后应重新核验相关结论。
### 19.但是我发现了一个必须处理的问题

这份报告不是“项目很好，直接往上堆 Agent”这么简单。

Codex 找出了几个真实技术债，其中有一个跟你求职方向非常相关：

**中文 BM25 现在有问题。**

当前 BM25 分词正则只识别 `[A-Za-z0-9]+`，中文实际上进不了正常索引。 PROJECT_A_CODEBASE_AUDIT

还有多租户权限撤销、会话隔离、Qdrant/PostgreSQL 入库一致性等问题。 PROJECT_A_CODEBASE_AUDIT

这些东西反而可以变成以后面试里的材料：

> “我不是拿开源项目改个 UI。我先对原项目做代码审计，发现中文 BM25、多租户权限边界、跨存储一致性等问题，然后在此基础上进行 Agent 化改造。”

这个故事比“我从零写了一个聊天机器人”强很多。
