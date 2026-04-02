# Task Plan

## Workspace Commit Prep (2026-04-02)

- [x] 盘点当前工作区改动并确认提交主题。
- [x] 运行本次提交的最小验证命令。
- [x] 提交当前工作区改动。
- [x] 回填验证结果与提交信息。

## Workspace Commit Prep Notes

- 2026-04-02: 本次提交主题收敛为“认证、会话持久化、Deep Agents/skills 对齐、部署与运行时加固”，不是单点修补。
- 2026-04-02: 提交时明确排除本地状态文件与生成物：`.claude/settings.local.json`、`.superset/config.json`、`src/conversation_history/*`；其余源码、测试、文档、部署脚本纳入版本控制。
- 2026-04-02: `pytest tests -q` → `154 passed`
- 2026-04-02: `ruff check .` → 失败；当前工作区仍有 `34` 个问题，主要在 `src/tools/*`、`src/agent/router.py`、`tests/test_auth.py`，本次未顺手做大范围风格清理。
- 2026-04-02: `mypy src` → 失败；当前工作区仍有 `61` 个类型错误，主要集中在既有 `orchestrator`、`conversations`、`tools`、`openai_compat` 等模块，本次提交未额外扩展类型治理范围。
- 2026-04-02: 为恢复全量测试，已将 `tests/test_data_agent.py` 中过期的 `_get_full_subagent_prompt` 断言切到当前 Deep Agents `skills=["/skills/data-analysis"]` 契约与运行时 prompt 构造逻辑。

## Full Dev Docker Environment Bring-up (2026-04-02)

- [x] 检查开发环境变量文件与 Docker Compose 可用性。
- [x] 启动完整 Docker 开发环境（全部服务）。
- [x] 验证容器状态、关键日志与健康接口。

## Full Dev Docker Environment Bring-up Notes

- 2026-04-02: 使用 `docker compose -f docker-compose.dev.yml --env-file .env.dev up -d --build` 成功拉起完整开发环境，包含 `api`、`postgres`、`etcd`、`minio`、`milvus`。
- 2026-04-02: `docker compose ... ps` 显示所有服务均为 `Up`，其中 `postgres`、`minio`、`milvus` 已进入 `healthy` 状态，`api` 正常监听宿主机 `8000`。
- 2026-04-02: `docker compose ... logs --tail=120 api` 显示 FastAPI 启动完成，应用启动阶段数据库 checkpointer 初始化成功；存在一条 `psycopg_pool` 异步连接池构造器弃用警告，但未影响本次启动。
- 2026-04-02: `curl -fsS http://127.0.0.1:8000/api/v1/health` 返回 `{\"status\":\"ok\",\"version\":\"0.1.0\",\"components\":{\"database\":\"ok\",\"milvus\":\"ok\"}}`，说明 API、数据库和 Milvus 关键链路已可用。

## Upload Cache Permission Fix (2026-03-30)

- [x] 确认生产 `uploads` bind mount 与 API 容器 UID 10001 的权限错配根因。
- [x] 修复部署/文档，使生产 `uploads` 目录权限与容器运行用户一致。
- [x] 补启动期上传目录可写性校验与回归测试。
- [x] 运行针对性验证并记录结果。

## Upload Cache Permission Fix Notes

- 2026-03-30: 根因不是 OSS SDK 或业务链路，而是生产 `docker-compose.yml` 把宿主机 `${APP_DATA_ROOT}/uploads` bind mount 到 `/app/uploads` 后，覆盖了镜像构建期 `chown -R appuser:appuser /app` 的结果；API 进程实际仍以 `uid=10001` 运行，因此宿主机 `uploads/` 若归属部署用户且权限为 `755`，就会在首次创建 `oss_cache/` 时触发 `Permission denied`。
- 2026-03-30: 修复方式没有放宽 API 容器权限，也没有改成 root 运行；而是在 `scripts/deploy_remote.sh` 中保留现有数据目录准备流程后，额外对 `${APP_DATA_ROOT}/uploads` 单独执行 `chown -R 10001:10001` 与 `chmod -R u+rwX`，让 bind mount 后的目录权限与容器运行用户一致。
- 2026-03-30: 同时在 `src.main.ensure_upload_dir_ready()` 增加启动期校验，服务启动时就会显式创建 `UPLOAD_DIR/oss_cache` 并做一次写探针；如果宿主机挂载目录不可写，会在健康流量进来前直接失败并给出明确错误，而不是等到附件回读时才炸。
- 2026-03-30: README 已同步更新生产目录准备和手工验证命令，明确 `uploads/` 必须授予容器 `uid=10001` 写权限。
- 2026-03-30: 已验证：
  - `pytest tests/test_main.py tests/test_deploy_scripts.py -q` → `8 passed`
  - `ruff check src/main.py tests/test_main.py tests/test_deploy_scripts.py` → `All checks passed!`
  - `git diff --check -- src/main.py scripts/deploy_remote.sh README.md tests/test_main.py tests/test_deploy_scripts.py tasks/todo.md` → clean

## MinIO Drive Loss Guard (2026-03-30)

- [x] 复盘 `listPathRaw: 0 drives provided` 与当前部署/卷状态，确认是对象存储后端瞬时失效而非应用代码调用错误。
- [x] 在部署脚本中补 MinIO 存储元数据和近期错误日志校验，避免类似状态上线后只靠日志暴露。
- [x] 运行脚本回归测试与语法检查，记录验证结果。

## MinIO Drive Loss Guard Notes

- 2026-03-30: 用户提供的报错发生在 MinIO `ListObjectsV1(bucket=a-bucket)` 路径，调用方是 Milvus 使用的 aws-sdk-cpp；这不是应用 API 自己在列桶。
- 2026-03-30: 本地复盘显示当前 MinIO 卷内仍存在 `/minio_data/.minio.sys/format.json`、`.minio.sys/buckets/` 和 `a-bucket/`，同时 Milvus 在 `2026-03-30 06:30:02 UTC` 已再次成功完成 `finish list object`，说明故障更符合“底层驱动列表瞬时为空”而不是持续性桶配置错误。
- 2026-03-30: 结合同日已修复的 `deploy_prod.sh` 持久化目录排除缺失问题，这类日志最可疑的根因是 `$APP_DATA_ROOT/minio` 曾被误删、误挂载或短暂不可见，导致 MinIO 在某个时间窗内看到空驱动集合。
- 2026-03-30: 现在 `scripts/deploy_remote.sh` 在依赖服务启动后会额外校验 `/minio_data/.minio.sys/format.json` 与 buckets 元数据目录，并扫描最近 2 分钟 MinIO 日志中的 `listPathRaw: 0 drives provided`；命中则直接中止部署，避免带病上线。
- 2026-03-30: 已验证：
  - `pytest tests/test_deploy_scripts.py -q` → `6 passed`
  - `bash -n scripts/deploy_prod.sh scripts/deploy_remote.sh` → 通过
  - `ruff check tests/test_deploy_scripts.py` → `All checks passed!`
  - `git diff --check -- scripts/deploy_remote.sh tests/test_deploy_scripts.py tasks/todo.md tasks/lessons.md` → clean

