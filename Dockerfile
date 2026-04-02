FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# 先复制依赖清单，确保业务代码变更不会让依赖层失效
COPY pyproject.toml ./

# 从 pyproject.toml 提取运行时依赖，避免每次改 src 都重新 pip install
RUN python - <<'PY' > /tmp/requirements.txt
import tomllib
from pathlib import Path

with Path("pyproject.toml").open("rb") as fp:
    data = tomllib.load(fp)

for dep in data["project"]["dependencies"]:
    print(dep)
PY

# 显式预装 CPU 版 torch，避免 Linux 镜像解析出大体积 CUDA 依赖
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install --no-cache-dir -r /tmp/requirements.txt

# 最后复制源码，保证日常代码改动只影响这一层
COPY src/ ./src/

# 创建上传目录
RUN useradd --system --create-home --uid 10001 appuser \
    && mkdir -p /app/uploads \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
