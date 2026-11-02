"""JourneyLayer: today's khoj, another khoj, report back, which child, parent questions
(s10b §4.4 to §4.9, §4.10 supervision line)."""

from datetime import time, timedelta
from typing import Final
from uuid import UUID

import pytest

from app.constants.braj_words import BRAJ_RULE
from app.constants.child_talk_copy import WHO_IS_WRITING, WHO_IS_WRITING_NO_CHILD
from app.constants.journey_copy import (
    ACKNOWLEDGED,
    ADD_CHILD_PROMPT,
    AGE_COMING_SOON,
    DELETE_DATA_BUTTON,
    DELETE_DATA_OFFER,
    DONE_THANKS,
    HELLO_NOTHING_OPEN,
    KHOJ_DONE,
    KHOJ_OTHER,
    KHOJ_STILL_OPEN,
    KHOJ_TODAY,
    NICKNAME_ONLY,
    NICKNAME_SAVED,
    NO_DETAILS_SUMMARY,
    NUDGE_ASK,
    NUDGE_OFF_REPLY,
    PROGRESS_HEADER,
    REFLECTION_FALLBACK,
    STOP_DAILY_BUTTON,
    STOP_WHICH,
    SUPERVISION_LINE,
    WHICH_CHILD,
    WHICH_KHOJ,
)
from app.constants.onboarding_copy import CHILD_TALK_NO, CHILD_TALK_YES, COPY
from app.constants.small_talk_copy import GOOD_NIGHT, GOODBYE
from app.core.errors import ProviderError, ProviderResponseInvalid, ProviderUnavailable
from app.domain.enums import ActivityStatus, CopyKey, Language, Route, StepOutcome
from app.domain.models.activity import OfferRecord
from app.domain.models.learner import Learner
from app.domain.models.photo import ObjectCount, PhotoFindings
from app.domain.models.turn import Exchange
from app.domain.models.writes import (
    ActivityOffered,
    ActivityReported,
    LearnerUpsert,
    NudgePreference,
)
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
from tests.support.parent_answers import HINDI_ANSWER, HINGLISH_ANSWER
from tests.support.prompts import shipped_registry
from tests.support.turn_context import NOW, button_reply, text_message, turn_context

pytestmark = pytest.mark.unit

H = Language.HINGLISH
MUNNI = child()
FIRST = first_choice()


ABOUT_MARG_REPLY: Final = {
    "answer": "Marg har sandesh ko bhejne se pehle suraksha ke liye jaanchta hai.",
    "unknown": False,
    "spoken_text": "मार्ग हर संदेश को भेजने से पहले सुरक्षा के लिए जाँचता है।",
}


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
            "parent_intent": FakeLanguageModel([intent or reading("question")]),
            "about_marg": FakeLanguageModel([ABOUT_MARG_REPLY]),
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
    assert result.prompt_versions == {"activity_personalise": "1.1.0"}


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
    assert [button.id for button in result.reply.buttons] == ["jrn:today"]
    assert result.prompt_versions == {"parent_reflection": "1.3.0"}


async def test_done_with_nothing_said_gets_thanks_and_a_question_by_code() -> None:
    # Owner's demo, 2026-11-01: the model praised a khoj nobody had described
    layer, llm = layer_with()
    result = await khoj(button=KHOJ_DONE, open_activity=offer(FIRST, MUNNI), layer=layer)
    assert result.reply.body == DONE_THANKS[H].format(child="Munni")
    assert [button.id for button in result.reply.buttons] == ["jrn:today"]
    assert llm.by_prompt["parent_reflection"].prompts == []
    [written] = result.writes
    assert isinstance(written, ActivityReported)
    assert written.status is ActivityStatus.DONE
    assert written.summary == NO_DETAILS_SUMMARY