## Production Deploy Data Loss Fix (2026-03-30)

- [x] 复现并确认生产部署报错根因，不接受只围绕 `psql` 表象修补。
- [x] 修复部署脚本，阻止 `rsync --delete` 误删远端生产数据目录。
- [x] 补回归测试覆盖“代码目录与 APP_DATA_ROOT 重合”的危险场景。
- [x] 运行针对性验证并记录结果。

## Production Deploy Data Loss Fix Notes

- 2026-03-30: 当前生产命令把 `--target-dir /data/private-domain-ai-brain` 传给 `scripts/deploy_prod.sh`，而 `docker-compose.yml` 里的 `APP_DATA_ROOT` 默认值也是 `/data/private-domain-ai-brain`。这意味着“代码目录”和“生产数据卷根目录”被配置成了同一路径。
- 2026-03-30: `scripts/deploy_prod.sh` 使用 `rsync --delete "$REPO_ROOT/" "$REMOTE:$TARGET_DIR/"` 同步代码，但排除列表只忽略了 `uploads/`，没有排除 `postgres/`、`etcd/`、`minio/`、`milvus/`、`backups/`。当远端同一路径下存在这些运行时目录而本地仓库不存在时，`rsync --delete` 会把它们删掉。
- 2026-03-30: 用户日志里 `psql: ... could not open file "global/pg_filenode.map"` 与 PostgreSQL 数据目录被删除/损坏一致；因此真实问题不是迁移命令连接方式，而是部署脚本允许危险目录布局并在同步阶段破坏了卷数据。
- 2026-03-30: 修复方式是在 `scripts/deploy_prod.sh` 的 `rsync` 排除列表中补齐 `postgres/`、`etcd/`、`minio/`、`milvus/`、`backups/`，让代码同步即使落在同一根目录也不会删除持久化卷目录。
- 2026-03-30: 同时新增回归测试，直接执行 `deploy_prod.sh` 并检查真实组装出来的 `rsync` 参数，锁住 `--target-dir /data/private-domain-ai-brain` 这类高风险场景。
- 2026-03-30: 已验证：
  - `pytest tests/test_deploy_scripts.py -q` → `6 passed`
  - `ruff check tests/test_deploy_scripts.py` → `All checks passed!`
  - `bash -n scripts/deploy_prod.sh scripts/deploy_remote.sh` → 通过
  - `git diff --check -- scripts/deploy_prod.sh tests/test_deploy_scripts.py tasks/todo.md tasks/lessons.md` → clean

## Production OSS Deploy Readiness (2026-03-30)

- [x] 在生产部署脚本中前置校验 OSS 运行时配置，避免缺配置时发布成功但功能不可用。
- [x] 更新 README 的生产发布说明，明确 OSS 配置和上线后验证步骤。
- [x] 补部署文档/脚本的最小回归测试，并完成验证。

## Production OSS Deploy Readiness Notes

- 2026-03-30: `scripts/deploy_remote.sh` 之前只校验数据库、认证和 OpenClaw 相关环境变量；在 OSS 已成为附件上传/回读事实源后，生产环境即使缺少 `OSS_ACCESS_KEY_ID/SECRET/BUCKET_NAME/ENDPOINT` 也可能完成发布，但附件功能会在上线后才失败。
- 2026-03-30: 现在远端部署前会显式校验上述 4 个 OSS 变量非空，缺失时直接中止发布，避免“发布成功但功能不可用”的假成功。
- 2026-03-30: README 的生产发布说明已同步补充 OSS 必填项和发布后最小验证命令，降低手工发布时遗漏远端 `.env` 配置的概率。
- 2026-03-30: 已验证：
  - `pytest tests/test_deploy_scripts.py -q` → `5 passed`
  - `ruff check tests/test_deploy_scripts.py` → `All checks passed!`
  - `bash -n scripts/deploy_prod.sh scripts/deploy_remote.sh && git diff --check` → 通过

## Data Analysis Recursion Fix (2026-03-30)

- [x] 复现并确认 data-analysis 递归爆掉的根因，不接受仅调高 recursion_limit 的表面修复。
- [x] 修复 `run_python_analysis` 的受控 import / 执行环境，并收紧数据分析提示词，避免模型反复生成无效代码。
- [x] 补回归测试并验证数据分析链路的关键行为。

## Data Analysis Recursion Fix Notes

- 2026-03-30: 根因不是 `recursion_limit=12` 太小，而是 `run_python_analysis` 的 AST 白名单允许 `import pandas as pd`，但执行环境里禁用了 `__import__`，导致模型每次生成常规分析代码都会得到 `ImportError: __import__ not found`，随后在工具循环里反复重试直到 LangGraph 递归上限触发。
- 2026-03-30: 修复方式是给沙箱增加受控 `__import__`，对白名单模块放行，并把 `pandas` 映射到带路径白名单的 `_safe_pd`，避免 `import pandas as pd` 绕过 `UPLOAD_DIR` 限制。
- 2026-03-30: 同时收紧了数据分析系统提示词，明确 `pd / np / plt` 已预置，不要重复 import，也不要在代码里硬编码 `/app/uploads/...` 路径，应通过 `run_python_analysis(file_path=...)` 让工具自动加载 `df`。
- 2026-03-30: 已验证：
  - `pytest tests/test_data_agent.py -q` → `12 passed`
  - `ruff check src/subagents/data_analysis.py tests/test_data_agent.py` → `All checks passed!`
  - `python - <<'PY' ... import pandas as pd; pd.read_csv(...) ... PY` → 返回 `2`
  - `git diff --check` → clean

## OSS-First Attachment Fetching (2026-03-30)

- [x] 将附件物化统一切到阿里云 OSS -> `UPLOAD_DIR/oss_cache`，不再默认走系统临时文件。
- [x] 收敛 `/api/v1/chat`、`/api/v1/chat/stream` 和 OpenAI 兼容层的附件错误语义，区分附件不存在与 OSS 存储不可用。
- [x] 补回归测试并验证 data-analysis / attachment-analysis 仍能消费新的附件路径。

