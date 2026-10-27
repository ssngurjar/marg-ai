"""CuriositySignalExtractor: domains, engagement and the child's own question (s13 §4.4)."""

from uuid import uuid4

import pytest

from app.core.errors import ProviderUnavailable
from app.domain.enums import CuriosityDomain
from app.domain.models.base import TurnId
from app.domain.models.curiosity import CuriositySource, CuriositySourceKind, ExtractSignals
from app.telemetry.curiosity_signal_extractor import (
    CuriosityExtraction,
    CuriositySignalExtractor,
    ExtractedSignals,
    _ExtractionChecks,
)
from tests.fakes.language_model import FakeLanguageModel, ScriptedOutput
from tests.support.journey import CURIOSITY_SIGNALS, child
from tests.support.prompts import shipped_registry

pytestmark = pytest.mark.unit

REPORT = "Munni ne kaha parchhai suraj ki wajah se ghoomti hai, aur poocha raat ko kya hoga"


def task(kind: CuriositySourceKind = "parent_report", text: str = REPORT) -> ExtractSignals:
    return ExtractSignals(
        turn_id=TurnId(uuid4()),
        learner_id=child().id,
        user_text=text,
        source=CuriositySource(
            learner_id=child().id,
            kind=kind,
            hint_domains=[CuriosityDomain.EARTH_SKY] if kind == "parent_report" else [],
            activity_title="Shadow time" if kind == "parent_report" else None,
        ),
        child_age=5,
    )


async def extract(
    output: ScriptedOutput, extract_task: ExtractSignals | None = None
) -> tuple[ExtractedSignals, FakeLanguageModel]:
    llm = FakeLanguageModel([output])
    result = await CuriositySignalExtractor(llm, shipped_registry()).extract(extract_task or task())
    return result, llm


async def test_a_report_is_judged_with_the_activitys_domains_as_a_hint() -> None:
    result, llm = await extract(CURIOSITY_SIGNALS)
    assert result.signals.engagement == 2
    prompt = llm.prompts[0]
    assert "Shadow time" in prompt.system
    assert "earth_sky" in prompt.system
    assert "about 5 years old" in prompt.system
    assert REPORT not in prompt.system  # the parent's words stay in the user slot
    assert REPORT in prompt.user
    assert llm.models == ["meta-models/muse-spark-open"]  # C9: Muse Spark Open


async def test_a_relayed_question_always_counts_as_the_child_asking() -> None:
    not_marked = {**CURIOSITY_SIGNALS, "child_asked_question": False}
    result, _ = await extract(not_marked, task("relayed_question", "Munni poochh rahi hai…"))
    assert result.signals.child_asked_question


async def test_the_model_down_is_raised_for_the_runner_to_record() -> None:
    with pytest.raises(ProviderUnavailable, match="503"):
        await extract(ProviderUnavailable("503", provider="baseten"))


@pytest.mark.parametrize(
    ("answer", "kind", "problem"),
    [
        (
            {"domains": ["earth_sky", "earth_sky"]},
            "parent_report",
            "domains: list each at most once",
        ),
        ({"engagement": 0, "child_asked_question": True}, "parent_report", "child_asked_question"),
        ({"engagement": 2, "domains": []}, "parent_report", "domains: name at least one"),
        ({"engagement": 0, "domains": []}, "relayed_question", "engagement: a child who asked"),
    ],
)
def test_the_checks_catch_each_inconsistency(
    answer: dict[str, object], kind: CuriositySourceKind, problem: str
) -> None:
    extraction = CuriosityExtraction.model_validate({**CURIOSITY_SIGNALS, **answer})
    problems = _ExtractionChecks.problems(extraction, kind)
    assert any(found.startswith(problem) for found in problems), problems


def test_a_quiet_child_is_recorded_honestly_with_no_domains() -> None:
    quiet = CuriosityExtraction(domains=[], engagement=0, child_asked_question=False)
    assert _ExtractionChecks.problems(quiet, "parent_report") == []


@pytest.mark.parametrize("field", [{"engagement": 4}, {"engagement": -1}, {"domains": ["a", "b"]}])
def test_out_of_range_answers_are_refused_by_the_schema(field: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="validation error"):
        CuriosityExtraction.model_validate({**CURIOSITY_SIGNALS, **field})
