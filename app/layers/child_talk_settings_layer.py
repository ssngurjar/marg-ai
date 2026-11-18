"""ChildTalkSettingsLayer: a parent's settings for their children's own talk (s10b §4.16).

    consent   the one-time question whether a child may talk to Marg themselves (C13), with
              its buttons; the answer is onboarding's (`onb:childtalk:`)
    limit     how long each child may talk a day (owner, 2026-11-13): 20 minutes, 30 minutes or
              1 hour on buttons (`jrn:limit:<limit>:<child>`), or typed, with no limit typed
              only ("Munni ka limit hata do"). Asked right after the yes; the parent can see or
              change it any time in words clearly about it (ChildTalkLimitParser).
    time left "Munni ka Marg se kitna time bacha hai?": the child's time today and what's
              left of their limit, from today's sessions (owner, 2026-11-13)

Fixed copy, no model. The limit is the parent's alone: inside a child session every button and
any message about the limit gets "ask Mummy-Papa" (ChildTalkLayer), so a child can't change it.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.constants.child_talk_copy import (
    CHANGE_LIMIT_HINT,
    CHILD_TALK_LIMIT_ASK,
    CHILD_TALK_LIMIT_BUTTON,
    CHILD_TALK_LIMIT_SET,
    CHILD_TALK_LIMIT_WHICH_CHILD,
    CHILD_TALK_NO_LIMIT_SET,
    DAILY_LIMIT_NAMES,
    NO_DAILY_LIMIT,
    NOT_TALKED_TODAY,
    TALKED_TODAY,
    TIME_LEFT_TODAY,
    TIME_USED_UP_TODAY,
    limit_buttons,
    minutes_said,
)
from app.constants.journey_copy import KHOJ_BUTTONS, TODAY_KHOJ_BUTTON, UNNAMED_CHILD
from app.constants.onboarding_copy import CHILD_FALLBACK, COPY
from app.domain.enums import AgeBand, CopyKey, DailyTalkLimit, Language, StepOutcome
from app.domain.models.child_session import ChildSessionSpan, DailyTalkTime
from app.domain.models.learner import Learner
from app.domain.models.reply import CanonicalReply, ReplyButton
from app.domain.models.writes import ChildTalkDailyLimit
from app.domain.rules.child_daily_limit_rules import ChildDailyLimitRules
from app.domain.rules.child_session_rules import ChildSessionLimits
from app.domain.rules.child_talk_limit_parser import ChildTalkLimitParser
from app.domain.rules.stage_rules import StageRules
from app.layers.layer_result import LayerResult

_ASK = "ask"  # `jrn:limit:ask:<child>`: show that child's limit question
_TIME_LEFT = "time"  # `jrn:limit:time:<child>`: how much of that child's time is left today


@dataclass(frozen=True, slots=True)
class ParentTurnFacts:
    """What a child-talk setting reply needs from the parent's turn."""

    learners: Sequence[Learner]
    child_talk_today: Sequence[ChildSessionSpan]  # TurnContext.child_talk_today
    now: datetime
    limits: ChildSessionLimits  # the session cap, for the day's time
    khoj_open: bool  # keep the open khoj's buttons after the reply


@dataclass(frozen=True, slots=True)
class _Request:
    child: Learner | None  # None: not said; the only child who may talk, or ask which
    limit: DailyTalkLimit | None  # to set; None: show the limit and the choices
    time_left: bool  # asks how much of today's time is left or used (reads, never sets)


class ChildTalkSettingsLayer:
    @staticmethod
    def daily_limit(
        facts: ParentTurnFacts, button: str | None, user_text: str, register: Language
    ) -> LayerResult | None:
        """A limit button, a message clearly about the limit, or a question about the time
        left today (ChildTalkLimitParser). None: none of these, or no child on the list could
        talk to Marg (child talk is for 3-8), so the message is answered instead."""
        request = _read(facts.learners, button, user_text)
        if request is None:
            return None
        return _LimitReply.for_request(facts, request, register)

    @staticmethod
    def consent_question(child: Learner, register: Language) -> LayerResult:
        """ "May Munni talk to Marg herself?", with the yes and no buttons for this child."""
        ask = COPY[(CopyKey.ASK_CHILD_TALK, register)]
        buttons = tuple(
            ReplyButton(id=f"{button.id}:{child.id}", title=button.title) for button in ask.buttons
        )
        values = {"child": child.nickname or CHILD_FALLBACK[register]}
        return _fixed(ask.body.format_map(values), register, buttons)


