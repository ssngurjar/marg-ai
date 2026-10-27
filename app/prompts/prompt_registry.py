"""PromptRegistry: versioned prompt templates rendered into requests (s05 §4.3, CLAUDE.md §10).

One file per prompt, `app/prompts/<id>.md.j2`, with TOML frontmatter between `+++` lines and the
line `=== USER ===` between the system part and the user part. Every template is checked at
startup against the output type its spec declares, so a broken prompt fails the deploy, not a
turn. User text never reaches a template raw: `UserSlot.wrap` escapes and delimits it first.
The model comes from settings; reasoning effort from MODEL_REASONING_EFFORT (spike E).
"""

import re
import tomllib
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Final

from jinja2 import Environment, StrictUndefined, UndefinedError
from pydantic import BaseModel, ConfigDict, ValidationError

from app.core.errors import ConfigError
from app.core.strict_json_schema import StrictJsonSchema
from app.core.types import ReasoningEffort
from app.providers.ports import GenerationRequest, RenderedPrompt

PROMPTS_DIRECTORY: Final = Path(__file__).parent
USER_SEPARATOR: Final = "=== USER ==="
_FRONTMATTER: Final = re.compile(r"\A\+\+\+\n(.*?)\n\+\+\+\n(.*)\Z", re.DOTALL)

type TemplateValue = str | int | bool | Sequence[str] | Mapping[str, str] | None