async def test_a_photo_without_words_tells_the_model_it_doesnt_know_what_happened() -> None:
    # Owner's demo, 2026-11-01: a photo alone got "your little helper sorted the piles…"
    layer, llm = layer_with()
    open_one = offer(FIRST, MUNNI)
    ctx = turn_context(text_message(""), learners=[MUNNI], open_activity=open_one)
    await layer.handle(ctx, ParentMessage("", [], STONES), NOW, H)
    [prompt] = llm.by_prompt["parent_reflection"].prompts
    assert "You don't know what the child said, did or noticed" in prompt.system


async def test_a_report_with_words_is_reflected_on_as_told() -> None:
    layer, llm = layer_with()
    await khoj(
        text="Munni ne 7 patte gine", button=None, open_activity=offer(FIRST, MUNNI), layer=layer
    )
    [prompt] = llm.by_prompt["parent_reflection"].prompts
    assert "You don't know what the child said" not in prompt.system


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
    assert result.prompt_versions == {"curiosity_moment": "1.0.5", "parent_answer": "1.4.0"}
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


def reading(  # noqa: PLR0913  # one keyword per field of the reading a test sets
    intent: str,
    language: str = "hinglish",
    *,
    braj: bool = False,
    asked: str | None = None,
    name: str | None = None,
    about: str | None = None,
) -> dict[str, object]:
    return {
        "intent": intent,
        "language": language,
        "braj": braj,
        "asked_language": asked,
        "child_name": name,
        "report_about": about,
    }


async def test_a_report_read_as_a_report_gets_the_reflection() -> None:
    layer, llm = layer_with(intent=reading("report"))
    result = await khoj(
        text="usne patte gine", button=None, open_activity=offer(FIRST, MUNNI), layer=layer
    )
    assert result.reply.body.startswith(REFLECTION_PRAISE)
    assert result.prompt_versions["parent_intent"] == "1.14.0"
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


@pytest.mark.parametrize("text", ["Hi", "Hellooo", "thanks"])
async def test_a_greeting_with_nothing_open_offers_todays_khoj_by_name(text: str) -> None:
    # owner's demo (2026-10-29): "Hi" made the parent answer ask the child's age
    layer, llm = layer_with()
    result = await khoj(text=text, button=None, layer=layer)
    assert result.reply.body == HELLO_NOTHING_OPEN[H].format(child=MUNNI.nickname)
    assert [button.id for button in result.reply.buttons] == ["jrn:today"]
    assert llm.by_prompt["parent_answer"].prompts == []


EARLIER_SUGGESTION = Exchange(
    user_text="he jumped like a frog",
    reply_text="Very nice! Today, hop like a frog together in the courtyard.",
    route=Route.JOURNEY,
    at=NOW - timedelta(minutes=1),
)


async def answer_after_a_suggestion(text: str, open_activity: OfferRecord | None) -> LayerResult:
    layer, _ = layer_with()
    message = text_message(text)
    ctx = turn_context(message, learners=[MUNNI], open_activity=open_activity).model_copy(
        update={"recent_exchanges": [EARLIER_SUGGESTION]}
    )
    return await layer.handle(ctx, ParentMessage(text, []), NOW, H)


@pytest.mark.parametrize("text", ["ok", "thanks", "theek hai"])
async def test_ok_after_a_suggestion_gets_encouragement_not_the_menu(text: str) -> None:
    # Owner's demo, 2026-11-01: "ok" to "hop like a frog together" got "Hello! Would you like
    # today's khoj…"
    result = await answer_after_a_suggestion(text, open_activity=None)
    assert result.reply.body == ACKNOWLEDGED[H]
    assert result.reply.buttons == []


async def test_ok_with_a_khoj_open_keeps_its_buttons() -> None:
    result = await answer_after_a_suggestion("ok", open_activity=offer(FIRST, MUNNI))
    assert result.reply.body == ACKNOWLEDGED[H]
    assert [button.id for button in result.reply.buttons] == [KHOJ_DONE, KHOJ_OTHER]


async def test_a_greeting_mid_conversation_still_gets_the_hello() -> None:
    result = await answer_after_a_suggestion("Hi", open_activity=None)
    assert result.reply.body == HELLO_NOTHING_OPEN[H].format(child=MUNNI.nickname)


