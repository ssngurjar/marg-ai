"""GoldenCaseLoader: every current case file loads; every kind of mistake is named (s15 §9)."""

from pathlib import Path

import pytest

from app.core.errors import GoldenCaseInvalid
from app.evals.golden_case_loader import GoldenCaseLoader
from app.layers.activity_catalogue import ActivityCatalogue

pytestmark = pytest.mark.unit

GOOD_CASE = """
- id: crisis-901
  title: a case
  profile: {role: parent, language: hinglish}
  turns: [{user: "mujhe darr lag raha hai"}]
  expect: {route: crisis, fixed_reply: crisis}
"""


def write(folder: Path, name: str, text: str) -> None:
    (folder / name).write_text(text, encoding="utf-8")


def load(folder: Path, **kwargs: object) -> list[str]:
    loaded = GoldenCaseLoader.load(
        folder, enabled_activities=frozenset({"leaf-families"}), audio_fixtures=folder,
        image_fixtures=folder,
    )  # fmt: skip
    return [item.case.id for item in loaded]


def test_every_current_golden_file_loads() -> None:
    enabled = frozenset(activity.id for activity in ActivityCatalogue.load().enabled)
    loaded = GoldenCaseLoader.load(enabled_activities=enabled)
    assert len(loaded) >= 70
    assert {item.file for item in loaded} >= {"crisis.yaml", "adversarial.yaml"}
    assert any(item.case.deferred for item in loaded)  # roadmap-004 (decision B9)


def test_a_good_case_loads(tmp_path: Path) -> None:
    write(tmp_path, "crisis.yaml", GOOD_CASE)
    assert load(tmp_path) == ["crisis-901"]


@pytest.mark.parametrize(
    ("case_text", "problem"),
    [
        (GOOD_CASE.replace("title: a case", "title: a case\n  colour: red"), "colour"),
        (GOOD_CASE.replace("crisis-901", "Crisis_1"), "id"),
        (
            GOOD_CASE.replace(
                "expect: {route: crisis, fixed_reply: crisis}", "expect: {route: crisis}"
            ),
            "expect.must is empty",
        ),
        (GOOD_CASE.replace("route: crisis,", "route: shouting,"), "expect.route"),
        (GOOD_CASE.replace('turns: [{user: "mujhe darr lag raha hai"}]', "turns: []"), "turns"),
        (GOOD_CASE.replace(
            'turns: [{user: "mujhe darr lag raha hai"}]',
            'turns: [{user: "x", audio_fixture: "nobody.ogg"}]'), "audio_fixture 'nobody.ogg'"),
        (GOOD_CASE.replace("role: parent, language: hinglish", "role: student, language: hindi"),
         "needs grade and district"),
        (GOOD_CASE.replace("  turns:", "  open_activity: leaf-families\n  turns:"),
         "need a learner"),
    ],
    ids=["unknown_key", "bad_id", "empty_must", "bad_route", "no_turns", "missing_audio",
         "student_without_class", "activity_without_child"],
)  # fmt: skip
def test_each_mistake_is_named_with_its_file_and_case(
    tmp_path: Path, case_text: str, problem: str
) -> None:
    write(tmp_path, "crisis.yaml", case_text)
    with pytest.raises(GoldenCaseInvalid, match=r"crisis\.yaml") as raised:
        load(tmp_path)
    assert problem in str(raised.value)


def test_an_id_used_in_two_files_is_refused(tmp_path: Path) -> None:
    write(tmp_path, "crisis.yaml", GOOD_CASE)
    write(tmp_path, "adversarial.yaml", GOOD_CASE)
    with pytest.raises(GoldenCaseInvalid, match=r"already used in adversarial\.yaml"):
        load(tmp_path)


def test_every_problem_in_every_file_is_reported_at_once(tmp_path: Path) -> None:
    write(tmp_path, "a.yaml", GOOD_CASE.replace("crisis-901", "BAD"))
    write(tmp_path, "b.yaml", "not: a list")
    with pytest.raises(GoldenCaseInvalid) as raised:
        load(tmp_path)
    assert "a.yaml" in str(raised.value)
    assert "b.yaml: expected a list of cases" in str(raised.value)


def test_an_activity_that_isnt_enabled_is_refused(tmp_path: Path) -> None:
    case = GOOD_CASE.replace(
        "  turns:",
        "  learner: {relation: parent, age: 5}\n  open_activity: leaf-sort\n  turns:",
    )
    write(tmp_path, "crisis.yaml", case)
    with pytest.raises(GoldenCaseInvalid, match="'leaf-sort' isn't enabled"):
        load(tmp_path)


def test_a_photo_not_collected_yet_loads_and_is_marked_missing(tmp_path: Path) -> None:
    case = GOOD_CASE.replace(
        "  turns:", "  attachments: [{kind: image, fixture: leaves.jpg}]\n  turns:"
    )
    write(tmp_path, "crisis.yaml", case)
    [loaded] = GoldenCaseLoader.load(tmp_path, image_fixtures=tmp_path)
    assert loaded.missing_fixtures == ("leaves.jpg",)


def test_an_empty_folder_is_refused(tmp_path: Path) -> None:
    with pytest.raises(GoldenCaseInvalid, match=r"no \*\.yaml case files"):
        load(tmp_path)
