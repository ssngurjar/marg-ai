"""The child bank stays a valid test set, and its runner scores and exits as the owner set it
(scripts/child_bank.py; owner, 2026-11-20: exit 0 at 85% or above, else 1). Offline: a fake model
stands in for the live one."""

import re
from collections import Counter
from collections.abc import Mapping
from datetime import timedelta
from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError

from app.core.errors import ProviderUnavailable
from app.domain.enums import ChildIntent, Language, LeavingReason
from app.layers.child_intent_reader import (
    ChildIntentRead,
    ChildIntentReader,
    ChildIntentReading,
    _ReadingChecks,
)
from app.providers.ports import GenerationRequest, GenerationResult, RenderedPrompt
from scripts.bank_results import BankResults, BankRun
from scripts.child_bank import (
    BANK_NAME,
    TARGET,
    ChildBank,
    ChildBankRunner,
    ChildBankScorer,
    ChildCase,
    Reading,
)
from tests.fakes.language_model import USAGE
from tests.support.prompts import shipped_registry

pytestmark = pytest.mark.unit

BANK = ChildBank.load()
CHILD_MESSAGE = re.compile(r"<child_message>\n(.*)\n</child_message>", re.DOTALL)
MARG_SAID = re.compile(r"<marg_said>\n(.*)\n</marg_said>", re.DOTALL)


def expected(case: ChildCase) -> ChildIntentReading:
    return ChildIntentReading(
        intent=case.intent,
        asked_language=case.asked,
        leaving_after=case.leaving_after,
        handover_after=case.handover_after,
        leaving_reason=case.leaving_reason,
    )


def case_of(intent: ChildIntent = ChildIntent.TALK, text: str = "chaand kyun?") -> ChildCase:
    return ChildCase(text=text, intent=intent, lang="hinglish")


def read_as(case: ChildCase) -> ChildIntentRead:
    """The reading the case expects, as the reader returns it."""
    return ChildIntentRead(
        intent=case.intent,
        asked_language=case.asked,
        leaving_after=case.leaving_after,
        handover_after=case.handover_after,
        leaving_reason=case.leaving_reason,
        usage=USAGE,
        prompt_versions={"child_intent": "1.5.0"},
        failed=None,
    )


def run_of(right: int, readings: int) -> BankRun:
    case = case_of()
    right_reading = Reading(case, read_as(case))
    wrong_reading = Reading(case, read_as(case_of(ChildIntent.LEAVING)))
    return ChildBankScorer.score([right_reading] * right + [wrong_reading] * (readings - right))


type Scripted = ChildIntentReading | ProviderUnavailable
type CaseKey = tuple[str, str]  # the child's words, and what Marg said before ("" for nothing)


def key(case: ChildCase) -> CaseKey:
    return (case.text, case.marg_said or "")


class ByMessageModel:
    """Satisfies `LanguageModel`: answers each child message with the reading scripted for it
    and for what Marg said before, both found in the prompt's slots, as the live model would
    read them there."""

    def __init__(self, readings: Mapping[CaseKey, Scripted]) -> None:
        self.readings = dict(readings)
        self.prompts: list[RenderedPrompt] = []

    async def generate[OutputT: BaseModel](
        self, request: GenerationRequest[OutputT]
    ) -> GenerationResult[OutputT]:
        self.prompts.append(request.prompt)
        scripted = self.readings[
            (slot(CHILD_MESSAGE, request.prompt), slot(MARG_SAID, request.prompt))
        ]
        if isinstance(scripted, ProviderUnavailable):
            raise scripted
        output = request.output_type.model_validate(scripted.model_dump())
        return GenerationResult(output=output, usage=USAGE, latency_ms=5)


def slot(pattern: re.Pattern[str], prompt: RenderedPrompt) -> str:
    found = pattern.search(prompt.user)
    assert found is not None, f"no {pattern.pattern} in the prompt"
    return found.group(1)


def runner_for(readings: Mapping[CaseKey, Scripted]) -> tuple[ChildBankRunner, ByMessageModel]:
    model = ByMessageModel(readings)
    reader = ChildIntentReader(model, shipped_registry(), timedelta(seconds=4))
    return ChildBankRunner(reader), model


# --- the bank stays a valid, useful test set --------------------------------------------------


def test_every_one_of_the_seven_intents_has_at_least_five_cases() -> None:
    counts = Counter(case.intent for case in BANK.cases)
    assert len(ChildIntent) == 7
    assert {intent: counts[intent] for intent in ChildIntent if counts[intent] < 5} == {}


