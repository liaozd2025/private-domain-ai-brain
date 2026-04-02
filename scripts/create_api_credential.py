#!/usr/bin/env python3
"""生成 API 凭证并输出可执行 SQL。"""

from __future__ import annotations

import argparse
import hashlib
import secrets


def hash_secret(secret_key: str) -> str:
    return hashlib.sha256(secret_key.encode("utf-8")).hexdigest()


def generate_app_id() -> str:
    return f"app_{secrets.token_hex(16)}"


def generate_secret_key() -> str:
    return f"sk_{secrets.token_hex(32)}"


def escape_sql(value: str) -> str:
    return value.replace("'", "''")


def build_upsert_sql(app_id: str, secret_hash: str, app_name: str) -> str:
    return f"""INSERT INTO api_credentials (app_id, secret_hash, app_name)
VALUES (
  '{escape_sql(app_id)}',
  '{escape_sql(secret_hash)}',
  '{escape_sql(app_name)}'
)
ON CONFLICT (app_id) DO UPDATE
SET secret_hash = EXCLUDED.secret_hash,
    app_name = EXCLUDED.app_name,
    is_active = TRUE,
    updated_at = NOW();"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate app_id / secret_key / secret_hash for api_credentials."
    )
    parser.add_argument(
        "--app-name",
        default="默认应用",
        help="Display name stored in api_credentials.",
    )
    parser.add_argument("--app-id", help="Use a fixed app_id instead of generating one.")
    parser.add_argument("--secret-key", help="Use a fixed secret_key instead of generating one.")
    parser.add_argument(
        "--sql-only",
        action="store_true",
        help="Print SQL only so the output can be piped into psql.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    app_id = args.app_id or generate_app_id()
    secret_key = args.secret_key or generate_secret_key()
    secret_hash = hash_secret(secret_key)
    sql = build_upsert_sql(app_id=app_id, secret_hash=secret_hash, app_name=args.app_name)

    if args.sql_only:
        print(sql)
        return 0

    print(f"app_id={app_id}")
    print(f"secret_key={secret_key}")
    print(f"secret_hash={secret_hash}")
    print()
    print(sql)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
