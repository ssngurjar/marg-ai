"""ChildTalkLayer: a child talks to Marg.ai directly, with the parent's consent (s10b §4.16, C13).

    start    `kid:start[:<child>]` or "Main Munni hoon": consent and the cooldown are checked;
             a session opens (ChildSessionStart). A question in the same message is answered.
    turn     the child's message → child_talk prompt → a very short, true, kind reply in the
             child's register, ending "Mummy-Papa ko bhi batana" (added by code), voice always
    end      at the turn or time limit, or "bye"/"bas": a kind goodbye with a find-out activity,
             ChildSessionEnd, and a short summary for the parent (topics, never the child's words)

Inside a session nothing changes the account: deletion, adding a child and any other button get
"Mummy-Papa karenge" (C16). Asking for a language ("Hindi") changes only this session's replies.
A reply to a child follows what they asked for, then how they write, then the family's language;
a child who tapped their name on "Who's writing?" gets the message they came with answered.
Crisis in a child's words is handled before this layer, by the orchestrator, with child-worded
fixed text (s07).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import ClassVar, Final, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.constants.child_hazards import (
    CHILD_HAZARD_WORDS,
    CHILD_SAFE_TOOL_PHRASES,
    NEVER_TALK_ABOUT,
    TALKABLE_HAZARDS,
)
from app.constants.child_safety_words import (
    CHILD_MANIPULATION_PHRASES,
    CHILD_PERSONAL_TOPICS,
    QUESTION_WORDS,
)
from app.constants.child_talk_copy import (
    ASK_A_GROWNUP,
    CHILD_FALLBACK,
    CHILD_GOODBYE,
    CHILD_HELLO,
    CHILD_LANGUAGE_SWITCHED,
    CHILD_REFUSE_DANGER,
    CHILD_REFUSE_HURTING,
    CHILD_REFUSE_OTHER,
    CHILD_TALK_COOLDOWN,
    CHILD_TALK_NOT_ENABLED,
    CHILD_TALK_ON_BUTTON,
    PARENT_SUMMARY,
    PARENT_SUMMARY_NO_TOPICS,
    TELL_YOUR_PARENTS,
    TOPIC_LABELS,
    UNNAMED_CHILD_NAME,
    WHICH_CHILD_IS_TALKING,
    WHO_IS_WRITING,
)
from app.constants.journey_words import CAREER_WORDS, EXPOSURE_PUSH_WORDS, LABEL_WORDS
from app.constants.onboarding_copy import CHILD_TALK_YES
from app.core.errors import ProviderResponseInvalid
from app.domain.enums import (
    ChildSessionEndReason,
    CuriosityDomain,
    Language,
    SafetyCategory,
    StepOutcome,
)
from app.domain.models.child_session import ChildSession
from app.domain.models.curiosity import CuriositySource
from app.domain.models.learner import Learner
from app.domain.models.reply import CanonicalReply, ReplyButton
from app.domain.models.turn import TurnContext
from app.domain.models.usage import StepUsage
from app.domain.models.writes import (
    ChildSessionEnd,
    ChildSessionLanguage,
    ChildSessionStart,
    ChildTalkTurn,
)
from app.domain.rules.activity_validator import ActivityValidator
from app.domain.rules.child_hazard_matcher import ChildHazardMatcher
from app.domain.rules.child_question_detector import ChildQuestionDetector
from app.domain.rules.child_reply_matcher import ChildReplyMatcher
from app.domain.rules.child_session_rules import KID_START, ChildSessionLimits, ChildSessionRules
from app.domain.rules.onboarding_answer_parser import OnboardingAnswerParser
from app.domain.rules.phrase_finder import PhraseFinder
from app.domain.rules.register_detector import RegisterDetector
from app.domain.rules.sentence_case import SentenceCase
from app.domain.rules.stage_rules import StageRules
from app.layers.layer_result import LayerResult
from app.layers.local_voice import LocalVoice
from app.layers.parent_question_layer import ParentQuestionLayer
from app.prompts.prompt_registry import PromptRegistry, PromptSpec
from app.providers.ports import LanguageModel


class ChildReply(BaseModel):
    """The model's reply to the child (strict schema: every field required)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    confident: bool
    answer: str = Field(min_length=1, max_length=240)
    find_out: str = Field(max_length=160)
    ask_back: str = Field(min_length=1, max_length=120)
    who_explores_this: str = Field(max_length=160)
    topic: CuriosityDomain | None
    spoken_text: str = Field(min_length=1, max_length=900)