def test_no_message_is_in_the_bank_twice_after_the_same_reply() -> None:
    # the same words may come twice only after different replies ("nahi")
    seen = Counter((case.text.strip().lower(), case.marg_said) for case in BANK.cases)
    assert [case for case, count in seen.items() if count > 1] == []


def test_a_bare_nahi_is_read_against_what_marg_asked() -> None:
    # owner, 2026-11-20: after "Aur kuch jaanna hai?" it's going; after a question, an answer
    by_context = {
        case.marg_said: case.intent for case in BANK.cases if case.text in {"nahi", "no", "नहीं"}
    }
    leaving = [said for said, intent in by_context.items() if intent is ChildIntent.LEAVING]
    answers = [said for said, intent in by_context.items() if intent is ChildIntent.TALK]
    assert len(leaving) >= 3
    assert len(answers) >= 3
    assert by_context[None] is ChildIntent.UNSURE  # nothing said before: can't tell
    assert all(said is not None and "?" in said for said in leaving + answers)


def test_the_childs_name_in_the_third_person_is_covered_both_ways() -> None:
    named = {case.text: case.intent for case in BANK.cases if case.text.startswith("Munni ")}
    assert named["Munni ne aaj kya kiya?"] is ChildIntent.PARENT_HERE
    assert named["Munni ko bhookh lagi hai"] is ChildIntent.TALK
    assert named["Munni ne ek titli dekhi!"] is ChildIntent.TALK


def test_a_miss_names_what_the_words_followed() -> None:
    after = ChildCase(
        text="nahi",
        intent=ChildIntent.LEAVING,
        lang="hinglish",
        marg_said="Accha!\n\nAur kuch jaanna hai? Mujhse kuch bhi poochho.",
    )
    # the last 40 characters, whitespace squeezed
    assert after.label == "nahi (after: …uch jaanna hai? Mujhse kuch bhi poochho.)"
    assert len("uch jaanna hai? Mujhse kuch bhi poochho.") == 40
    assert case_of().label == "chaand kyun?"
    run = ChildBankScorer.score([Reading(after, read_as(case_of()))])
    assert run.misses[0].text == after.label


def test_every_expected_reading_passes_the_readers_own_checks() -> None:
    # a case the reader could never return (a language on leaving…) would be a miss forever
    assert [case.text for case in BANK.cases if _ReadingChecks.problems(expected(case)) != []] == []


def test_the_owners_messages_are_in_the_bank_as_decided() -> None:
    by_text = {case.text: case for case in BANK.cases}
    assert by_text["main khelne ja rhi hoon"].intent is ChildIntent.LEAVING
    assert by_text["ab man nhi hai"].intent is ChildIntent.LEAVING
    assert by_text["mummy aagyi ab unse baat kro"].intent is ChildIntent.PARENT_HERE
    assert by_text["ye kya hai? ab main ja rahi hoon"].leaving_after
    assert by_text["ye kya hai? mummy se baat karo"].handover_after


def test_two_things_in_one_message_are_covered_each_way() -> None:
    leaving_after = [case for case in BANK.cases if case.leaving_after]
    handover_after = [case for case in BANK.cases if case.handover_after]
    asked_with_talk = [
        case for case in BANK.cases if case.asked and case.intent is ChildIntent.TALK
    ]
    assert len(leaving_after) >= 4
    assert len(handover_after) >= 4
    assert len(asked_with_talk) >= 3


def test_a_feeling_with_goodbye_words_stays_to_listen() -> None:
    [case] = [case for case in BANK.cases if "daantte" in case.text]
    assert case.intent is ChildIntent.TALK
    assert not case.leaving_after


def test_every_language_switch_names_the_language() -> None:
    switches = [case for case in BANK.cases if case.intent is ChildIntent.LANGUAGE_SWITCH]
    assert [case.text for case in switches if case.asked is None] == []


def test_the_bank_covers_hindi_hinglish_english_and_braj() -> None:
    devanagari = [case for case in BANK.cases if any("ऀ" <= letter <= "ॿ" for letter in case.text)]
    by_lang = Counter(case.lang for case in BANK.cases)
    assert len(devanagari) >= 10
    assert by_lang["hinglish"] >= 20
    assert by_lang["english"] >= 10
    assert by_lang["braj"] >= 2


