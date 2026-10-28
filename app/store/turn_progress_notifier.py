"""TurnProgressNotifier: `NOTIFY turn_progress` with a turn id (s04 §4.6, s14 §4.4).

Sent inside the transaction that changed what a visitor would see (a step recorded, the turn's
text or route set, the turn finalized, a khoj card queued), so it's delivered on commit and
never for a change that rolled back. The api's TurnProgressHub listens and updates the web
visitor's live trace. The payload is only the turn id: no text, no user.
"""

from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.base import TurnId

CHANNEL: Final = "turn_progress"
_NOTIFY: Final = text("SELECT pg_notify('turn_progress', :turn_id)")


class TurnProgressNotifier:
    @staticmethod
    async def notify(session: AsyncSession, turn_id: TurnId) -> None:
        await session.execute(_NOTIFY, {"turn_id": str(turn_id)})
