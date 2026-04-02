#!/usr/bin/env bash
set -euo pipefail

log() {
    printf '[deploy_remote] %s\n' "$*"
}

die() {
    printf '[deploy_remote] ERROR: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
用法:
  bash scripts/deploy_remote.sh [--backup] [--dry-run]

选项:
  --backup     部署前导出 PostgreSQL 备份到 APP_DATA_ROOT/backups
  --dry-run    仅打印关键动作，不执行写操作
  -h, --help   显示帮助
EOF
}

require_cmd() {
    local cmd="$1"
    command -v "$cmd" >/dev/null 2>&1 || die "缺少命令: $cmd"
}

run_cmd() {
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '[dry-run] '
        printf '%q ' "$@"
        printf '\n'
        return 0
    fi
    "$@"
}

run_fs_cmd() {
    local prefix=()
    if [[ -n "$SUDO_BIN" ]]; then
        prefix+=("$SUDO_BIN")
    fi
    run_cmd "${prefix[@]}" "$@"
}

read_env_raw() {
    local key="$1"
    local line
    line="$(grep -E "^${key}=" .env | tail -n 1 || true)"
    [[ -n "$line" ]] || return 1
    printf '%s' "${line#*=}"
}

normalize_env_value() {
    local value="${1%$'\r'}"
    if [[ "$value" == \"*\" && "$value" == *\" ]]; then
        value="${value:1:-1}"
    elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
        value="${value:1:-1}"
    fi
    printf '%s' "$value"
}

read_env_value() {
    local key="$1"
    local raw
    raw="$(read_env_raw "$key" || true)"
    normalize_env_value "$raw"
}

is_placeholder_value() {
    local key="$1"
    local value="$2"
    case "$key" in
        POSTGRES_PASSWORD|MINIO_ACCESS_KEY|MINIO_SECRET_KEY|SECRET_KEY|OPENCLAW_WEBHOOK_SECRET)
            [[ "$value" == change-this-* ]]
            ;;
        OPENAI_API_KEY)
            [[ "$value" == "sk-xxx" ]]
            ;;
        API_CORS_ORIGINS)
            [[ "$value" == *"your-frontend.example.com"* ]]
            ;;
        *)
            return 1
            ;;
    esac
}

validate_required_env() {
    local key="$1"
    local value
    value="$(read_env_value "$key")"
    [[ -n "$value" ]] || die ".env 缺少必填项或值为空: $key"
    if is_placeholder_value "$key" "$value"; then
        die ".env 中 $key 仍是示例占位值"
    fi
}

psql_compose() {
    docker compose exec -T postgres env "PGPASSWORD=$POSTGRES_PASSWORD" \
        psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"
}

psql_scalar() {
    psql_compose -Atqc "$1" | tr -d '[:space:]'
}

ensure_schema_migrations_table() {
    psql_compose -c \
        "CREATE TABLE IF NOT EXISTS schema_migrations (filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW());" \
        >/dev/null
}

migration_applied() {
    local filename="$1"
    local safe="${filename//\'/\'\'}"
    [[ "$(psql_scalar "SELECT EXISTS (SELECT 1 FROM schema_migrations WHERE filename = '$safe');")" == "t" ]]
}

record_migration() {
    local filename="$1"
    local safe="${filename//\'/\'\'}"
    psql_compose -c \
        "INSERT INTO schema_migrations (filename) VALUES ('$safe') ON CONFLICT (filename) DO NOTHING;" \
        >/dev/null
}

migration_schema_present() {
    local filename="$1"
    local sql=""

    case "$filename" in
        2026-03-20-add-conversation-metadata.sql)
            read -r -d '' sql <<'EOF' || true
SELECT
    EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = 'conversation_metadata'
    )
    AND EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'conversation_metadata'
          AND column_name = 'is_deleted'
    )
    AND EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'conversation_metadata'
          AND column_name = 'deleted_at'
    );
EOF
            ;;
        2026-03-20-add-customer-service-support.sql)
            read -r -d '' sql <<'EOF' || true
SELECT
    EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'conversation_metadata'
          AND column_name = 'user_role'
    )
    AND EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = 'customer_service_messages'
    )
    AND EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = 'human_handoffs'
    );
EOF
            ;;
        2026-03-23-add-conversation-messages.sql)
            read -r -d '' sql <<'EOF' || true
SELECT
    EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'conversation_metadata'
          AND column_name = 'message_source'
    )
    AND EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = 'conversation_messages'
    );
EOF
            ;;
        2026-03-24-add-api-credentials.sql)
            read -r -d '' sql <<'EOF' || true
SELECT
    EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = 'api_credentials'
    )
    AND EXISTS (
        SELECT 1
        FROM information_schema.triggers
        WHERE event_object_schema = 'public'
          AND event_object_table = 'api_credentials'
          AND trigger_name = 'api_credentials_updated_at'
    );
EOF
            ;;
        2026-03-26-add-file-id-to-uploaded-files.sql)
            read -r -d '' sql <<'EOF' || true