@pytest.mark.parametrize(
    ("raw", "problem"),
    [
        ({"text": "x", "intent": "question", "lang": "hinglish"}, "intent"),  # a parent intent
        ({"text": "x", "intent": "talk", "lang": "french"}, "lang"),
        ({"text": "x", "intent": "talk", "lang": "hinglish", "asked": "tamil"}, "asked"),
        ({"text": "x", "intent": "talk", "lang": "hinglish", "leaving_after": "maybe"}, "leaving"),
        ({"intent": "talk", "lang": "hinglish"}, "text"),
        ({"text": "x", "intent": "talk", "lang": "hinglish", "open_khoj": True}, "open_khoj"),
    ],
)
def test_a_malformed_case_is_refused(raw: dict[str, object], problem: str) -> None:
    with pytest.raises(ValidationError, match=problem):
        ChildCase.model_validate(raw)


def test_a_bank_with_a_key_beside_cases_is_refused() -> None:
    with pytest.raises(ValidationError, match="target"):
        ChildBank.model_validate({"cases": [], "target": 0.5})


# --- scoring --------------------------------------------------------------------------------------


def test_a_right_reading_has_nothing_wrong() -> None:
    case = case_of()
    assert Reading(case, read_as(case)).wrong == []


def reading_of(
    intent: ChildIntent = ChildIntent.TALK,
    *,
    asked: Language | None = None,
    leaving_after: bool = False,
    handover_after: bool = False,
    reason: LeavingReason | None = None,
) -> ChildIntentRead:
    return ChildIntentRead(
        intent=intent,
        asked_language=asked,
        leaving_after=leaving_after,
        handover_after=handover_after,
        leaving_reason=reason,
        usage=USAGE,
        prompt_versions={},
        failed=None,
    )


@pytest.mark.parametrize(
    ("got", "wrong"),
    [
        (reading_of(ChildIntent.LEAVING, reason=LeavingReason.PLAY), ["intent leaving, not talk"]),
        (reading_of(asked=Language.HINDI), ["asked hindi, not None"]),
        (reading_of(leaving_after=True), ["leaving_after True, not False"]),
        (reading_of(handover_after=True), ["handover_after True, not False"]),
    ],
)
def test_each_field_read_wrong_is_named(got: ChildIntentRead, wrong: list[str]) -> None:
    assert Reading(case_of(), got).wrong == wrong


GOING = ChildCase(
    text="main khelne ja rhi hoon",
    intent=ChildIntent.LEAVING,
    lang="hinglish",
    leaving_reason=LeavingReason.PLAY,
)


@pytest.mark.parametrize(
    ("reason", "reported"),
    [
        (LeavingReason.PLAY, None),
        (LeavingReason.SLEEP, "leaving_reason sleep, not play"),
        (None, "leaving_reason none, not play"),  # none given, or odd
    ],
)
def test_a_wrong_or_missing_reason_is_never_a_leaving_miss(
    reason: LeavingReason | None, reported: str | None
) -> None:
    # owner, 2026-11-20: reported apart, if at all
    reading = Reading(GOING, reading_of(ChildIntent.LEAVING, reason=reason))
    assert reading.wrong == []
    assert reading.reason_wrong == reported
    run = ChildBankScorer.score([reading])
    assert (run.right, run.misses) == (1, [])


def test_the_reasons_are_tallied_apart_and_only_for_leaving_read_as_leaving() -> None:
    readings = [
        Reading(GOING, reading_of(ChildIntent.LEAVING, reason=LeavingReason.PLAY)),
        Reading(GOING, reading_of(ChildIntent.LEAVING, reason=None)),
        Reading(GOING, reading_of(ChildIntent.TALK)),  # the intent missed: scored, not here
        Reading(case_of(), reading_of()),  # not a leaving case
    ]
    tally = ChildBankScorer.reasons(readings)
    assert (tally.right, tally.of) == (1, 2)
    [miss] = tally.misses
    assert (miss.text, miss.wrong) == ("main khelne ja rhi hoon", "leaving_reason none, not play")
    report = tally.report()
    assert "## Why the child is going (not scored)" in report
    assert "1/2 reasons as expected (50%)" in report
    assert "- (hinglish) 'main khelne ja rhi hoon': leaving_reason none, not play" in report
    run = ChildBankScorer.score(readings)
    assert [miss.wrong for miss in run.misses] == ["intent talk, not leaving"]  # only that


def test_a_run_with_no_leaving_read_says_so() -> None:
    tally = ChildBankScorer.reasons([Reading(case_of(), reading_of())])
    assert (tally.right, tally.of) == (0, 0)
    assert "No leaving case was read as leaving." in tally.report()


