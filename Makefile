# Marg.ai developer commands. `make check` is the CLAUDE.md §2 verification loop.
TEST_DATABASE_URL := postgresql+asyncpg://marg:marg@localhost:55432/marg_test

.PHONY: setup fmt lint type test check test-db-up test-db-down test-int up down migrate worker \
	sidecar-setup sidecar sidecar-check

setup:
	uv sync
	cd services/ml_sidecar && uv sync

fmt:
	.venv/bin/ruff format .

lint:
	.venv/bin/ruff check .

type:
	.venv/bin/mypy .

test:
	.venv/bin/pytest

# ruff covers services/ml_sidecar from here; its types and tests run in its own environment.
check: fmt lint type test sidecar-check

test-db-up:
	docker compose -f docker-compose.test.yml up -d --wait

test-db-down:
	docker compose -f docker-compose.test.yml down -v

test-int:
	DATABASE_URL=$(TEST_DATABASE_URL) .venv/bin/alembic upgrade head
	DATABASE_URL=$(TEST_DATABASE_URL) .venv/bin/alembic downgrade base
	DATABASE_URL=$(TEST_DATABASE_URL) .venv/bin/alembic upgrade head
	DATABASE_URL=$(TEST_DATABASE_URL) .venv/bin/alembic check
	DATABASE_URL=$(TEST_DATABASE_URL) .venv/bin/pytest -m integration

up:
	docker compose up --build -d

down:
	docker compose down

# One worker process (s04). Run beside an api started with RUN_WORKER_IN_API=false, or beside
# other workers: leases keep each user's turns to one worker at a time.
worker:
	.venv/bin/python -m app.worker

# Migrates the LOCAL database only. There is deliberately no target for a deployed database
# (CLAUDE.md §8).
migrate:
	.venv/bin/alembic upgrade head

# The ML sidecar (services/ml_sidecar): Meta's MMS-TTS voice, needed only with
# VOICE_REPLIES_ENABLED=true, in its own Python 3.12 environment. `make sidecar` serves it on
# :8100 with this repo's .env (TTS_ENGINE, SIDECAR_TOKEN).
sidecar-setup:
	cd services/ml_sidecar && uv sync

sidecar:
	cd services/ml_sidecar && set -a && . ../../.env && set +a && \
		.venv/bin/uvicorn sidecar.server:build_app --factory --host 127.0.0.1 --port 8100 --no-access-log

sidecar-check:
	cd services/ml_sidecar && .venv/bin/mypy . && .venv/bin/pytest -q