## OSS-First Attachment Fetching Notes

- 2026-03-30: 之前 `/chat`、`/chat/stream` 解析 `file_id` 时会把 OSS 对象下载到系统临时目录，导致附件来源不稳定，也绕开了 `data_analysis.run_python_analysis()` 对 `UPLOAD_DIR` 的路径白名单。
- 2026-03-30: 现在统一通过 `src.memory.attachments.materialize_attachment_from_oss()` 把 OSS 对象物化到 `UPLOAD_DIR/oss_cache/<user_id>/<file_id>.<suffix>`；OpenAI 兼容层的图片附件也复用同一条路径。
- 2026-03-30: `resolve_attachment_refs_from_db()` 现在会把 `OSSStorageError` 映射为 `AttachmentStorageError`；`/api/v1/chat` 返回 `503`，`/api/v1/chat/stream` 返回 SSE `error` 事件，不再把存储故障伪装成附件不存在。
- 2026-03-30: 另外补了空附件短路，`attachments=[]` 时不再初始化数据库连接。
- 2026-03-30: 已验证：
  - `pytest tests/test_attachments.py tests/test_api.py tests/test_openai_compat.py -q` → `55 passed`
  - `ruff check src/memory/attachments.py src/storage/oss.py src/api/routes.py src/api/streaming.py src/api/openai_compat.py tests/test_attachments.py tests/test_api.py tests/test_openai_compat.py` → `All checks passed!`
  - `git diff --check` → clean

## Docker Build Cache Optimization (2026-03-30)

- [x] 调整 Dockerfile 分层，避免开发环境改业务代码时重装全部依赖。
- [x] 补 Dockerfile 回归测试，锁定“先装依赖，后拷源码”的构建顺序。
- [x] 运行针对性验证并记录结果。

## Docker Build Cache Optimization Notes

- 2026-03-30: 当前 `Dockerfile` 在 `pip install .` 前先 `COPY src/`，导致任何 Python 业务代码变更都会让依赖安装层失效，开发环境执行 `docker compose ... up --build api` 时经常重新下载整套依赖。
- 2026-03-30: 修复方式是仅先复制 `pyproject.toml`，在镜像构建时用 `tomllib` 导出运行时依赖到 `/tmp/requirements.txt`，完成 `torch + pip install -r /tmp/requirements.txt` 后再复制 `src/`。
- 2026-03-30: 这样改完后，只有依赖变更（`pyproject.toml`）才会触发重装；纯业务代码修改只会重建源码层。
- 2026-03-30: 已验证：
  - `pytest tests/test_docker_assets.py -q` → `1 passed`
  - `ruff check tests/test_docker_assets.py` → `All checks passed!`
  - `git diff --check` → clean
  - `docker build -q .` 已启动验证，但镜像依赖层较重，本轮未等待到最终完成结果

## OSS Upload Timeout Handling (2026-03-30)

- [x] 定位文件上传 500 的根因，区分配置错误与代码异常处理缺口。
- [x] 修复本地开发环境 OSS endpoint 拼写错误，并将 OSS 上传异常收敛成受控 503。
- [x] 补文件上传超时回归测试并完成验证。

## OSS Upload Timeout Handling Notes

- 2026-03-30: 真实根因有两层。第一层是 `.env.dev` 中 `OSS_ENDPOINT` 配成了 `https://oss-cn-wuhan-lr.allyuncs.com`，域名拼写错误，应为 `aliyuncs.com`。第二层是上传接口没有拦住 OSS SDK 异常，导致超时直接冒泡成未处理 500。
- 2026-03-30: 在 `src/storage/oss.py` 中新增 `OSSStorageError`，统一包装 `oss2` 缺失、上传失败和下载失败；`src/api/routes.py` 与 `src/api/openai_compat.py` 现在会把这类错误转成 `503 文件存储服务暂时不可用，请稍后重试`。
- 2026-03-30: 同步补齐 `.env.dev.example` 的 OSS 配置段，避免新的开发环境漏掉这组变量。
- 2026-03-30: 已验证：
  - `pytest tests/test_api.py::test_file_upload tests/test_api.py::test_file_upload_image tests/test_api.py::test_file_upload_returns_503_when_oss_times_out tests/test_webhooks.py -q` → `7 passed`
  - `ruff check src/storage/oss.py src/api/routes.py src/api/openai_compat.py tests/test_api.py tests/test_webhooks.py` → `All checks passed!`
  - `python - <<'PY' ... import src.main ... PY` → `True`

## OSS Import Startup Fix (2026-03-30)

- [x] 定位本地 Docker 启动时 `oss2` 缺失导致的服务导入崩溃。
- [x] 将 OSS 客户端改为懒加载，避免模块级强导入阻塞整个应用启动。
- [x] 补导入回归测试并完成针对性验证。

## OSS Import Startup Fix Notes

- 2026-03-30: 启动崩溃发生在 `src.api.openai_compat -> src.storage.oss` 的模块导入链路；`src/storage/oss.py` 在模块顶层直接 `import oss2`，导致镜像里缺包时整个 `src.main` 无法导入。
- 2026-03-30: 修复方式是把 `oss2` 改成 `src.storage.oss._get_oss2()` 懒加载；这样应用启动、健康检查和非 OSS 路径仍可正常工作，只有真正用到 OSS 上传/下载时才会报明确错误。
- 2026-03-30: 新增 `tests/test_webhooks.py::test_main_import_survives_when_oss2_missing`，锁定缺少 `oss2` 时主应用仍可导入。
- 2026-03-30: 已验证：
  - `pytest tests/test_webhooks.py -q` → `4 passed`
  - `ruff check src/storage/oss.py tests/test_webhooks.py` → `All checks passed!`
  - `python - <<'PY' ... import src.main ... PY` → `True`
  - `git diff --check` → clean

## Production Deploy Scripts (2026-03-27)

- [x] 将生产部署方案落成脚本，覆盖本地 rsync 发布和远端 Docker Compose 初始化/升级。
- [x] 为迁移执行、健康检查、可选备份和初始 API 凭证引导补最小回归测试。
- [x] 更新 README 的生产部署说明，并完成语法检查与针对性验证。

## Production Deploy Scripts Notes

