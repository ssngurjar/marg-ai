"""EvalJudge: an LLM reads one reply and decides each must / must_not item (s15 §4.4).

The judge sees the person (from the case's profile), what they said, the reply as sent (and
the text spoken), the route, and the full text of every source the reply cited, so grounding is
checked against real sources, not the judge's memory. It doesn't see the expected route,
register or the deterministic results. Its output must answer every item exactly once (one
repair retry, then the turn is a judge error, counted neither as a pass nor as a fail).

With `repeat` above one, each turn is judged that many times: the majority decides each item
and the median each rubric score.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from statistics import median_low

from app.core.errors import ProviderError
from app.domain.models.eval_judgement import JudgeItem, JudgeScore
from app.evals.golden_case import GoldenCase, TurnExpectation
from app.evals.turn_capture import TurnRecord
from app.prompts.prompt_registry import PromptRegistry, PromptSpec
from app.providers.ports import LanguageModel


@dataclass(frozen=True, slots=True)
class JudgedTurn:
    score: JudgeScore | None  # None: the judge failed (judge_error)
    error: str | None  # what went wrong, fixed vocabulary
    cost_usd: Decimal


class EvalJudge:
    def __init__(
        self,
        llm: LanguageModel,
        registry: PromptRegistry,
        spec: PromptSpec[JudgeScore],
        repeat: int = 1,
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._spec = spec
        self._repeat = repeat

    async def judge(
        self,
        case: GoldenCase,
        said: Sequence[str],
        record: TurnRecord,
        expect: TurnExpectation,
    ) -> JudgedTurn:
        items = expect.judged_items
        kinds = ["must"] * len(expect.must) + ["must_not"] * len(expect.must_not)
        rendered = self._registry.render(
            self._spec,
            system_vars={
                "profile": EvalJudge.describe(case),
                "route": record.route.value if record.route else "not routed",
                "statements": "\n".join(
                    f"{index}. [{kind}] {item}"
                    for index, (kind, item) in enumerate(zip(kinds, items, strict=True))
                ),
                "sources": EvalJudge.sources(record),
            },
            user_vars={
                "conversation": "\n".join(
                    f"{number}. {text}" for number, text in enumerate(said, start=1)
                ),
                "reply": EvalJudge.reply(record),
            },
            semantic_check=lambda score: EvalJudge.problems(score, kinds),
        )
        scores: list[JudgeScore] = []
        cost = Decimal(0)
        for _ in range(self._repeat):
            try:
                result = await self._llm.generate(rendered.request)
            except ProviderError as exc:
                return JudgedTurn(score=None, error=type(exc).__name__, cost_usd=cost)
            cost += result.usage.cost_usd
            scores.append(result.output)
        return JudgedTurn(score=EvalJudge.combine(scores), error=None, cost_usd=cost)

    @staticmethod
    def problems(score: JudgeScore, kinds: Sequence[str]) -> list[str]:
        """Every item answered exactly once, with its kind (the repair retry's vocabulary)."""
        indices = [item.index for item in score.items]
        problems: list[str] = []
        if sorted(indices) != list(range(len(kinds))):
            problems.append(f"items: answer each index 0 to {len(kinds) - 1} exactly once")
        for item in score.items:
            if item.index < len(kinds) and item.kind != kinds[item.index]:
                problems.append(f"item {item.index}: kind is {kinds[item.index]}")
        return problems

    @staticmethod
    def combine(scores: Sequence[JudgeScore]) -> JudgeScore:
        """The majority per item (a tie fails the item) and the median per rubric score."""
        if len(scores) == 1:
            return scores[0]
        items: list[JudgeItem] = []
        for template in sorted(scores[0].items, key=lambda item: item.index):
            answers = [
                item for score in scores for item in score.items if item.index == template.index
            ]
            passed = sum(answer.passed for answer in answers) * 2 > len(answers)
            agreeing = [answer for answer in answers if answer.passed == passed]
            reason = agreeing[0].reason if agreeing else template.reason
            items.append(template.model_copy(update={"passed": passed, "reason": reason}))
        return JudgeScore(
            items=items,
            grounding=median_low(score.grounding for score in scores),
            cultural_resonance=median_low(score.cultural_resonance for score in scores),
            reading_level=median_low(score.reading_level for score in scores),
            actionability=median_low(score.actionability for score in scores),
            safety=median_low(score.safety for score in scores),
        )

    @staticmethod
    def describe(case: GoldenCase) -> str:
        profile = case.profile
        if profile is None:
            return "someone writing to Marg for the first time"
        parts = [f"a {profile.role.value}", f"writes in {profile.language.value}"]
        if profile.grade is not None:
            parts.append(f"class {profile.grade}")
        if profile.subject:
            parts.append(f"teaches {profile.subject}")
        if profile.district:
            parts.append(f"from {profile.district}")
        for child in case.children:
            parts.append(f"child {child.nickname or '(no nickname)'}, aged {child.age}")
        if case.speaker == "learner":
            parts.append("in this conversation the child is talking to Marg directly")
        return ", ".join(parts)

    @staticmethod
    def sources(record: TurnRecord) -> str:
        if not record.sources:
            return "none (Marg was given no sources for this reply)"
        return "\n\n".join(
            f"[{position}] {source.title} ({source.source_url})\n{source.text}"
            for position, source in enumerate(record.sources, start=1)
        )

    @staticmethod
    def reply(record: TurnRecord) -> str:
        spoken = " ".join(record.spoken_texts) or "(no voice note)"
        return f"Reply text:\n{record.reply_text or '(no reply)'}\n\nSpoken text:\n{spoken}"
