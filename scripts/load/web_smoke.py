"""The 10-user smoke test (s16 §4.6, exception E4): concurrent visitors through `/demo`.

Each visitor plays the parent journey a judge would: hello, consent, the parent role, their
child, the first khoj, waiting for every reply before the next message. Afterwards the database
is asked the questions that matter: was any message left without a turn, did any turn go out
twice or stay silent, how long did people wait. The report goes to stdout as markdown.

Run against a server you started (with its own database, never a shared one):
    .venv/bin/python -m scripts.load.web_smoke --target http://127.0.0.1:8013 \\
        --database-url postgresql+asyncpg://...  --users 10
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

import httpx
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

POLL_S: Final = 0.5
TURN_LIMIT_S: Final = 60.0
HTTP_OK: Final = 200
HTTP_ACCEPTED: Final = 202


class _Button(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str


class _Part(BaseModel):
    model_config = ConfigDict(extra="ignore")
    buttons: list[_Button]


class _Turn(BaseModel):
    """The part of `GET /demo/messages/{id}` this test reads."""

    model_config = ConfigDict(extra="ignore")
    status: str
    parts: list[_Part]


class _MessageView(BaseModel):
    model_config = ConfigDict(extra="ignore")
    turn: _Turn | None


@dataclass(frozen=True, slots=True)
class Step:
    text: str | None = None
    button: str | None = None  # an id from the previous reply; a prefix picks the first match


JOURNEY: Final = (
    Step(text="Namaste"),
    Step(button="onb:consent:yes"),
    Step(button="onb:role:parent"),
    Step(text="Meri beti Munni 5 saal ki hai"),
    Step(text="Aaj ki khoj batao"),
)


@dataclass(slots=True)
class VisitorRun:
    visitor: int
    waits_s: list[float] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


class WebSmokeTest:
    def __init__(self, target: str, users: int) -> None:
        self._target = target.rstrip("/")
        self._users = users

    async def run(self) -> list[VisitorRun]:
        return list(await asyncio.gather(*(self._visit(number) for number in range(self._users))))

    async def _visit(self, number: int) -> VisitorRun:
        run = VisitorRun(visitor=number)
        origin = {"origin": self._target}
        async with httpx.AsyncClient(base_url=self._target, timeout=30) as client:
            session = await client.get("/demo/session")
            if session.status_code != HTTP_OK:
                run.problems.append(f"session: http {session.status_code}")
                return run
            offered: list[str] = []
            for step in JOURNEY:
                payload = self._payload(step, offered)
                if payload is None:
                    run.problems.append(f"no button like {step.button!r} was offered")
                    return run
                started = asyncio.get_running_loop().time()
                posted = await client.post("/demo/messages", json=payload, headers=origin)
                if posted.status_code != HTTP_ACCEPTED:
                    run.problems.append(f"post: http {posted.status_code} {posted.text[:80]}")
                    return run
                turn = await self._reply(client, str(posted.json()["message_id"]))
                if turn is None:
                    run.problems.append(f"no reply within {TURN_LIMIT_S:.0f} s")
                    return run
                run.waits_s.append(asyncio.get_running_loop().time() - started)
                offered = [button.id for part in turn.parts for button in part.buttons]
        return run

    @staticmethod
    def _payload(step: Step, offered: Sequence[str]) -> dict[str, str] | None:
        if step.button is None:
            return {"text": step.text or ""}
        match = next((button for button in offered if button.startswith(step.button)), None)
        return {"button_id": match} if match is not None else None

    @staticmethod
    async def _reply(client: httpx.AsyncClient, message_id: str) -> _Turn | None:
        deadline = asyncio.get_running_loop().time() + TURN_LIMIT_S
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(POLL_S)
            response = await client.get(f"/demo/messages/{message_id}")
            turn = _MessageView.model_validate_json(response.content).turn
            if turn is not None and turn.parts and turn.status != "processing":
                return turn
        return None


class SmokeReport:
    """What the database says happened (s16 §4.6 pass criteria), as markdown."""

    @staticmethod
    async def markdown(engine: AsyncEngine, runs: Sequence[VisitorRun]) -> str:
        async with engine.connect() as connection:
            stuck = await _count(
                connection, "SELECT count(*) FROM inbox_messages WHERE status <> 'done'"
            )
            silent = await _count(
                connection,
                "SELECT count(*) FROM turns t WHERE t.status = 'completed' AND NOT EXISTS "
                "(SELECT 1 FROM outbox_messages o WHERE o.turn_id = t.id)",
            )
            doubled = await _count(
                connection,
                "SELECT count(*) FROM (SELECT channel, external_id FROM inbox_messages "
                "GROUP BY channel, external_id HAVING count(*) > 1) AS twice",
            )
            fallbacks = await _count(
                connection,
                "SELECT count(*) FROM turns WHERE fixed_reply_kind IN "
                "('holding', 'try_again_later')",
            )
            turns = await _count(connection, "SELECT count(*) FROM turns")
            cost = (
                await connection.execute(text("SELECT coalesce(sum(cost_usd), 0) FROM turn_steps"))
            ).scalar_one()
            steps = (
                await connection.execute(
                    text(
                        "SELECT step, percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms), "
                        "percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms), count(*) "
                        "FROM turn_steps GROUP BY step ORDER BY 2 DESC"
                    )
                )
            ).all()
        waits = sorted(wait for run in runs for wait in run.waits_s)
        problems = [f"visitor {run.visitor}: {problem}" for run in runs for problem in run.problems]
        lines = [
            f"Visitors: {len(runs)}; replies received: {len(waits)}; turns: {turns}; "
            f"cost ${float(cost):.3f}",
            "",
            "| Criterion | Result | Target |",
            "|---|---|---|",
            f"| Messages never answered | {stuck} | 0 |",
            f"| Completed turns with no reply | {silent} | 0 |",
            f"| Messages stored twice | {doubled} | 0 |",
            f"| Fallback replies (holding, try again) | {fallbacks} of {turns} | ≤ 2% |",
            f"| Wait for a reply, p50 / p95 | {_percentile(waits, 0.5):.1f} s / "
            f"{_percentile(waits, 0.95):.1f} s | ≤ 6 s / ≤ 12 s (text) |",
            f"| Visitor problems | {len(problems)} | 0 |",
            "",
            "| Step | p50 ms | p95 ms | count |",
            "|---|---|---|---|",
            *(f"| {row[0]} | {row[1]:.0f} | {row[2]:.0f} | {row[3]} |" for row in steps),
        ]
        lines.extend(["", *problems] if problems else [])
        return "\n".join(lines) + "\n"


async def _count(connection: AsyncConnection, sql: str) -> int:
    result = await connection.execute(text(sql))
    return int(result.scalar_one())


def _percentile(values: Sequence[float], share: float) -> float:
    if not values:
        return 0.0
    return values[min(round(share * (len(values) - 1)), len(values) - 1)]


async def run_smoke(target: str, database_url: str, users: int) -> int:
    runs = await WebSmokeTest(target, users).run()
    engine = create_async_engine(database_url)
    try:
        report = await SmokeReport.markdown(engine, runs)
    finally:
        await engine.dispose()
    sys.stdout.write(report)
    return 0 if not any(run.problems for run in runs) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="the s16 10-user smoke test through /demo")
    parser.add_argument("--target", required=True)
    parser.add_argument("--database-url", required=True, help="the server's own database")
    parser.add_argument("--users", type=int, default=10)
    arguments = parser.parse_args()
    raise SystemExit(
        asyncio.run(run_smoke(arguments.target, arguments.database_url, arguments.users))
    )


if __name__ == "__main__":
    main()
