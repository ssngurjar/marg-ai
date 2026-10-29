"""JourneyLayer: today's khoj, another khoj, report back, which child, parent questions
(s10b §4.4 to §4.9, §4.10 supervision line)."""

from datetime import time, timedelta

import pytest

from app.constants.journey_copy import (
    ADD_CHILD_PROMPT,
    AGE_COMING_SOON,
    KHOJ_DONE,
    KHOJ_OTHER,
    KHOJ_STILL_OPEN,
    KHOJ_TODAY,
    NUDGE_ASK,
    NUDGE_OFF_REPLY,
    REFLECTION_FALLBACK,
    SUPERVISION_LINE,
    WHICH_CHILD,
)
from app.core.errors import ProviderError, ProviderResponseInvalid, ProviderUnavailable
from app.domain.enums import ActivityStatus, Language, StepOutcome
from app.domain.models.activity import OfferRecord
from app.domain.models.learner import Learner
from app.domain.models.photo import ObjectCount, PhotoFindings
from app.domain.models.writes import ActivityOffered, ActivityReported, NudgePreference
from app.layers.activity_catalogue import CatalogueActivitySource
from app.layers.journey_layer import (
    ActivityPersonalisation,
    JourneyLayer,
    JourneySettings,
    ParentMessage,
    ParentReflection,
    _KhojChecks,
    _ReflectionChecks,
)
from app.layers.layer_result import LayerResult
from app.layers.parent_question_layer import ParentQuestionLayer
from tests.fakes.language_model import FakeLanguageModel, PromptRoutedLanguageModel, ScriptedOutput
from tests.support.child_talk import consented_child
from tests.support.journey import (
    CURIOSITY_MOMENT,
    MOMENT_SAY,
    NOT_A_CHILD_QUESTION,
    PERSONALISED_INTRO,
    REFLECTION,
    REFLECTION_PRAISE,
    child,
    first_choice,
    offer,
    personalisation_for,
    shipped_catalogue,
)
from tests.support.parent_answers import HINGLISH_ANSWER
from tests.support.prompts import shipped_registry
from tests.support.turn_context import NOW, button_reply, text_message, turn_context

pytestmark = pytest.mark.unit

H = Language.HINGLISH
MUNNI = child()
FIRST = first_choice()


def layer_with(
    personalise: ScriptedOutput | None = None,
    reflect: ScriptedOutput = REFLECTION,
    answer: ScriptedOutput = HINGLISH_ANSWER,
    curiosity: ScriptedOutput = CURIOSITY_MOMENT,
    *,
    intent: ScriptedOutput | None = None,
) -> tuple[JourneyLayer, PromptRoutedLanguageModel]:
    """`intent`: turns intent reading on, with this as Muse Spark's reading."""
    llm = PromptRoutedLanguageModel(
        {
            "activity_personalise": FakeLanguageModel([personalise or personalisation_for(FIRST)]),
            "parent_reflection": FakeLanguageModel([reflect]),
            "parent_answer": FakeLanguageModel([answer]),
            "curiosity_moment": FakeLanguageModel([curiosity]),
            "parent_intent": FakeLanguageModel([intent or {"intent": "question"}]),
        }
    )
    registry = shipped_registry()
    layer = JourneyLayer(
        llm,
        registry,
        CatalogueActivitySource(shipped_catalogue()),
        ParentQuestionLayer(llm, registry),
        JourneySettings(repeat_window=timedelta(days=30), read_intent=intent is not None),
    )
    return layer, llm


async def khoj(
    *,
    learners: list[Learner] | None = None,
    text: str = "",
    button: str | None = KHOJ_TODAY,
    open_activity: OfferRecord | None = None,
    layer: JourneyLayer | None = None,
) -> LayerResult:
    journey = layer or layer_with()[0]
    message = button_reply(button) if button else text_message(text)
    ctx = turn_context(message, learners=learners or [MUNNI], open_activity=open_activity)
    ids = [button] if button else []
    return await journey.handle(ctx, ParentMessage(text, ids), NOW, H)


def offered(result: LayerResult) -> ActivityOffered:
    [write] = [write for write in result.writes if isinstance(write, ActivityOffered)]
    return write


