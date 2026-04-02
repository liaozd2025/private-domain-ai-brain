---
name: knowledge-base
description: Use when answering private-domain operations questions from the knowledge base, selecting retrieval patterns, filtering by doc_type, and producing citation-grounded answers or no-result responses.
---

# 知识库技能规范 (SKILL.md)

## 知识库结构

### Collection Schema (Milvus)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | VARCHAR(64) | 文档 ID |
| content | VARCHAR(65535) | 文档内容（分块后） |
| title | VARCHAR(500) | 文档标题 |
| source | VARCHAR(500) | 来源文件名/URL |
| doc_type | VARCHAR(50) | 文档类型（见下方） |
| metadata | JSON | 额外元数据 |
| embedding | FLOAT_VECTOR(1024) | BGE-large-zh 向量 |

### 文档类型 (doc_type)

| 类型 | 说明 | 示例 |
|------|------|------|
| `strategy` | 运营策略/方法论 | 私域流量运营白皮书 |
| `sop` | 标准操作规程 | 门店社群建群 SOP |
| `template` | 模板/框架 | 活动方案模板 |
| `case` | 案例/复盘 | 某连锁品牌裂变案例 |
| `policy` | 政策/规则 | 企微使用规范 |
| `faq` | 常见问题 | 门店运营 FAQ |

## 查询模式

### 1. 单次检索
适用：问题明确、单一话题
```
search_and_rerank(query="私域裂变活动如何设计", doc_type="strategy")
```

### 2. 多步检索（查询分解）
适用：复杂问题、多维度需求
```
Step 1: search_and_rerank(query="社群冷启动方法")
Step 2: search_and_rerank(query="社群活跃度提升技巧")
Step 3: 综合两次结果合成完整答案
```

### 3. 类型过滤
适用：用户明确需要特定类型文档
```
search_knowledge_base(query="建群话术", doc_type="template", top_k=5)
```

## 答案质量标准

### 高质量答案结构
```
[核心回答] 2-3 段，直接回答问题

**关键要点：**
- 要点 1
- 要点 2

**操作建议：**
具体可执行的步骤

---
【参考来源】
[1] 文档标题 (来源文件)
[2] 文档标题 (来源文件)
```

### 无结果时的标准回复
```
抱歉，知识库中暂未找到关于「{话题}」的相关资料。

您可以：
1. 换个角度描述您的问题
2. 联系总部运营团队获取最新资料
3. 查看相关的 [其他话题] 内容
```

## 常用检索关键词映射

| 用户说 | 检索关键词 |
|--------|----------|
| "怎么拉新" | 私域获客 裂变增长 引流方法 |
| "怎么留住客户" | 复购率提升 会员运营 客户留存 |
| "社群不活跃" | 社群运营 活跃度提升 群管理 |
| "写活动方案" | 活动策划 促销方案 营销活动 |
| "企微怎么用" | 企业微信运营 企微功能 私聊运营 |
