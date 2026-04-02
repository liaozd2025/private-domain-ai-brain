# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

私域运营专家 AI 智脑 — a multi-agent supervisor system for door/retail private-domain operations. Built on LangGraph + Deep Agents + FastAPI + PostgreSQL + Milvus.

## Common Commands

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Start all services (API + PostgreSQL + Milvus)
docker-compose up -d

# Run all tests
pytest tests/ -v

# Run a single test file
pytest tests/test_api.py -v

# Run a single test
pytest tests/test_api.py::test_chat_sync -v

# Lint
ruff check .

# Type check
mypy src

# Initialize/reset database (full schema)
psql "$DATABASE_URL" -f scripts/init_db.sql

# Apply incremental migrations (for existing databases)
psql "$DATABASE_URL" -f scripts/migrations/<migration>.sql

# Run API locally
python -m uvicorn src.main:app --reload
```

## Architecture

### Request Flow

```
User Request → FastAPI (src/api/routes.py)
    ↓
Mode Selector (src/agent/mode_selector.py)  ← auto|chat|plan
    │
    ├─ chat → Orchestrator (src/agent/orchestrator.py)
    │          → Router (src/agent/router.py)  ← intent classification
    │          → Sub-agent dispatch
    │
    └─ plan → Plan Runner (src/agent/plan_runner.py)
               → Deep Agents + Skills integration
```

### Sub-agents (`src/subagents/`)

| Agent | Route condition | Key behavior |
|-------|----------------|-------------|
| `knowledge_base.py` | `knowledge_query` | Milvus RAG + BGE reranker |
| `content_generation.py` | `content_generation` | Multi-platform templates (WeChat/Xiaohongshu/Douyin) |
| `data_analysis.py` | `data_analysis` | CSV/Excel sandbox + chart generation, store diagnosis mode |
| `attachment_analysis.py` | `attachment_analysis` | Vision model (Qwen2.5-VL) for image/doc understanding |
| `customer_service.py` | `user_role=customer` | Strict KB-only, human handoff lifecycle |

### Key Layers

- **`src/agent/`** — Orchestration logic (supervisor, router, plan runner, mode selector)
- **`src/api/`** — FastAPI routes, schemas, WebSocket streaming, webhooks, OpenAI compatibility
- **`src/memory/`** — PostgreSQL persistence (conversations, checkpointer, profiles, handoffs)
- **`src/subagents/`** — Individual agent implementations
- **`src/skills/`** — Skill prompt files (`{name}/SKILL.md`) + shared runtime loader
- **`src/tools/`** — External integrations (Milvus, OpenClaw)

### Skills System

All skills live in `src/skills/{name}/SKILL.md` with YAML frontmatter. Sub-agents load them via the shared `src/skills/runtime.py` loader. Deep Agents plan runner uses `skills=["/skills"]` with `FilesystemBackend`. Never fork skill content across agents — single source of truth.

### API Layers

- **Primary REST**: `POST /api/v1/chat`, WebSocket `/api/v1/chat/stream`
- **OpenAI Compat**: `POST /v1/chat/completions` (for Cherry Studio integration), model IDs: `private-domain-{auto,chat,plan}`
- **Webhooks**: `POST /api/v1/webhooks/wecom`, `/api/v1/webhooks/openclaw`
- **Handoff queue**: `/api/v1/handoffs` — pending → claimed → resolved lifecycle

### Database Schema

LangGraph creates `checkpoints`, `checkpoint_writes`, `checkpoint_blobs` for thread state. Custom tables:
- `conversation_metadata` — thread title, user_id, role, channel, soft-delete
- `user_profiles` — extends LangGraph store with role/preferences/topics
- `customer_service_messages` — chat history for customer service mode
- `human_handoffs` — handoff queue with unique constraint on active handoffs
- `uploaded_files` — attachment metadata

### Mode Selection Logic

`mode_selector.py` uses heuristic short-circuit (keyword match) first, lazy LLM fallback only when needed. Defaults to `chat`. Both sync (`routes.py`) and streaming (`streaming.py`) and OpenAI compat (`openai_compat.py`) must have feature parity.

### Customer Service Mode

`user_role=customer` in the request bypasses the normal orchestrator and routes to `CustomerServiceSupervisor`. This agent answers strictly from KB only; triggers human handoff on empty retrieval, low confidence, or explicit "转人工". While a handoff is active (`pending`/`claimed`), AI will not reply.

## Configuration

All settings are in `src/config.py` (Pydantic Settings). Key env vars:
- `PRIMARY_LLM` / `PRIMARY_MODEL` — defaults to `openai` / `Pro/MiniMaxAI/MiniMax-M2.5`
- `ROUTER_MODEL` — lightweight LLM for intent routing
- `VISION_MODEL` — for attachment analysis
- `POSTGRES_*` — database connection
- `MILVUS_*` — vector store connection

Copy `.env.example` to `.env` to get started.

## Engineering Lessons

- **Migrations**: Always provide standalone SQL migration files in `scripts/migrations/` for existing databases — never rely solely on `init_db.sql`.
- **Deep Agents First**: Before custom implementation, check official Deep Agents docs for built-in capabilities (skills, memory, handoff).
- **Feature Parity**: When adding features, implement them consistently across REST routes, WebSocket streaming, and OpenAI compat layer.
- **Skill Assets**: Reuse `src/skills/runtime.py` loader — do not duplicate SKILL.md content into sub-agent files.
- **Auto Mode**: Use heuristic short-circuit + lazy LLM loading to avoid initializing LLM clients on every request.