async def test_small_talk_read_by_the_model_gets_the_same_hello() -> None:
    layer, llm = layer_with(intent=reading("small_talk"))
    result = await khoj(text="bas aise hi yaad aaya", button=None, layer=layer)
    assert result.reply.body == HELLO_NOTHING_OPEN[H].format(child=MUNNI.nickname)
    assert llm.by_prompt["parent_answer"].prompts == []


@pytest.mark.parametrize(
    ("chosen", "heard", "text", "reply_in"),
    [
        # the rules call marker-less Roman Hindi English; the model hears Hinglish
        (Language.ENGLISH, Language.HINGLISH, "beta school jata hai roz", Language.HINGLISH),
        (Language.ENGLISH, Language.HINGLISH, "aaj khana banaya", Language.HINGLISH),
        # never overruled: Devanagari, the rules' own Hinglish, or a model that hears English
        (Language.HINDI, Language.HINGLISH, "आज खाना बनाया", Language.HINDI),
        (Language.HINGLISH, Language.ENGLISH, "kya karein", Language.HINGLISH),
        (Language.ENGLISH, Language.ENGLISH, "my son sleeps late", Language.ENGLISH),
        (Language.ENGLISH, None, "aaj khana banaya", Language.ENGLISH),
    ],
)
def test_the_model_settles_only_roman_text_the_rules_called_english(
    chosen: Language, heard: Language | None, text: str, reply_in: Language
) -> None:
    assert JourneyLayer.reply_language(chosen, heard, text) is reply_in


async def test_a_reply_goes_out_in_the_language_the_model_heard() -> None:
    layer, llm = layer_with(intent=reading("question", "hinglish"))
    ctx = turn_context(text_message("aaj khana nahi khaya"), learners=[MUNNI])
    result = await layer.handle(
        ctx, ParentMessage("aaj khana nahi khaya", []), NOW, Language.ENGLISH
    )
    assert result.reply.body_language is Language.HINGLISH
    [prompt] = llm.by_prompt["parent_answer"].prompts
    assert "Hinglish" in prompt.system


async def test_braj_heard_by_the_model_gets_light_braj_without_a_marker_word() -> None:
    layer, llm = layer_with(answer=HINDI_ANSWER, intent=reading("question", "hindi", braj=True))
    text = "छोरा पढ़तो नहीं"  # one marker only: the word rule alone says not Braj
    ctx = turn_context(text_message(text), learners=[MUNNI])
    await layer.handle(ctx, ParentMessage(text, []), NOW, Language.HINDI)
    [prompt] = llm.by_prompt["parent_answer"].prompts
    assert BRAJ_RULE[Language.HINDI] in prompt.system


# --- a language asked for, for this reply only (owner, 2026-11-01) --------------------------------

HINDI_PERSONALISATION: dict[str, object] = {
    "intro": "आज मुन्नी के साथ एक छोटी खोज कीजिए।",
    "steps": [
        f"कदम {number}: बच्चे के साथ ध्यान से कीजिए।" for number in range(1, len(FIRST.steps) + 1)
    ],
    "questions_to_ask": ["तुम्हें क्या दिखा?", "तुम्हें ऐसा क्यों लगता है?"],
    "listen_for": "बच्चे की अपनी सोच, चाहे जवाब सही न हो।",
    "parent_tip": "सवाल पूछकर जवाब का इंतज़ार कीजिए।",
    "spoken_text": "आज मुन्नी के साथ एक छोटी खोज। बच्चे के साथ ध्यान से कीजिए।",
}