async def test_every_reason_missing_still_passes_the_bank() -> None:
    # the reason is never scored: a model that gives none still reads every case right
    readings: dict[CaseKey, Scripted] = {
        key(case): expected(case).model_copy(update={"leaving_reason": None}) for case in BANK.cases
    }
    runner, _ = runner_for(readings)
    read = await runner.read_all(BANK.cases, repeat=1)
    run = ChildBankScorer.score(read)
    assert (run.right, run.readings) == (len(BANK.cases), len(BANK.cases))
    assert ChildBankScorer.exit_status(run) == 0
    tally = ChildBankScorer.reasons(read)
    leaving = [case for case in BANK.cases if case.intent is ChildIntent.LEAVING]
    assert (tally.right, tally.of) == (0, len(leaving))


def test_every_leaving_case_says_why_and_every_reason_is_covered() -> None:
    leaving = [case for case in BANK.cases if case.intent is ChildIntent.LEAVING]
    assert [case.text for case in leaving if case.leaving_reason is None] == []
    assert {case.leaving_reason for case in leaving} == set(LeavingReason)
    others = [case for case in BANK.cases if case.intent is not ChildIntent.LEAVING]
    assert [case.text for case in others if case.leaving_reason is not None] == []


def test_a_failed_reading_is_one_miss_that_says_why() -> None:
    case = case_of()
    failed = ChildIntentRead(
        intent=None,
        asked_language=None,
        leaving_after=False,
        handover_after=False,
        leaving_reason=None,
        usage=None,
        prompt_versions={},
        failed="child_intent_failed=ProviderUnavailable",
    )
    assert Reading(case, failed).wrong == [
        "failed (child_intent_failed=ProviderUnavailable), not talk"
    ]


def test_unsure_read_as_talk_is_a_miss() -> None:
    # strict: the bank measures the reading, not whether the reply would have come out the same
    case = case_of(ChildIntent.UNSURE, "wo wala")
    assert Reading(case, read_as(case_of(ChildIntent.TALK))).wrong == ["intent talk, not unsure"]


def test_the_score_counts_per_language_and_per_intent() -> None:
    talk = case_of(ChildIntent.TALK, "chaand kyun?")
    leaving = ChildCase(text="I have to go", intent=ChildIntent.LEAVING, lang="english")
    run = ChildBankScorer.score([Reading(talk, read_as(talk)), Reading(leaving, read_as(talk))])
    assert run.bank == BANK_NAME
    assert (run.readings, run.right) == (2, 1)
    assert run.total_by_lang == Counter({"hinglish": 1, "english": 1})
    assert run.right_by_lang == Counter({"hinglish": 1})
    assert run.total_by_section == Counter({"talk": 1, "leaving": 1})
    assert run.right_by_section == Counter({"talk": 1})
    [miss] = run.misses
    assert (miss.text, miss.lang, miss.wrong) == (
        "I have to go",
        "english",
        "intent talk, not leaving",
    )
    report = BankResults.report(run)
    assert "| leaving | 0 | 1 | 0% |" in report
    assert "| talk | 1 | 1 | 100% |" in report


# --- the cutoff: 85% and above exits 0, below exits 1 -----------------------------------------


@pytest.mark.parametrize(
    ("right", "readings", "status"),
    [
        (100, 100, 0),
        (85, 100, 0),  # exactly at the cutoff
        (84, 100, 1),
        (17, 20, 0),  # 85.0%
        (16, 20, 1),  # 80.0%
        (34, 40, 0),  # 85.0%
        (33, 39, 1),  # 84.6%
        (98, 115, 0),  # 85.2%: the bank's size
        (97, 115, 1),  # 84.3%
        (0, 115, 1),
    ],
)
def test_the_exit_status_follows_the_85_percent_cutoff(
    right: int, readings: int, status: int
) -> None:
    assert ChildBankScorer.exit_status(run_of(right, readings)) == status


def test_a_run_with_no_readings_fails() -> None:
    assert ChildBankScorer.exit_status(ChildBankScorer.score([])) == 1


@given(st.integers(min_value=1, max_value=400).flatmap(
    lambda readings: st.tuples(st.integers(min_value=0, max_value=readings), st.just(readings))
))  # fmt: skip
def test_a_run_passes_exactly_when_85_in_100_or_more_are_right(counts: tuple[int, int]) -> None:
    right, readings = counts
    assert ChildBankScorer.passes(run_of(right, readings)) is (right * 100 >= 85 * readings)