def _read(learners: Sequence[Learner], button: str | None, user_text: str) -> _Request | None:
    if button is not None:
        if not button.startswith(f"{CHILD_TALK_LIMIT_BUTTON}:"):
            return None
        return _LimitButton.read(button, learners)
    child = ChildTalkLimitParser.child_named(user_text, learners)
    if ChildTalkLimitParser.asks_time_left(user_text, learners):
        return _Request(child=child, limit=None, time_left=True)
    if ChildTalkLimitParser.is_about_the_limit(user_text, learners):
        # a question never sets it ("kya 1 ghanta ki limit theek hai?"): it is shown
        asks = ChildTalkLimitParser.asks_a_question(user_text)
        limit = None if asks else ChildTalkLimitParser.limit_named(user_text)
        return _Request(child=child, limit=limit, time_left=False)
    return None


class _LimitButton:
    @staticmethod
    def read(button: str, learners: Sequence[Learner]) -> _Request:
        """`jrn:limit:<limit|ask|time>:<child>` → what was asked for which child; anything not
        understood (an old, edited or another account's button) names no child and sets
        nothing: the parent is asked again."""
        nothing = _Request(child=None, limit=None, time_left=False)
        match button.removeprefix(f"{CHILD_TALK_LIMIT_BUTTON}:").split(":"):
            case [limit_part, child_part]:
                child = _LimitButton._own_child(learners, child_part)
            case _:
                return nothing
        if child is None:
            return nothing  # a limit is never applied to a child the button didn't name
        if limit_part == _TIME_LEFT:
            return _Request(child=child, limit=None, time_left=True)
        if limit_part == _ASK or limit_part not in {limit.value for limit in DailyTalkLimit}:
            return _Request(child=child, limit=None, time_left=False)
        return _Request(child=child, limit=DailyTalkLimit(limit_part), time_left=False)

    @staticmethod
    def _own_child(learners: Sequence[Learner], raw_id: str) -> Learner | None:
        for learner in learners:
            if str(learner.id) == raw_id:
                return learner
        return None


