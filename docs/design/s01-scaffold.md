# S1 — Scaffold

> **Hackathon build level: Full. One process while exception E1 holds.** We build the full design by default; lite only as the listed exceptions in [mvp-scope.md](mvp-scope.md), which wins for the hackathon where it differs.

## 1. Purpose

Set up the repository so every later step starts on solid ground: dependency management,
strict checkers, test markers, typed settings, the error hierarchy, logging that can't leak
personal data, the app factory with health endpoints, the composition root, an enforced layering
rule, CI, and Docker. Nothing here talks to WhatsApp or a model. When S1 is done, the
verification loop from CLAUDE.md §2 runs green on an almost-empty app, locally and on CI.

## 2. Read first

- [00-overview.md](00-overview.md) §2 (processes), §5 (layering)
- [contracts.md](contracts.md) §4 (errors), §7 (settings), §3 (`Clock`)
- [data-model.md](data-model.md) §5 (migration conventions)
- [plan.md](../../plan.md) §6 (approved stack), §9 (folder structure)
- [CLAUDE.md](../../CLAUDE.md) §1, §2, §6, §8, §9

## 3. Scope

**In**
- `pyproject.toml`, `uv.lock`, `.python-version` (3.13), `.env.example`, `Makefile`
- `app/core/config.py`, `app/core/errors.py`, `app/core/logging.py`, `app/core/clock.py`
- `app/store/db.py` (async engine and session factory only, no tables)
- `app/main.py` (app factory), `app/api/health.py`, `app/wiring.py`
- Alembic initialised (`alembic.ini`, `alembic/env.py`), no revisions yet
- `tests/conftest.py`, `tests/fakes/clock.py`, `tests/unit/test_layering.py` and the S1 unit tests
- `.github/workflows/ci.yml`, `Dockerfile`, `docker-compose.yml`, `docker-compose.test.yml`

**Out (owner)**
- Any table or migration revision → S3 creates the first one (`users`, `inbox_messages`).
- The `app/worker/` package (`python -m app.worker`) and the `worker` compose service → S4.
  Adding an entrypoint with nothing to run would be a stub (CLAUDE.md §1).
- Settings beyond the S1 set (§7) → each step adds its own settings to `config.py` and
  `.env.example` in the same commit. A setting nothing reads isn't added early.
- Provider readiness probes → S16 adds them to the probe list built here.
- `app/core/identity.py` (user hashing and address encryption) → S3.

## 4. Design

### 4.1 Repository tooling

`uv` manages the virtualenv in `.venv/` and the lockfile. CLAUDE.md requires `.venv/bin/<tool>`,
and `uv sync` creates exactly that, so `make` targets call `.venv/bin/...` directly.

```toml
# pyproject.toml
[project]
name = "marg-ai"
version = "0.1.0"
requires-python = ">=3.13,<3.14"
dependencies = [
  "fastapi",                 # each pinned with == at `uv add` time; exact versions live in uv.lock
  "uvicorn[standard]",
  "pydantic",
  "pydantic-settings",
  "httpx",
  "openai",
  "sqlalchemy[asyncio]",
  "asyncpg",
  "alembic",
  "jinja2",
  "structlog",
]

[dependency-groups]
dev = [
  "ruff",
  "mypy",
  "pytest",
  "pytest-asyncio",
  "hypothesis",
  "respx",
  "types-PyYAML",            # added with pyyaml (S10)
]

[project.scripts]
marg = "app.cli:main"        # added in the step that creates app/cli.py (S11), not in S1
```

**Approved dependencies added by later steps (decision B6), each in the step that first imports it:**

| Package | Group | Added in | Why |
|---|---|---|---|
| `cryptography` | runtime | S3 | AES-256-GCM address encryption (decision A1) |
| `pyyaml` | runtime | S10 | curriculum catalogue, activity catalogue (s10b), golden eval files (s15) |
| `types-PyYAML` | dev | S10 | typed stubs for `pyyaml` (mypy strict) |
| `pgvector` | runtime | S11 | SQLAlchemy `Vector` column type |

`tenacity` is **not** used: the retry policy is a small deadline-aware class in
`app/providers/http.py` (contracts §5). `regex` is not used: grapheme-safe splitting uses
`unicodedata` (s05 §4.7, s11). `[project.scripts]` is shown for orientation only: S1 doesn't add it.

Every version is pinned with `==` when it's added (`uv add 'fastapi==<current>'`), so
`pyproject.toml` and `uv.lock` agree and builds are reproducible.

### 4.2 Ruff

