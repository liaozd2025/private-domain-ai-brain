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

## 环境划分

- `docker-compose.yml`：生产环境，默认 `APP_ENV=production`
- `docker-compose.dev.yml`：开发环境，默认 `APP_ENV=development`
- `.env.example`：生产环境变量模板
- `.env.dev.example`：开发环境变量模板

## 开发环境启动

### 1. 准备开发环境变量

```bash
cp .env.dev.example .env.dev
```

开发环境默认关闭 API 认证，并暴露这些端口：

- `8000`：API
- `5432`：PostgreSQL
- `19530`：Milvus
- `9091`：Milvus health
- `9000/9001`：MinIO / MinIO Console

### 2. 使用 Docker Compose 启动开发环境

```bash
docker compose -f docker-compose.dev.yml --env-file .env.dev up -d --build api
```

这条命令会：

- 只构建 `api` 镜像
- 自动拉起 `postgres`、`etcd`、`minio`、`milvus` 这些依赖服务
- 不会去“编译”这些依赖，它们直接使用官方镜像

### 3. 查看开发日志

```bash
docker compose -f docker-compose.dev.yml logs -f api
```

### 4. 停止开发环境

```bash
docker compose -f docker-compose.dev.yml --env-file .env.dev down
```

开发环境特点：

- `api` 挂载 `./src:/app/src`，支持 `uvicorn --reload`
- `uploads` 映射到项目目录 `./uploads`
- PostgreSQL / Milvus / MinIO 使用 Docker named volumes，适合本机反复启动

## 生产环境启动

### 1. 配置生产环境变量

```bash
cp .env.example .env
# 编辑 .env，填入真实密钥和生产域名
```

生产环境至少要改这些值：

- `POSTGRES_PASSWORD`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `OPENAI_API_KEY`
- `SECRET_KEY`
- `OPENCLAW_WEBHOOK_SECRET`
- `OSS_ACCESS_KEY_ID`
- `OSS_ACCESS_KEY_SECRET`
- `OSS_BUCKET_NAME`
- `OSS_ENDPOINT`
- `API_CORS_ORIGINS`

### 2. 准备生产数据目录

```bash
sudo mkdir -p /data/private-domain-ai-brain/{uploads,postgres,etcd,minio,milvus}
sudo chown -R $USER /data/private-domain-ai-brain
sudo chown -R 10001:10001 /data/private-domain-ai-brain/uploads
sudo chmod -R u+rwX /data/private-domain-ai-brain/uploads
```

说明：

- `uploads/` 会 bind mount 到 API 容器内的 `/app/uploads`
- API 容器默认以 `uid=10001` 运行，因此宿主机 `uploads/` 至少要允许 `10001` 写入，否则首次创建 `oss_cache/` 时会报 `Permission denied`

### 3. 启动生产环境

```bash
docker compose up -d --build
```

生产环境特点：

- 默认宿主机数据目录是 `/data/private-domain-ai-brain/`
- 生产 compose 不再暴露 Postgres 和 Milvus 到宿主机公网端口
- PostgreSQL 默认映射为宿主机 `5431 -> 容器 5432`，应用内部连接仍使用 `postgres:5432`
- OpenClaw webhook 需要 `X-OpenClaw-Signature`

### 4. 查看生产日志

```bash
docker compose logs -f api
```

可额外验证上传缓存目录权限：

```bash
docker compose exec api id
docker compose exec api sh -lc 'mkdir -p /app/uploads/oss_cache/healthcheck && touch /app/uploads/oss_cache/healthcheck/probe'
```

### 5. 停止生产环境

```bash
docker compose down
```

`down` 不会删除生产 bind mount 数据；只有你手动删除 `/data/private-domain-ai-brain/*` 才会清空。

### 6. 用部署脚本发布到生产

如果你的生产环境是“单机 Linux + Docker Compose”，并且希望从本地工作区通过 `rsync + ssh` 发布到服务器，可以直接使用：

```bash
bash scripts/deploy_prod.sh \
  --host your-prod-host \
  --user ubuntu \
  --target-dir /opt/private-domain-ai-brain \
  --identity ~/.ssh/id_ed25519 \
  --backup
```

这套脚本约定：

- 本地入口是 `scripts/deploy_prod.sh`，它会同步当前工作区到远端
- 远端执行逻辑在 `scripts/deploy_remote.sh`
- 远端 `.env` 必须提前准备好，脚本不会上传密钥
- 默认要求 `APP_ENV=production`，并校验关键密钥和 OSS 配置已填真实值
- 数据库相关配置里，`POSTGRES_PORT` 保持容器内端口 `5432`；如需从宿主机访问 PostgreSQL，请改 `POSTGRES_HOST_PORT`，默认是 `5431`
- 首次部署时，如 `AUTH_ENABLED=true` 且数据库里还没有有效 `api_credentials`，脚本会自动生成一个初始凭证并打印一次
- `--backup` 会在迁移前导出 PostgreSQL 备份到 `${APP_DATA_ROOT}/backups/`
- `--dry-run` 只打印将执行的动作，不真正修改远端环境

前提条件：

- 远端已安装 Docker Engine 和 Docker Compose 插件
- 远端已有反向代理或负载均衡转发到 `:8000`
- 远端项目目录下存在 `.env`

当前脚本不负责：

- 安装/配置 Nginx、Caddy、HTTPS
- 备份 Milvus / MinIO
- 零停机蓝绿发布

发布完成后，至少执行这些检查：

```bash
cd /opt/private-domain-ai-brain
docker compose ps
docker compose logs --tail=200 api
curl -fsS http://127.0.0.1:8000/api/v1/health
```

