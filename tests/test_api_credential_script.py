import subprocess
import sys
from pathlib import Path

SCRIPT_PATH = Path("scripts/create_api_credential.py")


def test_api_credential_script_outputs_deterministic_values():
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--app-name",
            "默认应用",
            "--app-id",
            "app_e918d505953f8d0a552beead85bb9ee4",
            "--secret-key",
            "sk_demo_123456",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "app_id=app_e918d505953f8d0a552beead85bb9ee4" in result.stdout
    assert "secret_key=sk_demo_123456" in result.stdout
    assert (
        "secret_hash=7fc198cfbacda791ea116ff568dc751b5556f9d2efcc23c6b2413ea0b21258b4"
        in result.stdout
    )
    assert "INSERT INTO api_credentials (app_id, secret_hash, app_name)" in result.stdout
    assert "ON CONFLICT (app_id) DO UPDATE" in result.stdout
    assert "is_active = TRUE" in result.stdout


def test_api_credential_script_sql_only_mode():
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--app-name",
            "默认应用",
            "--app-id",
            "app_fixed",
            "--secret-key",
            "sk_fixed",
            "--sql-only",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "app_id=" not in result.stdout
    assert "secret_key=" not in result.stdout
    assert "secret_hash=" not in result.stdout
    assert "INSERT INTO api_credentials" in result.stdout
