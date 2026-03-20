# Task Plan

- [x] Inspect repository structure, configuration, tests, and recent git history.
- [x] Draft the contributor-guide outline for this repository.
- [x] Create `AGENTS.md` with repository-specific guidance.
- [x] Verify commands, structure references, and document length.

## Comments

- 2026-03-19: Repository has no commit history yet on `main`, so commit guidance will establish a Conventional Commits baseline.
- 2026-03-19: `tasks/lessons.md` is not present; no correction-driven lesson update was required for this task.
- 2026-03-19: Verified `AGENTS.md` title/sections manually and confirmed the document length is 338 words.

## SiliconFlow Config

- [x] Inspect existing provider and environment-variable wiring.
- [x] Create a local `.env` that routes both primary and router models through SiliconFlow's OpenAI-compatible API.
- [ ] Replace the placeholder API key with the real SiliconFlow key.
- [x] Verify the local configuration loads into `Settings`.
- [ ] Verify the app can initialize and answer a request with the new provider.

## SiliconFlow Notes

- 2026-03-19: The code already supports an OpenAI-compatible provider, so SiliconFlow is configured through `OPENAI_API_KEY` and `OPENAI_BASE_URL` instead of adding a new provider.
- 2026-03-19: `.env` was created locally with a placeholder key because no real SiliconFlow API key was provided in the session.
- 2026-03-19: `python - <<'PY' ... Settings() ... PY` confirmed `PRIMARY_LLM=openai`, `PRIMARY_MODEL=deepseek-ai/DeepSeek-V3`, `ROUTER_LLM=openai`, `ROUTER_MODEL=Qwen/Qwen2.5-7B-Instruct`, and `OPENAI_BASE_URL=https://api.siliconflow.cn/v1`.
- 2026-03-19: `python -m pytest tests/test_router.py -q` passed (`7 passed in 0.07s`).
- 2026-03-19: `python -m pytest tests/test_api.py -q` fails in the current baseline with `AttributeError: module 'src.memory' has no attribute 'checkpointer'`; this is unrelated to the SiliconFlow config change.

## Attachment Analysis

- [x] Add file metadata persistence and resolve chat attachments by `file_id` on the server side.
- [x] Extend upload support to image files and add a dedicated attachment analysis route.
- [x] Add a vision-model-backed attachment analysis agent for images and mixed attachments.
- [x] Add regression tests for image upload, attachment routing, and server-side attachment resolution.
- [x] Verify the full test suite passes after dependency install.

## Attachment Analysis Notes

- 2026-03-19: Added local metadata persistence under `uploads/_meta/` so clients only send `file_id`, not `file_path`.
- 2026-03-19: Added `VISION_LLM` / `VISION_MODEL` config for SiliconFlow multimodal analysis while keeping the main text model unchanged.
- 2026-03-19: Installed missing runtime deps from `pyproject.toml` (`pandas`, `matplotlib`, `openpyxl`, `pypdf`, `python-docx`) so analysis and document parsing tests can run locally.
- 2026-03-19: `python -m pytest tests -q` passed (`37 passed in 12.52s`).

## LangChain / Plan Mode

- [x] Add failing API and WebSocket tests for `mode=plan`.
- [x] Upgrade LangChain / LangGraph dependency floors and align local runtime packages.
- [x] Add a Deep Agents-backed plan runner with thread-aware persistence and domain tools.
- [x] Route `/api/v1/chat` and `/api/v1/chat/stream` by mode while keeping `mode=chat` backward compatible.
- [x] Remove legacy agent API assumptions that break on modern LangChain.
- [x] Run targeted regression tests, then the full suite.

## LangChain / Plan Mode Notes