- 2026-03-27: 新增 `scripts/deploy_prod.sh` 作为本地发布入口，固定采用 `rsync + ssh` 同步当前工作区到远端，再调用 `scripts/deploy_remote.sh` 执行实际部署；默认不上传 `.env`、`uploads/`、`tests/`、`tasks/` 等非生产目录。
- 2026-03-27: `scripts/deploy_remote.sh` 会先校验生产 `.env`、创建 `${APP_DATA_ROOT}` 下的持久化目录、启动依赖服务、执行可选 PostgreSQL 备份、再处理迁移和 API 启动。
- 2026-03-27: 迁移没有引入 Alembic，而是在 PostgreSQL 里补了 `schema_migrations` 账本表；脚本会按 migration 文件逐个检查对应对象是否已存在，已存在就只回填记录，不重放旧 SQL，避免 `CREATE TRIGGER` 这类非幂等 migration 在新库上重复执行。
- 2026-03-27: 生产认证默认开启，因此脚本在 `AUTH_ENABLED=true` 且 `api_credentials` 为空时，会在 `api` 容器内生成并写入一条初始凭证，并把 `app_id/secret_key` 只打印一次。
- 2026-03-27: 用户在 macOS 自带 Bash 3.2 下真实执行时，`set -u` 配合空数组展开会把 `for arg in "${REMOTE_DEPLOY_ARGS[@]}"` 打成 `unbound variable`；修复为先判断数组长度，再进入循环，并补了可执行回归测试。
- 2026-03-27: 已验证：
  - `pytest tests/test_deploy_scripts.py tests/test_db_scripts.py tests/test_api_credential_script.py -q` → `10 passed`
  - `ruff check tests/test_deploy_scripts.py tests/test_db_scripts.py tests/test_api_credential_script.py` → `All checks passed!`
  - `bash -n scripts/deploy_prod.sh scripts/deploy_remote.sh` → 通过
  - `git diff --check` → clean

## Production Postgres Host Port (2026-03-28)

- [x] 将生产 PostgreSQL 的宿主机暴露端口切到 `5431`，保持容器内连接端口仍为 `5432`。
- [x] 同步更新 `.env.example`、README 和最小回归测试。

## /chat/stream Deep Agents Review (2026-03-25)

- [x] 检查 `/api/v1/chat/stream`、`DeepPlanRunner`、客服链路与会话持久化的实际调用顺序。
- [x] 对照 Deep Agents 官方能力与当前测试，找出结构性问题、风险边界和测试失真点。
- [x] 输出按严重度排序的 review 结论，并记录关键证据位置。

## Conversation Metadata Transaction Fix (2026-03-24)

- [x] 复现并确认 `conversation_messages` 已落库但 `conversation_metadata` 被回滚的根因。
- [x] 先补回归测试，锁定 `RETURNING` 写路径必须走提交事务。
- [x] 修复 `conversations` 与 `customer_service` 中所有同类写路径。
- [x] 运行针对性测试、静态检查和全量测试，记录结果与剩余风险。

## Async DB CancelledError Fix (2026-03-24)

- [x] 确认 `CancelledError` 日志的根因与受影响代码路径。
- [x] 先补回归测试，锁定 SQLAlchemy 异步驱动使用 `psycopg`。
- [x] 将共享 SQLAlchemy AsyncEngine 从 `asyncpg` 对齐到 `psycopg`。
- [x] 运行针对性测试与静态检查，记录验证结果。
- [x] 更新评论与经验，沉淀这次修复结论。

## Dev API-Only Build

- [x] 确认开发编排中实际会 build 的服务范围。
- [x] 将开发环境启动说明改为只构建 `api`，依赖服务直接启动。
- [x] 验证 compose 配置与启动命令符合预期。

## Comments

- 2026-03-25: `/api/v1/chat/stream` 的 customer 分支在入口处先调用 `ConversationStore.save_user_message()/save_assistant_message()`，而 `CustomerServiceSupervisor.invoke()` 内部又通过 `CustomerServiceStore.append_message()` 回写统一会话存储，导致客户消息与客服回复在统一会话表中重复记账；转人工场景还会把同一条提示同时记成 `system` 和 `assistant`。
- 2026-03-25: `DeepPlanRunner` 直接把 `FilesystemBackend(root_dir=PROJECT_ROOT / "src", virtual_mode=True)` 暴露给线上 `/chat/stream` 的 plan 模式。根据官方文档，`FilesystemBackend` 提供宿主文件系统读写能力；当前根目录指向应用源码，意味着终端用户请求可间接读取甚至修改 `src/` 下的代码和 prompt 资产。
- 2026-03-25: `chat_stream()` 在进入生成器前就无条件初始化 `orchestrator`、`mode_selector`、`customer_service_supervisor`，使 customer-only / plan-only 请求也要承担不相关的 LLM、checkpointer 和客服链路初始化成本，且会放大单点初始化失败面。
- 2026-03-25: `DeepPlanRunner` 用枚举序号重新生成 `task_1/task_2/...`，并按当前位置推断当前任务；一旦 `write_todos` 重排或改写 todo 列表，前端收到的 task/tool 归属就会漂移，进度 UI 会把工具调用挂到错误任务上。
- 2026-03-25: `tests/test_api.py` 的 plan 流 mock 仍断言不存在于真实实现中的 `tool_name="analyze_uploaded_data"`，没有覆盖 `task`/`analyze_uploaded_attachments` 等真实 Deep Agents 事件，说明当前 SSE 测试对 plan 流事件结构存在失真。

- 2026-03-24: 用户现场现象是 `/chat/stream` 已写入 `conversation_messages`，但 `conversation_metadata` 无新行；根因不是 SSE 本身，而是 `ConversationStore._fetchrow()` / `CustomerServiceStore._fetchrow()` 用 `engine.connect()` 执行了 `INSERT/UPDATE ... RETURNING`，连接关闭时事务被回滚。
- 2026-03-24: 先按 TDD 在 `tests/test_conversation_store.py` 和 `tests/test_customer_service.py` 增加 fake async engine 回归测试，RED 阶段确认 metadata upsert 和客服消息 returning insert 错误走了 `connect()`。
- 2026-03-24: 生产修复是在两个 store 中新增 `_write_fetchrow()`，统一用 `engine.begin()` 包裹所有 `RETURNING` 写语句；纯读查询仍保留 `_fetchrow()` + `engine.connect()`。
- 2026-03-24: 本轮验证结果：
  - `pytest tests/test_conversation_store.py::test_record_messages_commits_metadata_upsert_with_transaction tests/test_customer_service.py::test_customer_service_store_append_message_commits_returning_insert -q` → RED: `2 failed`
  - 同命令修复后 → GREEN: `2 passed`
  - `pytest tests/test_conversation_store.py tests/test_customer_service.py tests/test_api.py -q` → `38 passed`
  - `ruff check src/memory/conversations.py src/memory/customer_service.py tests/test_conversation_store.py tests/test_customer_service.py` → `All checks passed!`
  - `pytest tests -q` → `124 passed, 1 failed`
  - `git diff --check` → clean