def test_the_cutoff_is_the_owners() -> None:
    assert Fraction(85, 100) == TARGET


# --- the runner, end to end with a fake model -----------------------------------------------


async def test_the_whole_bank_read_right_passes_and_every_case_is_read_once() -> None:
    runner, model = runner_for({key(case): expected(case) for case in BANK.cases})
    readings = await runner.read_all(BANK.cases, repeat=1)
    run = ChildBankScorer.score(readings)
    assert (run.readings, run.right) == (len(BANK.cases), len(BANK.cases))
    assert ChildBankScorer.exit_status(run) == 0
    assert len(model.prompts) == len(BANK.cases)


async def test_marg_said_goes_to_the_reader_when_a_case_gives_it() -> None:
    runner, model = runner_for({key(case): expected(case) for case in BANK.cases})
    with_context = [case for case in BANK.cases if case.marg_said]
    without = [case for case in BANK.cases if not case.marg_said][:1]
    await runner.read_all([*with_context, *without], repeat=1)
    shown = {(slot(CHILD_MESSAGE, prompt), slot(MARG_SAID, prompt)) for prompt in model.prompts}
    assert with_context
    for case in with_context:
        assert (case.text, case.marg_said) in shown
    assert (without[0].text, "") in shown


async def test_repeat_reads_every_case_that_many_times() -> None:
    cases = BANK.cases[:3]
    runner, model = runner_for({key(case): expected(case) for case in cases})
    readings = await runner.read_all(cases, repeat=2)
    assert len(readings) == 6
    assert len(model.prompts) == 6
    assert Counter(reading.case.text for reading in readings) == Counter(
        {case.text: 2 for case in cases}
    )


@pytest.mark.parametrize("repeat", [0, -1])
async def test_a_repeat_below_one_is_refused(repeat: int) -> None:
    runner, model = runner_for({})
    with pytest.raises(ValueError, match=f"repeat must be at least 1, not {repeat}"):
        await runner.read_all(BANK.cases, repeat=repeat)
    assert model.prompts == []


async def test_failed_readings_count_as_misses_and_fail_the_run_below_the_cutoff() -> None:
    # 18 of 115 failing (the model down) leaves 97 right: 84.3%, below the cutoff
    failing = {key(case) for case in BANK.cases[:18]}
    readings: dict[CaseKey, Scripted] = {
        key(case): ProviderUnavailable("503", provider="meta_model_api")
        if key(case) in failing
        else expected(case)
        for case in BANK.cases
    }
    runner, _ = runner_for(readings)
    run = ChildBankScorer.score(await runner.read_all(BANK.cases, repeat=1))
    assert len(BANK.cases) == 115
    assert (run.right, len(run.misses)) == (97, 18)
    assert all("failed (child_intent_failed=ProviderUnavailable)" in m.wrong for m in run.misses)
    assert ChildBankScorer.exit_status(run) == 1


async def test_a_misread_intent_shows_in_the_per_intent_table() -> None:
    # every leaving case read as talk: leaving at 0%, the rest right
    readings: dict[CaseKey, Scripted] = {}
    for case in BANK.cases:
        if case.intent is ChildIntent.LEAVING:
            readings[key(case)] = expected(case_of(ChildIntent.TALK))
        else:
            readings[key(case)] = expected(case)
    runner, _ = runner_for(readings)
    run = ChildBankScorer.score(await runner.read_all(BANK.cases, repeat=1))
    leaving = run.total_by_section["leaving"]
    assert run.right_by_section["leaving"] == 0
    assert run.right == len(BANK.cases) - leaving
    assert f"| leaving | 0 | {leaving} | 0% |" in BankResults.report(run)


def test_the_owners_checks_are_in_the_bank() -> None:
    # 2026-11-20: a question with a leaving word is a question; water is going; "na" switches
    by_text = {case.text: case for case in BANK.cases}
    assert by_text["bye bolne ke baad suraj kahan jata hai?"].intent is ChildIntent.TALK
    assert not by_text["bye bolne ke baad suraj kahan jata hai?"].leaving_after
    assert by_text["mujhe paani peena hai"].intent is ChildIntent.LEAVING
    english = by_text["English mein bolo na"]
    assert (english.intent, english.asked) == (ChildIntent.LANGUAGE_SWITCH, Language.ENGLISH)