SELECT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'uploaded_files'
      AND column_name = 'file_id'
);
EOF
            ;;
        *)
            return 1
            ;;
    esac

    [[ "$(psql_scalar "$sql")" == "t" ]]
}

wait_for_container_health() {
    local service="$1"
    local timeout="$2"
    local start_ts
    start_ts="$(date +%s)"

    while true; do
        local container_id status now_ts
        container_id="$(docker compose ps -q "$service")"
        [[ -n "$container_id" ]] || die "未找到服务容器: $service"
        status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id" 2>/dev/null || true)"
        case "$status" in
            healthy|running)
                log "服务已就绪: $service ($status)"
                return 0
                ;;
            unhealthy|exited|dead)
                die "服务异常: $service ($status)"
                ;;
        esac
        now_ts="$(date +%s)"
        if (( now_ts - start_ts >= timeout )); then
            die "等待服务超时: $service"
        fi
        sleep 2
    done
}

wait_for_api_health() {
    local url="http://127.0.0.1:8000/api/v1/health"
    local timeout=300
    local start_ts response compact now_ts
    start_ts="$(date +%s)"

    while true; do
        response="$(curl -fsS "$url" 2>/dev/null || true)"
        compact="$(printf '%s' "$response" | tr -d '[:space:]')"
        if [[ "$compact" == *'"status":"ok"'* ]]; then
            log "API 健康检查通过"
            return 0
        fi

        now_ts="$(date +%s)"
        if (( now_ts - start_ts >= timeout )); then
            log "API 健康检查失败，最近一次响应: ${response:-<empty>}"
            docker compose ps || true
            docker compose logs --tail=200 api postgres milvus minio etcd || true
            die "API 未在超时时间内变为健康状态"
        fi
        sleep 2
    done
}

verify_minio_storage_sanity() {
    log "校验 MinIO 存储元数据"
    docker compose exec -T minio sh -c \
        'test -f /minio_data/.minio.sys/format.json && test -d /minio_data/.minio.sys/buckets' \
        >/dev/null || die "MinIO 存储元数据不完整，检查 $APP_DATA_ROOT/minio 是否被清空、误挂载或损坏"
}

fail_on_recent_minio_drive_errors() {
    local recent_logs
    recent_logs="$(docker compose logs --since=2m minio 2>&1 || true)"
    if printf '%s' "$recent_logs" | grep -Fq 'listPathRaw: 0 drives provided'; then
        printf '%s\n' "$recent_logs" >&2
        die "MinIO 最近日志出现 '0 drives provided'，底层存储目录可能短暂丢失或损坏"
    fi
}

backup_database() {
    local backup_dir="$APP_DATA_ROOT/backups"
    local backup_file="$backup_dir/postgres-$(date +%Y%m%d-%H%M%S).sql.gz"
    log "导出 PostgreSQL 备份到 $backup_file"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '[dry-run] docker compose exec -T postgres env PGPASSWORD=<redacted> pg_dump -U %q -d %q | gzip > %q\n' \
            "$POSTGRES_USER" "$POSTGRES_DB" "$backup_file"
        return 0
    fi
    docker compose exec -T postgres env "PGPASSWORD=$POSTGRES_PASSWORD" \
        pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" | gzip > "$backup_file"
}

apply_pending_migrations() {
    local migrations=()
    local migration_count applied_count=0

    while IFS= read -r file; do
        migrations+=("$file")
    done < <(find scripts/migrations -maxdepth 1 -type f -name '*.sql' | sort)

    migration_count="${#migrations[@]}"
    (( migration_count > 0 )) || die "未找到 scripts/migrations/*.sql"

    ensure_schema_migrations_table

    for file in "${migrations[@]}"; do
        local name
        name="$(basename "$file")"
        if migration_applied "$name"; then
            continue
        fi

        if migration_schema_present "$name"; then
            log "检测到迁移产物已存在，仅回填记录: $name"
            record_migration "$name"
            continue
        fi

        log "执行迁移: $name"
        if [[ "$DRY_RUN" -eq 1 ]]; then
            printf '[dry-run] docker compose exec -T postgres env PGPASSWORD=<redacted> psql -v ON_ERROR_STOP=1 -U %q -d %q < %q\n' \
                "$POSTGRES_USER" "$POSTGRES_DB" "$file"
        else
            psql_compose < "$file"
            record_migration "$name"
        fi
        applied_count=$((applied_count + 1))
    done

    log "迁移执行完成，新增应用 $applied_count 个文件"
}

bootstrap_api_credential_if_needed() {
    local auth_enabled current_count output

    auth_enabled="$(read_env_value "AUTH_ENABLED")"
    if [[ -z "$auth_enabled" ]]; then
        auth_enabled="true"
    fi

    case "${auth_enabled,,}" in
        false|0|no)
            log "AUTH_ENABLED=false，跳过 API 凭证引导"
            return 0
            ;;
    esac

    current_count="$(psql_scalar "SELECT COUNT(*) FROM api_credentials WHERE is_active = TRUE;")"
    if [[ "$current_count" != "0" ]]; then
        log "已存在激活的 API 凭证，跳过初始凭证生成"
        return 0
    fi

    log "未检测到激活的 API 凭证，创建默认生产凭证"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '[dry-run] docker compose exec -T api python - <<'"'"'PY'"'"' ... PY\n'
        return 0
    fi

    output="$(docker compose exec -T api python - <<'PY'