CHILD_TALK: Final = PromptSpec(prompt_id="child_talk", output_type=ChildReply)
CHILD_REDIRECT: Final = PromptSpec(prompt_id="child_redirect", output_type=ChildReply)
type RedirectReason = Literal["hurting", "weapons", "rules", "unanswered"]
YOUNGEST_BAND_MAX_AGE: Final = 5  # 3-5: at most 8 words a sentence; 6-8: at most 12


@dataclass(frozen=True, slots=True)
class _Answer:
    text: CanonicalReply
    topic: CuriosityDomain | None
    usages: list[StepUsage]
    prompt_versions: dict[str, str]
    degraded_reason: str | None


class ChildTalkLayer:
    WORDS_PER_SENTENCE: ClassVar[dict[Literal["young", "older"], int]] = {"young": 8, "older": 12}
    REDIRECT_REASONS: ClassVar[dict[SafetyCategory, RedirectReason]] = {
        SafetyCategory.VIOLENT_CRIMES: "hurting",
        SafetyCategory.INDISCRIMINATE_WEAPONS: "weapons",
        SafetyCategory.NON_VIOLENT_CRIMES: "rules",
    }
    """A child's message blocked only for these gets a model-written redirect instead of a fixed
    refusal (owner, 2026-10-28: "think of how a human mentor would reply"). Everything else
    blocked (sexual content, medical, privacy…) keeps the fixed child refusal."""
    _REASON_ORDER: ClassVar[tuple[RedirectReason, ...]] = ("hurting", "weapons", "rules")

    CARRY_WINDOW: ClassVar[timedelta] = timedelta(minutes=10)
    """How long after "Who's writing?" a tapped name still brings the child's message along."""

    def __init__(
        self, llm: LanguageModel, registry: PromptRegistry, limits: ChildSessionLimits
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._limits = limits

    async def handle(  # noqa: PLR0913  # plus the input check's verdict (owner, 2026-10-28)
        self,
        ctx: TurnContext,
        user_text: str,
        interactive_ids: Sequence[str],
        now: datetime,
        register: Language,
        *,
        blocked: frozenset[SafetyCategory] = frozenset(),
    ) -> LayerResult:
        """Raises ProviderError when the model can't be reached (the orchestrator answers).
        `blocked`: the input check blocked the child's message for these (all in
        REDIRECT_REASONS): the turn gets a redirect, never an answer to what was asked."""
        session = ctx.child_session
        if session is None:
            return await self._start(
                ctx, user_text, interactive_ids, now, register, blocked=blocked
            )
        learner = _learner(ctx.learners, session.learner_id)
        if ChildTalkLayer._is_account_action(user_text, interactive_ids):
            return _fixed(ASK_A_GROWNUP, register)
        if ChildSessionRules.is_over(session, now, self._limits):
            return self._goodbye(session, learner, register, ChildSessionEndReason.TIME_LIMIT, ())
        if ChildSessionRules.says_goodbye(user_text):
            return self._goodbye(session, learner, register, ChildSessionEndReason.CHILD_ENDED, ())
        asked = OnboardingAnswerParser.language_named(user_text)
        if asked is not None:
            switched = _fixed(CHILD_LANGUAGE_SWITCHED, asked)
            language = ChildSessionLanguage(session_id=session.id, language=asked)
            return switched.model_copy(update={"writes": [language]})
        voice = LocalVoice.for_turn(register, ctx, user_text)
        return await self._turn(
            session, learner, user_text, now, register, voice=voice, blocked=blocked
        )

    @staticmethod
    def language_for(ctx: TurnContext, child_words: str, family_language: Language) -> Language:
        """The language of a reply to a child (owner, 2026-10-29): the one they ask for now
        ("Hindi") or asked for earlier in this session; else Hindi words in how they write
        (Devanagari → Hindi, Roman → Hinglish); else the family's. Roman words with no Hindi
        marker aren't evidence of English: "Main Munni hoon" has none."""
        asked = OnboardingAnswerParser.language_named(child_words)
        if asked is not None:
            return asked
        session = ctx.child_session
        if session is not None and session.language is not None:
            return session.language
        written_in = RegisterDetector.detect(child_words)
        if written_in in {Language.HINDI, Language.HINGLISH}:
            return written_in
        return family_language

    @staticmethod
    def words_before_the_name(
        ctx: TurnContext, user_text: str, interactive_ids: Sequence[str], now: datetime
    ) -> str:
        """A child who wrote ("me Munni hoon, aaj kya karein"), was asked "Who's writing?" and
        tapped their name: the message they came with, so it gets answered. "" otherwise."""
        tapped_name = any(button.startswith(KID_START) for button in interactive_ids)
        if user_text or not tapped_name or not ctx.recent_exchanges:
            return ""
        last = ctx.recent_exchanges[-1]
        if now - last.at > ChildTalkLayer.CARRY_WINDOW:
            return ""
        for question in WHO_IS_WRITING.values():
            if last.reply_text.startswith(question.split("{names}")[0]):
                return last.user_text
        return ""

    @staticmethod
    def redirects(categories: frozenset[SafetyCategory]) -> bool:
        """A blocked child message gets a redirect only when every category allows one."""
        return bool(categories) and categories <= frozenset(ChildTalkLayer.REDIRECT_REASONS)

    # --- start --------------------------------------------------------------------------------

    async def _start(  # noqa: PLR0913  # handle's inputs, passed on
        self,
        ctx: TurnContext,
        user_text: str,
        interactive_ids: Sequence[str],
        now: datetime,
        register: Language,
        *,
        blocked: frozenset[SafetyCategory],
    ) -> LayerResult:
        learner = ChildSessionRules.chosen_learner(interactive_ids, user_text, ctx.learners)
        if learner is None:
            return _fixed(WHICH_CHILD_IS_TALKING, register)
        name = learner.nickname or UNNAMED_CHILD_NAME[register]
        if learner.child_talk_consented_at is None:
            button = ReplyButton(
                id=f"{CHILD_TALK_YES}:{learner.id}", title=CHILD_TALK_ON_BUTTON[register]
            )
            return _fixed(CHILD_TALK_NOT_ENABLED, register, (button,), name=name)
        if ChildSessionRules.in_cooldown(ctx.last_child_session_ended_at, now, self._limits):
            return _fixed(CHILD_TALK_COOLDOWN, register)
        session = ChildSession(
            id=uuid4(), learner_id=learner.id, started_at=now, turns_count=0, topics=[]
        )
        start = ChildSessionStart(session_id=session.id, learner_id=learner.id)
        if not blocked and not ChildQuestionDetector.asks(user_text):
            hello = _fixed(CHILD_HELLO, register, name=name)
            return hello.model_copy(update={"writes": [start]})
        voice = LocalVoice.for_turn(register, ctx, user_text)
        result = await self._turn(
            session, learner, user_text, now, register, voice=voice, blocked=blocked
        )
        return result.model_copy(update={"writes": [start, *result.writes]})

    # --- a turn and the goodbye -------------------------------------------------------------------

    async def _turn(  # noqa: PLR0913  # plus the turn's local voice (owner, 2026-10-28)
        self,
        session: ChildSession,
        learner: Learner,
        user_text: str,
        now: datetime,
        register: Language,
        *,
        voice: str,
        blocked: frozenset[SafetyCategory] = frozenset(),
    ) -> LayerResult:
        if blocked:
            reason = ChildTalkLayer._reason(blocked)
            answer = await self._redirect(
                learner, user_text, now, register, voice=voice, reason=reason
            )
        else:
            answer = await self._answer(learner, user_text, now, register, voice)
        counted = ChildTalkTurn(session_id=session.id, topic=answer.topic)
        source = CuriositySource(
            learner_id=learner.id, kind="child_words", hint_domains=[], activity_title=None
        )
        if not ChildSessionRules.is_last_turn(session, self._limits):
            return LayerResult(
                curiosity=source if answer.degraded_reason is None else None,
                reply=answer.text,
                usages=answer.usages,
                prompt_versions=answer.prompt_versions,
                outcome=StepOutcome.DEGRADED if answer.degraded_reason else StepOutcome.OK,
                degraded_reason=answer.degraded_reason,
                writes=[counted],
                hazard_rule=TALKABLE_HAZARDS,  # talked about, never done (d7)
            )
        new_topics = (answer.topic,) if answer.topic else ()
        goodbye = self._goodbye(
            session, learner, register, ChildSessionEndReason.TURN_LIMIT, new_topics
        )
        reply = answer.text.model_copy(
            update={
                "body": f"{answer.text.body}\n\n{goodbye.reply.body}",
                "spoken_text": f"{answer.text.spoken_text} {goodbye.reply.spoken_text}",
            }
        )
        return goodbye.model_copy(
            update={
                "reply": reply,
                "usages": answer.usages,
                "prompt_versions": answer.prompt_versions,
                "writes": [counted, *goodbye.writes],
                "curiosity": source if answer.degraded_reason is None else None,
                "hazard_rule": TALKABLE_HAZARDS,  # the last answer may still talk about one
            }
        )

    def _goodbye(
        self,
        session: ChildSession,
        learner: Learner,
        register: Language,
        reason: ChildSessionEndReason,
        new_topics: Sequence[CuriosityDomain],
    ) -> LayerResult:
        """The goodbye to the child (spoken), then the parent's summary (text only)."""
        summary = ChildTalkLayer.parent_summary(
            learner.nickname, [*session.topics, *new_topics], register
        )
        return LayerResult(
            reply=CanonicalReply(
                body=f"{CHILD_GOODBYE[register]}\n\n{summary}",
                body_language=register,
                spoken_text=CHILD_GOODBYE[_voice_language(register)],
                citations=[],
                buttons=[],
                fixed_kind=None,
            ),
            usages=[],
            prompt_versions={},
            outcome=StepOutcome.OK,
            degraded_reason=None,
            writes=[ChildSessionEnd(session_id=session.id, reason=reason)],
            hazard_rule=frozenset(),
        )

    async def _answer(
        self, learner: Learner, user_text: str, now: datetime, register: Language, voice: str
    ) -> _Answer:
        age = StageRules.age_on(learner.birth_year, now.date())
        band: Literal["young", "older"] = "young" if age <= YOUNGEST_BAND_MAX_AGE else "older"
        max_words = self.WORDS_PER_SENTENCE[band]
        rendered = self._registry.render(
            CHILD_TALK,
            system_vars={
                "language_rule": ParentQuestionLayer.LANGUAGE_RULES[register].replace(
                    "answer and try_this", "answer, find_out and ask_back"
                )
                + f" {voice}",
                "spoken_rule": ParentQuestionLayer.SPOKEN_RULES[register],
                "child_age": age,
                "max_words": max_words,
                "topics": ", ".join(domain.value for domain in CuriosityDomain),
            },
            user_vars={"child": learner.nickname or "", "child_message": user_text},
            semantic_check=lambda reply: _ChildChecks.problems(reply, register, max_words),
        )
        versions = {rendered.request.prompt.prompt_id: rendered.request.prompt.prompt_version}
        try:
            result = await self._llm.generate(rendered.request)
        except ProviderResponseInvalid:
            # Twice-failed checks: a redirect instead (owner, 2026-10-28), then fixed text
            redirect = await self._redirect(
                learner, user_text, now, register, voice=voice, reason="unanswered"
            )
            return _Answer(
                redirect.text,
                redirect.topic,
                redirect.usages,
                {**versions, **redirect.prompt_versions},
                redirect.degraded_reason or "child_redirect_after=ProviderResponseInvalid",
            )
        reply = _ChildText.reply(result.output, register)
        return _Answer(reply, result.output.topic, [result.usage], versions, None)

    async def _redirect(  # noqa: PLR0913  # the same inputs as an answer, plus the reason
        self,
        learner: Learner,
        user_text: str,
        now: datetime,
        register: Language,
        *,
        voice: str,
        reason: RedirectReason,
    ) -> _Answer:
        """What a kind elder says when they won't answer directly: why, gently, and something
        safe to wonder about instead. Fixed text if it fails its checks twice."""
        age = StageRules.age_on(learner.birth_year, now.date())
        band: Literal["young", "older"] = "young" if age <= YOUNGEST_BAND_MAX_AGE else "older"
        max_words = self.WORDS_PER_SENTENCE[band]
        rendered = self._registry.render(
            CHILD_REDIRECT,
            system_vars={
                "language_rule": ParentQuestionLayer.LANGUAGE_RULES[register].replace(
                    "answer and try_this", "answer, find_out and ask_back"
                )
                + f" {voice}",
                "spoken_rule": ParentQuestionLayer.SPOKEN_RULES[register],
                "child_age": age,
                "max_words": max_words,
                "reason": reason,
                "topics": ", ".join(domain.value for domain in CuriosityDomain),
            },
            user_vars={"child": learner.nickname or "", "child_message": user_text},
            semantic_check=lambda reply: _ChildChecks.problems(reply, register, max_words),
        )
        versions = {rendered.request.prompt.prompt_id: rendered.request.prompt.prompt_version}
        try:
            result = await self._llm.generate(rendered.request)
        except ProviderResponseInvalid:
            # Twice-failed checks: a kind fixed reply, never an unchecked one (DEGRADED)
            return _Answer(
                ChildTalkLayer._redirect_fallback(reason, register),
                None,
                [],
                versions,
                "child_fallback=ProviderResponseInvalid",
            )
        reply = _ChildText.reply(result.output, register)
        return _Answer(reply, result.output.topic, [result.usage], versions, None)

    @staticmethod
    def _redirect_fallback(reason: RedirectReason, register: Language) -> CanonicalReply:
        if reason == "unanswered":
            return _child_reply_text(CHILD_FALLBACK[register], None, register)
        copy = {
            "hurting": CHILD_REFUSE_HURTING,
            "weapons": CHILD_REFUSE_DANGER,
            "rules": CHILD_REFUSE_OTHER,
        }[reason]
        voice = _voice_language(register)  # these already send the child to Mummy-Papa
        return CanonicalReply(
            body=copy[register],
            body_language=register,
            spoken_text=copy[voice],
            citations=[],
            buttons=[],
            fixed_kind=None,
        )

    @staticmethod
    def _reason(blocked: frozenset[SafetyCategory]) -> RedirectReason:
        reasons = {ChildTalkLayer.REDIRECT_REASONS[category] for category in blocked}
        for reason in ChildTalkLayer._REASON_ORDER:
            if reason in reasons:
                return reason
        raise ValueError("a redirect needs a category from REDIRECT_REASONS")

    @staticmethod
    def parent_summary(
        nickname: str | None, topics: Sequence[CuriosityDomain], register: Language
    ) -> str:
        """What the child asked about, for the parent: reviewed wording and topic labels only,
        never the child's words. Used at the goodbye, and by maintenance for a session the
        child left without one."""
        return _ParentSummary.text(nickname, topics, register)

    @staticmethod
    def _is_account_action(user_text: str, interactive_ids: Sequence[str]) -> bool:
        """Anything that would change the account (C16): deletion, adding a child, or any
        button but `kid:`. A language request changes only the session (handled before)."""
        if any(not button.startswith(KID_START) for button in interactive_ids):
            return True
        return OnboardingAnswerParser.asks_for_deletion(
            user_text
        ) or OnboardingAnswerParser.asks_to_add_child(user_text)


class _ChildText:
    @staticmethod
    def reply(child_reply: ChildReply, register: Language) -> CanonicalReply:
        parts = [child_reply.answer]
        if child_reply.find_out.strip():
            parts.append(child_reply.find_out)
        parts.append(child_reply.ask_back)
        if child_reply.who_explores_this.strip():
            parts.append(SentenceCase.of(child_reply.who_explores_this))
        return _child_reply_text("\n\n".join(parts), child_reply.spoken_text, register)


def _child_reply_text(body: str, spoken: str | None, register: Language) -> CanonicalReply:
    """A reply to the child: "tell Mummy and Papa too" is added by code to every one."""
    voice = _voice_language(register)
    spoken_body = spoken if spoken is not None else CHILD_FALLBACK[voice]
    return CanonicalReply(
        body=f"{body}\n\n{TELL_YOUR_PARENTS[register]}",
        body_language=register,
        spoken_text=f"{spoken_body} {TELL_YOUR_PARENTS[voice]}",
        citations=[],
        buttons=[],
        fixed_kind=None,
    )


class _ParentSummary:
    @staticmethod
    def text(nickname: str | None, topics: Sequence[CuriosityDomain], register: Language) -> str:
        name = nickname or UNNAMED_CHILD_NAME[register]
        unique_topics = list(dict.fromkeys(topics))
        if not unique_topics:
            return PARENT_SUMMARY_NO_TOPICS[register].format(name=name)
        labels = [TOPIC_LABELS[topic][register] for topic in unique_topics]
        return PARENT_SUMMARY[register].format(name=name, topics=", ".join(labels))


class _ChildChecks:
    """The semantic check: fixed-vocabulary problems for the one repair retry."""

    @staticmethod
    def problems(
        reply: ChildReply,
        register: Language,
        max_words: int,
    ) -> list[str]:
        written = [reply.answer, reply.find_out, reply.ask_back, reply.who_explores_this]
        joined = " ".join(written)
        problems: list[str] = []
        if _ChildChecks._longest_sentence(written) > max_words:
            problems.append(f"text: keep every sentence to at most {max_words} words")
        if ChildReplyMatcher.manipulates(
            f"{joined} {reply.spoken_text}", CHILD_MANIPULATION_PHRASES
        ):
            problems.append("text: talks about secrets or being the child's only friend")
        if ChildReplyMatcher.asks_personal_details(joined, QUESTION_WORDS, CHILD_PERSONAL_TOPICS):
            problems.append("text: asks the child for personal details")
        if ChildHazardMatcher.find(reply.find_out, CHILD_HAZARD_WORDS, CHILD_SAFE_TOOL_PHRASES):
            problems.append("find_out: nothing dangerous, even what the child asked about")
        talked_about = ChildHazardMatcher.find(f"{joined} {reply.spoken_text}", CHILD_HAZARD_WORDS)
        if talked_about & NEVER_TALK_ABOUT:
            problems.append("text: nothing about medicine; say to ask Mummy, Papa or a doctor")
        if ChildHazardMatcher.spoken_only(
            reply.spoken_text, joined, CHILD_HAZARD_WORDS, CHILD_SAFE_TOOL_PHRASES
        ):
            problems.append("spoken_text: names a danger the written text doesn't")
        if ActivityValidator.mentions_buying(written):
            problems.append("text: asks for something to be bought")
        if PhraseFinder.contains_any(joined, LABEL_WORDS):
            problems.append("text: labels the child")
        if PhraseFinder.contains_any(joined, CAREER_WORDS):
            problems.append("text: mentions careers, jobs or exams")
        if PhraseFinder.contains_any(reply.who_explores_this, EXPOSURE_PUSH_WORDS):
            problems.append("who_explores_this: tells the child to become something")
        problems.extend(RegisterDetector.script_problems(joined, reply.spoken_text, register))
        return problems

    @staticmethod
    def _longest_sentence(texts: Sequence[str]) -> int:
        longest = 0
        for text in texts:
            for sentence in ChildReplyMatcher.sentences(text):
                longest = max(longest, len(sentence.split()))
        return longest


def _fixed(
    copy: Mapping[Language, str],
    register: Language,
    buttons: Sequence[ReplyButton] = (),
    name: str = "",
) -> LayerResult:
    """Fixed child-talk copy. The spoken text comes from the voice's own language (Hindi for
    Hinglish) and leaves the nickname out: it may be in Roman letters the Hindi voice can't
    read."""
    return LayerResult(
        reply=CanonicalReply(
            body=copy[register].format(name=name),
            body_language=register,
            spoken_text=copy[_voice_language(register)].format(name=""),
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


def _voice_language(register: Language) -> Language:
    return Language.HINDI if register is Language.HINGLISH else register


def _learner(learners: Sequence[Learner], learner_id: UUID) -> Learner:
    for learner in learners:
        if learner.id == learner_id:
            return learner
    raise ValueError("an open child session always belongs to one of the parent's learners")
