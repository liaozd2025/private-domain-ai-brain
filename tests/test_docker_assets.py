from pathlib import Path


def test_dockerfile_installs_dependencies_before_copying_source():
    content = Path("Dockerfile").read_text(encoding="utf-8")

    assert 'COPY pyproject.toml ./' in content
    assert 'python - <<\'PY\' > /tmp/requirements.txt' in content
    assert 'pip install --no-cache-dir -r /tmp/requirements.txt' in content
    assert 'COPY src/ ./src/' in content
    assert 'pip install --no-cache-dir .' not in content

    deps_install_index = content.index('pip install --no-cache-dir -r /tmp/requirements.txt')
    copy_src_index = content.index('COPY src/ ./src/')
    assert deps_install_index < copy_src_index