```toml
[tool.ruff]
line-length = 100
target-version = "py313"
extend-exclude = [".venv", "*.md"]  # ruff also formats code blocks in Markdown; the docs' snippets are illustrations

[tool.ruff.lint]
select = [
  "E", "W", "F", "I", "N", "UP", "B", "A", "C4", "SIM", "RET", "PIE", "PTH", "RUF",
  "ANN",    # every function annotated; ANN401 bans `Any` in annotations
  "BLE",    # no blind `except Exception`
  "TRY",    # exception hygiene (raise-from, no bare raise of Exception)
  "S",      # bandit: no shell=True, no hardcoded secrets
  "DTZ",    # no naive datetimes
  "T20",    # no print in app code
  "ERA",    # no commented-out code
  "FIX", "TD",  # no TODO / FIXME / XXX (CLAUDE.md §1)
  "ASYNC",  # no blocking calls inside async functions
  "PT",     # pytest style
  "PL",     # pylint subset
  "FBT",    # no boolean positional args
  "TID",    # banned APIs, see below
]
ignore = [
  "TRY003",  # long messages in exception constructors are what CLAUDE.md asks for
  "N818",    # contracts.md names exceptions by what happened (LeaseLost, ProviderTimeout)
]

[tool.ruff.lint.flake8-tidy-imports.banned-api]
"typing.Any".msg = "CLAUDE.md §1: never use Any. Use a TypeVar, Protocol, TypedDict, Literal or object + narrowing."
"datetime.datetime.now".msg = "Use app.core.clock.Clock so time is injectable."
"datetime.datetime.utcnow".msg = "Naive UTC. Use app.core.clock.Clock."
"subprocess.run".msg = "Use asyncio.create_subprocess_exec with a timeout (CLAUDE.md §12)."

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101", "PLR2004"]          # assert and literal values are how tests work
"scripts/spikes/**" = ["T20"]              # spike scripts print their measurements
"app/core/clock.py" = ["TID251"]           # the one place allowed to call datetime.now
```

These per-file ignores are set once, here, deliberately. CLAUDE.md §1 forbids widening them
later without explicit approval.

### 4.3 Mypy

```toml
[tool.mypy]
python_version = "3.13"
strict = true
disallow_any_unimported = true
disallow_any_explicit = true
disallow_any_decorated = false        # FastAPI decorators return Any-typed callables; see note
warn_unreachable = true
warn_unused_ignores = true
enable_error_code = ["ignore-without-code", "redundant-expr", "truthy-bool", "possibly-undefined"]
plugins = ["pydantic.mypy"]
exclude = ["^\\.venv/"]

[tool.pydantic-mypy]
init_forbid_extra = true
init_typed = true
warn_required_dynamic_aliases = true
```

Note on `disallow_any_decorated = false`: it's the one strict flag left off, because FastAPI's
route decorators are typed with `Callable[..., Any]` internally, and enabling it would force an
ignore on every route. Approved by the owner (decision B7).

### 4.4 Pytest

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
addopts = "-m 'not integration' --strict-markers --strict-config -ra"
markers = [
  "unit: pure or fake-backed, no I/O",
  "contract: parsing of real-shaped external payloads",
  "integration: needs docker-compose.test.yml Postgres",
]
filterwarnings = ["error"]
xfail_strict = true
```

`tests/conftest.py` registers two Hypothesis profiles and picks one from the environment:

```python
settings.register_profile("dev", max_examples=100, deadline=None)
settings.register_profile("ci", max_examples=300, deadline=None, derandomize=True,
                          print_blob=True)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))
```

`derandomize=True` keeps CI deterministic (CLAUDE.md §3).

### 4.5 Settings — `app/core/config.py`

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8",
                                      extra="ignore", frozen=True)

    environment: Literal["local", "test", "staging", "prod"] = "local"
    database_url: SecretStr
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

def load_settings() -> Settings:
    """Read settings once at startup. Raises ConfigError naming every bad field."""
```

- `load_settings()` catches `pydantic.ValidationError` and raises
  `ConfigError("invalid settings: DATABASE_URL (missing), ENVIRONMENT (input should be 'local', 'test', 'staging' or 'prod')")`,
  chained `from exc`. The message lists field names and reasons, **never values**: a secret that
  fails validation must not end up in a log.
- `database_url` must use the `postgresql+asyncpg://` scheme. A field validator rejects anything
  else with a message naming the expected scheme.
- Later steps append their fields under a comment naming the step, and update `.env.example` in
  the same commit.

### 4.6 Errors — `app/core/errors.py`

The whole hierarchy from contracts.md §4 is created in S1, because every later step raises from it.
These are complete classes, not stubs.