- 2026-03-24: 全量唯一失败是 `tests/test_webhooks.py::test_openclaw_webhook_accepts_valid_signature`，表现为顺序/环境相关的 `socksio` 缺失导致 mock 未命中；该用例单跑可过，与本次事务修复无直接代码关联。
- 2026-03-24: 用户随后纠正了真实需求边界：不仅 `thread_id=""`，纯空白字符串也应视为新会话。主 API 之前对 `""` 已能生成新 `thread_*`，但 `"   "` 会被当成真实 thread_id 继续透传。
- 2026-03-24: 针对该纠正，在 `ChatRequest` 增加 `thread_id` 归一化 validator，把空字符串和纯空白统一转成 `None`；并新增 `/api/v1/chat`、`/api/v1/chat/stream` 的空白 thread_id 回归测试。
- 2026-03-24: 本轮验证结果：
  - `pytest tests/test_api.py::test_chat_blank_thread_id_generates_new_thread_and_persists_metadata tests/test_api.py::test_chat_stream_blank_thread_id_generates_new_thread_and_persists_metadata -q` → RED: `2 failed`
  - 同命令修复后 → GREEN: `4 passed`
  - `pytest tests/test_api.py -q` → `31 passed`
  - `ruff check src/api/schemas.py tests/test_api.py` → `All checks passed!`
  - `python - <<'PY' ... ChatRequest(thread_id='').thread_id / ChatRequest(thread_id='   ').thread_id ... PY` → `None / None / thread_123`

- 2026-03-24: 用户提供的栈来自 `sqlalchemy.dialects.postgresql.asyncpg` 的连接终止路径，触发条件是请求 cancel scope 下的连接回收；同仓 `src/memory/checkpointer.py` 已使用 `psycopg`，当前 SQLAlchemy 层单独使用 `asyncpg` 形成了不必要的双驱动分裂。
- 2026-03-24: 先按 TDD 将 `tests/test_db.py` 改为期望 `postgresql+psycopg://...`，RED 阶段得到预期失败；随后把 `src/config.py` 的 `database_url_async` 改为 `psycopg` 并移除 `pyproject.toml` 中未再使用的 `asyncpg` 依赖。
- 2026-03-24: 针对性验证通过：
  - `pytest tests/test_db.py -q` → RED: `1 failed`
  - `pytest tests/test_db.py -q` → GREEN: `1 passed`
  - `pytest tests/test_db.py tests/test_profile_store.py tests/test_conversation_store.py tests/test_auth.py -q` → `21 passed`
  - `ruff check src/config.py src/memory/db.py tests/test_db.py` → `All checks passed!`

- 2026-03-24: `docker-compose.dev.yml` 当前只有 `api` 服务声明了 `build`，其余依赖都使用现成镜像；本次只需要收紧文档和推荐命令，避免误解为“开发环境全量编译”。
- 2026-03-24: `docker compose -f docker-compose.dev.yml --env-file .env.dev config` 验证通过；渲染结果中仅 `api` 含 `build`，`postgres`/`etcd`/`minio`/`milvus` 均为镜像服务。

## Code Quality Fixes (2026-03-22)

- [x] Step 1: Webhook security - defusedxml XXE protection, POST signature verification, shared httpx client + WeChat token TTL cache
- [x] Step 2: Sandbox + SSRF - AST-based code validator, upload_dir path restriction, SSRF host check, 10MB/20MB size limits
- [x] Step 3: Data layer bugs - SQL param index bug in is_customer_thread(), checkpointer init try/except + reset, close cleanup
- [x] Step 4: Concurrency safety - asyncio.Lock double-check on all 5 singletons, fire-and-forget task ref fix in orchestrator
- [x] Step 5: Input validation - 500 error detail sanitization in routes/streaming, file_id path traversal guard
- [x] Step 6: Code cleanup - remove dead AgentExecutor/create_tool_calling_agent/\_FallbackAgent code from 3 subagents

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

## API Credential Utility

- [x] Add a small utility script to generate `app_id`, `secret_key`, and `secret_hash` for `api_credentials`.
- [x] Add a regression test that locks the script's deterministic hash and SQL output when explicit values are provided.
- [x] Verify the script output and targeted tests.

## API Credential Utility Notes

- 2026-03-24: Goal is a minimal operator utility only; keep auth runtime unchanged and generate ready-to-run UPSERT SQL instead of adding a second credential management path.
- 2026-03-24: Added `scripts/create_api_credential.py` with fixed-or-random `app_id` / `secret_key` inputs, SHA-256 hashing, and `--sql-only` output for direct `psql` piping.
- 2026-03-24: Added `tests/test_api_credential_script.py` to lock deterministic hash output and SQL-only behavior.
- 2026-03-24: Verified:
  - `python -m pytest tests/test_api_credential_script.py -q` → `2 passed in 0.53s`
  - `python -m ruff check scripts/create_api_credential.py tests/test_api_credential_script.py` → `All checks passed!`
  - `python scripts/create_api_credential.py --app-name '默认应用' --app-id app_e918d505953f8d0a552beead85bb9ee4 --secret-key sk_demo_123456`
  - `python scripts/create_api_credential.py --app-name '默认应用' --app-id app_fixed --secret-key sk_fixed --sql-only`

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

## Customer Service Agent And Human Handoff

- [x] Add failing tests for customer-role routing, strict KB-only answering, automatic human handoff, and handoff APIs.
- [x] Implement customer-service message storage, human handoff persistence, and SQL init/migration scripts.
- [x] Implement `CustomerServiceSupervisor` and a strict KB-only customer service agent with conservative handoff rules.
- [x] Wire customer-service routing into sync chat, streaming chat, webhook flows, conversation history, and human handoff APIs.
- [x] Update docs, task notes, and verification evidence for the customer-service capability.

## Customer Service Agent And Human Handoff Notes

## Unified Conversation Pagination

- [x] Step 1: Add RED tests for unified `conversation_messages` schema, cursor-based conversation list/detail APIs, and old-session exclusion.
- [x] Step 2: Add PostgreSQL init/migration SQL plus conversation store schema changes for `conversation_messages` and `message_source`.
- [x] Step 3: Implement unified conversation message persistence and cursor pagination in the conversation store.
- [x] Step 4: Route chat, plan, `/v1`, webhook, and human handoff write paths into `conversation_messages`.
- [x] Step 5: Refactor conversation list/detail APIs to read only the unified message model and return opaque paging cursors.
- [x] Step 6: Run targeted tests, full regression, and record verification evidence.