# --- A: today's khoj -------------------------------------------------------------------------


async def test_todays_khoj_is_the_chosen_activity_personalised_with_the_supervision_line() -> None:
    result = await khoj()
    assert result.outcome is StepOutcome.OK
    assert result.reply.body.startswith(PERSONALISED_INTRO)
    assert result.reply.body.endswith(SUPERVISION_LINE[H])
    assert result.reply.spoken_text is not None
    assert result.reply.spoken_text.endswith(SUPERVISION_LINE[H])
    assert [button.id for button in result.reply.buttons] == [KHOJ_DONE, KHOJ_OTHER]
    assert offered(result).activity_id == FIRST.id
    assert offered(result).learner_id == MUNNI.id
    assert result.hazard_rule == frozenset(FIRST.hazards)
    assert result.prompt_versions == {"activity_personalise": "1.0.5"}


async def test_the_reviewed_text_is_kept_as_the_fallback_reply() -> None:
    result = await khoj()
    assert result.fallback_reply is not None
    assert FIRST.steps[0] in result.fallback_reply.body
    assert result.fallback_reply.body.endswith(SUPERVISION_LINE[H])


@pytest.mark.parametrize("text", ["aaj ki khoj", "Aaj ki KHOJ bhejo", "आज की खोज"])
async def test_asking_for_a_khoj_in_words_works_like_the_button(text: str) -> None:
    result = await khoj(text=text, button=None)
    assert offered(result).activity_id == FIRST.id


async def test_the_model_sees_the_childs_name_only_in_a_user_slot() -> None:
    layer, llm = layer_with()
    await khoj(layer=layer)
    prompt = llm.by_prompt["activity_personalise"].prompts[0]
    assert "Munni" not in prompt.system
    assert "<child>\nMunni\n</child>" in prompt.user


@pytest.mark.parametrize(
    "failure",
    [
        ProviderResponseInvalid("failed after repair", provider="meta_model_api", retryable=False),
        ProviderUnavailable("503", provider="meta_model_api"),
    ],
    ids=["checks-failed", "model-down"],
)
async def test_if_personalising_fails_the_reviewed_text_is_sent(failure: ProviderError) -> None:
    layer, _ = layer_with(personalise=failure)
    result = await khoj(layer=layer)
    assert result.outcome is StepOutcome.DEGRADED
    assert result.degraded_reason == f"catalogue_fallback={type(failure).__name__}"
    assert FIRST.steps[0] in result.reply.body
    assert result.reply.body.endswith(SUPERVISION_LINE[H])
    assert result.fallback_reply is None
    assert offered(result).activity_id == FIRST.id


async def test_with_several_children_and_no_signal_it_asks_which_child() -> None:
    golu = child(2, None, age=4)
    result = await khoj(learners=[MUNNI, golu])
    assert result.reply.body == WHICH_CHILD[H]
    assert [button.id for button in result.reply.buttons] == [
        f"{KHOJ_TODAY}:{MUNNI.id}",
        f"{KHOJ_TODAY}:{golu.id}",
    ]
    assert [button.title for button in result.reply.buttons] == ["Munni", "4 saal ka bachcha"]
    assert result.writes == []


@pytest.mark.parametrize("age", [1, 2, 9, 12])
async def test_a_child_outside_3_to_8_gets_coming_soon(age: int) -> None:
    result = await khoj(learners=[child(age=age)])
    assert result.reply.body == AGE_COMING_SOON[H]
    assert result.writes == []


# --- C: another khoj -------------------------------------------------------------------------


async def test_another_khoj_skips_the_open_one_and_offers_a_different_activity() -> None:
    open_one = offer(FIRST, MUNNI)
    result = await khoj(button=KHOJ_OTHER, open_activity=open_one, layer=layer_for_any())
    skipped, new = result.writes
    assert skipped == ActivityReported(
        learner_activity_id=open_one.learner_activity_id,
        status=ActivityStatus.SKIPPED,
        summary=None,
    )
    assert isinstance(new, ActivityOffered)
    assert new.activity_id != FIRST.id