@pytest.mark.parametrize("intent", ["same_khoj_again", "new_khoj"])
async def test_the_open_khoj_asked_for_in_hindi_comes_again_in_hindi_and_nothing_new(
    intent: str,
) -> None:
    # Owner's demo: "please send khoj again in hindi" came back in English
    layer, llm = layer_with(
        personalise=HINDI_PERSONALISATION, intent=reading(intent, "english", asked="hindi")
    )
    result = await khoj(
        text="please send khoj again in hindi",
        button=None,
        open_activity=offer(FIRST, MUNNI),
        layer=layer,
    )
    assert result.outcome is StepOutcome.OK
    assert result.reply.body_language is Language.HINDI
    assert result.reply.body.startswith(str(HINDI_PERSONALISATION["intro"]))
    assert result.reply.body.endswith(SUPERVISION_LINE[Language.HINDI])
    assert result.writes == []  # the same khoj: nothing offered, nothing skipped
    [prompt] = llm.by_prompt["activity_personalise"].prompts
    assert FIRST.title in prompt.system
    assert "Devanagari" in prompt.system


async def test_if_rewording_in_the_asked_language_fails_the_reviewed_words_come_degraded() -> None:
    layer, _ = layer_with(
        personalise=ProviderUnavailable("503", provider="meta_model_api"),
        intent=reading("same_khoj_again", "english", asked="hinglish"),
    )
    result = await khoj(
        text="send khoj in hinglish", button=None, open_activity=offer(FIRST, MUNNI), layer=layer
    )
    assert result.outcome is StepOutcome.DEGRADED
    assert result.degraded_reason == "catalogue_fallback=ProviderUnavailable"
    assert FIRST.steps[0] in result.reply.body
    assert result.reply.body_language is Language.HINGLISH
    assert result.writes == []


async def test_a_new_khoj_asked_for_in_a_language_with_nothing_open_is_todays_in_it() -> None:
    layer, _ = layer_with(
        personalise=HINDI_PERSONALISATION, intent=reading("new_khoj", "english", asked="hindi")
    )
    result = await khoj(text="send today's khoj in hindi", button=None, layer=layer)
    assert result.reply.body_language is Language.HINDI
    assert offered(result).learner_id == MUNNI.id


async def test_another_khoj_asked_for_in_a_language_is_still_a_different_one() -> None:
    # the reviewed words are enough here: the test is about which khoj, not its wording
    layer, _ = layer_with(
        personalise=ProviderUnavailable("503", provider="meta_model_api"),
        intent=reading("another_khoj", "english", asked="hinglish"),
    )
    result = await khoj(
        text="send another one in hinglish",
        button=None,
        open_activity=offer(FIRST, MUNNI),
        layer=layer,
    )
    [skipped] = [write for write in result.writes if isinstance(write, ActivityReported)]
    assert skipped.status is ActivityStatus.SKIPPED
    assert offered(result).activity_id != FIRST.id


async def test_a_question_asked_to_be_answered_in_hindi_is_answered_in_hindi() -> None:
    layer, llm = layer_with(
        answer=HINDI_ANSWER, intent=reading("question", "english", asked="hindi")
    )
    result = await khoj(text="my son won't eat, answer in hindi", button=None, layer=layer)
    assert result.reply.body_language is Language.HINDI
    [prompt] = llm.by_prompt["parent_answer"].prompts
    assert "Devanagari" in prompt.system


async def test_writing_in_english_without_asking_keeps_the_usual_language() -> None:
    layer, _ = layer_with(intent=reading("same_khoj_again", "english"))
    result = await khoj(
        text="send that activity again please",
        button=None,
        open_activity=offer(FIRST, MUNNI),
        layer=layer,
    )
    assert result.reply.body_language is H
    assert result.writes == []


# --- a longer message asking to delete everything (owner, 2026-11-01) ----------------------------


async def test_a_longer_deletion_request_gets_the_offer_that_starts_the_usual_deletion() -> None:
    layer, llm = layer_with(intent=reading("delete_data", "hinglish"))
    result = await khoj(text="mera sab data mita do, ab nahi chahiye", button=None, layer=layer)
    assert result.reply.body == DELETE_DATA_OFFER[H]
    assert [button.id for button in result.reply.buttons] == ["onb:delete:ask"]
    assert result.writes == []  # nothing is deleted here: the button asks once more
    assert llm.by_prompt["parent_answer"].prompts == []


