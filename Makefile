# Marg.ai developer commands. `make check` is the CLAUDE.md §2 verification loop.
TEST_DATABASE_URL := postgresql+asyncpg://marg:marg@localhost:55432/marg_test

.PHONY: setup fmt lint type test check test-db-up test-db-down test-int up down migrate

setup:
	uv sync

fmt:
	.venv/bin/ruff format .

lint:
	.venv/bin/ruff check .

type:
	.venv/bin/mypy .

test:
	.venv/bin/pytest

check: fmt lint type test

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

# Migrates the LOCAL database only. There is deliberately no target for a deployed database
# (CLAUDE.md §8).
migrate:
	.venv/bin/alembic upgrade head