- 2026-03-19: Local runtime before implementation had `langchain==1.0.5` and `langgraph==1.1.2`; official latest versions checked during planning were `langchain==1.2.12`, `langgraph==1.1.3`, and `deepagents==0.4.11`.
- 2026-03-19: Repository code already used `langgraph.StateGraph` but did not use `deepagents` or any user-visible plan-mode API.
- 2026-03-19: `create_tool_calling_agent` is no longer importable from `langchain.agents` under the newer runtime, so tool/action paths need a non-legacy implementation.
- 2026-03-19: Added `mode=plan` to sync and streaming chat interfaces; sync responses now return `plan`, and WebSocket plan mode emits `plan -> step -> token -> done`.
- 2026-03-19: Added `src/agent/plan_runner.py` on top of `deepagents.create_deep_agent(...)`, reusing the existing checkpointer and role-aware system prompt.
- 2026-03-19: Introduced `src/agent/runtime.py` so modern `create_agent()` can replace legacy `AgentExecutor/create_tool_calling_agent` assumptions in the subagents and tool-action path.
- 2026-03-19: Verified targeted checks:
  - `python -m pytest tests/test_api.py -q`
  - `python -m pytest tests/test_kb_agent.py -q`
  - `python -m pytest tests/test_data_agent.py -q`
  - `python -m pytest tests/test_content_agent.py -q`
  - `python -m pytest tests -q`
  - `python -m ruff check src/agent/orchestrator.py src/agent/plan_runner.py src/agent/runtime.py src/api/routes.py src/api/schemas.py src/api/streaming.py src/subagents/content_generation.py src/subagents/data_analysis.py tests/test_api.py`
- 2026-03-19: Verified local package versions after upgrade:
  - `langchain==1.2.12`
  - `langgraph==1.1.3`
  - `deepagents==0.4.11`
  - `langchain-openai==1.1.11`
  - `langchain-community==0.4.1`
  - `langgraph-checkpoint-postgres==3.0.5`

## Docker Build Fix

- [x] Investigate the Docker image build failure caused by `zlib-state`.
- [x] Add the missing system dependency required to compile `zlib-state` in the API image.
- [x] Investigate the Docker Compose startup failure caused by fixed Milvus container names.
- [x] Remove global Milvus `container_name` entries and the obsolete Compose `version` field.
- [x] Investigate the Docker Compose startup failure caused by a host PostgreSQL port collision.
- [x] Make the host PostgreSQL port configurable and default it to `5433`.

## Docker Build Fix Notes

- 2026-03-19: Root cause was not application code. The container image lacked `zlib.h`, so `zlib-state` failed during native wheel compilation on Linux `aarch64`.
- 2026-03-19: Fixed by adding `zlib1g-dev` to `Dockerfile` before `pip install -e ".[dev]"`.
- 2026-03-19: After the image built successfully, `docker-compose up -d` still failed because `docker-compose.yml` hard-coded `milvus-etcd`, `milvus-minio`, and `milvus-standalone`, which conflicted with stale local containers from a previous Milvus install.
- 2026-03-19: Fixed by removing those `container_name` entries so Compose uses project-scoped names, and by removing the obsolete top-level `version` field to silence the deprecation warning.
- 2026-03-19: A second startup failure came from host port `5432` already being occupied by another local PostgreSQL container (`docker-db-1`).
- 2026-03-19: Fixed by changing the PostgreSQL port mapping to `${POSTGRES_PORT:-5433}:5432`, which preserves host access while avoiding the most common local conflict by default.

## OpenAI Compatibility Layer

- [x] Add failing tests for OpenAI-compatible model listing, chat completions, SSE streaming, and image input translation.
- [x] Add a `/v1` compatibility router for Cherry Studio using `private-domain-chat` and `private-domain-plan` model aliases.
- [x] Map OpenAI `messages[]` into internal prompt plus image attachments, and render plan-mode output as plain text.
- [x] Document Cherry Studio configuration and verify targeted regressions.

## OpenAI Compatibility Notes

- 2026-03-19: Added `src/api/openai_compat.py` with `/v1/models` and `/v1/chat/completions`, including `stream=true` SSE output in OpenAI chunk format.
- 2026-03-19: Added model aliases `private-domain-chat` and `private-domain-plan`; the plan alias routes to `DeepPlanRunner` and renders the structured plan into Markdown text for OpenAI-compatible clients.
- 2026-03-19: The adapter rebuilds context from incoming `messages[]` and maps OpenAI image parts directly into internal image attachments under `uploads/openai_compat/`, avoiding the existing `file_id` upload flow.
- 2026-03-19: Explicitly rejects unsupported OpenAI fields for v1 (`tools`, `tool_choice`, `response_format`, `n!=1`, `logprobs`, `audio`, `modalities`) with a 400 response instead of pretending to support them.

## Main Model Switch