async def test_stop_everything_asks_whether_to_stop_messages_or_delete_and_changes_nothing() -> (
    None
):
    # critic review D1, 2026-11-01: "sab band karo, mujhe ye nahi chahiye" is either
    layer, llm = layer_with(intent=reading("stop_all", "hinglish"))
    result = await khoj(text="sab band karo, mujhe ye nahi chahiye", button=None, layer=layer)
    assert result.reply.body == STOP_WHICH[H]
    assert [button.id for button in result.reply.buttons] == ["nudge:off", "onb:delete:ask"]
    assert result.writes == []  # nothing is turned off or deleted until a button is tapped
    assert llm.by_prompt["parent_answer"].prompts == []


@pytest.mark.parametrize("register", list(Language))
def test_the_stop_buttons_fit_whatsapp_in_every_language(register: Language) -> None:
    for button in (STOP_DAILY_BUTTON[register], DELETE_DATA_BUTTON[register]):
        assert len(button.title) <= 20  # WhatsApp's button title limit


@pytest.mark.parametrize("text", ["👍", "ok ok", "🥰"])
async def test_a_parents_emoji_or_ok_ok_is_small_talk_with_no_model(text: str) -> None:
    # owner, 2026-11-02: small talk is answered alike for every persona
    layer, llm = layer_with(intent=reading("question", "hinglish"))
    result = await khoj(text=text, button=None, layer=layer)
    assert llm.by_prompt["parent_intent"].prompts == []
    assert llm.by_prompt["parent_answer"].prompts == []
    assert result.reply.body != GOOD_NIGHT[H]


async def test_a_parents_ttyl_gets_a_goodbye_not_enjoy_it_together() -> None:
    layer, _ = layer_with(intent=reading("question", "hinglish"))
    result = await khoj(text="Ttyl", button=None, layer=layer)
    assert result.reply.body == GOODBYE[H]


async def test_a_parents_good_night_gets_good_night_not_enjoy_it_together() -> None:
    layer, llm = layer_with(intent=reading("question", "hinglish"))
    result = await khoj(text="ok good night", button=None, layer=layer)
    assert result.reply.body == GOOD_NIGHT[H]
    assert llm.by_prompt["parent_intent"].prompts == []


async def test_a_question_about_marg_is_answered_from_the_facts_not_the_parent_answer() -> None:
    # owner, 2026-11-01: "what data do you keep?" once got invented claims
    layer, llm = layer_with(intent=reading("about_marg", "hinglish"))
    result = await khoj(text="mera data kaun dekhta hai", button=None, layer=layer)
    assert result.reply.body == ABOUT_MARG_REPLY["answer"]
    assert llm.by_prompt["parent_answer"].prompts == []
    assert len(llm.by_prompt["about_marg"].prompts) == 1
    assert result.step_note == "about_marg=true"


async def test_if_the_reading_fails_a_request_to_add_a_child_still_gets_the_button() -> None:
    layer, _ = layer_with(intent=ProviderUnavailable("503", provider="meta_model_api"))
    result = await khoj(text="ek aur bachcha add karna hai", button=None, layer=layer)
    assert result.reply.body == ADD_CHILD_PROMPT[H]
    assert [button.id for button in result.reply.buttons] == ["onb:add-child"]


# --- a child's home name given after onboarding (owner, 2026-11-01) -----------------------------


async def test_a_home_name_given_later_is_saved_for_the_child_and_confirmed() -> None:
    # Owner's demo: "bacche ka naam prisa hai" got a kind answer, and the name was lost
    layer, llm = layer_with(intent=reading("child_name", name="Prisa"))
    unnamed = child(1, nickname=None, age=6)
    result = await khoj(
        text="bacche ka naam prisa hai", button=None, learners=[unnamed], layer=layer
    )
    assert result.reply.body == NICKNAME_SAVED[H].format(child="Prisa")
    assert result.writes == [
        LearnerUpsert(
            learner_id=unnamed.id,
            relation=unnamed.relation,
            nickname="Prisa",
            birth_year=unnamed.birth_year,
        )
    ]
    assert llm.by_prompt["parent_answer"].prompts == []