import hashlib
import os
import secrets

from psycopg import connect

app_id = f"app_{secrets.token_hex(16)}"
secret_key = f"sk_{secrets.token_hex(32)}"
secret_hash = hashlib.sha256(secret_key.encode("utf-8")).hexdigest()

dsn = (
    f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
    f"@{os.environ.get('POSTGRES_HOST', 'postgres')}:{os.environ.get('POSTGRES_PORT', '5432')}"
    f"/{os.environ['POSTGRES_DB']}"
)

with connect(dsn) as conn:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO api_credentials (app_id, secret_hash, app_name)
            VALUES (%s, %s, %s)
            """,
            (app_id, secret_hash, "bootstrap-prod-client"),
        )

print(f"app_id={app_id}")
print(f"secret_key={secret_key}")
PY
)"

    printf '\n[deploy_remote] 初始 API 凭证（请立即妥善保存，仅显示一次）\n%s\n\n' "$output"
}

BACKUP=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --backup)
            BACKUP=1
            shift
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage
            die "未知参数: $1"
            ;;
    esac
done

[[ -f ".env" ]] || die "当前目录缺少 .env，请先在远端准备生产环境变量文件"
[[ -f "docker-compose.yml" ]] || die "当前目录缺少 docker-compose.yml"

require_cmd docker
require_cmd curl
require_cmd gzip
require_cmd grep
require_cmd find

if command -v sudo >/dev/null 2>&1 && [[ "$(id -u)" -ne 0 ]]; then
    SUDO_BIN="sudo"
else
    SUDO_BIN=""
fi

APP_ENV="$(read_env_value "APP_ENV")"
[[ "$APP_ENV" == "production" ]] || die ".env 中 APP_ENV 必须为 production，当前为: ${APP_ENV:-<empty>}"

validate_required_env "POSTGRES_PASSWORD"
validate_required_env "MINIO_ACCESS_KEY"
validate_required_env "MINIO_SECRET_KEY"
validate_required_env "OPENAI_API_KEY"
validate_required_env "SECRET_KEY"
validate_required_env "OPENCLAW_WEBHOOK_SECRET"
validate_required_env "API_CORS_ORIGINS"
validate_required_env "OSS_ACCESS_KEY_ID"
validate_required_env "OSS_ACCESS_KEY_SECRET"
validate_required_env "OSS_BUCKET_NAME"
validate_required_env "OSS_ENDPOINT"

POSTGRES_DB="$(read_env_value "POSTGRES_DB")"
POSTGRES_USER="$(read_env_value "POSTGRES_USER")"
POSTGRES_PASSWORD="$(read_env_value "POSTGRES_PASSWORD")"
APP_DATA_ROOT="$(read_env_value "APP_DATA_ROOT")"

[[ -n "$POSTGRES_DB" ]] || POSTGRES_DB="ai_brain"
[[ -n "$POSTGRES_USER" ]] || POSTGRES_USER="ai_brain"
[[ -n "$APP_DATA_ROOT" ]] || APP_DATA_ROOT="/data/private-domain-ai-brain"

log "准备生产数据目录: $APP_DATA_ROOT"
run_fs_cmd mkdir -p \
    "$APP_DATA_ROOT/uploads" \
    "$APP_DATA_ROOT/postgres" \
    "$APP_DATA_ROOT/etcd" \
    "$APP_DATA_ROOT/minio" \
    "$APP_DATA_ROOT/milvus" \
    "$APP_DATA_ROOT/backups"
run_fs_cmd chown -R "$(id -u):$(id -g)" "$APP_DATA_ROOT"
run_fs_cmd chown -R 10001:10001 "$APP_DATA_ROOT/uploads"
run_fs_cmd chmod -R u+rwX "$APP_DATA_ROOT/uploads"

log "校验 compose 配置"
run_cmd docker compose config -q

log "启动依赖服务"
run_cmd docker compose up -d postgres etcd minio milvus

if [[ "$DRY_RUN" -eq 0 ]]; then
    wait_for_container_health postgres 180
    wait_for_container_health minio 180
    verify_minio_storage_sanity
    fail_on_recent_minio_drive_errors
    wait_for_container_health milvus 300
    fail_on_recent_minio_drive_errors
fi

if [[ "$BACKUP" -eq 1 ]]; then
    backup_database
fi

if [[ "$DRY_RUN" -eq 0 ]]; then
    apply_pending_migrations
else
    log "dry-run 模式下跳过真实迁移执行"
fi

log "构建并启动 API 服务"
run_cmd docker compose up -d --build api

if [[ "$DRY_RUN" -eq 0 ]]; then
    wait_for_api_health
    bootstrap_api_credential_if_needed
    docker compose ps
else
    log "dry-run 模式下跳过健康检查和初始凭证引导"
fi

log "远端部署完成"