```python
class MargError(Exception):
    """Base for every exception raised by Marg.ai code."""

class ConfigError(MargError): ...

class ProviderError(MargError):
    def __init__(self, message: str, *, provider: str, retryable: bool) -> None: ...
    provider: str
    retryable: bool

class ProviderTimeout(ProviderError):           # retryable=True fixed in __init__
class ProviderRateLimited(ProviderError):       # adds retry_after: float | None
class ProviderUnavailable(ProviderError):       # retryable=True
class ProviderRejected(ProviderError):          # retryable=False
class ProviderResponseInvalid(ProviderError):   # retryable=True (the policy retries it once)

class SafetyUnavailable(MargError): ...
class MediaError(MargError): ...
class MediaTooLarge(MediaError): ...
class MediaUnsupported(MediaError): ...
class TranscodeFailed(MediaError): ...
class TtsTextInvalid(MediaError): ...
class ChannelError(MargError): ...
class SignatureInvalid(ChannelError): ...
class PayloadInvalid(ChannelError): ...
class InvalidAddressCiphertext(ChannelError): ...
class DeliveryFailed(ChannelError): ...
class DomainError(MargError): ...
class InvalidTransition(DomainError): ...
class InvalidProfileValue(DomainError): ...
class StoreError(MargError): ...
class LeaseLost(StoreError): ...
class NotFound(StoreError): ...
class CorpusValidationError(MargError): ...
class GoldenCaseInvalid(MargError): ...
class LinkInvalid(MargError): ...
class BudgetExceeded(MargError): ...
class RateLimited(MargError): ...
```

Subclasses with fixed retryability set it in their own `__init__`, so a caller can't build a
`ProviderTimeout` that claims to be non-retryable.

### 4.7 Logging — `app/core/logging.py`

structlog, JSON lines to stdout, one event per line.

```python
def configure_logging(level: str, *, environment: str) -> None:
    """Install the processor chain. Called once from create_app and the worker entrypoint."""

def redact_personal_data(logger: WrappedLogger, method_name: str,
                         event_dict: EventDict) -> EventDict:
    """structlog processor. Runs last before rendering, so nothing bypasses it."""
```

Processor chain, in order: `contextvars.merge_contextvars` → `add_log_level` →
`TimeStamper(fmt="iso", utc=True)` → `StackInfoRenderer` → `format_exc_info` →
**`redact_personal_data`** → `JSONRenderer`.

`structlog.contextvars` carries `turn_id`, `user_hash` and `step` from S4 onwards. Every line
in a turn gets them without passing them around.

**Redaction rules** (CLAUDE.md §11: logs never contain phone numbers, transcripts or replies):

1. **Denied keys.** If a key (at any depth in nested dicts and lists) matches the denylist, its
   value becomes `"[redacted]"`. Matching is case-insensitive on the whole key:
   `phone`, `wa_id`, `from`, `address`, `recipient`, `text`, `body`, `transcript`, `user_text`,
   `reply_text`, `spoken_text`, `caption`, `profile`, `name`, `raw_payload`, `payload`,
   `authorization`, `token`, `access_token`, `secret`, `password`, `api_key`, `cookie`.
2. **Value patterns.** Every string value not already redacted, **including `event`** (the log
   message), is scanned and matches are replaced:
   - phone numbers: `\+?\d[\d\s-]{8,14}\d`, which covers E.164 with optional separators and
     10-digit Indian mobiles → `"[phone]"`
   - bearer tokens and keys: `(?i)bearer\s+[A-Za-z0-9._~+/=-]+` → `"Bearer [redacted]"`
   - long opaque strings (≥ 32 chars of `[A-Za-z0-9_-]`) that aren't hex `user_hash`es
     (exactly 64 lowercase hex chars) → `"[token]"`
3. `SecretStr` values render as `**********` by default. The processor also replaces any
   `SecretStr` instance it finds with `"[redacted]"`, in case something calls `.get_secret_value()`
   on the way.
4. Exceptions: `format_exc_info` turns the traceback into a string first, so the pattern rules
   run over the traceback text too.

`user_hash` is deliberately allowed: it's the identifier we log *instead of* the phone number.

### 4.8 Clock — `app/core/clock.py`

```python
class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)
```

It satisfies the `Clock` Protocol from contracts.md §3. That Protocol is declared in
`app/providers/ports.py`, which S1 creates containing only `Clock`. S5 adds the rest.
`tests/fakes/clock.py` provides `FixedClock(at: datetime)` with `advance(by: timedelta) -> None`.

### 4.9 Database engine — `app/store/db.py`

```python
def create_engine(settings: Settings) -> AsyncEngine:
    """asyncpg engine. pool_size=5, max_overflow=5, pool_pre_ping=True, pool_recycle=300."""

def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]: ...

async def ping(engine: AsyncEngine) -> None:
    """SELECT 1. Raises StoreError chained from the driver error on failure."""
```

