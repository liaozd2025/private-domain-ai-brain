# Main Model Switch Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将项目主模型统一切换为 `Pro/MiniMaxAI/MiniMax-M2.5`，并保留现有 OpenAI 兼容接入方式。

**Architecture:** 当前项目的主模型选择由 `Settings.primary_llm` / `Settings.primary_model` 控制，运行时由 `.env` 覆盖代码默认值。此次改动直接统一三个层面：代码默认值、示例配置、本地运行配置；并用一个最小配置测试锁住默认行为，避免再次出现默认值与实际运行值分叉。

**Tech Stack:** Python 3.11, Pydantic Settings, pytest

### Task 1: 记录任务计划

**Files:**
- Modify: `tasks/todo.md`
- Create: `docs/plans/2026-03-19-main-model-switch.md`

**Step 1: 更新任务跟踪文档**

在 `tasks/todo.md` 追加本次模型切换清单和备注，说明当前主模型配置现状。

**Step 2: 保存实现计划**

将本实现计划写入 `docs/plans/2026-03-19-main-model-switch.md`。

### Task 2: 为默认主模型写失败测试

**Files:**
- Create: `tests/test_config.py`
- Test: `tests/test_config.py`

**Step 1: 写失败测试**

编写一个测试，清除 `PRIMARY_LLM` / `PRIMARY_MODEL` 相关环境变量后实例化 `Settings(_env_file=None)`，断言默认主提供商为 `openai`，默认主模型为 `Pro/MiniMaxAI/MiniMax-M2.5`。

**Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_config.py -q`
Expected: FAIL，当前默认值仍是旧配置。

### Task 3: 切换默认值与环境模板

**Files:**
- Modify: `src/config.py`
- Modify: `.env.example`
- Modify: `.env`

**Step 1: 最小实现**

把 `Settings.primary_llm` 默认值切到 `LLMProvider.OPENAI`，`Settings.primary_model` 默认值切到 `Pro/MiniMaxAI/MiniMax-M2.5`。同步把 `.env.example` 和本地 `.env` 的主模型配置改成相同值，并更新相应注释。

**Step 2: 运行测试确认通过**

Run: `python -m pytest tests/test_config.py -q`
Expected: PASS

### Task 4: 校验配置生效

**Files:**
- Modify: `tasks/todo.md`

**Step 1: 做最小配置校验**

Run: `python - <<'PY' ... Settings() ... PY`
Expected: 输出 `PRIMARY_LLM=openai` 且 `PRIMARY_MODEL=Pro/MiniMaxAI/MiniMax-M2.5`

**Step 2: 回写结果**

将测试与配置校验结果追加到 `tasks/todo.md` 注释区，并勾选完成项。
