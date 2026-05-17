# syntax=docker/dockerfile:1.7

# ---------- builder ----------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Project metadata + source. LICENSE must be present because
# pyproject.toml declares ``license = { file = "LICENSE" }`` and
# hatchling validates that file at build time.
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src

RUN uv sync --frozen --no-dev

# ---------- runtime ----------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    # The default config writes to ``.tmp/`` under CWD which is not
    # writable when the container runs as uid 1000. Redirect cache and
    # persistence to ``/data`` so a single mounted volume covers both.
    CACHE_DIR=/data/cache \
    PERSIST_DATABASE_URL=sqlite+aiosqlite:////data/omniquery.db \
    OMNIQUERY_LOG_DIR=/data/logs \
    MPLCONFIGDIR=/data/mpl

RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 --shell /bin/bash omniquery \
 # Pre-create /data so the non-root user can write caches and the
 # SQLite persistence file from the first request. When compose mounts
 # a named volume here, the ownership is preserved.
 && mkdir -p /data \
 && chown -R 1000:1000 /data

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/src /app/src
COPY docs /app/docs
COPY pyproject.toml LICENSE /app/

WORKDIR /app
USER omniquery

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" \
      || exit 1

ENTRYPOINT ["omniquery-web"]