Neon's pooled endpoint closes idle connections, which is why `pool_pre_ping` and a short
`pool_recycle` are set. Alembic's `env.py` reads `DATABASE_URL` through `load_settings()` and
runs migrations with the async engine (`connection.run_sync(do_run_migrations)`).

### 4.10 Composition root — `app/wiring.py`

The **only** module that constructs concrete adapters. Everything else receives dependencies.

```python
@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    clock: Clock
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    readiness_probes: tuple[ReadinessProbe, ...]

def build_container(settings: Settings) -> Container: ...
async def close_container(container: Container) -> None:   # disposes the engine
```

Later steps add fields (`language_model`, `transcriber`, `whatsapp_sender`, …) to `Container`
and build them in `build_container`. Tests build a `Container` with fakes directly.

### 4.11 App factory and health — `app/main.py`, `app/api/health.py`

```python
def create_app(settings: Settings | None = None,
               container: Container | None = None) -> FastAPI:
    """Factory used by uvicorn (--factory) and tests. Loads settings if not given,
    configures logging, builds the container in the lifespan, mounts routers."""
```

- The container is stored on `app.state.container` and read through a dependency in
  `app/api/deps.py`: `def get_container(request: Request) -> Container`.
- Routers are registered in one place, in `create_app`.

```python
class HealthResponse(BaseModel):
    status: Literal["ok"]

class ProbeResult(BaseModel):
    name: str
    ok: bool
    detail: str | None          # e.g. "connection refused"; never secrets or URLs with credentials
    critical: bool              # a failing critical probe makes the service not ready

class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    environment: Literal["local", "test", "staging", "prod"]   # lets the s16 load driver refuse prod
    checks: list[ProbeResult]

@dataclass(frozen=True, slots=True)
class ReadinessProbe:                     # app/api/readiness.py
    name: str
    critical: bool
    check: Callable[[], Awaitable[None]]  # raises a MargError when the dependency isn't usable
```

The probe carries its own `name` and `critical` so a timeout can still be reported under the
right name; `run_probe` turns a `MargError` or a timeout into `ok=False`.

| Route | Behaviour |
|---|---|
| `GET /healthz` | Liveness. Always `200 {"status":"ok"}` if the process is serving. No I/O. |
| `GET /readyz` | Runs every probe concurrently, each with a 2 s timeout. `200` + `ready` when every critical probe passes, otherwise `503` + `not_ready`. Always returns the full `checks` list. |

S1 has one probe, `database` (critical), which calls `ping(engine)`. A probe that raises or times
out becomes `ProbeResult(ok=False, detail=<exception class and short reason>)`. It never
propagates, and it never reports ok when it isn't. S16 adds the provider probes.

### 4.12 Layering test — `tests/unit/test_layering.py`

This turns 00-overview.md §5 into a failing test. It's a small AST import-graph checker, with no
dependency on a third-party import linter.

**Algorithm**
1. Walk every `*.py` under `app/`. Module name from the path (`app/layers/mentor.py` → `app.layers.mentor`).
2. Parse with `ast`. Collect imports from `ast.Import` and `ast.ImportFrom`, including those
   inside `if TYPE_CHECKING:` blocks (type-only imports still couple layers). Resolve relative
   imports using `level` and the module's package.
3. For each `app.*` import, compare the importer's **area** with the imported area against the
   rules table. The area is the second path segment (`app.layers.x` → `layers`). For
   `providers`, `providers.ports` and `providers.http` are separate areas from the adapter
   packages (`providers.llm`, `providers.speech`, …).
4. For each third-party import, check the restricted-library table.
5. Collect **every** violation and fail once with a list of `importer → imported (rule)` lines,
   so one run shows everything.

**Rules (internal imports allowed, besides the area importing itself)**

| Area | May import |
|---|---|
| `domain` | `core.errors`, `core.types` only |
| `layers` | `domain`, `providers.ports`, `prompts`, `rag` (retrieval interfaces), `core.errors`, `core.types` |
| `pipeline` | `domain`, `layers`, `providers.ports`, `safety`, `store`, `telemetry`, `core` |
| `safety` | `domain`, `providers.ports`, `prompts`, `core` |
| `telemetry` | `domain`, `providers.ports`, `prompts`, `store`, `core` |
| `rag` | `domain`, `providers.ports`, `store`, `core` |
| `audio` | `domain`, `core` |
| `prompts` | `domain`, `core.errors`, `core.types` |
| `channels` | `domain`, `providers.ports`, `providers.http`, `core` |
| `providers.ports` | `domain`, `core.errors`, `core.types` |
| `providers.http` | `core` |
| `providers.<adapter>` | `domain`, `providers.ports`, `providers.http`, `core`, `audio` |
| `store` | `domain`, `core` |
| `api` | `domain`, `channels`, `store`, `core`, `pipeline` (hand-off only), `telemetry` (dashboard queries) |
| `core` | `core` only |
| `worker`, `evals` | anything except `api` |
| `wiring`, `main`, `cli` | anything (composition roots) |