def layer_for_any() -> JourneyLayer:
    """A layer whose personalisation always fails, so any chosen activity's text is used."""
    layer, _ = layer_with(
        personalise=ProviderResponseInvalid("x", provider="meta_model_api", retryable=False)
    )
    return layer


# --- B: report back ----------------------------------------------------------------------


async def test_a_report_gets_a_specific_reflection_and_is_recorded_done() -> None:
    open_one = offer(FIRST, MUNNI)
    result = await khoj(
        text="Munni ne kaha parchhai suraj ki wajah se ghoomti hai",
        button=None,
        open_activity=open_one,
    )
    assert result.reply.body.startswith(REFLECTION_PRAISE)
    assert result.writes == [
        ActivityReported(
            learner_activity_id=open_one.learner_activity_id,
            status=ActivityStatus.DONE,
            summary="Munni noticed the shadow moved during the day.",
        )
    ]
    assert [button.id for button in result.reply.buttons] == ["jrn:today", "onb:add-child"]
    assert result.prompt_versions == {"parent_reflection": "1.2.2"}


async def test_done_button_with_an_open_activity_reflects() -> None:
    result = await khoj(button=KHOJ_DONE, open_activity=offer(FIRST, MUNNI))
    assert result.reply.body.startswith(REFLECTION_PRAISE)


async def test_if_the_reflection_fails_a_warm_fixed_reply_and_the_first_question_go() -> None:
    open_one = offer(FIRST, MUNNI)
    layer, _ = layer_with(reflect=ProviderUnavailable("503", provider="baseten"))
    result = await khoj(
        text="usne kuch nahi kiya", button=None, open_activity=open_one, layer=layer
    )
    assert result.reply.body == f"{REFLECTION_FALLBACK[H]}\n{FIRST.questions_to_ask[0]}"
    assert result.outcome is StepOutcome.DEGRADED
    assert result.degraded_reason == "reflection_failed=ProviderUnavailable"
    assert result.writes == [
        ActivityReported(
            learner_activity_id=open_one.learner_activity_id,
            status=ActivityStatus.DONE,
            summary=None,
        )
    ]


async def test_done_with_nothing_open_offers_todays_khoj() -> None:
    result = await khoj(button=KHOJ_DONE)
    assert offered(result).activity_id == FIRST.id


async def test_an_open_activity_no_longer_in_the_catalogue_is_treated_as_none() -> None:
    gone = offer(FIRST, MUNNI).model_copy(update={"activity_id": "retired-one"})
    result = await khoj(text="bachcha khana nahi khata", button=None, open_activity=gone)
    assert result.reply.body.startswith(str(HINGLISH_ANSWER["answer"]))


# --- D: parent questions -------------------------------------------------------------------


async def test_a_question_with_nothing_open_gets_the_parent_answer_with_the_hazard_rule_on() -> (
    None
):
    result = await khoj(text="Beta khana nahi khata, kya karein?", button=None)
    assert result.reply.body.startswith(str(HINGLISH_ANSWER["answer"]))
    assert result.hazard_rule == frozenset()
    assert result.writes == []


# --- the curiosity moment (C11) -------------------------------------------------------------

RELAYED = "Munni poochh rahi hai, chaand roz shape kyun badalta hai?"


async def test_a_relayed_child_question_gets_the_curiosity_moment() -> None:
    layer, llm = layer_with()
    result = await khoj(text=RELAYED, button=None, layer=layer)
    assert result.reply.body.startswith(MOMENT_SAY)
    assert result.prompt_versions == {"curiosity_moment": "1.0.5"}
    assert llm.by_prompt["parent_answer"].prompts == []
    assert result.writes == []


async def test_the_parents_own_question_falls_through_to_the_parent_answer_with_both_costs() -> (
    None
):
    layer, _ = layer_with(curiosity=NOT_A_CHILD_QUESTION)
    result = await khoj(
        text="Munni ki neend poori nahi hoti, kya karein?", button=None, layer=layer
    )
    assert result.reply.body.startswith(str(HINGLISH_ANSWER["answer"]))
    assert result.prompt_versions == {"curiosity_moment": "1.0.5", "parent_answer": "1.0.2"}
    assert len(result.usages) == 2
    assert result.hazard_rule == frozenset()