## 本地非 Docker 开发

如果你不想在开发环境用 Docker 跑 API，也可以只启动依赖容器，再本机运行 FastAPI：

```bash
cp .env.dev.example .env.dev
docker compose -f docker-compose.dev.yml --env-file .env.dev up -d postgres etcd minio milvus
cp .env.dev .env
pip install -e ".[dev]"
python -m uvicorn src.main:app --reload
```

## 已有数据库执行增量迁移

如果你的 PostgreSQL 已经初始化过，需要额外执行增量迁移 SQL：

```bash
psql "postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@localhost:$POSTGRES_PORT/$POSTGRES_DB" -f scripts/migrations/2026-03-20-add-conversation-metadata.sql
psql "postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@localhost:$POSTGRES_PORT/$POSTGRES_DB" -f scripts/migrations/2026-03-20-add-customer-service-support.sql
```

`scripts/init_db.sql` 只负责全新初始化；已有库升级请执行 `scripts/migrations/` 下对应脚本。

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
| GET | `/api/v1/handoffs` | 人工接管队列 |
| GET | `/api/v1/handoffs/{id}` | 人工接管详情 |
| POST | `/api/v1/handoffs/{id}/claim` | 人工领取会话 |
| POST | `/api/v1/handoffs/{id}/reply` | 人工回复客户 |
| POST | `/api/v1/handoffs/{id}/resolve` | 结束人工接管 |
| GET | `/api/v1/users/{id}/profile` | 用户画像 |
| POST | `/api/v1/webhooks/wecom` | 企微Webhook |
| POST | `/api/v1/webhooks/openclaw` | OpenClaw Webhook |
| GET | `/api/v1/health` | 健康检查 |
| GET | `/v1/models` | OpenAI 兼容模型清单 |
| POST | `/v1/chat/completions` | OpenAI 兼容聊天接口 |

## Chat 与 Plan 模式

一方接口现在默认使用 `mode=auto`。后端会保守判断本轮请求走普通 `chat` 还是 `plan`：

```json
{
  "message": "我是门店老板，帮我做一个提升会员复购率的三步方案",
  "user_id": "boss_001",
  "mode": "auto"
}
```

如果你要强制覆盖自动判断，仍然可以显式传 `mode=chat` 或 `mode=plan`。`plan` 模式基于 Deep Agents；同步接口会返回 `requested_mode` 和 `resolved_mode`，WebSocket 会先发 `mode` 事件，再按 `plan/task/tool/token/done` 输出执行进度：

```json
{
  "message": "先规划再执行一份门店活动方案",
  "user_id": "boss_001",
  "mode": "plan"
}
```

## 客服模式与转人工

一方接口支持显式传 `user_role=customer` 进入客服链路。客服模式固定按单轮客服交互处理，不走 `plan`：

```json
{
  "message": "退款怎么处理？",
  "user_id": "cust_001",
  "user_role": "customer"
}
```

客服回答严格基于知识库中 `doc_type=customer_service` 的内容。知识库检索为空、相关性不足，或客户主动要求人工时，系统会自动创建人工接管记录，并返回：

`这个问题我暂时无法准确回答，已为您转接人工客服，请稍候。`

`GET /api/v1/conversations/{thread_id}` 对客服线程会返回客服消息流；其中人工回复和系统转人工提示也会出现在历史里。企微和 OpenClaw webhook 默认按客服消息处理，只有 OpenClaw metadata 显式声明内部角色时才回退到内部助手链路。

## Cherry Studio 接入

可将本服务作为 Cherry Studio 的自定义 `OpenAI` 服务商接入：

- Base URL: `http://localhost:8000/v1`
- Model:
  - `private-domain-auto`：自动选择 chat 或 plan
  - `private-domain-chat`：普通聊天
  - `private-domain-plan`：计划模式，会把内部 plan 渲染成文本再返回
- API Key：首版兼容层不校验，可按 Cherry Studio 要求随便填一个占位值

`/v1/chat/completions` 现在按服务端会话模式工作：新会话不传 `thread_id`，响应会返回顶层 `thread_id`；后续续聊只需继续传同一个 `thread_id` 和本轮最新一条用户消息。历史列表和详情继续复用 `/api/v1/conversations` 系列接口。兼容层还支持顶层 `user_role` 与 `store_id` 字段；`store_id` 当前只透传预留，不触发额外业务逻辑。

自动模式示例：

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "private-domain-auto",
    "user": "boss_001",
    "user_role": "门店老板",
    "store_id": "store_001",
    "messages": [
      {"role": "user", "content": "帮我分析今天门店转化率"}
    ]
  }'
```

续聊示例：

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "private-domain-chat",
    "user": "boss_001",
    "thread_id": "thread_1234567890abcd",
    "user_role": "门店老板",
    "store_id": "store_001",
    "messages": [
      {"role": "user", "content": "继续分析上面这个门店的会员复购问题"}
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
    "user": "boss_001",
    "thread_id": "thread_1234567890abcd",
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

## OpenClaw Webhook 验签

`POST /api/v1/webhooks/openclaw` 现在要求请求头 `X-OpenClaw-Signature`，格式：

```text
sha256=<HMAC_SHA256(request_body, OPENCLAW_WEBHOOK_SECRET)>
```

## 技术栈

- **Agent框架**: LangGraph + LangChain + Deep Agents
- **API**: FastAPI + WebSocket
- **LLM**: Claude Sonnet (主力) / Qwen-Plus (路由)
- **向量DB**: Milvus
- **存储**: PostgreSQL
- **Embedding**: BGE-large-zh-v1.5
- **Reranker**: BGE-reranker-v2-m3