**Restricted third-party libraries**

| Library | Only in |
|---|---|
| `openai` | `providers` |
| `httpx` | `providers`, `channels` (tests are outside `app/` and unrestricted) |
| `sqlalchemy`, `asyncpg` | `store`, `wiring`, `main`, `worker`, `cli` |
| `fastapi`, `starlette` | `api`, `main`, `wiring` |
| `jinja2` | `prompts` |
| `yaml` (pyyaml) | `layers` (catalogue loaders), `rag` (corpus frontmatter), `evals`, `cli` |
| `cryptography` | `core` (`app/core/identity.py`) |
| `pgvector` | `store` |
| `structlog` | `core` only. Other code logs through `app.core.logging.get_logger`, so the redaction chain can't be bypassed. `domain`, `layers` and `prompts` don't log at all: the orchestrator records what they did. |

The test has its own tests: `test_layering_detects_violation` builds a fake package tree in
`tmp_path` (`app/domain/x.py` importing `app.store.db`) and asserts the checker reports exactly
that edge. `test_layering_resolves_relative_imports` checks `from ..store import db` inside
`app/domain/` is caught. `test_layering_includes_type_checking_imports` does the same for imports
under `if TYPE_CHECKING:`.

This table is the detailed form of 00-overview.md §5, which was brought in line with it on 2026-10-25.

### 4.13 CI — `.github/workflows/ci.yml`

Triggers: push to `main`, pull requests. Three jobs:

```yaml
jobs:
  check:                       # the verification loop, in order
    runs-on: ubuntu-latest
    env: { HYPOTHESIS_PROFILE: ci }
    steps:
      - uses: actions/checkout@<pinned tag>
      - uses: astral-sh/setup-uv@<pinned tag>
      - run: uv python install 3.13
      - run: uv sync --frozen
      - run: .venv/bin/ruff format --check .
      - run: .venv/bin/ruff check .
      - run: .venv/bin/mypy .
      - run: .venv/bin/pytest

  integration:                 # from S3 onwards, once there's a migration to run
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env: { POSTGRES_USER: marg, POSTGRES_PASSWORD: marg, POSTGRES_DB: marg_test }
        ports: ["55432:5432"]
        options: >-
          --health-cmd "pg_isready -U marg" --health-interval 5s --health-retries 10
    env:
      DATABASE_URL: postgresql+asyncpg://marg:marg@localhost:55432/marg_test
      HYPOTHESIS_PROFILE: ci
    steps:
      - checkout, setup-uv, uv sync --frozen (as above)
      - run: .venv/bin/alembic upgrade head
      - run: .venv/bin/alembic downgrade base
      - run: .venv/bin/alembic upgrade head
      - run: .venv/bin/pytest -m integration

  docker:
    runs-on: ubuntu-latest
    steps:
      - checkout
      - run: docker build -t marg-ai:ci .
```

In S1, the `integration` job runs `pytest -m integration` against the `/readyz` integration test
only. The alembic commands are no-ops until S3 adds a revision, which is fine.

Action versions are pinned to release tags (not `@main`). The workflow never needs secrets.

### 4.14 Docker

```dockerfile
# Dockerfile — one image for api and worker; the command differs
FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:<pinned version> /uv /usr/local/bin/uv
WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
RUN uv sync --frozen --no-dev
RUN useradd --system --uid 10001 marg && chown -R marg /srv
USER marg
EXPOSE 8000
CMD [".venv/bin/uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
```

ffmpeg is installed in S1 even though S6 is its first user. It's part of the base image, so
installing it now keeps image layers stable. S1's exit check confirms `ffmpeg -codecs` lists
`libopus` inside the image.

```yaml
# docker-compose.yml (local development)
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment: { POSTGRES_USER: marg, POSTGRES_PASSWORD: marg, POSTGRES_DB: marg }
    ports: ["5432:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck: { test: ["CMD", "pg_isready", "-U", "marg"], interval: 5s, retries: 10 }
  api:
    build: .
    env_file: .env
    environment:
      DATABASE_URL: postgresql+asyncpg://marg:marg@postgres:5432/marg
    ports: ["8000:8000"]
    depends_on: { postgres: { condition: service_healthy } }
volumes:
  pgdata: {}
```

S4 adds the `worker` service: same image, command `.venv/bin/python -m app.worker`.