- [x] Write the implementation plan for switching the primary model to `Pro/MiniMaxAI/MiniMax-M2.5`.
- [x] Add a failing regression test for the default primary provider/model selection.
- [x] Update code defaults and environment templates to use `Pro/MiniMaxAI/MiniMax-M2.5` as the primary model.
- [x] Verify the targeted tests and settings load with the new primary model.

## Main Model Switch Notes

- 2026-03-19: Current local `.env` still points `PRIMARY_MODEL` to `deepseek-ai/DeepSeek-V3`, while code defaults and `.env.example` still reflect the older Claude-based setup.
- 2026-03-19: Added `tests/test_config.py` to lock the default primary provider/model to `openai` + `Pro/MiniMaxAI/MiniMax-M2.5`.
- 2026-03-19: Verified TDD red-green for `tests/test_config.py`:
  - RED: `python -m pytest tests/test_config.py -q` failed because `Settings.primary_llm` defaulted to `claude`.
  - GREEN: after updating `src/config.py`, `.env.example`, and local `.env`, the same command passed (`1 passed in 0.03s`).
- 2026-03-19: `python - <<'PY' ... Settings() ... PY` confirmed `PRIMARY_LLM=openai`, `PRIMARY_MODEL=Pro/MiniMaxAI/MiniMax-M2.5`, and `OPENAI_BASE_URL=https://api.siliconflow.cn/v1`.

## Store Diagnosis Skill

- [x] Add failing tests for store-diagnosis detection and diagnosis-specific prompt construction.
- [x] Rewrite the `data-analysis` skill into a store-diagnosis skill with reference docs for rules and case patterns.
- [x] Wire the diagnosis skill into the runtime data-analysis agent so store-diagnosis requests use the structured prompt.
- [x] Run targeted regression tests and record the verification evidence.

## Store Diagnosis Skill Notes

- 2026-03-19: Current `src/skills/data-analysis/SKILL.md` is a generic markdown note and is not wired into runtime behavior.
- 2026-03-19: Runtime analysis behavior currently comes from `src/subagents/data_analysis.py`, which uses one static system prompt for all data-analysis requests.
- 2026-03-19: Added regression tests for diagnosis-mode detection, diagnosis prompt construction, and dynamic agent creation; RED run of `python -m pytest tests/test_data_agent.py -q` failed with 3 expected failures because the diagnosis helpers and dynamic prompt path did not exist yet.
- 2026-03-19: Rewrote `src/skills/data-analysis/SKILL.md` with frontmatter and created `references/store-diagnosis-rules.md` plus `references/store-diagnosis-cases.md` for progressive disclosure.
- 2026-03-19: Added runtime helpers in `src/subagents/data_analysis.py` to detect store-diagnosis requests, load the skill/reference bundle, and build a diagnosis-only prompt while preserving the generic data-analysis path.
- 2026-03-19: Verified:
  - `python -m pytest tests/test_data_agent.py -q` → `9 passed in 1.11s`
  - `python -m ruff check src/subagents/data_analysis.py tests/test_data_agent.py` → `All checks passed!`
  - `python -m pytest tests -q` → `53 passed in 2.48s`

## Conversation Management

- [x] Add failing tests for conversation list, rename, soft delete, and auto-create metadata.
- [x] Implement conversation metadata storage on PostgreSQL with soft-delete support.
- [x] Add conversation management APIs and extend conversation history responses with metadata.
- [x] Wire metadata updates into chat, plan, streaming, and webhook entrypoints.
- [x] Run targeted tests, full regression, and static checks; record the evidence.

## Conversation Management Notes