class _Frontmatter(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    version: str
    model_setting: str  # e.g. "MODEL_TEXT": which setting names the model
    max_output_tokens: int
    output_model: str


@dataclass(frozen=True, slots=True)
class PromptSpec[OutputT: BaseModel]:
    prompt_id: str
    output_type: type[OutputT]


@dataclass(frozen=True, slots=True)
class WrappedSlot:
    text: str
    truncated: bool


@dataclass(frozen=True, slots=True)
class RenderedRequest[OutputT: BaseModel]:
    request: GenerationRequest[OutputT]
    truncated_slots: tuple[str, ...]  # slot names cut at USER_SLOT_MAX_CHARS (recorded in detail)


@dataclass(frozen=True, slots=True)
class _Template:
    frontmatter: _Frontmatter
    system: str
    user: str


@dataclass(frozen=True, slots=True)
class PromptSettings:
    models: Mapping[str, str]  # setting name → model id, e.g. {"MODEL_TEXT": "muse-spark-1.3"}
    reasoning_effort: ReasoningEffort
    user_slot_max_chars: int


class UserSlot:
    """User text, made safe to place in a prompt (s05 §4.3)."""

    _NAME: ClassVar[re.Pattern[str]] = re.compile(r"[a-z_]+")

    @staticmethod
    def wrap(name: str, text: str, max_chars: int) -> WrappedSlot:
        if not UserSlot._NAME.fullmatch(name):
            raise ConfigError(f"slot name {name!r} must match [a-z_]+")
        cleaned = unicodedata.normalize("NFC", text)
        cleaned = "".join(
            character
            for character in cleaned
            if character in "\n\t" or unicodedata.category(character) != "Cc"
        )
        cleaned = (
            cleaned.replace("<", "\u2039")
            .replace(">", "\u203a")
            .replace(USER_SEPARATOR, "=== user ===")
        )
        truncated = len(cleaned) > max_chars
        if truncated:
            cut = cleaned[:max_chars]
            last_space = cut.rfind(" ")
            cleaned = (cut[:last_space] if last_space > 0 else cut) + " […]"
        return WrappedSlot(text=f"<{name}>\n{cleaned}\n</{name}>", truncated=truncated)


class PromptRegistry:
    def __init__(
        self,
        specs: Sequence[PromptSpec[BaseModel]],
        settings: PromptSettings,
        directory: Path = PROMPTS_DIRECTORY,
    ) -> None:
        self._settings = settings
        self._environment = Environment(
            undefined=StrictUndefined,
            autoescape=False,  # noqa: S701  # prompts are plain text, never HTML; user text is pre-escaped
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._templates = self._load(specs, directory)

    def render[OutputT: BaseModel](
        self,
        spec: PromptSpec[OutputT],
        *,
        system_vars: Mapping[str, TemplateValue],
        user_vars: Mapping[str, str],
        semantic_check: Callable[[OutputT], list[str]] | None = None,
    ) -> RenderedRequest[OutputT]:
        template = self._templates[spec.prompt_id]
        frontmatter = template.frontmatter
        wrapped = {
            name: UserSlot.wrap(name, text, self._settings.user_slot_max_chars)
            for name, text in user_vars.items()
        }
        context = {
            "system": dict(system_vars),
            "user": {name: slot.text for name, slot in wrapped.items()},
        }
        try:
            system = self._environment.from_string(template.system).render(context)
            user = self._environment.from_string(template.user).render(context)
        except UndefinedError as exc:
            raise ConfigError(
                f"prompt {frontmatter.id} v{frontmatter.version}: {exc.message}"
            ) from exc
        request = GenerationRequest[OutputT](
            prompt=RenderedPrompt(
                prompt_id=frontmatter.id,
                prompt_version=frontmatter.version,
                system=system,
                user=user,
            ),
            output_type=spec.output_type,
            model=self._settings.models[frontmatter.model_setting],
            reasoning_effort=self._settings.reasoning_effort,
            max_output_tokens=frontmatter.max_output_tokens,
            semantic_check=semantic_check,
        )
        truncated = tuple(name for name, slot in wrapped.items() if slot.truncated)
        return RenderedRequest(request=request, truncated_slots=truncated)

    def _load(
        self, specs: Sequence[PromptSpec[BaseModel]], directory: Path
    ) -> dict[str, _Template]:
        """Read and check every template (s05 §4.3 startup checks)."""
        templates: dict[str, _Template] = {}
        files = {path.name.removesuffix(".md.j2"): path for path in directory.glob("*.md.j2")}
        spec_ids = {spec.prompt_id for spec in specs}
        if missing := spec_ids - files.keys():
            raise ConfigError(f"prompt specs without a template: {', '.join(sorted(missing))}")
        if unused := files.keys() - spec_ids:
            raise ConfigError(f"prompt templates without a spec: {', '.join(sorted(unused))}")
        for spec in specs:
            template = self._parse(files[spec.prompt_id])
            frontmatter = template.frontmatter
            if frontmatter.id != spec.prompt_id:
                raise ConfigError(f"{spec.prompt_id}.md.j2 declares id {frontmatter.id!r}")
            if frontmatter.output_model != spec.output_type.__name__:
                raise ConfigError(
                    f"prompt {spec.prompt_id}: output_model {frontmatter.output_model} doesn't "
                    f"match {spec.output_type.__name__}"
                )
            if frontmatter.model_setting not in self._settings.models:
                raise ConfigError(f"prompt {spec.prompt_id}: unknown {frontmatter.model_setting}")
            StrictJsonSchema.from_model(spec.output_type)
            templates[spec.prompt_id] = template
        return templates

    @staticmethod
    def _parse(path: Path) -> _Template:
        match = _FRONTMATTER.match(path.read_text(encoding="utf-8"))
        if match is None:
            raise ConfigError(f"{path.name}: missing +++ frontmatter")
        try:
            frontmatter = _Frontmatter.model_validate(tomllib.loads(match.group(1)))
        except (tomllib.TOMLDecodeError, ValidationError) as exc:
            raise ConfigError(f"{path.name}: invalid frontmatter") from exc
        if not frontmatter.version.strip():
            raise ConfigError(f"{path.name}: version is empty")
        body = match.group(2)
        if body.count(USER_SEPARATOR) != 1:
            raise ConfigError(f"{path.name}: needs exactly one {USER_SEPARATOR!r} line")
        system, user = body.split(USER_SEPARATOR)
        return _Template(
            frontmatter=frontmatter, system=system.strip() + "\n", user=user.strip() + "\n"
        )