```yaml
# docker-compose.test.yml (ephemeral, for integration tests)
services:
  postgres-test:
    image: pgvector/pgvector:pg16
    environment: { POSTGRES_USER: marg, POSTGRES_PASSWORD: marg, POSTGRES_DB: marg_test }
    ports: ["55432:5432"]
    tmpfs: [/var/lib/postgresql/data]
    healthcheck: { test: ["CMD", "pg_isready", "-U", "marg"], interval: 2s, retries: 20 }
```

### 4.15 Commands — `Makefile`

| Target | Runs |
|---|---|
| `make setup` | `uv sync` (creates `.venv`, installs dev group) |
| `make fmt` | `.venv/bin/ruff format .` |
| `make lint` | `.venv/bin/ruff check .` |
| `make type` | `.venv/bin/mypy .` |
| `make test` | `.venv/bin/pytest` |
| `make check` | fmt → lint → type → test, stopping at the first failure (the CLAUDE.md §2 loop) |
| `make test-db-up` / `test-db-down` | `docker compose -f docker-compose.test.yml up -d --wait` / `down -v` |
| `make test-int` | `DATABASE_URL=…55432/marg_test .venv/bin/pytest -m integration` |
| `make up` / `make down` | `docker compose up --build -d` / `docker compose down` |
| `make migrate` | `.venv/bin/alembic upgrade head` against the **local** database only |

There's deliberately no target that migrates a deployed database (CLAUDE.md §8).

### 4.16 `.env.example`

S1 commits only the S1 block. Each later step appends its block, in the same commit as the code
that reads it. Names are exactly those in contracts.md §7. The full file at the end of the build:

```dotenv
# Marg.ai settings. Copy to .env (never committed). Each step adds its own block.
# S1
ENVIRONMENT=local
DATABASE_URL=postgresql+asyncpg://marg:marg@localhost:5432/marg
LOG_LEVEL=INFO
# S3 (identity, WhatsApp)
PUBLIC_BASE_URL=
USER_HASH_SALT=
ADDRESS_ENCRYPTION_KEY=
WHATSAPP_GRAPH_BASE_URL=
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_APP_SECRET=
WHATSAPP_VERIFY_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
WEBHOOK_MAX_BODY_BYTES=5000000
# S4 (turn engine)
TURN_BUDGET_S=25
LEASE_DURATION_S=60
TURN_DEBOUNCE_MS=1000
WORKER_CONCURRENCY=8
MAX_MESSAGES_PER_TURN=5
MAX_TURN_ATTEMPTS=3
STALE_MESSAGE_HOURS=23
RECENT_EXCHANGES=6
OUTBOX_CONCURRENCY=4
OUTBOX_MAX_ATTEMPTS=5
OUTBOX_SENDING_STUCK_S=60
POLL_INTERVAL_S=2
MAINTENANCE_INTERVAL_S=30
SHUTDOWN_GRACE_S=20
PURGE_SWEEP_AFTER_S=600
RETENTION_TURN_TEXT_DAYS=90
RETENTION_RAW_PAYLOAD_DAYS=7
# S5 (models, prompts, safety core)
MODEL_API_BASE_URL=https://api.meta.ai/v1
MODEL_API_KEY=
MODEL_TEXT=muse-spark-1.3
MODEL_AUDIO=muse-spark-1.2
MODEL_JUDGE=muse-spark-1.3
USER_SLOT_MAX_CHARS=4000
PROMPT_CANARY=
SAFETY_BASE_URL=
SAFETY_API_KEY=
SAFETY_MODEL=
# TIMEOUT_<STEP>_S for each StepName, plus TIMEOUT_EMBED_S (defaults in contracts §7)
# S6 (voice)
MODEL_STT=muse-voice-transcribe-1.0
SIDECAR_BASE_URL=
SIDECAR_TOKEN=
STT_FALLBACK_ENABLED=false
MAX_INBOUND_AUDIO_BYTES=5242880
MIN_VOICE_NOTE_MS=700
MIN_VOICED_MS=300
MAX_VOICE_NOTE_SECONDS=180
TRANSCODE_TIMEOUT_S=5
STT_MAX_KEYWORDS=100
TTS_MAX_SENTENCE_CHARS=250
TTS_MAX_SPOKEN_CHARS=1200
REPLY_AUDIO_FOR_TEXT_INPUT=false
# S7 (safety policy)
SAFETY_POLICY_MODEL_ENABLED=true
# S10 / S12 (grounding)
SEARCH_GROUNDING_ENABLED=false
# S10b (parent journey)
NUDGE_TEMPLATE_NAME=
NUDGE_QUIET_START=20:00
NUDGE_QUIET_END=07:00
NUDGE_DAILY_LIMIT=200
ACTIVITY_REPEAT_DAYS=30
# S11 (retrieval)
QUERY_REWRITE_ENABLED=false
RETRIEVAL_TOP_K=5
RETRIEVAL_MIN_SIMILARITY=0.80
# S13 (telemetry)
SESSION_SIGNING_KEY=
SESSION_SIGNING_KEY_PREVIOUS=
DASHBOARD_LINK_TTL_S=900
DASHBOARD_COOKIE_TTL_S=7200
K_ANONYMITY_FLOOR=5
# S14 (web demo)
DAILY_COST_CAP_USD=5
DEMO_RATE_LIMIT_PER_HOUR=30
DEMO_IP_RATE_LIMIT_PER_HOUR=90
DEMO_MAX_AUDIO_BYTES=1000000
DEMO_SSE_MAX_S=600
DEMO_SSE_MAX_CONNECTIONS=200
DEMO_CAPTCHA_ENABLED=false
TURNSTILE_SECRET=
# S15 (evals)
EVAL_DATABASE_ADMIN_URL=
EVAL_CONCURRENCY=4
# S16 (hardening)
CHANNEL_SINK_ENABLED=false
```