- 2026-03-20: Current backend only persists thread state in LangGraph checkpointer and exposes `GET /api/v1/conversations/{thread_id}`; there is no user-scoped conversation list or title management yet.
- 2026-03-20: `scripts/init_db.sql` already creates `conversation_metadata`, but the table is not used anywhere in the current codebase.
- 2026-03-20: Added RED tests for chat auto-create metadata, conversation listing, rename, soft delete, and conversation store helpers; initial `python -m pytest tests/test_api.py tests/test_conversation_store.py -q` failed with 7 expected failures because `src.memory.conversations` and the new APIs did not exist.
- 2026-03-20: Added `src/memory/conversations.py` with auto-title generation, PostgreSQL schema bootstrap, per-user listing, rename, soft delete, and restore-on-new-turn behavior.
- 2026-03-20: Extended conversation APIs with `GET /api/v1/conversations`, `PATCH /api/v1/conversations/{thread_id}`, and `DELETE /api/v1/conversations/{thread_id}`, and enriched conversation history responses with metadata fields.
- 2026-03-20: Wired successful chat, plan, WebSocket, WeCom, and OpenClaw entrypoints to record conversation metadata while keeping `/v1` compatibility calls out of the conversation list.
- 2026-03-20: Verified:
  - `python -m pytest tests/test_api.py tests/test_conversation_store.py -q` → `20 passed in 0.98s`
  - `python -m ruff check src/api/routes.py src/api/schemas.py src/api/streaming.py src/api/webhooks.py src/memory/conversations.py tests/test_api.py tests/test_conversation_store.py` → `All checks passed!`
  - `python -m pytest tests -q` → `60 passed in 2.23s`

## Conversation SQL Migration

- [x] Add a failing regression test that requires a standalone SQL migration for conversation metadata.
- [x] Add an incremental SQL migration for existing databases to create/alter `conversation_metadata`.
- [x] Document how to apply the migration for already-initialized environments.
- [x] Verify the new regression test and relevant checks.

## Conversation SQL Migration Notes

- 2026-03-20: User feedback identified a real delivery gap: the conversation feature shipped with runtime schema bootstrap and `scripts/init_db.sql`, but without a standalone SQL migration for existing databases.
- 2026-03-20: Added `tests/test_db_scripts.py` first; RED run of `python -m pytest tests/test_db_scripts.py -q` failed because `scripts/migrations/2026-03-20-add-conversation-metadata.sql` did not exist.
- 2026-03-20: Added `scripts/migrations/2026-03-20-add-conversation-metadata.sql` to support existing PostgreSQL instances and documented the execution command in `README.md`.
- 2026-03-20: Verified:
  - `python -m pytest tests/test_db_scripts.py -q` → `1 passed in 0.01s`
  - `python -m ruff check tests/test_db_scripts.py` → `All checks passed!`
  - `python -m pytest tests -q` → `61 passed in 2.12s`

## Auto Mode And Plan Progress

- [x] Add failing tests for automatic chat/plan selection, response mode fields, and rich plan progress events.
- [x] Implement a reusable mode selector with explicit override, heuristic routing, and conservative fallback.
- [x] Wire auto mode into sync chat, streaming chat, webhooks, and OpenAI compatibility aliases.
- [x] Upgrade plan streaming events so the frontend can render task/tool progress safely.
- [x] Update docs and record verification evidence.

## Auto Mode And Plan Progress Notes

- 2026-03-20: Current behavior still relies on explicit `mode=chat|plan` for first-party APIs and `private-domain-chat|private-domain-plan` model aliases for `/v1`; there is no backend auto-selection layer yet.
- 2026-03-20: Added RED tests for `ModeSelector`, default `mode=auto`, `requested_mode/resolved_mode` response fields, WebSocket `mode/task/tool` events, and `private-domain-auto` alias; initial `python -m pytest tests/test_mode_selector.py tests/test_api.py tests/test_openai_compat.py -q` failed with 10 expected failures because the selector module, new response fields, and auto alias did not exist.
- 2026-03-20: Added `src/agent/mode_selector.py` with explicit override, heuristic-first routing, lazy LLM fallback, and conservative chat fallback.
- 2026-03-20: Updated first-party sync/streaming chat, WeCom/OpenClaw webhooks, and `/v1/chat/completions` to use the selector; OpenAI compatibility now exposes `private-domain-auto`.
- 2026-03-20: Upgraded `plan_runner.stream()` to emit richer `plan/task/tool/token/done` progress events with safe summaries so the frontend can show Manus/Claude Code-style background activity.
- 2026-03-20: Verified:
  - `python -m pytest tests/test_mode_selector.py tests/test_api.py tests/test_openai_compat.py -q` → `31 passed in 1.78s`
  - `python -m ruff check src/agent/mode_selector.py src/agent/plan_runner.py src/api/routes.py src/api/schemas.py src/api/streaming.py src/api/openai_compat.py src/api/webhooks.py tests/test_mode_selector.py tests/test_api.py tests/test_openai_compat.py` → `All checks passed!`
  - `python -m pytest tests -q` → `67 passed in 2.75s`