## Unified Conversation Pagination Notes

- 2026-03-23: 本次改造按新会话模型直接切换，不兼容旧 checkpoint 会话和旧客服消息会话；列表隐藏旧会话，详情对旧会话返回 404。
- 2026-03-23: 会话详情前端不再区分普通会话和客服会话，统一读取 `conversation_messages`，统一支持 `before/after` 游标。
- 2026-03-23: `conversation_metadata` 新增 `message_source`，只有 `unified` 会话会进入列表；明细统一写入 `conversation_messages`。
- 2026-03-23: 已验证：
  - `python -m pytest tests/test_db_scripts.py tests/test_conversation_store.py tests/test_api.py -q` → `36 passed in 1.83s`
  - `python -m pytest tests/test_openai_compat.py tests/test_api.py tests/test_customer_service.py tests/test_webhooks.py -q` → `47 passed in 2.14s`
  - `python -m pytest tests -q` → `104 passed in 3.73s`
  - `python -m ruff check src/memory/conversations.py src/api/routes.py src/api/schemas.py tests/test_db_scripts.py tests/test_conversation_store.py tests/test_api.py` → `All checks passed!`
  - `python -m ruff check src/api/openai_compat.py src/api/streaming.py src/api/webhooks.py src/memory/customer_service.py` → `All checks passed!`
- 2026-03-23: `python -m ruff check src tests` 在当前基线下仍有仓库既有问题，集中在 `src/agent/router.py`、`src/tools/*` 和 `tests/test_attachment_agent.py`，与本次改造无关。

## SQLAlchemy Refactor

- [x] Step 1: Add RED tests for async SQLAlchemy URL, shared engine access, and store internals no longer passing raw SQL strings.
- [x] Step 2: Add a shared SQLAlchemy Async Core database module and async engine lifecycle management.
- [x] Step 3: Refactor `conversations` / `customer_service` / `user_profile` stores from `asyncpg` to SQLAlchemy Core while preserving behavior.
- [x] Step 4: Keep existing API behavior unchanged and verify the conversation/customer-service write paths still pass.
- [x] Step 5: Run focused lint/tests and full regression; record evidence.

## SQLAlchemy Refactor Notes

- 2026-03-23: 本次 SQLAlchemy 改造覆盖所有自写 PostgreSQL 存储层：`src/memory/conversations.py`、`src/memory/customer_service.py`、`src/memory/store.py`；LangGraph checkpointer 继续使用原有同步连接链路。
- 2026-03-23: 新增 `src/memory/db.py` 作为共享 SQLAlchemy Async Core 封装，统一维护 table metadata、async engine、runtime schema ensure 与 shutdown dispose。
- 2026-03-23: `src/config.py` 增加 `database_url_async`，使用 `postgresql+asyncpg://...`；`src/main.py` 在应用关闭时统一 dispose 共享 async engine。
- 2026-03-23: 已验证：
  - `python -m pytest tests/test_db.py tests/test_profile_store.py tests/test_conversation_store.py -q` → `9 passed in 0.60s`
  - `python -m pytest tests/test_api.py tests/test_openai_compat.py tests/test_customer_service.py tests/test_webhooks.py -q` → `47 passed in 4.38s`
  - `python -m pytest tests -q` → `106 passed in 4.60s`
  - `python -m ruff check src/config.py src/main.py src/memory/db.py src/memory/store.py src/memory/conversations.py src/memory/customer_service.py src/api/openai_compat.py src/api/routes.py src/api/streaming.py src/api/webhooks.py tests/test_db.py tests/test_profile_store.py tests/test_conversation_store.py tests/test_api.py tests/test_openai_compat.py tests/test_customer_service.py tests/test_webhooks.py` → `All checks passed!`

- 2026-03-20: Approved scope is `user_role=customer` for first-party chat APIs, webhook traffic defaults to customer-service routing, and OpenAI-compatible `/v1` stays internal-only for v1.
- 2026-03-20: Customer-service answers must be strictly grounded in knowledge-base results filtered by `doc_type=customer_service`; empty or low-confidence retrieval must trigger human handoff instead of free-form generation.
- 2026-03-20: Human handoff is a full lifecycle feature in v1: create pending queue entries, support claim/reply/resolve APIs, persist customer/ai/human/system messages, and suppress further AI replies while a handoff is active.
- 2026-03-20: Added RED tests in `tests/test_customer_service.py`, `tests/test_api.py`, and `tests/test_db_scripts.py`; initial `python -m pytest tests/test_customer_service.py tests/test_api.py -q` failed with 10 expected failures because `customer` role routing, `CustomerServiceSupervisor`, customer history handling, handoff APIs, and migration SQL did not exist yet.
- 2026-03-20: Added `src/agent/customer_service.py` with `CustomerServiceSupervisor` and a strict KB-only `CustomerServiceKBAgent`; unresolved or explicit human-request messages now create/refresh handoff records and return the standard transfer message.
- 2026-03-20: Added `src/memory/customer_service.py`, updated `conversation_metadata` to carry `user_role`, and created `customer_service_messages` / `human_handoffs` in both `scripts/init_db.sql` and `scripts/migrations/2026-03-20-add-customer-service-support.sql`.
- 2026-03-20: Wired `user_role=customer` into sync chat, WebSocket streaming, conversation history, handoff management APIs, and webhook flows; customer streams now emit only `token/done/error`, while WeCom and default OpenClaw traffic use the customer-service chain.
- 2026-03-20: Final self-review caught an OpenClaw channel persistence bug; webhook routing now keeps the actual inbound `channel` value when invoking agents, recording conversation metadata, and replying to the upstream API.
- 2026-03-20: User reported that the frontend still calls `POST /v1/chat/completions`, and sending `转人工` did not enter the customer-service handoff flow. Root cause was that OpenAI compatibility only routed between `orchestrator / plan_runner` and had no customer-service split.
- 2026-03-20: Added RED coverage in `tests/test_openai_compat.py` for both sync and streaming `/v1/chat/completions` transfer requests. Initial `python -m pytest tests/test_openai_compat.py -q` failed with 2 expected failures because compatibility responses still came from the normal chat route.
- 2026-03-20: Updated `src/api/openai_compat.py` to support `metadata.user_role` / `metadata.thread_id`, derive a stable compatibility `thread_id`, and route explicit handoff requests plus existing customer-service threads into `CustomerServiceSupervisor`.
- 2026-03-20: Verified:
  - `python -m pytest tests/test_customer_service.py tests/test_api.py tests/test_db_scripts.py -q` → `30 passed in 2.07s`
  - `python -m ruff check src/agent/customer_service.py src/api/routes.py src/api/schemas.py src/api/streaming.py src/api/webhooks.py src/memory/conversations.py src/memory/customer_service.py tests/test_api.py tests/test_customer_service.py tests/test_db_scripts.py` → `All checks passed!`
  - `python -m pytest tests -q` → `78 passed in 2.76s`

