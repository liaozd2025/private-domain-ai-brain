# Subagent Skill Alignment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 `knowledge-base`、`content-generation` 和现有 `data-analysis` 共用 `src/skills` 作为运行时指令资产来源，减少硬编码 prompt 与 skill 文档脱节的问题。

**Architecture:** 保持现有 orchestrator、API 和工具调用路径不变，只新增一个轻量的 runtime skill loader，由各子智能体在构造 system prompt 时读取对应 `SKILL.md`。`plan_runner` 继续使用 Deep Agents 官方 `skills=[...]`，非 deepagents 子智能体则复用同一份 skill 目录作为单一事实源。

**Tech Stack:** Python 3.11、FastAPI、LangChain `create_agent` 包装层、Deep Agents 0.4.11、pytest、ruff。

### Task 1: 锁定 prompt 必须从 skill 目录构造

**Files:**
- Modify: `tests/test_content_agent.py`
- Modify: `tests/test_kb_agent.py`

**Step 1: Write the failing tests**

在 `tests/test_content_agent.py` 增加断言，要求内容生成 system prompt 包含 `content-generation` skill 中的关键段落，并包含共享的私域运营领域知识。  
在 `tests/test_kb_agent.py` 增加断言，要求知识库 system prompt 包含 `knowledge-base` skill 中的检索规则，并包含共享的私域运营领域知识。

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_content_agent.py tests/test_kb_agent.py -q`  
Expected: FAIL，因为当前 prompt 仍是硬编码字符串，未读取 `src/skills/*/SKILL.md`。

### Task 2: 新增共享 runtime skill loader

**Files:**
- Create: `src/skills/runtime.py`
- Test: `tests/test_content_agent.py`
- Test: `tests/test_kb_agent.py`

**Step 1: Write minimal runtime loader**

实现缓存式读取函数，支持：
- 定位 `src/skills/<skill-name>/SKILL.md`
- 拼接多个 skill 段落
- 生成统一的 markdown bundle，供子智能体作为 system prompt 片段使用

**Step 2: Keep YAGNI**

不做通用注册中心、不做动态触发器、不做远程 backend；只做本项目运行时需要的本地 skill 文本加载。

### Task 3: 重构知识库与内容生成子智能体

**Files:**
- Modify: `src/subagents/knowledge_base.py`
- Modify: `src/subagents/content_generation.py`
- Optionally modify: `src/subagents/data_analysis.py`

**Step 1: Replace hard-coded system prompts with builders**

为知识库和内容生成分别提供 `build_*_system_prompt()`：
- `knowledge-base` = 共享 `private-domain-ops` + `knowledge-base`
- `content-generation` = 共享 `private-domain-ops` + `content-generation`

`data-analysis` 保持现有门店诊断逻辑，但如果能复用同一个 loader，则复用，不改行为。

**Step 2: Minimal implementation**

保持现有 `ModernToolAgent` / legacy fallback 调用方式不变，只替换 prompt 来源，不改工具集、不改接口参数。

### Task 4: 验证与记录

**Files:**
- Modify: `tasks/todo.md`
- Modify: `tasks/lessons.md`

**Step 1: Run targeted checks**

Run: `python -m pytest tests/test_content_agent.py tests/test_kb_agent.py -q`  
Expected: PASS

Run: `python -m ruff check src/skills/runtime.py src/subagents/content_generation.py src/subagents/knowledge_base.py tests/test_content_agent.py tests/test_kb_agent.py`  
Expected: PASS

**Step 2: Run regression suite**

Run: `python -m pytest tests -q`  
Expected: PASS

**Step 3: Document the result**

在 `tasks/todo.md` 记录这次对齐的范围和边界，在 `tasks/lessons.md` 记录“当官方 skill 机制不能直接覆盖非 deepagents 子智能体时，应复用同一 skill 资产作为单一事实源，而不是继续分叉硬编码 prompt”。
