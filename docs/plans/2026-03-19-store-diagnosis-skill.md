# Store Diagnosis Skill Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将通用 `data-analysis` 能力升级为“美容门店五大指标诊断”能力，并同步接入运行时 prompt。

**Architecture:** 通过三层改动完成升级：一是重写 `src/skills/data-analysis/` 下的 skill 与引用资料；二是在 `src/subagents/data_analysis.py` 内引入门店诊断模式识别和动态 prompt 组装；三是用最小回归测试锁住识别、prompt 构造和诊断请求走专用 agent 的行为。

**Tech Stack:** Python 3.11, pytest, python-docx, pandas

### Task 1: 写失败测试

**Files:**
- Modify: `tests/test_data_agent.py`

**Step 1: 添加门店诊断识别测试**

验证带有“五大指标/门店诊断/行动计划”等关键词的查询和附件会触发门店诊断模式。

**Step 2: 添加诊断 prompt 构造测试**

验证诊断模式 prompt 包含“数据完整性检查 / 五大指标诊断 / 行动计划表 / 品牌化动作建议”等结构。

**Step 3: 添加动态 agent 测试**

验证门店诊断请求不会复用默认静态 prompt，而会基于诊断 prompt 创建 agent。

### Task 2: 重写 skill 与引用资料

**Files:**
- Modify: `src/skills/data-analysis/SKILL.md`
- Create: `src/skills/data-analysis/references/store-diagnosis-rules.md`
- Create: `src/skills/data-analysis/references/store-diagnosis-cases.md`

**Step 1: 把主 SKILL.md 改成可触发的 skill 文档**

加入 frontmatter、触发条件、输入形态、工作流程、输出契约和常见错误。

**Step 2: 提炼规则资料**

从“需要收集的材料清单”和案例中整理五大指标定义、阈值、缺数追问、组合诊断规则。

**Step 3: 提炼案例模式**

把门店诊断笔记总结成问题模式、证据模式、通用动作和品牌化动作。

### Task 3: 接入运行时

**Files:**
- Modify: `src/subagents/data_analysis.py`

**Step 1: 增加诊断模式识别与 skill 读取**

实现门店诊断请求识别、skill/reference 文件读取和动态 prompt 构造。

**Step 2: 在 analyze 流程中使用动态 prompt**

默认请求复用现有 agent；诊断请求使用诊断 prompt 创建 agent，并保持现有返回接口不变。

### Task 4: 验证与记录

**Files:**
- Modify: `tasks/todo.md`

**Step 1: 跑目标测试**

Run: `python -m pytest tests/test_data_agent.py -q`

**Step 2: 如通过，补充静态校验**

Run: `python -m ruff check src/subagents/data_analysis.py tests/test_data_agent.py`

**Step 3: 回写证据**

将测试与 lint 结果补充到 `tasks/todo.md`。
