from pathlib import Path

DEPLOY_PROD_PATH = Path("scripts/deploy_prod.sh")
DEPLOY_REMOTE_PATH = Path("scripts/deploy_remote.sh")
README_PATH = Path("README.md")
COMPOSE_PATH = Path("docker-compose.yml")
ENV_EXAMPLE_PATH = Path(".env.example")


def test_deploy_scripts_exist_and_reference_expected_capabilities():
    deploy_prod = DEPLOY_PROD_PATH.read_text(encoding="utf-8")
    deploy_remote = DEPLOY_REMOTE_PATH.read_text(encoding="utf-8")

    assert DEPLOY_PROD_PATH.exists()
    assert DEPLOY_REMOTE_PATH.exists()

    assert "rsync" in deploy_prod
    assert "ssh" in deploy_prod
    assert "--backup" in deploy_prod
    assert "--dry-run" in deploy_prod
    assert "scripts/deploy_remote.sh" in deploy_prod
    assert "--exclude=uploads/" in deploy_prod
    assert "--exclude=postgres/" in deploy_prod
    assert "--exclude=etcd/" in deploy_prod
    assert "--exclude=minio/" in deploy_prod
    assert "--exclude=milvus/" in deploy_prod
    assert "--exclude=backups/" in deploy_prod
    assert "--exclude=tests/" in deploy_prod

    assert "schema_migrations" in deploy_remote
    assert "migration_schema_present" in deploy_remote
    assert "2026-03-24-add-api-credentials.sql" in deploy_remote
    assert "pg_dump" in deploy_remote
    assert "/api/v1/health" in deploy_remote
    assert "api_credentials" in deploy_remote
    assert "docker compose up -d --build api" in deploy_remote
    assert 'validate_required_env "OSS_ACCESS_KEY_ID"' in deploy_remote
    assert 'validate_required_env "OSS_ACCESS_KEY_SECRET"' in deploy_remote
    assert 'validate_required_env "OSS_BUCKET_NAME"' in deploy_remote
    assert 'validate_required_env "OSS_ENDPOINT"' in deploy_remote
    assert "verify_minio_storage_sanity" in deploy_remote
    assert "/minio_data/.minio.sys/format.json" in deploy_remote
    assert "fail_on_recent_minio_drive_errors" in deploy_remote
    assert "listPathRaw: 0 drives provided" in deploy_remote
    assert 'chown -R 10001:10001 "$APP_DATA_ROOT/uploads"' in deploy_remote
    assert 'chmod -R u+rwX "$APP_DATA_ROOT/uploads"' in deploy_remote


def test_deploy_scripts_have_valid_bash_syntax():
    import subprocess

    result = subprocess.run(
        ["bash", "-n", str(DEPLOY_PROD_PATH), str(DEPLOY_REMOTE_PATH)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_deploy_prod_runs_without_optional_remote_args(tmp_path):
    import os
    import subprocess

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    call_log = tmp_path / "calls.log"

    for name in ("ssh", "rsync"):
        stub_path = bin_dir / name
        stub_path.write_text(
            "#!/usr/bin/env bash\n"
            "printf '%s\\n' \"$0 $*\" >> \"$CALL_LOG\"\n"
            "exit 0\n",
            encoding="utf-8",
        )
        stub_path.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["CALL_LOG"] = str(call_log)

    result = subprocess.run(
        [
            "bash",
            str(DEPLOY_PROD_PATH),
            "--host",
            "192.0.2.10",
            "--user",
            "root",
            "--target-dir",
            "/tmp/private-domain-ai-brain",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "部署流程结束" in result.stdout
    assert "deploy_remote.sh" in call_log.read_text(encoding="utf-8")


def test_deploy_prod_rsync_excludes_persistent_dirs_for_app_data_root_target(tmp_path):
    import os
    import subprocess

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    call_log = tmp_path / "calls.log"

    for name in ("ssh", "rsync"):
        stub_path = bin_dir / name
        stub_path.write_text(
            "#!/usr/bin/env bash\n"
            "printf '%s\\n' \"$0 $*\" >> \"$CALL_LOG\"\n"
            "exit 0\n",
            encoding="utf-8",
        )
        stub_path.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["CALL_LOG"] = str(call_log)

    result = subprocess.run(
        [
            "bash",
            str(DEPLOY_PROD_PATH),
            "--host",
            "192.168.168.105",
            "--user",
            "root",
            "--target-dir",
            "/data/private-domain-ai-brain",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr

    call_text = call_log.read_text(encoding="utf-8")
    assert "--exclude=uploads/" in call_text
    assert "--exclude=postgres/" in call_text
    assert "--exclude=etcd/" in call_text
    assert "--exclude=minio/" in call_text
    assert "--exclude=milvus/" in call_text
    assert "--exclude=backups/" in call_text


def test_readme_documents_production_deploy_scripts():
    content = README_PATH.read_text(encoding="utf-8")

    assert "scripts/deploy_prod.sh" in content
    assert "--backup" in content
    assert "deploy_remote.sh" in content
    assert "OSS_ACCESS_KEY_ID" in content
    assert "curl -fsS http://127.0.0.1:8000/api/v1/health" in content
    assert "chown -R 10001:10001 /data/private-domain-ai-brain/uploads" in content
    assert "mkdir -p /app/uploads/oss_cache/healthcheck" in content


def test_production_postgres_host_port_uses_5431_while_internal_port_stays_5432():
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    env_example = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    readme = README_PATH.read_text(encoding="utf-8")

    assert '${POSTGRES_HOST_PORT:-5431}:5432' in compose
    assert "POSTGRES_HOST=postgres" in env_example
    assert "POSTGRES_PORT=5432" in env_example
    assert "POSTGRES_HOST_PORT=5431" in env_example
    assert "5431 -> 容器 5432" in readme
