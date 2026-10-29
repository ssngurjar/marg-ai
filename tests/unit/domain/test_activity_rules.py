"""Activity validation, selection, the d7 hazard words and the shipped catalogue (s10b §4.3,
§4.6, §4.10; CLAUDE.md §3 domain/activities)."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from app.constants.child_hazards import CHILD_HAZARD_WORDS, CHILD_SAFE_TOOL_PHRASES
from app.core.errors import CorpusValidationError
from app.domain.enums import ActivityStatus, CuriosityDomain, LearnerRelation
from app.domain.models.activity import Activity, PastActivity
from app.domain.models.learner import Learner, LearnerId
from app.domain.rules.activity_chooser import ActivityChooser
from app.domain.rules.activity_validator import ActivityValidator
from app.domain.rules.child_hazard_matcher import ChildHazardMatcher
from app.domain.rules.learner_chooser import LearnerChooser, RecentOffer
from app.layers.activity_catalogue import ActivityCatalogue

pytestmark = pytest.mark.unit

TODAY = date(2026, 10, 27)  # winter
NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
MATERIALS = frozenset({"stick", "stones", "leaves", "bowl", "water in a bowl"})
HAZARDS = frozenset(CHILD_HAZARD_WORDS)
D = CuriosityDomain


def raw(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "shadow-time", "version": 1, "status": "enabled", "age_min": 4, "age_max": 8,
        "domains": ["earth_sky"], "setting": "outdoors", "season": "any",
        "duration_minutes": 5, "materials": ["stick", "stones"], "title": "Parchhai",
        "steps": ["Push a stick into the ground.", "Mark the shadow with a stone."],
        "questions_to_ask": ["Where did it go?", "Why?"], "listen_for": "Ideas about the sun.",
        "parent_tips": ["Wait for the answer."], "hazards": [], "safety_notes": [],
        "reviewed_by_role": "owner", "reviewed_on": date(2026, 10, 27),
    }  # fmt: skip
    base.update(overrides)
    return base


def validate(data: dict[str, object]) -> Activity:
    return ActivityValidator.validate(
        data, materials=MATERIALS, hazards=HAZARDS, hazard_words=CHILD_HAZARD_WORDS
    )


def activity(
    activity_id: str,
    domains: list[CuriosityDomain],
    *,
    ages: tuple[int, int] = (3, 8),
    season: Literal["any", "summer", "monsoon", "winter"] = "any",
) -> Activity:
    return validate(
        raw(
            id=activity_id,
            domains=[d.value for d in domains],
            age_min=ages[0],
            age_max=ages[1],
            season=season,
        )
    )


# --- validation ----------------------------------------------------------------------------


def test_a_good_activity_validates() -> None:
    assert validate(raw()).id == "shadow-time"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"materials": ["stick", "plastic toy"]}, "materials: not on the list: plastic toy"),
        ({"steps": ["Take the child to the pond."]}, "undeclared hazards: water_body"),
        ({"steps": ["Light a candle and watch."]}, "undeclared hazards: fire"),
        ({"steps": ["Buy some clay from the market."]}, "asks for something to be bought"),
        ({"parent_tips": ["Costs only ₹10."]}, "asks for something to be bought"),
        ({"age_max": 9}, "age_max: above 8"),
        ({"age_min": 2}, "age_min: below 3"),
        ({"age_min": 7, "age_max": 5}, "age_min: greater than age_max"),
        ({"reviewed_by_role": None}, "status: enabled needs reviewed_by_role"),
        ({"hazards": ["water_body"]}, "safety_notes: each declared hazard needs a note"),
        ({"hazards": ["lava"], "safety_notes": ["x"]}, "hazards: not on the list: lava"),
        ({"steps": ["x" * 161]}, "steps: longer than 160"),
    ],
)
def test_each_rule_rejects_naming_the_field(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(CorpusValidationError, match=message):
        validate(raw(**overrides))


@pytest.mark.parametrize("missing", ["steps", "domains", "listen_for", "hazards"])
def test_a_missing_field_is_named(missing: str) -> None:
    data = raw()
    del data[missing]
    with pytest.raises(CorpusValidationError, match=missing):
        validate(data)


def test_an_unknown_key_is_rejected() -> None:
    with pytest.raises(CorpusValidationError, match="price"):
        validate(raw(price=10))


def test_a_declared_hazard_with_a_note_may_be_mentioned() -> None:
    declared = raw(
        steps=["Sit by the village well with your child and listen."],
        hazards=["water_body"],
        safety_notes=["Hold your child's hand; never let them lean over."],
    )
    assert validate(declared).hazards == ["water_body"]


def test_a_draft_needs_no_review() -> None:
    assert validate(raw(status="draft", reviewed_by_role=None, reviewed_on=None)).status == "draft"


# --- the shipped catalogue -------------------------------------------------------------------


def test_the_shipped_catalogue_meets_the_launch_bar() -> None:
    catalogue = ActivityCatalogue.load()
    enabled = catalogue.enabled
    assert len(enabled) >= 7
    domains = {domain for item in enabled for domain in item.domains}
    assert len(domains) >= 6
    assert sum(1 for item in enabled if item.setting in {"home", "kitchen"}) >= 3
    assert all(item.age_min >= 3 and item.age_max <= 8 for item in enabled)


def test_a_broken_catalogue_file_stops_startup(tmp_path: Path) -> None:
    directory = tmp_path
    source = ActivityCatalogue.load().activities[0]
    shipped = Path("content/activities")
    for name in ("_materials.yaml", "_hazards.yaml"):
        (directory / name).write_text((shipped / name).read_text())
    (directory / f"{source.id}.yaml").write_text(
        (shipped / f"{source.id}.yaml").read_text().replace("status: enabled", "status: maybe")
    )
    with pytest.raises(CorpusValidationError, match=f"{source.id}.yaml"):
        ActivityCatalogue.load(directory)


# --- selection -----------------------------------------------------------------------------


def past(activity_id: str, domains: list[CuriosityDomain], days_ago: int) -> PastActivity:
    return PastActivity(
        activity_id=activity_id,
        domains=domains,
        offered_at=NOW - timedelta(days=days_ago),
        status=ActivityStatus.DONE,
    )


WINDOW = timedelta(days=30)


def test_season_of_each_month() -> None:
    seasons = [ActivityChooser.season_of(date(2026, month, 1)) for month in range(1, 13)]
    assert seasons == [
        "winter", "winter", "summer", "summer", "summer", "summer",
        "monsoon", "monsoon", "monsoon", "winter", "winter", "winter",
    ]  # fmt: skip


def test_a_recent_activity_is_not_repeated() -> None:
    a = activity("a-one", [D.EARTH_SKY])
    b = activity("b-two", [D.EARTH_SKY])
    chosen = ActivityChooser.choose([a, b], [past("a-one", [D.EARTH_SKY], 3)], (), TODAY, WINDOW)
    assert chosen == b


def test_rotation_prefers_a_domain_the_child_hasnt_had() -> None:
    sky = activity("a-sky", [D.EARTH_SKY])
    words = activity("b-words", [D.WORDS_STORIES])
    history = [past("x", [D.EARTH_SKY], 1)]
    assert ActivityChooser.choose([sky, words], history, (), TODAY, WINDOW) == words


def test_when_everything_is_recent_the_oldest_offered_comes_back() -> None:
    a = activity("a-one", [D.EARTH_SKY])
    b = activity("b-two", [D.WORDS_STORIES])
    history = [past("b-two", [D.WORDS_STORIES], 1), past("a-one", [D.EARTH_SKY], 5)]
    assert ActivityChooser.choose([a, b], history, (), TODAY, WINDOW) == a


def test_no_candidates_means_none() -> None:
    assert ActivityChooser.choose([], [], (), TODAY, WINDOW) is None


@pytest.mark.parametrize(("age", "fits"), [(3, False), (4, True), (8, True), (9, False)])
def test_fits_the_age_range(age: int, *, fits: bool) -> None:
    assert ActivityChooser.fits(activity("a", [D.EARTH_SKY], ages=(4, 8)), age, TODAY) is fits


def test_an_out_of_season_activity_doesnt_fit() -> None:
    monsoon = activity("rain-walk", [D.EARTH_SKY], season="monsoon")
    assert not ActivityChooser.fits(monsoon, 5, TODAY)


CATALOGUE = ActivityCatalogue.load().enabled
IDS = [item.id for item in CATALOGUE]


@settings(max_examples=200)
@given(
    offered=st.lists(st.tuples(st.sampled_from(IDS), st.integers(0, 60)), max_size=12),
    age=st.integers(3, 8),
)
def test_selection_never_breaks_age_or_the_repeat_window_and_is_deterministic(
    offered: list[tuple[str, int]], age: int
) -> None:
    by_id = {item.id: item for item in CATALOGUE}
    history = sorted(
        (past(item_id, by_id[item_id].domains, days) for item_id, days in offered),
        key=lambda item: item.offered_at,
        reverse=True,
    )
    candidates = [item for item in CATALOGUE if ActivityChooser.fits(item, age, TODAY)]
    chosen = ActivityChooser.choose(candidates, history, (), TODAY, WINDOW)
    assert chosen == ActivityChooser.choose(candidates, history, (), TODAY, WINDOW)
    if not candidates:
        assert chosen is None
        return
    assert chosen is not None
    assert chosen.age_min <= age <= chosen.age_max
    recent = {item.activity_id for item in history if item.offered_at.date() > TODAY - WINDOW}
    if any(item.id not in recent for item in candidates):
        assert chosen.id not in recent


def test_a_daily_khoj_covers_every_domain_the_catalogue_has() -> None:
    """Breadth by construction: as many days as activities, every domain at least once."""
    candidates = [item for item in CATALOGUE if ActivityChooser.fits(item, 5, TODAY)]
    history: list[PastActivity] = []
    seen: set[CuriosityDomain] = set()
    for day in range(len(candidates)):
        today = TODAY + timedelta(days=day)
        chosen = ActivityChooser.choose(candidates, history, (), today, WINDOW)
        assert chosen is not None
        seen.update(chosen.domains)
        history.insert(
            0,
            PastActivity(
                activity_id=chosen.id,
                domains=chosen.domains,
                offered_at=datetime.combine(today, datetime.min.time(), UTC),
                status=ActivityStatus.OFFERED,
            ),
        )
    assert seen == {domain for item in candidates for domain in item.domains}


# --- d7 hazard words -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "hazard"),
    [
        ("Take her near the pond", "water_body"), ("talab ke paas jaiye", "water_body"),
        ("बच्चे को आग के पास मत ले जाइए", "fire"), ("use a sharp knife", "sharp_tool"),
        ("Climb the tree together", "height"), ("dawai de dijiye", "medicine"),
        ("Cross the road to the shop", "road"),
    ],
)  # fmt: skip
def test_hazard_words_are_found(text: str, hazard: str) -> None:
    assert hazard in ChildHazardMatcher.find(text, CHILD_HAZARD_WORDS)


@pytest.mark.parametrize(
    "text", ["Mix the dough well", "Sit in a sunny spot", "Ask a question", "Diesel ka daam"]
)
def test_ordinary_words_are_not_hazards(text: str) -> None:
    assert ChildHazardMatcher.find(text, CHILD_HAZARD_WORDS) == frozenset()


HAZARD_PHRASES = [
    (kind, phrase) for kind, phrases in CHILD_HAZARD_WORDS.items() for phrase in phrases
]


@given(
    pair=st.sampled_from(HAZARD_PHRASES),
    prefix=st.sampled_from(["", "Aaj ", "बच्चे के साथ ", "Please "]),
    suffix=st.sampled_from(["", " ke paas", " today.", "!", " 😊"]),
)
@example(pair=("water_body", "kuan"), prefix="", suffix="")
def test_a_hazard_found_alone_is_found_in_any_context(
    pair: tuple[str, str], prefix: str, suffix: str
) -> None:
    kind, phrase = pair
    assert kind in ChildHazardMatcher.find(f"{prefix}{phrase}{suffix}", CHILD_HAZARD_WORDS)


@pytest.mark.parametrize(
    "text",
    [
        "Gol nok wali kainchi se kaagaz kaato", "Cut paper with round-tip scissors",
        "बच्चों वाली कैंची से कागज़ काटो", "Use children's scissors with Mummy",
    ],
)  # fmt: skip
def test_a_child_safe_tool_is_not_a_hazard(text: str) -> None:
    assert ChildHazardMatcher.find(text, CHILD_HAZARD_WORDS, CHILD_SAFE_TOOL_PHRASES) == frozenset()


def test_a_safe_tool_masks_only_itself() -> None:
    text = "Gol nok wali kainchi se kaagaz kaato, chaaku se nahi"
    found = ChildHazardMatcher.find(text, CHILD_HAZARD_WORDS, CHILD_SAFE_TOOL_PHRASES)
    assert found == frozenset({"sharp_tool"})  # the chaaku still counts


def test_plain_scissors_are_still_a_hazard() -> None:
    found = ChildHazardMatcher.find("Kainchi se kaato", CHILD_HAZARD_WORDS, CHILD_SAFE_TOOL_PHRASES)
    assert found == frozenset({"sharp_tool"})


@given(
    safe=st.sampled_from(CHILD_SAFE_TOOL_PHRASES),
    other=st.text(alphabet="abcdefghijklmnopqrstuvwxyz अआकखगचजटतदनपमरलवसह😊", max_size=60),
)
@example(safe="gol nok wali kainchi", other="kainchi")
@example(safe="round-tip scissors", other="gol nok ki kainchi")  # `other` is a safe phrase too
def test_masking_safe_tools_never_adds_a_hazard(safe: str, other: str) -> None:
    text = f"{other} {safe} {other}"
    masked = ChildHazardMatcher.find(text, CHILD_HAZARD_WORDS, CHILD_SAFE_TOOL_PHRASES)
    assert masked <= ChildHazardMatcher.find(text, CHILD_HAZARD_WORDS)
    around = ChildHazardMatcher.find(
        f"{other} {other}", CHILD_HAZARD_WORDS, CHILD_SAFE_TOOL_PHRASES
    )
    assert masked == around


@pytest.mark.parametrize(
    ("spoken", "written", "expected"),
    [
        ("साँप के कान नहीं होते", "Saanp ke kaan nahi hote", frozenset()),
        ("पत्ते गिनो, फिर नदी पर चलो", "Patte gino", frozenset({"water_body"})),
        ("गोल नोक वाली कैंची से काटो", "Gol nok wali kainchi se kaato", frozenset()),
    ],
)
def test_spoken_only_finds_a_hazard_the_written_text_lacks(
    spoken: str, written: str, expected: frozenset[str]
) -> None:
    found = ChildHazardMatcher.spoken_only(
        spoken, written, CHILD_HAZARD_WORDS, CHILD_SAFE_TOOL_PHRASES
    )
    assert found == expected


# --- choosing the child ----------------------------------------------------------------------


def child(number: int, nickname: str | None) -> Learner:
    return Learner(
        id=LearnerId(UUID(int=number)),
        relation=LearnerRelation.PARENT,
        nickname=nickname,
        birth_year=2021,
        child_talk_consented_at=None,
    )


MUNNI, GOLU = child(1, "Munni"), child(2, "Golu")


def test_a_button_naming_a_child_wins() -> None:
    chosen = LearnerChooser.choose([MUNNI, GOLU], str(GOLU.id), "Munni ne kaha", [], NOW)
    assert chosen == GOLU


def test_a_nickname_in_the_message_picks_that_child() -> None:
    assert LearnerChooser.choose([MUNNI, GOLU], None, "aaj Munni ne patte gine", [], NOW) == MUNNI


def test_otherwise_the_child_of_the_latest_recent_offer() -> None:
    offers = [
        RecentOffer(MUNNI.id, NOW - timedelta(hours=30)),
        RecentOffer(GOLU.id, NOW - timedelta(hours=2)),
    ]
    assert LearnerChooser.choose([MUNNI, GOLU], None, "ho gaya", offers, NOW) == GOLU


def test_an_offer_older_than_48_hours_doesnt_count() -> None:
    offers = [RecentOffer(GOLU.id, NOW - timedelta(hours=49))]
    assert LearnerChooser.choose([MUNNI, GOLU], None, "ho gaya", offers, NOW) is None


def test_the_only_child_is_chosen_and_several_without_a_signal_ask() -> None:
    assert LearnerChooser.choose([MUNNI], None, "hello", [], NOW) == MUNNI
    assert LearnerChooser.choose([MUNNI, GOLU], None, "hello", [], NOW) is None


def test_a_button_for_someone_elses_child_is_ignored() -> None:
    stranger = str(UUID(int=99))
    assert LearnerChooser.choose([MUNNI], stranger, "", [], NOW) == MUNNI


# --- what a photo counts (s10b §4.14; owner, 2026-10-28) -----------------------------------------


@pytest.mark.parametrize("phrases", [[], ["leaf"], ["stone", "leaf", "bottle cap"]])
def test_count_phrases_are_optional_singular_lowercase_nouns(phrases: list[str]) -> None:
    assert validate(raw(photo_count_phrases=phrases)).photo_count_phrases == phrases


def test_an_activity_without_count_phrases_counts_nothing() -> None:
    data = raw()
    data.pop("photo_count_phrases", None)
    assert validate(data).photo_count_phrases == []


@pytest.mark.parametrize(
    "phrases",
    [["Leaf"], ["leaves!"], ["a big round flat stone"], [""], ["leaf", "stone", "twig", "seed"]],
    ids=["capitalised", "punctuation", "four_words", "empty", "four_phrases"],
)
def test_a_count_phrase_sam_cant_take_is_rejected(phrases: list[str]) -> None:
    with pytest.raises(CorpusValidationError, match="photo_count_phrases"):
        validate(raw(photo_count_phrases=phrases))


def test_the_shipped_count_phrases_are_the_reviewed_ones() -> None:
    catalogue = {
        activity.id: activity.photo_count_phrases for activity in ActivityCatalogue.load().enabled
    }
    assert catalogue["leaf-families"] == ["leaf"]
    assert catalogue["stone-tower"] == ["stone"]
    assert catalogue["sink-or-float"] == ["stone", "leaf", "bottle cap"]
    assert catalogue["shadow-time"] == ["stone"]
    assert catalogue["yesterday-story"] == []


def test_undeclared_words_name_each_word_once_in_list_order() -> None:
    text = "Frogs live near the pond and the river; the pond is cool. Mind the knife."
    words = ChildHazardMatcher.undeclared_words(text, CHILD_HAZARD_WORDS, ())
    assert words == ["pond", "river", "knife"]
    assert ChildHazardMatcher.undeclared_words(text, CHILD_HAZARD_WORDS, ("water_body",)) == [
        "knife"
    ]
    assert ChildHazardMatcher.undeclared_words("Look at the leaves.", CHILD_HAZARD_WORDS, ()) == []
