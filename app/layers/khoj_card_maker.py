"""KhojCardMaker: an illustrated card of a child's discovery (s10b §4.13, C6).

Two calls: a small Muse Spark one for the caption (headline and line, in the parent's
language), and Muse Image for the picture (the fixed style plus the activity's scene). The
caller checks both with safety before anything is stored or sent.
"""

from dataclasses import dataclass
from typing import ClassVar, Final

from pydantic import BaseModel, ConfigDict, Field

from app.constants.child_hazards import CHILD_HAZARD_WORDS
from app.constants.journey_words import CAREER_WORDS, LABEL_WORDS
from app.constants.khoj_card_style import ACTIVITY_SCENES, CARD_STYLE, DOMAIN_SCENES
from app.domain.enums import CuriosityDomain, Language
from app.domain.models.message import ImageClip
from app.domain.models.reply import LocalisedReply
from app.domain.models.usage import StepUsage
from app.domain.rules.child_hazard_matcher import ChildHazardMatcher
from app.domain.rules.phrase_finder import PhraseFinder
from app.domain.rules.register_detector import RegisterDetector
from app.layers.parent_question_layer import ParentQuestionLayer
from app.prompts.prompt_registry import PromptRegistry, PromptSpec
from app.providers.ports import ImageGenerator, LanguageModel


class KhojCardText(BaseModel):
    """The caption (strict schema)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    headline: str = Field(min_length=1, max_length=60)
    line: str = Field(min_length=1, max_length=90)


KHOJ_CARD_TEXT: Final = PromptSpec(prompt_id="khoj_card_text", output_type=KhojCardText)


@dataclass(frozen=True, slots=True)
class CardRequest:
    activity_id: str
    activity_title: str
    domains: list[CuriosityDomain]
    child_nickname: str | None
    summary: str  # the reflection's neutral English summary of what the child did
    register: Language


@dataclass(frozen=True, slots=True)
class KhojCard:
    caption: LocalisedReply  # headline and line, sent as the image's caption
    image: ImageClip
    usages: list[StepUsage]
    prompt_versions: dict[str, str]


class KhojCardMaker:
    GENERIC_SCENE: ClassVar[str] = "a child's small discovery in a village courtyard"

    def __init__(
        self, llm: LanguageModel, images: ImageGenerator, registry: PromptRegistry
    ) -> None:
        self._llm = llm
        self._images = images
        self._registry = registry

    async def make(self, request: CardRequest) -> KhojCard:
        """Raises ProviderError when either call fails."""
        rendered = self._registry.render(
            KHOJ_CARD_TEXT,
            system_vars={
                "title": request.activity_title,
                "language_rule": ParentQuestionLayer.LANGUAGE_RULES[request.register].replace(
                    "answer and try_this", "headline and line"
                ),
            },
            user_vars={"child": request.child_nickname or "", "summary": request.summary},
            semantic_check=lambda text: _CaptionChecks.problems(text, request.register),
        )
        text_result = await self._llm.generate(rendered.request)
        image, image_usage = await self._images.generate(self.image_prompt(request))
        caption = f"{text_result.output.headline}\n{text_result.output.line}"
        return KhojCard(
            caption=LocalisedReply(
                text=caption,
                spoken_text=caption,  # a card is never spoken
                reply_register=request.register,
                citations=[],
                buttons=[],
            ),
            image=image,
            usages=[text_result.usage, image_usage],
            prompt_versions={
                rendered.request.prompt.prompt_id: rendered.request.prompt.prompt_version
            },
        )

    @staticmethod
    def image_prompt(request: CardRequest) -> str:
        """The fixed style plus a scene: never the child's name or the parent's words."""
        scene = ACTIVITY_SCENES.get(request.activity_id)
        if scene is None and request.domains:
            scene = DOMAIN_SCENES[request.domains[0]]
        return CARD_STYLE + (scene or KhojCardMaker.GENERIC_SCENE)


class _CaptionChecks:
    @staticmethod
    def problems(text: KhojCardText, register: Language) -> list[str]:
        joined = f"{text.headline} {text.line}"
        problems: list[str] = []
        if PhraseFinder.contains_any(joined, LABEL_WORDS):
            problems.append("text: labels the child")
        if PhraseFinder.contains_any(joined, CAREER_WORDS):
            problems.append("text: mentions careers, jobs or exams")
        if ChildHazardMatcher.undeclared(joined, CHILD_HAZARD_WORDS, ()):
            problems.append("text: mentions a danger for a young child")
        for problem in RegisterDetector.script_problems(joined, joined, register):
            if problem.startswith("text:"):  # a card has no spoken text to check
                problems.append(problem)
        return problems