async def test_a_parent_question_without_the_childs_question_never_asks_the_curiosity_prompt() -> (
    None
):
    layer, llm = layer_with()
    await khoj(text="Beta khana nahi khata, kya karein?", button=None, layer=layer)
    assert llm.by_prompt["curiosity_moment"].prompts == []


async def test_with_a_khoj_open_the_childs_words_are_a_report_first() -> None:
    layer, llm = layer_with()
    result = await khoj(text=RELAYED, button=None, open_activity=offer(FIRST, MUNNI), layer=layer)
    assert result.reply.body.startswith(REFLECTION_PRAISE)
    assert llm.by_prompt["curiosity_moment"].prompts == []


# --- the checks on model text --------------------------------------------------------------


def personalisation(**changes: object) -> ActivityPersonalisation:
    return ActivityPersonalisation.model_validate({**personalisation_for(FIRST), **changes})


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        ({"steps": ["Ek hi kadam."]}, f"steps: expected exactly {len(FIRST.steps)} steps"),
        (
            {"intro": "Aaj talab ke paas chaliye!"},
            "text: mentions a danger the activity doesn't include",
        ),
        (
            {"parent_tip": "Munni bada hokar doctor ban jaayegi!"},
            "text: mentions careers, jobs or exams",
        ),
        ({"intro": "Munni toh genius hai!"}, "text: labels the child"),
        ({"listen_for": "Dukaan se khilona kharidiye."}, "text: asks for something to be bought"),
        (
            {"intro": "आज मुन्नी के साथ एक खोज!", "listen_for": "बच्चे की अपनी सोच।"},
            "text: expected Roman script",
        ),
        ({"spoken_text": "Aaj ek khoj."}, "spoken_text: expected Devanagari script"),
    ],
)
def test_the_personalisation_checks_catch_each_problem(
    changes: dict[str, object], problem: str
) -> None:
    assert problem in _KhojChecks.problems(personalisation(**changes), FIRST, H)


def test_a_good_personalisation_has_no_problems() -> None:
    assert _KhojChecks.problems(personalisation(), FIRST, H) == []


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        ({"praise_specific": "Munni bahut naughty hai par accha kiya."}, "text: labels the child"),
        ({"parent_tip": "Aage chalkar engineer banegi."}, "text: mentions careers, jobs or exams"),
    ],
)
def test_the_reflection_checks_catch_labels_and_careers(
    changes: dict[str, object], problem: str
) -> None:
    reflection = ParentReflection.model_validate({**REFLECTION, **changes})
    assert problem in _ReflectionChecks.problems(reflection, H, ())


def test_a_reflection_naming_an_undeclared_hazard_gets_a_repair_turn_naming_the_word() -> None:
    # owner's judge walkthrough (2026-10-29): "frogs live near the pond" reached safety_out,
    # was blocked by d7, and the parent got "couldn't answer"
    reflection = ParentReflection.model_validate(
        {**REFLECTION, "parent_tip": "Frogs live near the pond, so they jump."}
    )
    problems = _ReflectionChecks.problems(reflection, H, ())
    assert any('"pond"' in problem and "without them" in problem for problem in problems)
    assert not any("pond" in p for p in _ReflectionChecks.problems(reflection, H, ("water_body",)))


def test_a_good_reflection_has_no_hazard_problem() -> None:
    reflection = ParentReflection.model_validate(REFLECTION)
    assert _ReflectionChecks.problems(reflection, H, ()) == []


# --- the "Main bachcha hoon" button (C13) ------------------------------------------------------


async def test_a_khoj_for_a_child_with_talk_switched_on_offers_the_childs_button() -> None:
    talker = consented_child()
    result = await khoj(learners=[talker])
    assert [button.id for button in result.reply.buttons] == [
        KHOJ_DONE,
        KHOJ_OTHER,
        f"kid:start:{talker.id}",
    ]
    assert result.fallback_reply is not None
    assert result.fallback_reply.buttons[-1].id == f"kid:start:{talker.id}"


async def test_without_consent_there_is_no_childs_button() -> None:
    result = await khoj()
    assert all(not button.id.startswith("kid:") for button in result.reply.buttons)


