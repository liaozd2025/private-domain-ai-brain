# Conversation Management Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为每个用户增加 ChatGPT 风格的会话管理能力，并将会话元数据存储到 PostgreSQL。

**Architecture:** 复用现有 `thread_id` 作为会话主键，消息内容继续由 LangGraph checkpointer 管理；新增独立的 conversation metadata 存储层维护标题、渠道、消息数、最近活跃时间和软删除状态，并将其接到 chat / plan / stream / webhook 入口。

**Tech Stack:** FastAPI, Pydantic, asyncpg, PostgreSQL, pytest

### Task 1: 写失败测试

**Files:**
- Modify: `tests/test_api.py`
- Create: `tests/test_conversation_store.py`

**Step 1: API 行为测试**

添加会话列表、重命名、软删除、自动建档、详情返回 metadata 的失败测试。

**Step 2: Store 行为测试**

为标题生成、upsert、列表排序、软删除、恢复逻辑添加失败测试。

**Step 3: 运行测试确认失败**

Run: `python -m pytest tests/test_api.py tests/test_conversation_store.py -q`
Expected: FAIL，因为 store、schema 和路由尚不存在。

### Task 2: 实现会话元数据存储

**Files:**
- Create: `src/memory/conversations.py`
- Modify: `scripts/init_db.sql`

**Step 1: 定义 schema 与存储 API**

实现会话摘要模型对应的 PostgreSQL 读写逻辑，并补 `is_deleted` / `deleted_at`。

**Step 2: 支持自动标题与软删除恢复**

首条消息自动生成标题；已删除会话如果收到新消息则自动恢复。

### Task 3: 接入 API 与入口

**Files:**
- Modify: `src/api/schemas.py`
- Modify: `src/api/routes.py`
- Modify: `src/api/streaming.py`
- Modify: `src/api/webhooks.py`

**Step 1: 新增会话管理接口**

增加列表、重命名、删除接口，并让详情接口返回 metadata。

**Step 2: 接线元数据写入**

在 sync chat、plan、WebSocket 和 webhook 成功完成后更新会话 metadata。

### Task 4: 验证与文档

**Files:**
- Modify: `README.md`
- Modify: `tasks/todo.md`

**Step 1: 跑目标测试**

Run: `python -m pytest tests/test_api.py tests/test_conversation_store.py -q`

**Step 2: 跑全量与静态检查**

Run: `python -m pytest tests -q`
Run: `python -m ruff check src/api/routes.py src/api/schemas.py src/api/streaming.py src/api/webhooks.py src/memory/conversations.py tests/test_api.py tests/test_conversation_store.py`

**Step 3: 回写证据**

把测试和 lint 结果记录到 `tasks/todo.md`。