The local database URL has no real secret (it's the compose password), so it's given in full.
Every secret has an empty value.

## 5. Interfaces

| Module | Public names |
|---|---|
| `app/core/config.py` | `Settings`, `load_settings() -> Settings` |
| `app/core/errors.py` | every class in contracts.md §4 |
| `app/core/types.py` | `JsonValue` (contracts §2.1) |
| `app/core/logging.py` | `configure_logging(level, *, environment) -> None`, `redact_personal_data` (processor), `get_logger(name: str) -> BoundLogger` |
| `app/core/clock.py` | `SystemClock` |
| `app/providers/ports.py` | `Clock` (Protocol) |
| `app/store/db.py` | `create_engine`, `create_session_factory`, `ping` |
| `app/wiring.py` | `Container`, `build_container`, `close_container` |
| `app/api/health.py` | `router`, `HealthResponse`, `ProbeResult`, `ReadinessResponse`, `ReadinessProbe` |
| `app/api/deps.py` | `get_container` |
| `app/main.py` | `create_app` |
| `tests/fakes/clock.py` | `FixedClock` |

## 6. Data

No tables. Alembic is initialised with an async `env.py` and an empty `versions/` folder.
`alembic.ini` has no URL in it; `env.py` takes it from `load_settings()`.

## 7. Configuration

`ENVIRONMENT`, `DATABASE_URL`, `LOG_LEVEL`. Every other setting in contracts.md §7 is added by
the step that first reads it.

## 8. Failure modes

| Failure | Behaviour |
|---|---|
| A required setting is missing or invalid | Process exits at startup with `ConfigError` listing field names and reasons, no values |
| Database unreachable at startup | The app still starts (liveness ok). `/readyz` returns `503` with `database` failing. The deploy platform won't route traffic to it. |
| Database drops later | `/readyz` flips to `503` within one probe call. `pool_pre_ping` recovers connections when it returns. |
| A probe hangs | Its 2 s timeout turns it into `ok=False, detail="timeout"`. Other probes still report. |
| Something logs a phone number or token | Replaced by the redaction processor before output. Covered by property tests. |

## 9. Tests

**Unit**
- `test_load_settings_reads_environment`: all S1 fields read, with defaults applied.
- `test_load_settings_missing_database_url_names_field`: `pytest.raises(ConfigError, match="DATABASE_URL")`.
- `test_load_settings_invalid_environment_names_field_and_allowed_values`.
- `test_load_settings_rejects_non_asyncpg_scheme`: `postgres://…` → `ConfigError` naming `postgresql+asyncpg`.
- `test_config_error_message_never_contains_secret_value`: an invalid URL with a password in it; the password string is absent from `str(error)`.
- `test_provider_errors_fix_retryability`: `ProviderTimeout(...).retryable is True`, `ProviderRejected(...).retryable is False`; `ProviderRateLimited` keeps `retry_after`.
- `test_system_clock_returns_aware_utc`.
- `test_healthz_returns_ok`: exact body `{"status": "ok"}`.
- `test_readyz_ready_when_all_critical_probes_pass`: `200`, exact body (including `environment`).
- `test_readyz_not_ready_when_database_probe_fails`: `503`, `checks[0] == {"name":"database","ok":false,...}`.
- `test_readyz_probe_timeout_reported_not_raised`: a probe that sleeps past 2 s → `ok=false`, `detail="timeout"`, other probes still present.
- `test_readyz_noncritical_failure_still_ready`: a failing `critical=False` probe → `200`, `ready`, failure listed.
- `test_redaction_denied_keys_nested`: `{"payload": {...}}`, `{"x": [{"phone": "..."}]}`, `{"Authorization": "Bearer abc"}` all redacted.
- `test_redaction_scans_event_message`: `log.info("sending to +919812345678")` → no digits of the number in the output.
- `test_redaction_keeps_user_hash`: a 64-hex `user_hash` value survives unchanged.
- `test_redaction_handles_secretstr`.
- `test_redaction_in_exception_traceback`: an exception message containing a phone number is redacted in `exception` output.
- Layering tests from §4.12, plus the real check: `test_app_respects_layering` over the actual `app/` tree.

**Property** (`@pytest.mark.unit`)
- *Redaction:* for any generated Indian mobile number (`[6-9]\d{9}`, optionally `+91`-prefixed,
  with random spaces or dashes) embedded at a random position in arbitrary text (including
  Devanagari and emoji), the rendered JSON line contains no run of the number's 10 digits.
- *Redaction idempotence:* `redact(redact(event)) == redact(event)`.
- *Redaction never raises:* any JSON-like nested structure (`st.recursive` over dicts, lists,
  strings, ints, None) passes through without an exception, and all non-string, non-denied
  values are unchanged.
- *Layering checker:* for a generated set of `(importer_area, imported_area)` edges written as
  files into `tmp_path`, the checker reports exactly the edges the rules table forbids (checked
  against a direct table lookup, which is a different code path from the AST walk).

**Negative** (covered above): missing, invalid and wrongly-typed settings; probe exceptions and
timeouts; secrets in error messages; personal data in log keys, messages and tracebacks.

**Integration** (`@pytest.mark.integration`)
- `test_readyz_against_real_postgres`: with `docker-compose.test.yml` up, `/readyz` is `200`.
- `test_ping_raises_store_error_on_bad_credentials`: wrong password → `StoreError`, chained.

## 10. Exit check

1. `make check` runs all four stages green, from a clean clone after `make setup`.
2. `make test-db-up && make test-int` passes.
3. `make up`, then `curl -s localhost:8000/healthz` → `{"status":"ok"}` and
   `curl -s -o /dev/null -w '%{http_code}' localhost:8000/readyz` → `200`.
4. `docker compose stop postgres`, then `/readyz` → `503` with `database` failing;
   `docker compose start postgres` → back to `200` without restarting the api.
5. `docker compose run --rm api ffmpeg -hide_banner -codecs | grep -i opus` shows libopus.
6. CI is green on the commit pushed to `main`.
7. Adding `from app.store import db` to a file in `app/domain/` makes `pytest` fail with that
   edge named (then remove it).

## 11. Open questions

| Question | Recommendation |
|---|---|
| ~~Leave mypy's `disallow_any_decorated` off because of FastAPI decorators?~~ | **Resolved:** approved (decision B7). |
| Pin exact versions now, or let `uv.lock` carry them? | Pin with `==` in `pyproject.toml` too, so a reader sees the version without opening the lockfile. |
| Hosting choice (Fly.io or Railway) affects nothing in S1 | Decide in S3, when the webhook needs a public URL. |

## Contract changes (resolved 2026-10-25)

1. **`domain → core.errors`:** applied. 00-overview.md §5 now allows `domain` to import
   `core.errors` and `core.types` only.
2. **Missing areas in 00-overview.md §5, `api → domain`, `api → telemetry`:** applied. The overview
   points to §4.12 here for the full table. `rag` was added to `layers`, and `worker` / `evals` may
   import everything except `api`.
3. **`Clock` created in `app/providers/ports.py` by S1:** applied as written (no shape change).
4. **`pgvector`, `cryptography`:** approved (decision B6), added in S11 and S3. `pyyaml` (+
   `types-PyYAML`) approved as well; `tenacity` dropped.

## Decisions log

| Date | Change | Why | Approved |
|---|---|---|---|
| 2026-10-26 | Ruff ignores `N818`, keeping the contracts.md exception names | N818 conflicted with the contract names | owner |
| 2026-10-26 | Ruff excludes `*.md` | Ruff formats code blocks inside Markdown and rewrapped the design docs | implementation detail, reported to owner |
| 2026-10-26 | `ReadinessProbe` is a small dataclass (`name`, `critical`, `check`), in `app/api/readiness.py` | A timed-out probe must still report its name; also avoids a circular import between `deps` and `health` | implementation detail, reported to owner |
| 2026-10-26 | uvicorn runs with `--no-access-log` | Its access log bypasses redaction and would print query strings such as the WhatsApp verify token | CLAUDE.md §11, reported to owner |
| 2026-10-25 | Dependencies per B6; `disallow_any_decorated=false` per B7; layering table aligned with 00-overview §5; `ENVIRONMENT` adds `staging`; full error hierarchy from contracts §4; `.env.example` lists every setting grouped by step; worker is the `app/worker/` package | Consolidation against the updated foundation docs | owner (defaults B6, B7) |