async def test_with_child_talk_switched_off_there_is_no_childs_button() -> None:
    llm = PromptRoutedLanguageModel(
        {"activity_personalise": FakeLanguageModel([personalisation_for(FIRST)])}
    )
    registry = shipped_registry()
    layer = JourneyLayer(
        llm,
        registry,
        CatalogueActivitySource(shipped_catalogue()),
        ParentQuestionLayer(llm, registry),
        JourneySettings(repeat_window=timedelta(days=30), child_talk_enabled=False),
    )
    result = await khoj(learners=[consented_child()], layer=layer)
    assert all(not button.id.startswith("kid:") for button in result.reply.buttons)


async def test_after_a_report_the_child_can_start_talking() -> None:
    talker = consented_child()
    result = await khoj(
        text="Munni ne parchhai dekhi",
        button=None,
        learners=[talker],
        open_activity=offer(FIRST, talker),
    )
    assert result.reply.buttons[-1].id == f"kid:start:{talker.id}"


# --- E: the daily khoj message ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("button", "hour", "said"), [("nudge:08", 8, "subah 8"), ("nudge:18", 18, "shaam 6")]
)
async def test_choosing_a_time_turns_the_daily_message_on(
    button: str, hour: int, said: str
) -> None:
    layer, llm = layer_with()
    result = await khoj(button=button, layer=layer)
    assert result.writes == [NudgePreference(enabled=True, local_time=time(hour, 0))]
    assert f"Roz {said} baje" in result.reply.body
    assert llm.by_prompt["activity_personalise"].prompts == []


@pytest.mark.parametrize(
    ("text", "button"),
    [("", "nudge:off"), ("roz ka message band karo", None), ("message mat bhejo", None)],
)
async def test_turning_the_daily_message_off(text: str, button: str | None) -> None:
    result = await khoj(text=text, button=button)
    assert result.writes == [NudgePreference(enabled=False, local_time=None)]
    assert result.reply.body == NUDGE_OFF_REPLY[H]


@pytest.mark.parametrize("text", ["time badlo", "समय बदलो", "change the time"])
async def test_asking_to_change_the_time_offers_the_choice_again(text: str) -> None:
    result = await khoj(text=text, button=None)
    assert result.reply.body == NUDGE_ASK[H]
    assert [button.id for button in result.reply.buttons] == ["nudge:08", "nudge:18", "nudge:off"]
    assert result.writes == []


async def test_stop_alone_is_neither_deletion_nor_turning_off() -> None:
    result = await khoj(text="stop", button=None)
    assert not any(isinstance(write, NudgePreference) for write in result.writes)


# --- a photo of the child's work (s10b §4.14) ----------------------------------------------------

STONES = PhotoFindings(counts=[ObjectCount(phrase="stone", count=5)])


def test_photo_phrases_are_the_open_activitys_or_none_when_nothing_is_open() -> None:
    layer, _ = layer_with()
    tower = next(item for item in shipped_catalogue().enabled if item.id == "stone-tower")
    open_ctx = turn_context(learners=[MUNNI], open_activity=offer(tower, MUNNI))
    assert layer.photo_phrases(open_ctx) == ["stone"]
    assert layer.photo_phrases(turn_context(learners=[MUNNI])) is None


async def test_a_photo_alone_is_a_report_and_its_counts_reach_the_prompt_and_the_record() -> None:
    open_one = offer(FIRST, MUNNI)
    layer, llm = layer_with()
    ctx = turn_context(learners=[MUNNI], open_activity=open_one)
    result = await layer.handle(ctx, ParentMessage("", [], STONES), NOW, H)
    assert result.reply.body.startswith(REFLECTION_PRAISE)
    [prompt] = llm.by_prompt["parent_reflection"].prompts
    assert "a counting\nmodel found: 5 stone." in prompt.system
    assert "Ho gaya" in prompt.user  # a photo without words reports "done"
    [report] = result.writes
    assert isinstance(report, ActivityReported)
    assert report.photo_counts == [ObjectCount(phrase="stone", count=5)]


