# RAGForge AI

Multi-tenant **Retrieval-Augmented Generation (RAG) SaaS Platform** with hybrid semantic + keyword search, cross-encoder reranking, LangGraph state orchestration, and verifiable citations.

[![CI](https://github.com/daanialmirza5/Rag-forge-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/daanialmirza5/Rag-forge-ai/actions/workflows/ci.yml)
[![Next.js](https://img.shields.io/badge/Next.js-15-black?logo=next.js&logoColor=white)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Qdrant](https://img.shields.io/badge/Vector_DB-Qdrant-DC2626?logo=qdrant&logoColor=white)](https://qdrant.tech/)
[![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph-1C3C3C)](https://langchain-ai.github.io/langgraph/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

> **Verified Project A scope (2026-10-19):** The current LangGraph investigation produced one real report that the user confirmed in the browser. Separate targeted checks cover knowledge permissions, Celery ingestion, and authenticated ActionRequest creation/review/execution. These are scoped results, not a full-suite or production-readiness claim. The redesigned report view still needs visual verification; internal notification records are not email/SMS delivery. See [Project A demo steps](docs/PROJECT_A_DEMO.md) and [continuation log](docs/PROJECT_A_CONTINUATION.md).

> **Order-level inventory allocation blockage investigation (2026-10-21, synthetic fixture).** One complete authenticated Graph/API run passed with real model and SOP retrieval, six business-event citations, one separate SOP source and a limited same-shipment conclusion. It took 490.797 seconds; this single result is not a reliability or performance claim. On 2026-10-22 the user separately confirmed the saved response in the actual React page at local port 3111: concise layout, evidence expansion, request-ID copy and exit from loading. This was replay, not a new live browser-to-model run. See the [redacted evidence summary](docs/PROJECT_A_BASELINE_EVIDENCE.md) and [continuation log](docs/PROJECT_A_CONTINUATION.md).

---

## Overview

Most RAG demos are toy scripts limited to basic top-k cosine similarity on a single document. **RAGForge AI** is built as a multi-tenant SaaS architecture designed for real-world enterprise documents:
- **Multi-Tenant Isolation**: Multi-level hierarchy (`Organization` → `Workspace` → `Documents` → `Chunks`) with tenant-scoped payload filtering in Qdrant and relational metadata in PostgreSQL.
- **Hybrid Retrieval & Reranking**: Combines dense semantic vector embeddings (Voyage AI or local Ollama) with sparse keyword retrieval and cross-encoder reranking (`rerank-2`) before context injection.
- **Inspectable Retrieval Graph**: LangGraph handles query rewrite, hybrid retrieval, and reranking; chat generation and persistence run in the chat Service. Project A's investigation report uses its separate Core Agent.
- **Asynchronous Ingestion**: Offloads document parsing, OCR, recursive text chunking, and embedding generation to background Celery workers backed by Redis.

### Project A delivery status

| Capability | Verification method | Result | Date / version | Evidence path | Not covered |
|---|---|---|---|---|---|
| LangGraph investigation orchestration | Controlled Provider, old-loop/Graph comparison | 11 deterministic scenarios matched tool path, report, rejection and budgets; handoff records 90 related offline tests passed | 2026-10-19, current Graph | [11 replay cases](backend/tests/unit/test_core_graph_parity.py), [90-test handoff](docs/PROJECT_A_CONTINUATION.md) | Separate raw log for the 90-test total needs checking; these are not model reliability; no persistent Graph checkpoint |
| SOP retrieval and cited report | Authenticated real-model C05; separately, authenticated current-Graph browser submission | C05 passed once on the former Core loop; the current Graph returned one six-part report with four business event IDs and one separate SOP source, and the user confirmed browser delivery | 2026-10-18 legacy loop / 2026-10-19 current Graph | [Redacted C05 and current-Graph summaries](docs/PROJECT_A_BASELINE_EVIDENCE.md) | No stable pass rate or full C01-C12 matrix; redesigned report view has not had visual/expand/copy acceptance |
| Order-level allocation blockage investigation | Isolated PostgreSQL and offline checks; one authenticated current-Graph/API real-model run; separate local React saved-response replay | One synthetic Graph/API case passed: case → analysis → SOP; first report cited six business events and one SOP source, no correction, limited shipment-delay attribution, six-part handoff, 490.797 s. User confirmed saved response rendered in React with concise layout, evidence expansion, request-ID copy and loading exit (~163 ms to `report_rendered` in the earlier r4 check). | 2026-10-21 Graph/API; 2026-10-22 local replay; post-7c9e736 working tree | [Redacted run summary](docs/PROJECT_A_BASELINE_EVIDENCE.md) | No production case, repeatability estimate, C01-C12 matrix or live browser-to-model E2E |
| Knowledge permissions | Real isolated PostgreSQL and Qdrant retrieval with controlled chat Provider | C10 passed: authorized source reached model inputs; cross-workspace chunk/body/source ID was filtered; unauthorized API request was denied before Provider/retrieval | 2026-10-19, C10 | [Redacted C10 summary](docs/PROJECT_A_BASELINE_EVIDENCE.md) | Does not establish real chat-model behavior or document-level ACLs |
| ActionRequest creation and review | Isolated PostgreSQL tests plus authenticated HTTP/JWT demo | 21 targeted tests passed; same-enterprise key/content deduplicates, changed content conflicts, concurrent review yields one decision, and audit shares the transaction | 2026-10-19, current Service/API | [Redacted PG and HTTP summary](docs/PROJECT_A_BASELINE_EVIDENCE.md) | No automatic submission from investigation or Graph human interrupt |
| Controlled notification execution | Isolated PostgreSQL and authenticated HTTP checks | Only approved request can create one in-system notification record with `not_sent`; application status and audit commit together | 2026-10-19, current Service/API | [Redacted PG summary](docs/PROJECT_A_BASELINE_EVIDENCE.md), [demo steps](docs/PROJECT_A_DEMO.md) | No email/SMS sent; customer receipt unconfirmed |
| Celery document ingestion | Real isolated Redis broker/worker, PostgreSQL and Qdrant | One success, one controlled failure, and duplicate delivery of the same completed job produced no extra chunks/vectors/usage; failed document/job and Celery `FAILURE` were separately observed | 2026-10-19, current worker | [Redacted ingestion summary](docs/PROJECT_A_BASELINE_EVIDENCE.md) | Multi-worker races, crash recovery, other retry conditions and a general concurrency limit were not verified |

These runs belong to their stated versions and methods; their counts must not be added into a single reliability figure. The report does not automatically submit an ActionRequest, and approval alone does not create a notification record. Internal record creation is not external delivery. The evidence above does not establish a full scenario matrix or a current full backend-suite pass.

For a versioned, redacted account of these results, see the [Project A baseline evidence summary](docs/PROJECT_A_BASELINE_EVIDENCE.md). Per-run JSON/JSONL and logs remain local and are not included in the source baseline.

---

## Architecture

```mermaid
flowchart TD
    subgraph Frontend ["Web Client (Next.js 15 + Tailwind + shadcn/ui)"]
        Dashboard[Workspace Dashboard]
        ChatUI[RAG Chat & Citation Explorer]
        AdminPanel[Organization & Usage Admin]
    end

    subgraph API ["Gateway & API Layer (FastAPI)"]
        AuthRouter[/api/v1/auth - JWT & OAuth2/]
        DocRouter[/api/v1/documents - Ingestion Trigger/]
        ChatRouter[/api/v1/chat - Query & Streaming/]
        LangGraphEngine[LangGraph Retrieval\nRewrite → Hybrid Retrieve → Rerank]
    end

    subgraph Workers ["Async Processing (Celery)"]
        IngestionWorker[Document Parsing & OCR]
        ChunkingEngine[Recursive Chunking & Tokenizer]
        EmbeddingWorker[Embedding Dispatcher]
    end

    subgraph Storage ["Datastores & Queues"]
        Postgres[(PostgreSQL 16\nTenants | Workspaces | Chunks | Chat)]
        Qdrant[(Qdrant Vector DB\nHNSW Index + Tenant Filters)]
        Redis[(Redis\nCelery Broker & Rate Limiting)]
    end

    Frontend -->|JWT Bearer Auth| API
    DocRouter -->|Push Task| Redis
    Redis --> Workers
    Workers -->|Store Vectors| Qdrant
    Workers -->|Store Metadata| Postgres
    ChatRouter --> LangGraphEngine
    LangGraphEngine -->|Hybrid Search| Qdrant
    LangGraphEngine -->|Fetch History & Meta| Postgres
```

---

## Technology Stack

| Layer | Choice | Rationale |
|---|---|---|
| **Backend API** | FastAPI (Python 3.12, async) | Asynchronous I/O-bound throughput, native Pydantic v2 validation |
| **Relational DB** | PostgreSQL 16 | ACID transactions for tenants, users, documents, messages, and usage billing |
| **Vector Database** | Qdrant | Dedicated HNSW ANN index with payload filtering per tenant/workspace |
| **Cache & Queue** | Redis | High-speed Celery task broker, rate limiting, and session cache |
| **Async Workers** | Celery | Asynchronous ingestion pipeline (PDF parsing, OCR, chunking, embedding) |
| **LLM Inference** | Anthropic Claude (`claude-3-5-sonnet`) or Ollama (`llama3.1:8b`) | Query rewriting, synthesis, and citation generation (swappable provider) |
| **Embeddings** | Voyage AI (`voyage-3-large`) or Ollama (`nomic-embed-text`) | High-dimensional dense embeddings with provider abstraction |
| **Reranking** | Voyage AI Rerank (`rerank-2`) or Passthrough | Cross-encoder reranking of hybrid search candidate documents |
| **Orchestration** | LangGraph | Query rewrite, hybrid retrieval, and reranking for chat retrieval |
| **Frontend** | Next.js 15 (App Router) + TypeScript + Tailwind | Responsive dashboard, streaming chat UI, and administrative telemetry |
| **Monitoring** | Prometheus + Grafana, structlog | Real-time service metrics and structured audit logging |
| **CI/CD** | GitHub Actions | Automated linting, type-checking, and service-container integration tests |

---

## Repository Layout

```text
Rag-forge-ai/
├── backend/                  # FastAPI service, Celery workers, Alembic migrations, test suite
├── frontend/                 # Next.js 15 App Router client application
├── infra/                    # Prometheus configuration, Grafana dashboards
├── docs/                     # Technical architecture, database schemas, progress logs
├── .github/workflows/        # Automated CI/CD workflows
├── docker-compose.yml        # Multi-container local deployment
├── .env.example              # Environment variables template
├── LICENSE                   # MIT License
└── README.md
```

---

## Quickstart

### Option A — Free Local Stack (Ollama)

```bash
# 1. Pull local models in Ollama
ollama pull llama3.1:8b
ollama pull nomic-embed-text

# 2. Configure environment and launch containers
cp .env.example .env
docker compose up --build
```

### Option B — Cloud Providers (Claude + Voyage AI)

```bash
cp .env.example .env
# Set ANTHROPIC_API_KEY and VOYAGE_API_KEY in .env:
# LLM_PROVIDER=anthropic, EMBEDDING_PROVIDER=voyage, EMBEDDING_DIMENSIONS=1024, RERANK_PROVIDER=voyage
docker compose up --build
```

Once running:
- **Web Application**: [http://localhost:3000](http://localhost:3000)
- **API Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Prometheus Metrics**: [http://localhost:9090](http://localhost:9090)
- **Grafana Telemetry**: [http://localhost:3002](http://localhost:3002)

---

## Testing & Quality

To run the backend suite against configured test services:

```bash
cd backend
pytest tests/ -v
```

The Project A results listed above came from targeted, isolated runs. This README update did not rerun the backend suite, models, or scenario matrix. Continuous integration is configured in [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

---

## Documentation

- [System Architecture](docs/ARCHITECTURE.md)
- [Database Schema & ERD](docs/DATABASE.md)
- [Engineering Progress Log](docs/PROGRESS.md)
- [Project A demo steps and current API gap](docs/PROJECT_A_DEMO.md)
- [Project A continuation log](docs/PROJECT_A_CONTINUATION.md)

---

## License

This project is licensed under the [MIT License](LICENSE).