## Deep Agents Standard-First Policy

- [x] Record the repository-level rule that new agent capabilities must check Deep Agents official standards first.
- [x] Update long-lived project guidance so future implementations default to official Deep Agents mechanisms over custom systems.
- [x] Capture the policy as an engineering lesson to prevent future parallel ad-hoc abstractions.
- [x] Verify the documentation changes are clean and consistent.

## Deep Agents Standard-First Policy Notes

- 2026-03-20: Confirmed current repository behavior is mixed: Deep Agents is used for `plan_runner`, but the repository does not use the official `skills=[...]` integration path for most skill-like assets.
- 2026-03-20: Added a repository rule to `AGENTS.md` requiring future work on skills, planning, orchestration, memory, handoff, or multi-agent behavior to check Deep Agents official capabilities first and prefer the standard mechanism by default.
- 2026-03-20: Added a matching lesson to `tasks/lessons.md` so future changes do not drift back toward custom parallel systems without an explicit documented gap analysis.

## Deep Agents Skill Integration

- [x] Add RED tests that require `DeepPlanRunner` to wire official Deep Agents `skills=[...]`.
- [x] Standardize all `src/skills/*/SKILL.md` files to valid Agent Skills frontmatter.
- [x] Scope the Deep Agents filesystem backend safely so plan mode only exposes the intended project skill source.
- [x] Preserve existing `data-analysis` store-diagnosis behavior and verify no chat-path regressions.
- [x] Run targeted and full regression checks, then record the Deep Agents alignment notes.

## Deep Agents Skill Integration Notes

- 2026-03-20: Confirmed the local installed `deepagents==0.4.11` already supports the official `skills=[...]` parameter on `create_deep_agent(...)`, so this task should use the standard middleware path instead of adding a parallel custom skill registry.

## OpenAI Compatibility Session Linking

- [x] Add failing regression tests for `/v1/chat/completions` session IDs, stream thread propagation, top-level field precedence, and `store_id` passthrough.
- [x] Make `/v1/chat/completions` return and reuse canonical `thread_id` for sync and streaming chat/plan flows.
- [x] Stop replaying old assistant/user history when a request already carries `thread_id`; only use current-turn system + latest user content.
- [x] Persist successful `/v1` chat/plan turns into `conversation_metadata` so old sessions can be reopened through existing conversation APIs.
- [x] Add optional `store_id` to first-party and OpenAI-compatible chat entrypoints as a passthrough-only field.
- [x] Update README examples and record verification evidence.

## OpenAI Compatibility Session Linking Notes

- 2026-03-23: Frontend integration needs `/v1/chat/completions` to behave like a server-managed session API instead of a stateless prompt adapter, while still keeping the OpenAI-compatible envelope for clients that ignore extra top-level fields.
- 2026-03-23: Added RED coverage in `tests/test_openai_compat.py`; initial `python -m pytest tests/test_openai_compat.py -q` failed with 5 expected failures because responses lacked `thread_id`, normal `/v1` chat did not record conversation metadata, stream chunks did not expose session IDs, plan stream generated ad-hoc `oa_*` thread IDs, and top-level `store_id` was ignored.
- 2026-03-23: Updated `src/api/openai_compat.py` to accept top-level `thread_id` / `user_role` / `store_id` with `metadata.*` fallback, generate canonical `thread_*` IDs for new sessions, return `thread_id` in sync and streaming responses, reuse the same thread across plan streams, and persist successful `/v1` chat/plan turns into `conversation_metadata`.
- 2026-03-23: Adjusted current-turn prompt extraction so requests carrying `thread_id` no longer re-inject old assistant/user history into the new turn; only system messages plus the latest user message are translated for the active turn, leaving long-term context to the existing checkpointer.
- 2026-03-23: Added passthrough `store_id` fields to `ChatRequest`, WebSocket chat input handling, and the orchestrator / plan runner / customer-service entry signatures without enabling any new MCP or external data behavior yet.
- 2026-03-23: Verified:
  - `python -m pytest tests/test_openai_compat.py -q` → `17 passed in 1.73s`
- 2026-03-20: Added RED tests in `tests/test_plan_runner.py` and `tests/test_skill_metadata.py`; initial runs failed because `DeepPlanRunner` did not pass `skills`, and three `SKILL.md` files lacked YAML frontmatter while `data-analysis` used a non-compliant `name`.
- 2026-03-20: Updated `src/agent/plan_runner.py` to pass `skills=["/skills"]` and a `FilesystemBackend(root_dir=<repo>/src, virtual_mode=True)`, which keeps Deep Agents file operations scoped to `src/` and avoids the default non-virtual path behavior.
- 2026-03-20: Standardized all four skill docs under `src/skills/*/SKILL.md` to valid Agent Skills frontmatter with `name == directory name` and non-empty `description`.
- 2026-03-20: Preserved the existing `src/subagents/data_analysis.py` diagnosis-specific prompt injection for chat/data-analysis flows; the Deep Agents skill integration added here applies to `plan_runner` only.
- 2026-03-20: Verified:
  - `python -m pytest tests/test_plan_runner.py tests/test_skill_metadata.py -q` → `2 passed in 0.74s`
  - `python -m ruff check src/agent/plan_runner.py tests/test_plan_runner.py tests/test_skill_metadata.py` → `All checks passed!`
  - `git diff --check` → clean
  - `python -m pytest tests -q` → `82 passed in 3.86s`

## Subagent Skill Alignment

- [x] Write the implementation plan for aligning non-plan subagents to the shared skill assets.
- [x] Add RED tests that require knowledge-base and content-generation prompts to load skill documents from `src/skills`.
- [x] Introduce a shared runtime skill loader so subagents use the same skill asset source as plan mode.
- [x] Refactor knowledge-base and content-generation agents to build prompts from their skill docs plus shared private-domain-ops context.
- [x] Preserve existing data-analysis diagnosis behavior and verify targeted plus full regressions.

## Subagent Skill Alignment Notes