async def test_a_photo_with_nothing_counted_is_thanked_without_numbers() -> None:
    layer, llm = layer_with()
    ctx = turn_context(learners=[MUNNI], open_activity=offer(FIRST, MUNNI))
    result = await layer.handle(ctx, ParentMessage("dekhiye", [], PhotoFindings(counts=[])), NOW, H)
    [prompt] = llm.by_prompt["parent_reflection"].prompts
    assert "You can't see it: thank them for it warmly" in prompt.system
    assert "a counting\nmodel found" not in prompt.system
    [report] = result.writes
    assert isinstance(report, ActivityReported)
    assert report.photo_counts == []


async def test_a_report_without_a_photo_says_nothing_about_photos() -> None:
    layer, llm = layer_with()
    ctx = turn_context(learners=[MUNNI], open_activity=offer(FIRST, MUNNI))
    await layer.handle(ctx, ParentMessage("Munni ne kaha parchhai ghoomti hai", []), NOW, H)
    [prompt] = llm.by_prompt["parent_reflection"].prompts
    assert "photo" not in prompt.system


async def test_if_the_reflection_fails_the_photo_counts_are_still_recorded() -> None:
    layer, _ = layer_with(reflect=ProviderUnavailable("503", provider="baseten"))
    ctx = turn_context(learners=[MUNNI], open_activity=offer(FIRST, MUNNI))
    result = await layer.handle(ctx, ParentMessage("", [], STONES), NOW, H)
    assert result.outcome is StepOutcome.DEGRADED
    [report] = result.writes
    assert isinstance(report, ActivityReported)
    assert report.photo_counts == [ObjectCount(phrase="stone", count=5)]


async def test_answering_the_time_question_keeps_the_open_khojs_buttons() -> None:
    # owner's judge walkthrough (2026-10-29): the time question comes with the first khoj;
    # answering it first took "Done" away
    result = await khoj(button="nudge:off", open_activity=offer(FIRST, MUNNI))
    assert result.reply.body == NUDGE_OFF_REPLY[H]
    assert [button.id for button in result.reply.buttons] == ["jrn:done", "jrn:other"]


async def test_answering_the_time_question_with_nothing_open_adds_no_buttons() -> None:
    result = await khoj(button="nudge:off")
    assert result.reply.buttons == []


@pytest.mark.parametrize("text", ["Hi", "hello ji", "ok", "Thanks!", "शुक्रिया", "theek hai"])
async def test_a_greeting_or_thanks_with_a_khoj_open_is_not_a_report(text: str) -> None:
    # owner, 2026-10-29: "Hi" with a khoj open got a "Shabash!" reflection
    layer, llm = layer_with()
    result = await khoj(text=text, button=None, open_activity=offer(FIRST, MUNNI), layer=layer)
    assert result.reply.body == KHOJ_STILL_OPEN[H].format(title=FIRST.title)
    assert [button.id for button in result.reply.buttons] == ["jrn:done", "jrn:other"]
    assert result.writes == []  # nothing recorded as reported
    assert llm.by_prompt["parent_reflection"].prompts == []


@pytest.mark.parametrize("text", ["ok she counted 7 leaves", "Munni did it", "haan ho gaya"])
async def test_a_real_report_after_ok_is_still_a_report(text: str) -> None:
    layer, llm = layer_with()
    result = await khoj(text=text, button=None, open_activity=offer(FIRST, MUNNI), layer=layer)
    assert result.reply.body.startswith(REFLECTION_PRAISE)
    assert len(llm.by_prompt["parent_reflection"].prompts) == 1


# --- intent reading (owner, 2026-10-29) ----------------------------------------------------------


def reading(intent: str) -> dict[str, object]:
    return {"intent": intent}


async def test_a_report_read_as_a_report_gets_the_reflection() -> None:
    layer, llm = layer_with(intent=reading("report"))
    result = await khoj(
        text="usne patte gine", button=None, open_activity=offer(FIRST, MUNNI), layer=layer
    )
    assert result.reply.body.startswith(REFLECTION_PRAISE)
    assert result.prompt_versions["parent_intent"] == "1.0.0"
    [prompt] = llm.by_prompt["parent_intent"].prompts
    assert "usne patte gine" in prompt.user


