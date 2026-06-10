# 多阶段构建：builder 装依赖，runtime 只带必需品（镜像更小、更安全）
#
#   docker build -t blog-agent .
#   docker run --rm -p 8000:8000 --env-file ../../../.env blog-agent

# ---- 阶段 1：用 uv 安装依赖 ----
FROM ghcr.io/astral-sh/uv:python3.10-bookworm-slim AS builder
WORKDIR /app

# 字节码预编译 + copy 模式（容器里没有硬链接可用）
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# 先只拷依赖清单装依赖 —— 代码改动不会击穿这层缓存，重建快 10 倍
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# 再拷代码
COPY . .
RUN uv sync --frozen --no-dev

# ---- 阶段 2：运行时（不带 uv、不带构建缓存）----
FROM python:3.10-slim-bookworm
WORKDIR /app

# 非 root 运行（安全基线）
RUN useradd -m app
COPY --from=builder --chown=app:app /app /app
USER app

ENV PATH="/app/.venv/bin:$PATH" \
    HF_ENDPOINT="https://hf-mirror.com"

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