@pytest.mark.parametrize("name", ["Priya Kumari Sharma", "x" * 21, "Munni Rani"])
async def test_a_full_or_long_name_is_not_saved_and_a_short_one_is_asked_for(name: str) -> None:
    layer, _ = layer_with(intent=reading("child_name", name=name))
    result = await khoj(text=f"uska naam {name} hai", button=None, layer=layer)
    assert result.reply.body == NICKNAME_ONLY[H]
    assert result.writes == []


async def test_with_two_children_and_none_chosen_the_name_is_not_guessed() -> None:
    golu = child(2, "Golu", age=7)
    layer, llm = layer_with(intent=reading("child_name", name="Chotu"))
    result = await khoj(
        text="uska naam Chotu rakho", button=None, learners=[MUNNI, golu], layer=layer
    )
    assert result.writes == []
    assert len(llm.by_prompt["parent_answer"].prompts) == 1


async def test_a_name_intent_without_a_name_is_answered_not_saved() -> None:
    layer, llm = layer_with(intent=reading("child_name", name=None))
    result = await khoj(text="naam badalna hai", button=None, layer=layer)
    assert result.writes == []
    assert len(llm.by_prompt["parent_answer"].prompts) == 1


# --- "can my child talk to you?" (owner, 2026-11-01) ---------------------------------------------


async def test_asking_if_the_child_can_talk_gets_the_consent_question_with_its_buttons() -> None:
    # Owner's demo: the answer said "read my words to the child", though child talk exists
    layer, llm = layer_with(intent=reading("child_talk", "english"))
    result = await khoj(text="Can my child also talk to you", button=None, layer=layer)
    ask = COPY[(CopyKey.ASK_CHILD_TALK, H)]
    assert result.reply.body == ask.body.format(child="Munni")
    assert [button.id for button in result.reply.buttons] == [
        f"{CHILD_TALK_YES}:{MUNNI.id}",
        f"{CHILD_TALK_NO}:{MUNNI.id}",
    ]
    assert llm.by_prompt["parent_answer"].prompts == []
    assert result.writes == []


async def test_a_parent_who_already_said_yes_is_told_how_the_child_starts() -> None:
    munni = consented_child()
    layer, _ = layer_with(intent=reading("child_talk", "english"))
    result = await khoj(
        text="how can she talk directly", button=None, learners=[munni], layer=layer
    )
    enabled = COPY[(CopyKey.CHILD_TALK_ENABLED, H)]
    assert result.reply.body == enabled.body.format(child="Munni")
    assert [button.id for button in result.reply.buttons] == [f"kid:start:{munni.id}"]


async def test_with_two_young_children_and_none_chosen_the_first_is_asked_about() -> None:
    golu = child(2, "Golu", age=7)
    layer, _ = layer_with(intent=reading("child_talk"))
    result = await khoj(
        text="kya bachche khud baat kar sakte hain",
        button=None,
        learners=[MUNNI, golu],
        layer=layer,
    )
    assert result.reply.body == COPY[(CopyKey.ASK_CHILD_TALK, H)].body.format(child="Munni")
    assert result.reply.buttons[0].id == f"{CHILD_TALK_YES}:{MUNNI.id}"


async def test_with_no_child_aged_3_to_8_the_question_is_answered_instead() -> None:
    lala = child(3, "Lala", age=10)  # child talk is for 3-8-year-olds
    layer, llm = layer_with(intent=reading("child_talk"))
    await khoj(text="kya Lala khud baat kar sakta hai", button=None, learners=[lala], layer=layer)
    assert len(llm.by_prompt["parent_answer"].prompts) == 1


