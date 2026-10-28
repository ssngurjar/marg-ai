"""CorpusLoader: the corpus files, validated before anything is ingested (s11 §4.1).

One markdown file per official page, at `corpus/<topic>/<slug>.md`, with YAML frontmatter. Every
file is checked and every problem is listed, file by file, in one CorpusValidationError: a bad
file stops the whole ingestion before a single row is written. `corpus/SOURCES.md` and
`corpus/curriculum/` aren't corpus and are skipped by name.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated, ClassVar, Final, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    ValidationError,
    field_validator,
)

from app.core.errors import CorpusValidationError
from app.domain.enums import CorpusTopic

CORPUS_DIRECTORY: Final = Path(__file__).resolve().parents[2] / "corpus"

type Keyword = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
type Grade = Annotated[int, Field(ge=1, le=12)]


class CorpusFrontmatter(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(min_length=5, max_length=120)
    source_url: HttpUrl
    retrieved_on: date
    topic: CorpusTopic
    grades: list[Grade] = Field(default_factory=list)
    keywords: list[Keyword] = Field(min_length=1, max_length=15)
    language: Literal["english", "hindi"] = "english"

    @field_validator("source_url")
    @classmethod
    def _https_only(cls, url: HttpUrl) -> HttpUrl:
        if url.scheme != "https":
            raise ValueError("must be https")
        return url


@dataclass(frozen=True, slots=True)
class CorpusFile:
    path: str  # repo-relative, posix: "corpus/scholarships/nmms.md"
    frontmatter: CorpusFrontmatter
    body: str
    content_sha256: str


class CorpusLoader:
    MAX_AGE: ClassVar[timedelta] = timedelta(days=365)
    """A source older than this at ingest is refused: facts like dates and amounts go stale."""
    SKIPPED_FILES: ClassVar[frozenset[str]] = frozenset({"SOURCES.md"})
    SKIPPED_FOLDERS: ClassVar[frozenset[str]] = frozenset({"curriculum"})
    HEADING: ClassVar[re.Pattern[str]] = re.compile(r"^##+ \S", re.MULTILINE)
    RAW_HTML: ClassVar[re.Pattern[str]] = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")
    FRONTMATTER: ClassVar[re.Pattern[str]] = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)

    @staticmethod
    def load(today: date, root: Path = CORPUS_DIRECTORY) -> list[CorpusFile]:
        """Every corpus file under `root`, sorted by path. Raises CorpusValidationError listing
        every invalid file and why."""
        files: list[CorpusFile] = []
        problems: list[str] = []
        for path in CorpusLoader.corpus_paths(root):
            relative = path.relative_to(root.parent).as_posix()
            try:
                files.append(CorpusLoader.parse(relative, path.read_bytes(), today))
            except CorpusValidationError as exc:
                problems.append(str(exc))
        if problems:
            raise CorpusValidationError("\n".join(problems))
        return files

    @staticmethod
    def corpus_paths(root: Path) -> list[Path]:
        paths: list[Path] = []
        for path in sorted(root.rglob("*.md")):
            relative = path.relative_to(root)
            if path.name in CorpusLoader.SKIPPED_FILES or relative.parts[0] in (
                CorpusLoader.SKIPPED_FOLDERS
            ):
                continue  # not corpus, by name (s11 §4.1)
            paths.append(path)
        return paths

    @staticmethod
    def parse(path: str, content: bytes, today: date) -> CorpusFile:
        """One file. Raises CorpusValidationError naming the file and the problem."""
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CorpusValidationError(f"{path}: not UTF-8") from exc
        match = CorpusLoader.FRONTMATTER.match(text.replace("\r\n", "\n"))
        if match is None:
            raise CorpusValidationError(f"{path}: needs a --- frontmatter block at the top")
        frontmatter = CorpusLoader._frontmatter(path, match.group(1))
        body = match.group(2).strip()
        CorpusLoader._check(path, frontmatter, body, today)
        return CorpusFile(
            path=path,
            frontmatter=frontmatter,
            body=body,
            content_sha256=hashlib.sha256(content).hexdigest(),
        )

    @staticmethod
    def _frontmatter(path: str, raw: str) -> CorpusFrontmatter:
        try:
            loaded: object = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise CorpusValidationError(f"{path}: frontmatter is not valid YAML") from exc
        if not isinstance(loaded, dict):
            raise CorpusValidationError(f"{path}: frontmatter must be a mapping of keys")
        try:
            return CorpusFrontmatter.model_validate(loaded)
        except ValidationError as exc:
            reasons = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            )
            raise CorpusValidationError(f"{path}: {reasons}") from exc

    @staticmethod
    def _check(path: str, frontmatter: CorpusFrontmatter, body: str, today: date) -> None:
        folder = Path(path).parent.name
        if frontmatter.topic.value != folder:
            raise CorpusValidationError(
                f"{path}: topic {frontmatter.topic.value!r} must equal its folder {folder!r}"
            )
        if frontmatter.retrieved_on > today:
            raise CorpusValidationError(f"{path}: retrieved_on is in the future")
        if today - frontmatter.retrieved_on > CorpusLoader.MAX_AGE:
            raise CorpusValidationError(f"{path}: retrieved_on is over a year old; re-verify it")
        if not body:
            raise CorpusValidationError(f"{path}: the body is empty")
        if not CorpusLoader.HEADING.search(body):
            raise CorpusValidationError(f"{path}: the body needs at least one ## heading")
        if CorpusLoader.RAW_HTML.search(body):
            raise CorpusValidationError(f"{path}: the body contains raw HTML")
