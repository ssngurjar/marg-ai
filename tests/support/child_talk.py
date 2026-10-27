"""Child-talk test helpers: a consented child, an open session, a scripted child reply."""

from datetime import datetime, timedelta
from uuid import UUID

from app.domain.enums import CuriosityDomain
from app.domain.models.child_session import ChildSession
from app.domain.models.learner import Learner
from app.domain.rules.child_session_rules import ChildSessionLimits
from tests.support.journey import child
from tests.support.turn_context import NOW

LIMITS = ChildSessionLimits(
    max_turns=6, max_duration=timedelta(minutes=10), cooldown=timedelta(minutes=30)
)
SESSION_ID = UUID(int=77)
CHILD_ANSWER = "Chaand khud nahi chamakta. Suraj ki roshni padti hai."
CHILD_REPLY: dict[str, object] = {
    "confident": True,
    "answer": CHILD_ANSWER,
    "find_out": "Thali ko dhoop mein rakho aur dekho.",
    "ask_back": "Aaj raat chaand kaisa dikhega?",
    "who_explores_this": "Taaron ko samajhne waale log khagol-vaigyanik hote hain.",
    "topic": "earth_sky",
    "spoken_text": "चाँद खुद नहीं चमकता। सूरज की रोशनी पड़ती है। आज रात चाँद कैसा दिखेगा?",
}


def consented_child(number: int = 1, nickname: str | None = "Munni", age: int = 5) -> Learner:
    return child(number, nickname, age).model_copy(
        update={"child_talk_consented_at": NOW - timedelta(days=1)}
    )


def open_session(
    learner: Learner,
    *,
    turns: int = 0,
    started: datetime | None = None,
    topics: list[CuriosityDomain] | None = None,
) -> ChildSession:
    return ChildSession(
        id=SESSION_ID,
        learner_id=learner.id,
        started_at=started or NOW - timedelta(minutes=1),
        turns_count=turns,
        topics=topics or [],
    )