async def test_with_child_talk_switched_off_the_question_is_answered_instead() -> None:
    _, llm = layer_with(intent=reading("child_talk"))
    switched_off = JourneyLayer(
        llm,
        shipped_registry(),
        CatalogueActivitySource(shipped_catalogue()),
        ParentQuestionLayer(llm, shipped_registry()),
        JourneySettings(
            repeat_window=timedelta(days=30), child_talk_enabled=False, read_intent=True
        ),
    )
    result = await khoj(text="can my child talk to you", button=None, layer=switched_off)
    assert len(llm.by_prompt["parent_answer"].prompts) == 1
    assert result.reply.buttons == []


# --- someone else is writing on the parent's phone (owner, 2026-10-29) -------------------------


async def test_a_student_on_the_parents_phone_is_asked_who_and_not_answered() -> None:
    layer, llm = layer_with(intent=reading("someone_else", "english"))
    result = await khoj(text="I'm in class 10, what should I study", button=None, layer=layer)
    assert result.reply.body == WHO_IS_WRITING[H].format(names="Munni")
    assert [(button.id, button.title) for button in result.reply.buttons] == [
        (f"kid:start:{MUNNI.id}", "Munni")
    ]
    assert llm.by_prompt["parent_answer"].prompts == []  # the question isn't answered


async def test_each_young_child_on_the_list_is_a_button() -> None:
    golu = child(2, "Golu", age=7)
    layer, _ = layer_with(intent=reading("someone_else"))
    result = await khoj(
        text="main 7 saal ka hoon", button=None, learners=[MUNNI, golu], layer=layer
    )
    assert result.reply.body == WHO_IS_WRITING[H].format(names="Munni ya Golu")
    assert [button.title for button in result.reply.buttons] == ["Munni", "Golu"]


async def test_with_no_young_child_on_the_list_the_writer_is_sent_to_their_parent() -> None:
    lala = child(3, "Lala", age=10)  # child talk is for 3-8-year-olds
    layer, llm = layer_with(intent=reading("someone_else"))
    result = await khoj(
        text="mujhe homework mein madad chahiye", button=None, learners=[lala], layer=layer
    )
    assert result.reply.body == WHO_IS_WRITING_NO_CHILD[H]
    assert result.reply.buttons == []
    assert llm.by_prompt["parent_answer"].prompts == []


# --- which khoj a report is about (owner, 2026-11-01) --------------------------------------------

SKIPPED_EARLIER = next(
    activity for activity in shipped_catalogue().enabled if activity.id != FIRST.id
)


def histories(
    *, skipped_hours_ago: float = 1, skipped_status: ActivityStatus = ActivityStatus.SKIPPED
) -> tuple[OfferRecord, OfferRecord]:
    open_one = offer(FIRST, MUNNI, hours_ago=0.5, number=60)
    earlier = offer(
        SKIPPED_EARLIER, MUNNI, hours_ago=skipped_hours_ago, status=skipped_status, number=61
    )
    return open_one, earlier


async def report(
    message: ParentMessage, layer: JourneyLayer, *, earlier_exchange: Exchange | None = None
) -> LayerResult:
    open_one, earlier = histories()
    ctx = turn_context(
        text_message(message.text),
        learners=[MUNNI],
        open_activity=open_one,
        activity_history=[open_one, earlier],
    )
    if earlier_exchange is not None:
        ctx = ctx.model_copy(update={"recent_exchanges": [earlier_exchange]})
    return await layer.handle(ctx, message, NOW, H)


async def test_a_photo_alone_with_another_khoj_waiting_asks_which_one() -> None:
    # Owner's demo: an animal-walk photo was taken as the clothes-sorting report
    layer, llm = layer_with()
    result = await report(ParentMessage("", [], STONES), layer)
    assert result.reply.body == WHICH_KHOJ[H]
    assert [button.id for button in result.reply.buttons] == [
        f"jrn:about:{UUID(int=60)}",
        f"jrn:about:{UUID(int=61)}",
    ]
    assert result.writes == []
    assert llm.by_prompt["parent_reflection"].prompts == []