- 2026-03-20: Deep Agents 官方 `skills=[...]` 已用于 `plan_runner`，但 `knowledge-base` 与 `content-generation` 仍使用硬编码 prompt；第二阶段的目标是让这些非 deepagents 子智能体至少复用同一份 `src/skills` 资产，而不是继续分叉维护。
- 2026-03-20: Added RED tests in `tests/test_content_agent.py` and `tests/test_kb_agent.py`; initial run failed because `build_content_generation_system_prompt()` and `build_kb_system_prompt()` did not exist.
- 2026-03-20: Added `src/skills/runtime.py` as a minimal cached loader for local skill assets. It intentionally does not implement a registry or routing layer; it only provides a shared bundle builder for runtime prompt composition.
- 2026-03-20: Refactored `src/subagents/content_generation.py` to build its system prompt from `private-domain-ops` + `content-generation`, and `src/subagents/knowledge_base.py` to build from `private-domain-ops` + `knowledge-base`.
- 2026-03-20: Updated `src/subagents/data_analysis.py` to reuse the same loader for the store-diagnosis bundle, while preserving the existing diagnosis trigger and output contract.
- 2026-03-20: Verified:
  - `python -m pytest tests/test_content_agent.py tests/test_kb_agent.py -q` → `10 passed in 0.61s`
  - `python -m ruff check src/skills/runtime.py src/subagents/content_generation.py src/subagents/knowledge_base.py src/subagents/data_analysis.py tests/test_content_agent.py tests/test_kb_agent.py` → `All checks passed!`
  - `python -m pytest tests -q` → `84 passed in 2.95s`

## Webhook XML Import Robustness

- [x] Add a RED test that reproduces missing `defusedxml` without crashing `src.api.webhooks` import.
- [x] Refactor webhook XML parsing to lazily load `defusedxml` and fall back to stdlib `xml.etree.ElementTree` when the package is absent.
- [x] Verify targeted and full regressions, and record the environment lesson for container rebuilds.

## Webhook XML Import Robustness Notes

- 2026-03-22: Production traceback showed `ModuleNotFoundError: No module named 'defusedxml'` during `src.api.webhooks` import, which prevented `uvicorn` from loading the app at startup.
- 2026-03-22: Root-cause investigation showed the repository already declares `defusedxml>=0.7.1` in `pyproject.toml`, so the immediate crash was caused by a runtime environment mismatch or stale Docker image, amplified by a module-level hard import in `src/api/webhooks.py`.
- 2026-03-22: Added RED coverage in `tests/test_webhooks.py`; initial `python -m pytest tests/test_webhooks.py -q` failed because `src.api.webhooks` had no lazy XML parser helper and would still hard-fail when `defusedxml` was missing.
- 2026-03-22: Updated `src/api/webhooks.py` to lazily resolve the XML parser via `_get_xml_parser()`, preferring `defusedxml.ElementTree` and falling back to `xml.etree.ElementTree` with a warning instead of crashing at import time.
- 2026-03-22: Verified:
  - `python -m pytest tests/test_webhooks.py -q` → `1 passed in 0.40s`
  - `python -m ruff check src/api/webhooks.py tests/test_webhooks.py` → `All checks passed!`
  - `python -m pytest tests -q` → `85 passed in 6.35s`

## Production Docker Hardening

- [x] Step 1: Add RED tests for OpenClaw webhook signature verification and health-check error redaction.
- [x] Step 2: Harden runtime behavior: require OpenClaw webhook signature, redact health-check internals, and add Milvus health probing.
- [x] Step 3: Convert production Docker assets to production-oriented defaults: remove source bind mount, add `.dockerignore`, run non-root image, and switch stateful services to explicit host bind mounts.
- [ ] Step 4: Run targeted verification (`pytest`, `ruff`, `docker compose config`) and record the final evidence.

## Production Docker Hardening Notes

- 2026-03-24: Scope is single-host Docker Compose production hardening, not Kubernetes; default host data root is `/data/private-domain-ai-brain`.
- 2026-03-24: Stateful service storage is switching from Docker named volumes to explicit bind mounts for `uploads/postgres/etcd/minio/milvus`, so backup and host migration are operationally visible.
- 2026-03-24: `POSTGRES_PASSWORD`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, and `OPENCLAW_WEBHOOK_SECRET` are now treated as required deployment secrets instead of hidden weak defaults.
- 2026-03-24: `POST /api/v1/webhooks/openclaw` now requires `X-OpenClaw-Signature: sha256=<hmac>` using `OPENCLAW_WEBHOOK_SECRET`.
- 2026-03-24: 已验证：
  - `python -m pytest tests/test_webhooks.py tests/test_api.py tests/test_auth.py tests/test_config.py -q` → `43 passed in 1.71s`
  - `python -m ruff check src/api/routes.py src/api/webhooks.py src/config.py tests/test_webhooks.py tests/test_api.py` → `All checks passed!`
  - `APP_DATA_ROOT=/tmp/private-domain-ai-brain POSTGRES_PASSWORD=test-postgres-password MINIO_ACCESS_KEY=test-minio-access MINIO_SECRET_KEY=test-minio-secret docker compose config` → 渲染成功，`api` 无源码挂载，状态数据目录已变为显式 bind mount
  - `git diff --check` → clean
- 2026-03-24: `docker build -t private-domain-ai-brain-api:prod-verify .` 在首次验证时暴露出 `torch` 被解析为 CUDA 大包的问题，因此补充了 `Dockerfile` 的 CPU-only torch 预装步骤；修正后 build 已切到 `torch-2.11.0+cpu`，但完整镜像构建仍需较长依赖安装时间，本轮未拿到最终成功结果，已手动停止后台构建进程以避免继续占用资源。

## Dev And Prod Startup Docs

- [x] Step 1: Add a dedicated development Docker Compose file with hot reload and local service ports.
- [x] Step 2: Add a development environment template alongside the existing production template.
- [x] Step 3: Verify both compose variants render correctly and update the startup documentation.

## Dev And Prod Startup Docs Notes

- 2026-03-24: 新增 `docker-compose.dev.yml`，开发态保留 `./src:/app/src` 热更新、项目目录 `./uploads`、以及 `5432/19530/9091/9000/9001` 本地端口暴露。
- 2026-03-24: 新增 `.env.dev.example` 作为开发环境模板；生产环境继续使用 `.env.example`。
- 2026-03-24: 已验证：
  - `docker compose -f docker-compose.dev.yml --env-file .env.dev config` → 渲染成功，开发态端口与挂载符合预期
  - `docker compose --env-file .env.example config` → 渲染成功，生产态仍保持 bind mount 与收敛端口
  - `git diff --check` → clean