async def test_a_question_with_a_khoj_open_is_answered_not_taken_as_the_report() -> None:
    # the word rules took any text as the report while a khoj was open
    layer, llm = layer_with(intent=reading("question"))
    result = await khoj(
        text="bachcha khana nahi khata, kya karein",
        button=None,
        open_activity=offer(FIRST, MUNNI),
        layer=layer,
    )
    assert llm.by_prompt["parent_reflection"].prompts == []
    assert len(llm.by_prompt["parent_answer"].prompts) == 1
    assert not any(isinstance(write, ActivityReported) for write in result.writes)


async def test_the_same_khoj_again_resends_the_open_one_and_offers_nothing_new() -> None:
    layer, llm = layer_with(intent=reading("same_khoj_again"))
    result = await khoj(
        text="kal wali khoj phir se bhejo",
        button=None,
        open_activity=offer(FIRST, MUNNI),
        layer=layer,
    )
    assert FIRST.steps[0] in result.reply.body
    assert [button.id for button in result.reply.buttons][:2] == ["jrn:done", "jrn:other"]
    assert result.writes == []
    assert llm.by_prompt["activity_personalise"].prompts == []


async def test_the_same_khoj_with_nothing_open_offers_todays() -> None:
    layer, _ = layer_with(intent=reading("same_khoj_again"))
    result = await khoj(text="wahi wali khoj", button=None, layer=layer)
    assert offered(result).learner_id == MUNNI.id


async def test_add_a_child_points_to_the_button_that_starts_it() -> None:
    layer, _ = layer_with(intent=reading("add_child"))
    result = await khoj(text="meri ek aur beti hai", button=None, layer=layer)
    assert result.reply.body == ADD_CHILD_PROMPT[H]
    assert [button.id for button in result.reply.buttons] == ["onb:add-child"]


@pytest.mark.parametrize(
    ("intent", "body", "buttons"),
    [
        ("daily_time", NUDGE_ASK[H], ["nudge:08", "nudge:18", "nudge:off"]),
        ("daily_off", NUDGE_OFF_REPLY[H], []),
    ],
)
async def test_daily_message_wishes_read_from_free_words(
    intent: str, body: str, buttons: list[str]
) -> None:
    layer, _ = layer_with(intent=reading(intent))
    result = await khoj(text="subah ki jagah shaam ko bhejna", button=None, layer=layer)
    assert result.reply.body == body
    assert [button.id for button in result.reply.buttons] == buttons


async def test_a_child_question_goes_to_the_curiosity_moment_without_the_word_rule() -> None:
    layer, llm = layer_with(intent=reading("child_question"))
    await khoj(text="baarish kahan se aati hai, yeh jaanna hai", button=None, layer=layer)
    assert len(llm.by_prompt["curiosity_moment"].prompts) == 1


async def test_buttons_and_a_bare_greeting_never_call_the_intent_model() -> None:
    layer, llm = layer_with(intent=reading("question"))
    await khoj(button=KHOJ_DONE, open_activity=offer(FIRST, MUNNI), layer=layer)
    await khoj(text="Hi", button=None, open_activity=offer(FIRST, MUNNI), layer=layer)
    assert llm.by_prompt["parent_intent"].prompts == []


async def test_if_the_reading_fails_the_rules_decide_and_the_turn_says_so() -> None:
    layer, _ = layer_with(intent=ProviderUnavailable("503", provider="meta_model_api"))
    result = await khoj(
        text="Munni ne 7 patte gine", button=None, open_activity=offer(FIRST, MUNNI), layer=layer
    )
    assert result.reply.body.startswith(REFLECTION_PRAISE)  # the rules: text with a khoj open
    assert result.outcome is StepOutcome.DEGRADED
    assert result.degraded_reason == "intent_read_failed=ProviderUnavailable"


async def test_a_reading_outside_the_set_falls_back_to_the_rules() -> None:
    # the adapter refuses {"intent": "go_to_the_moon"} after its repair retry
    layer, _ = layer_with(
        intent=ProviderResponseInvalid("not an intent", provider="meta_model_api")
    )
    result = await khoj(text="kuch bhi", button=None, layer=layer)
    assert result.degraded_reason == "intent_read_failed=ProviderResponseInvalid"