async def test_a_photo_alone_with_only_the_open_khoj_is_its_report() -> None:
    layer, _ = layer_with()
    open_one = offer(FIRST, MUNNI, hours_ago=0.5, number=60)
    ctx = turn_context(
        text_message(""), learners=[MUNNI], open_activity=open_one, activity_history=[open_one]
    )
    result = await layer.handle(ctx, ParentMessage("", [], STONES), NOW, H)
    assert result.reply.body.startswith(REFLECTION_PRAISE)


@pytest.mark.parametrize("hours_ago", [49.0])
async def test_a_khoj_older_than_48_hours_isnt_asked_about(hours_ago: float) -> None:
    layer, _ = layer_with()
    open_one, earlier = histories(skipped_hours_ago=hours_ago)
    ctx = turn_context(
        text_message(""),
        learners=[MUNNI],
        open_activity=open_one,
        activity_history=[open_one, earlier],
    )
    result = await layer.handle(ctx, ParentMessage("", [], STONES), NOW, H)
    assert result.reply.body.startswith(REFLECTION_PRAISE)


async def test_tapping_the_earlier_khoj_reports_on_it_and_leaves_the_open_one() -> None:
    layer, _ = layer_with(reflect={**REFLECTION})
    result = await report(ParentMessage("", [f"jrn:about:{UUID(int=61)}"]), layer)
    [written] = [write for write in result.writes if isinstance(write, ActivityReported)]
    assert written.learner_activity_id == UUID(int=61)
    assert written.status is ActivityStatus.DONE


async def test_words_sent_before_the_question_come_with_the_tapped_khoj() -> None:
    layer, llm = layer_with()
    asked = Exchange(
        user_text="he jumped like a frog", reply_text=WHICH_KHOJ[H], route=Route.JOURNEY, at=NOW
    )
    await report(ParentMessage("", [f"jrn:about:{UUID(int=61)}"]), layer, earlier_exchange=asked)
    [prompt] = llm.by_prompt["parent_reflection"].prompts
    assert "he jumped like a frog" in prompt.user


async def test_a_report_in_words_about_the_earlier_khoj_goes_to_it() -> None:
    layer, _ = layer_with(intent=reading("report", "english", about=SKIPPED_EARLIER.title))
    result = await report(ParentMessage("he jumped like a frog", []), layer)
    [written] = [write for write in result.writes if isinstance(write, ActivityReported)]
    assert written.learner_activity_id == UUID(int=61)


async def test_a_report_in_words_that_cant_be_placed_asks_which_khoj() -> None:
    layer, llm = layer_with(intent=reading("report", "english", about=None))
    result = await report(ParentMessage("it went well", []), layer)
    assert result.reply.body == WHICH_KHOJ[H]
    assert llm.by_prompt["parent_reflection"].prompts == []


async def test_an_unknown_khoj_button_offers_todays_khoj() -> None:
    layer, _ = layer_with()
    result = await report(ParentMessage("", [f"jrn:about:{UUID(int=999)}"]), layer)
    assert offered(result).learner_id == MUNNI.id


# --- "how is my child doing?" (owner, 2026-11-01) ------------------------------------------------


async def test_asking_how_the_child_is_doing_gets_the_record_and_todays_khoj() -> None:
    # Owner's demo: "but we did lot of stuff, you can show the progress right"
    layer, llm = layer_with(intent=reading("progress", "english"))
    done = offer(FIRST, MUNNI, hours_ago=3, status=ActivityStatus.DONE, number=70)
    ctx = turn_context(text_message("how is my child doing"), learners=[MUNNI]).model_copy(
        update={"all_activities": [done]}
    )
    result = await layer.handle(ctx, ParentMessage("how is my child doing", []), NOW, H)
    assert result.reply.body.startswith(PROGRESS_HEADER[H].format(name="Munni"))
    assert FIRST.title in result.reply.body
    assert [button.id for button in result.reply.buttons] == ["jrn:today"]
    assert llm.by_prompt["parent_answer"].prompts == []
    assert result.writes == []
