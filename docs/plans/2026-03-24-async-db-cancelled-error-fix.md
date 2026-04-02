# Async DB CancelledError Fix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 消除请求取消场景下由 SQLAlchemy `asyncpg` 驱动触发的数据库连接终止异常日志。

**Architecture:** 当前项目的 LangGraph checkpointer 已使用 `psycopg`，而共享 SQLAlchemy AsyncEngine 仍单独使用 `asyncpg`。本次保持数据访问接口不变，只把 SQLAlchemy 异步连接串切到 `psycopg`，并用回归测试锁定这一驱动选择，避免再次进入已知的取消路径问题。

**Tech Stack:** FastAPI, SQLAlchemy AsyncEngine, psycopg, pytest

### Task 1: 锁定回归测试

**Files:**
- Modify: `tests/test_db.py`
- Test: `tests/test_db.py`

**Step 1: Write the failing test**

新增断言：`Settings.database_url_async` 应返回 `postgresql+psycopg://...`。

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py -q`
Expected: FAIL，因为当前实现仍返回 `postgresql+asyncpg://...`

**Step 3: Write minimal implementation**

更新 `src/config.py` 中 `database_url_async` 的驱动前缀为 `postgresql+psycopg://`。

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py -q`
Expected: PASS

### Task 2: 同步说明与依赖约束

**Files:**
- Modify: `src/config.py`
- Modify: `tests/test_db.py`

**Step 1: Keep code/comments aligned**

把测试描述从 “asyncpg 驱动” 改为 “psycopg 驱动”，避免实现与文案不一致。

**Step 2: Verify no stale references remain**

Run: `rg -n "postgresql\\+asyncpg|asyncpg 驱动" src tests`
Expected: 无 SQLAlchemy 异步驱动的旧断言残留

### Task 3: 验证

**Files:**
- Modify: `tasks/todo.md`
- Modify: `tasks/lessons.md`

**Step 1: Run targeted verification**

Run:
- `pytest tests/test_db.py tests/test_profile_store.py tests/test_conversation_store.py tests/test_auth.py -q`
- `ruff check src/config.py src/memory/db.py tests/test_db.py`

Expected: 全部通过

**Step 2: Document results**

把验证命令、结果和根因结论写回 `tasks/todo.md`，并在 `tasks/lessons.md` 记录“共享数据库栈避免双驱动分裂”的经验。
