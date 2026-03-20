# 私域运营专家 AI 智脑

基于 LangGraph Supervisor 模式的多智能体私域运营助手，支持门店老板/销售/店长/总部市场等多角色使用。

## 核心能力

| 能力 | 描述 |
|------|------|
| **智能路由** | 5类意图分类，闲聊不查KB，精准路由到专用子智能体 |
| **知识库问答** | Milvus向量检索 + BGE重排序 + 带引用答案 |
| **内容生成** | 朋友圈/小红书/抖音/企微多平台内容，角色感知 |
| **数据分析** | Excel/CSV解析、图片/文档理解、沙箱执行Python分析、图表生成 |
| **会话记忆** | PostgreSQL会话持久化 + 用户画像自动提取 |
| **多渠道接入** | Web Chat / 企微Webhook / OpenClaw集成 |

## 快速启动

### 1. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入必要的 API Key
```

### 2. Docker 启动（推荐）

```bash
docker-compose up -d
```

### 3. 本地开发

```bash
pip install -e ".[dev]"
python -m uvicorn src.main:app --reload
```

### 4. 已有数据库执行增量迁移

如果你的 PostgreSQL 已经初始化过，需要额外执行会话管理迁移 SQL：

```bash
psql "$DATABASE_URL" -f scripts/migrations/2026-03-20-add-conversation-metadata.sql
```

`scripts/init_db.sql` 只负责全新初始化；已有库升级请使用 `scripts/migrations/2026-03-20-add-conversation-metadata.sql`。

## API 端点

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/api/v1/chat` | 发送消息（同步） |
| WS | `/api/v1/chat/stream` | 流式对话 |
| POST | `/api/v1/files/upload` | 文件上传 |
| GET | `/api/v1/conversations` | 用户会话列表 |
| GET | `/api/v1/conversations/{id}` | 对话历史 |
| PATCH | `/api/v1/conversations/{id}` | 重命名会话 |
| DELETE | `/api/v1/conversations/{id}` | 删除会话（软删除） |
| GET | `/api/v1/users/{id}/profile` | 用户画像 |
| POST | `/api/v1/webhooks/wecom` | 企微Webhook |
| POST | `/api/v1/webhooks/openclaw` | OpenClaw Webhook |
| GET | `/api/v1/health` | 健康检查 |
| GET | `/v1/models` | OpenAI 兼容模型清单 |
| POST | `/v1/chat/completions` | OpenAI 兼容聊天接口 |

## Chat 与 Plan 模式

普通对话默认使用 `mode=chat`，走现有编排器：

```json
{
  "message": "我是门店老板，帮我做一个提升会员复购率的三步方案",
  "user_id": "boss_001",
  "mode": "chat"
}
```

如需“先规划、再执行、再汇报”，传 `mode=plan`。该模式基于 Deep Agents，会返回 `plan` 字段，并在 WebSocket 中先发送 `plan/step` 事件：

```json
{
  "message": "先规划再执行一份门店活动方案",
  "user_id": "boss_001",
  "mode": "plan"
}
```

## Cherry Studio 接入

可将本服务作为 Cherry Studio 的自定义 `OpenAI` 服务商接入：

- Base URL: `http://localhost:8000/v1`
- Model:
  - `private-domain-chat`：普通聊天
  - `private-domain-plan`：计划模式，会把内部 plan 渲染成文本再返回
- API Key：首版兼容层不校验，可按 Cherry Studio 要求随便填一个占位值

普通聊天示例：

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "private-domain-chat",
    "messages": [
      {"role": "system", "content": "你是门店经营顾问"},
      {"role": "user", "content": "帮我分析今天门店转化率"}
    ]
  }'
```

计划模式示例：

```bash
curl -N -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "private-domain-plan",
    "stream": true,
    "messages": [
      {"role": "user", "content": "先规划再执行一份会员召回方案"}
    ]
  }'
```

## 架构

```
用户请求 → FastAPI → 编排器(Supervisor)
                        ↓ 路由分类
              ┌─────────┼─────────┐─────────┐
           KB Agent  Data Agent Content Agent OpenClaw
              ↓          ↓          ↓
           Milvus     沙箱执行    模板系统
```

## 附件分析调用方式

先上传文件，再在聊天请求里仅传 `file_id`：

```bash
curl -X POST http://localhost:8000/api/v1/files/upload \
  -F "file=@poster.png" \
  -F "user_id=user123"
```

上传成功后，再把返回的 `file_id` 放进 `attachments`：

```json
{
  "message": "帮我看看这张图讲了什么",
  "user_id": "user123",
  "attachments": [{"file_id": "abc123"}]
}
```

支持类型：`png/jpg/jpeg/webp/csv/xlsx/pdf/docx/txt`。表格附件会优先走数据分析，图片和文档会走附件分析链路。

## 运行测试

```bash
pytest tests/ -v
```

## 技术栈

- **Agent框架**: LangGraph + LangChain + Deep Agents
- **API**: FastAPI + WebSocket
- **LLM**: Claude Sonnet (主力) / Qwen-Plus (路由)
- **向量DB**: Milvus
- **存储**: PostgreSQL
- **Embedding**: BGE-large-zh-v1.5
- **Reranker**: BGE-reranker-v2-m3
