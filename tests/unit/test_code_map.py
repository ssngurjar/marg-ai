"""docs/code-map.md must match the code (regenerate with `python -m scripts.code_map`)."""

import pytest

from scripts.code_map import MAP_PATH, render

pytestmark = pytest.mark.unit


def test_code_map_is_up_to_date() -> None:
    assert MAP_PATH.read_text(encoding="utf-8") == render(), (
        "docs/code-map.md is stale: run `.venv/bin/python -m scripts.code_map`"
    )
