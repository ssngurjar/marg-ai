"""Journey test helpers: the shipped catalogue, scripted model outputs, offer records."""

from datetime import date, datetime, timedelta
from functools import cache
from uuid import UUID

from app.domain.enums import ActivityStatus, LearnerRelation
from app.domain.models.activity import Activity, OfferRecord
from app.domain.models.learner import Learner, LearnerId
from app.domain.rules.activity_chooser import ActivityChooser
from app.layers.activity_catalogue import ActivityCatalogue
from tests.support.turn_context import NOW

PERSONALISED_INTRO = "Aaj Munni ke saath ek chhoti khoj!"
REFLECTION_PRAISE = "Munni ne dekha ki parchhai ghoomti hai, bahut dhyan se dekha!"


@cache
def shipped_catalogue() -> ActivityCatalogue:
    return ActivityCatalogue.load()


def child(number: int = 1, nickname: str | None = "Munni", age: int = 5) -> Learner:
    return Learner(
        id=LearnerId(UUID(int=number)),
        relation=LearnerRelation.PARENT,
        nickname=nickname,
        birth_year=NOW.year - age,
        child_talk_consented_at=None,
    )


def first_choice(age: int = 5, today: date | None = None) -> Activity:
    """What ActivityChooser picks for a child with no history."""
    day = today or NOW.date()
    candidates = [a for a in shipped_catalogue().enabled if ActivityChooser.fits(a, age, day)]
    chosen = ActivityChooser.choose(candidates, [], (), day, timedelta(days=30))
    if chosen is None:
        raise AssertionError("the shipped catalogue has an activity for every age 3-8")
    return chosen


def personalisation_for(activity: Activity) -> dict[str, object]:
    """A valid Hinglish activity_personalise answer for `activity` (same step count)."""
    steps = [
        f"Kadam {number}: bachche ke saath dhyan se kariye."
        for number in range(1, len(activity.steps) + 1)
    ]
    return {
        "intro": PERSONALISED_INTRO,
        "steps": steps,
        "questions_to_ask": ["Tumhe kya dikha?", "Tumhe aisa kyon lagta hai?"],
        "listen_for": "Bachche ki apni soch, chahe jawab sahi na ho.",
        "parent_tip": "Sawaal poochkar jawab ka intezaar kijiye.",
        "spoken_text": "आज मुन्नी के साथ एक छोटी खोज। बच्चे के साथ ध्यान से करिए।",
    }


REFLECTION: dict[str, object] = {
    "praise_specific": REFLECTION_PRAISE,
    "next_question": "Kal subah parchhai kahan hogi, Munni se poochiye?",
    "parent_tip": "Bachche ke galat jawab bhi soch ka hissa hain.",
    "summary_for_record": "Munni noticed the shadow moved during the day.",
    "spoken_text": "मुन्नी ने देखा कि परछाई घूमती है। कल सुबह परछाई कहाँ होगी, पूछिए।",
}


def offer(
    activity: Activity,
    learner: Learner,
    *,
    hours_ago: float = 2,
    status: ActivityStatus = ActivityStatus.OFFERED,
    number: int = 50,
) -> OfferRecord:
    return OfferRecord(
        learner_activity_id=UUID(int=number),
        learner_id=learner.id,
        activity_id=activity.id,
        activity_version=activity.version,
        offered_at=NOW - timedelta(hours=hours_ago),
        status=status,
    )


def at_time(day: date) -> datetime:
    return datetime.combine(day, NOW.timetz())


MOMENT_SAY = (
    "Chaand khud nahi chamakta, us par suraj ki roshni padti hai. Roz humein uska alag hissa"
    " roshan dikhta hai."
)
CURIOSITY_MOMENT: dict[str, object] = {
    "is_child_question": True,
    "confident": True,
    "say_to_child": MOMENT_SAY,
    "find_out_together": [
        "Ek steel plate ko aangan ki dhoop mein rakhiye.",
        "Plate ko dheere dheere ghumaiye aur dekhiye roshni kahan padti hai.",
    ],
    "materials_used": ["steel plate"],
    "ask_back": "Aaj raat chaand kaisa dikhega, tumhe kya lagta hai?",
    "who_explores_this": "Jo log chaand-taaron ko samajhte hain unhe khagol-vaigyanik kehte hain.",
    "spoken_text": "चाँद खुद नहीं चमकता, उस पर सूरज की रोशनी पड़ती है। आज रात चाँद कैसा दिखेगा?",
}
NOT_A_CHILD_QUESTION: dict[str, object] = {
    "is_child_question": False,
    "confident": False,
    "say_to_child": "",
    "find_out_together": [],
    "materials_used": [],
    "ask_back": "",
    "who_explores_this": "",
    "spoken_text": "",
}
