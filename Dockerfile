# One image for the api (and, from S4, the worker); only the command differs.
FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv
WORKDIR /srv
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
# Read at runtime: the khoj catalogue, the NCERT chapters for teachers, and the corpus that
# `marg ingest-corpus` loads into the database.
COPY content ./content
COPY corpus ./corpus
COPY alembic ./alembic
COPY alembic.ini ./
RUN uv sync --frozen --no-dev
RUN useradd --system --uid 10001 marg && chown -R marg /srv
USER marg
EXPOSE 8000
# --no-access-log: uvicorn's access log bypasses our redaction and would print query strings
# (e.g. the WhatsApp verify token). Requests are logged through app.core.logging instead.
# Open live-trace streams (up to DEMO_SSE_MAX_S) must not hold a deploy: close them after 25 s.
CMD [".venv/bin/uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--timeout-graceful-shutdown", "25"]
