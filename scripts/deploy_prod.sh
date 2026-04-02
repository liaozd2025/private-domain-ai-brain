#!/usr/bin/env bash
set -euo pipefail

log() {
    printf '[deploy_prod] %s\n' "$*"
}

die() {
    printf '[deploy_prod] ERROR: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
用法:
  bash scripts/deploy_prod.sh --host <host> --user <user> --target-dir <dir> [options]

必填参数:
  --host <host>            远端主机
  --user <user>            SSH 用户
  --target-dir <dir>       远端项目目录

可选参数:
  --port <port>            SSH 端口，默认 22
  --identity <path>        SSH 私钥路径
  --backup                 部署前导出 PostgreSQL 备份
  --dry-run                仅打印将执行的 rsync/ssh/deploy 动作
  -h, --help               显示帮助
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

HOST=""
REMOTE_USER=""
TARGET_DIR=""
PORT="22"
IDENTITY=""
BACKUP=0
DRY_RUN=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)
            HOST="${2:-}"
            shift 2
            ;;
        --user)
            REMOTE_USER="${2:-}"
            shift 2
            ;;
        --target-dir)
            TARGET_DIR="${2:-}"
            shift 2
            ;;
        --port)
            PORT="${2:-}"
            shift 2
            ;;
        --identity)
            IDENTITY="${2:-}"
            shift 2
            ;;
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

[[ -n "$HOST" ]] || die "必须提供 --host"
[[ -n "$REMOTE_USER" ]] || die "必须提供 --user"
[[ -n "$TARGET_DIR" ]] || die "必须提供 --target-dir"

require_cmd ssh
require_cmd rsync

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

[[ -f "$REPO_ROOT/docker-compose.yml" ]] || die "未找到 docker-compose.yml，当前不是项目根目录"
[[ -f "$REPO_ROOT/scripts/deploy_remote.sh" ]] || die "未找到 scripts/deploy_remote.sh"

SSH_ARGS=(-p "$PORT")
if [[ -n "$IDENTITY" ]]; then
    SSH_ARGS+=(-i "$IDENTITY")
fi

REMOTE="${REMOTE_USER}@${HOST}"
TARGET_DIR_Q="$(printf '%q' "$TARGET_DIR")"

RSYNC_ARGS=(
    -az
    --delete
    --exclude=.git/
    --exclude=.env
    --exclude=.env.dev
    --exclude=.env.prod
    --exclude=.venv/
    --exclude=venv/
    --exclude=__pycache__/
    --exclude=.pytest_cache/
    --exclude=.ruff_cache/
    --exclude=.mypy_cache/
    --exclude=htmlcov/
    --exclude=.coverage
    --exclude=uploads/
    --exclude=postgres/
    --exclude=etcd/
    --exclude=minio/
    --exclude=milvus/
    --exclude=backups/
    --exclude=tests/
    --exclude=tasks/
    --exclude=docs/
    --exclude=.claude/
    --exclude=.DS_Store
)

if [[ "$DRY_RUN" -eq 1 ]]; then
    RSYNC_ARGS+=(--dry-run)
fi

REMOTE_DEPLOY_ARGS=()
if [[ "$BACKUP" -eq 1 ]]; then
    REMOTE_DEPLOY_ARGS+=(--backup)
fi
if [[ "$DRY_RUN" -eq 1 ]]; then
    REMOTE_DEPLOY_ARGS+=(--dry-run)
fi

log "准备远端目录: $REMOTE:$TARGET_DIR"
run_cmd ssh "${SSH_ARGS[@]}" "$REMOTE" "mkdir -p $TARGET_DIR_Q"

log "同步当前工作区到远端"
run_cmd rsync "${RSYNC_ARGS[@]}" "$REPO_ROOT/" "$REMOTE:$TARGET_DIR/"

REMOTE_COMMAND="cd $TARGET_DIR_Q && bash scripts/deploy_remote.sh"
if [[ "${#REMOTE_DEPLOY_ARGS[@]}" -gt 0 ]]; then
    for arg in "${REMOTE_DEPLOY_ARGS[@]}"; do
        REMOTE_COMMAND+=" $(printf '%q' "$arg")"
    done
fi

log "预检远端环境"
run_cmd ssh "${SSH_ARGS[@]}" "$REMOTE" \
    'command -v docker >/dev/null 2>&1 || { echo "ERROR: 远端未安装 docker"; exit 1; }
     docker compose version >/dev/null 2>&1 || { echo "ERROR: 远端未安装 docker compose plugin"; exit 1; }'

log "执行远端部署"
run_cmd ssh "${SSH_ARGS[@]}" "$REMOTE" "$REMOTE_COMMAND"

log "部署流程结束"