class _LimitReply:
    @staticmethod
    def for_request(
        facts: ParentTurnFacts, request: _Request, register: Language
    ) -> LayerResult | None:
        """Answer, set, or ask what's missing: which child, their consent, or the limit."""
        child = request.child
        if child is None:
            talking = [
                learner for learner in facts.learners if learner.child_talk_consented_at is not None
            ]
            if len(talking) > 1:
                return _LimitReply.which_child(talking, request, facts.now, register)
            if talking:
                child = talking[0]
            else:
                young = _young(facts.learners, facts.now)
                if not young:
                    return None
                child = young[0]
        if child.child_talk_consented_at is None:
            return ChildTalkSettingsLayer.consent_question(child, register)
        after = _after(register, khoj_open=facts.khoj_open)
        if request.time_left:
            return _LimitReply.time_left(child, facts, register, after)
        if request.limit is None:
            return _LimitReply.ask(child, register)
        return _LimitReply.set(child, request.limit, register, after)

    @staticmethod
    def time_left(
        child: Learner,
        facts: ParentTurnFacts,
        register: Language,
        after: Sequence[ReplyButton],
    ) -> LayerResult:
        """ "⏱️ Aaj Munni ne Marg se 14 minute baat ki. Roz ki limit 30 minute hai, toh aaj 16
        minute aur baaki hain.", from today's sessions (reads; writes nothing)."""
        talk_time = ChildDailyLimitRules.talk_time(
            child, facts.child_talk_today, facts.now, facts.now, facts.limits
        )
        name = _name(child, register)
        if talk_time.used > timedelta(0):
            used = minutes_said(talk_time.used, register)
            talked = TALKED_TODAY[register].format(child=name, used=used)
        else:
            talked = NOT_TALKED_TODAY[register].format(child=name)
        body = f"{talked} {_LimitReply.what_is_left(talk_time, register)}"
        return _fixed(f"{body} {CHANGE_LIMIT_HINT[register]}", register, after)

    @staticmethod
    def what_is_left(talk_time: DailyTalkTime, register: Language) -> str:
        if talk_time.limit is DailyTalkLimit.NO_LIMIT:
            return NO_DAILY_LIMIT[register]
        limit = DAILY_LIMIT_NAMES[talk_time.limit][register]
        if ChildDailyLimitRules.is_used_up(talk_time):
            return TIME_USED_UP_TODAY[register].format(limit=limit)
        left_minutes = ChildDailyLimitRules.minutes_left_shown(talk_time) or 0
        # under a minute left but not used up: said as "less than a minute"
        left = minutes_said(timedelta(minutes=left_minutes), register)
        return TIME_LEFT_TODAY[register].format(limit=limit, left=left)

    @staticmethod
    def ask(child: Learner, register: Language) -> LayerResult:
        """The three limits on buttons, the child's limit now, and how to type "no limit"."""
        body = CHILD_TALK_LIMIT_ASK[register].format(
            child=_name(child, register),
            current=DAILY_LIMIT_NAMES[ChildDailyLimitRules.chosen(child)][register],
        )
        return _fixed(body, register, limit_buttons(str(child.id), register))

    @staticmethod
    def set(
        child: Learner, chosen: DailyTalkLimit, register: Language, after: Sequence[ReplyButton]
    ) -> LayerResult:
        name = _name(child, register)
        if chosen is DailyTalkLimit.NO_LIMIT:
            body = CHILD_TALK_NO_LIMIT_SET[register].format(child=name)
        else:
            limit = DAILY_LIMIT_NAMES[chosen][register]
            body = CHILD_TALK_LIMIT_SET[register].format(child=name, limit=limit)
        write = ChildTalkDailyLimit(learner_id=child.id, limit=chosen)
        return _fixed(body, register, after).model_copy(update={"writes": [write]})

    @staticmethod
    def which_child(
        talking: Sequence[Learner], request: _Request, now: datetime, register: Language
    ) -> LayerResult:
        """One button per child who can talk; what was asked (a limit, the time left) rides
        along."""
        if request.time_left:
            limit_part = _TIME_LEFT
        elif request.limit is not None:
            limit_part = request.limit.value
        else:
            limit_part = _ASK
        buttons = tuple(
            ReplyButton(
                id=f"{CHILD_TALK_LIMIT_BUTTON}:{limit_part}:{learner.id}",
                title=_button_title(learner, now, register),
            )
            for learner in talking
        )
        return _fixed(CHILD_TALK_LIMIT_WHICH_CHILD[register], register, buttons)


def _after(register: Language, *, khoj_open: bool) -> tuple[ReplyButton, ...]:
    """What comes next: the open khoj's buttons, or today's khoj."""
    return KHOJ_BUTTONS[register] if khoj_open else (TODAY_KHOJ_BUTTON[register],)


def _young(learners: Sequence[Learner], now: datetime) -> list[Learner]:
    return [
        learner
        for learner in learners
        if StageRules.age_band(learner.birth_year, now.date()) is AgeBand.FOUNDATIONAL_3_8
    ]


def _name(child: Learner, register: Language) -> str:
    return child.nickname or CHILD_FALLBACK[register]


def _button_title(child: Learner, now: datetime, register: Language) -> str:
    age = StageRules.age_on(child.birth_year, now.date())
    return (child.nickname or UNNAMED_CHILD[register].format(age=age))[:20]


def _fixed(body: str, register: Language, buttons: Sequence[ReplyButton]) -> LayerResult:
    """A reply to the parent that needs no model: fixed copy, checked like any other reply."""
    return LayerResult(
        reply=CanonicalReply(
            body=body,
            body_language=register,
            spoken_text=None,
            citations=[],
            buttons=list(buttons),
            fixed_kind=None,
        ),
        usages=[],
        prompt_versions={},
        outcome=StepOutcome.OK,
        degraded_reason=None,
        hazard_rule=frozenset(),
    )
