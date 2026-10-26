from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.support.layering import (
    ALLOWED_INTERNAL_IMPORTS,
    ANYTHING,
    ANYTHING_EXCEPT_API,
    area_of,
    check_layering,
    is_allowed,
)

pytestmark = pytest.mark.unit

APP_ROOT = Path(__file__).resolve().parents[2] / "app"


def write_module(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    for parent in path.relative_to(root).parents:
        (root / parent / "__init__.py").touch()
    path.write_text(source, encoding="utf-8")


def violations_as_text(app_root: Path) -> list[str]:
    return [str(violation) for violation in check_layering(app_root)]


def test_app_respects_layering() -> None:
    assert violations_as_text(APP_ROOT) == []


def test_layering_detects_violation(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    write_module(app_root, "domain/models.py", "from app.store import db\n")
    write_module(app_root, "store/db.py", "")
    assert violations_as_text(app_root) == [
        "app.domain.models → app.store.db (domain may not import store.db)"
    ]


def test_layering_resolves_relative_imports(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    write_module(app_root, "domain/models.py", "from ..store import db\n")
    write_module(app_root, "store/db.py", "")
    assert violations_as_text(app_root) == [
        "app.domain.models → app.store.db (domain may not import store.db)"
    ]


def test_layering_includes_type_checking_imports(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    write_module(
        app_root,
        "layers/mentor.py",
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from app.providers.llm import meta_model_api\n",
    )
    write_module(app_root, "providers/llm/meta_model_api.py", "")
    assert violations_as_text(app_root) == [
        "app.layers.mentor → app.providers.llm.meta_model_api "
        "(layers may not import providers.llm.meta_model_api)"
    ]


def test_layering_restricts_third_party_libraries(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    write_module(
        app_root, "domain/models.py", "import sqlalchemy\nimport structlog\nimport pydantic\n"
    )
    assert violations_as_text(app_root) == [
        "app.domain.models → sqlalchemy (sqlalchemy is only allowed in "
        "['cli', 'main', 'store', 'wiring', 'worker'])",
        "app.domain.models → structlog (structlog is only allowed in ['core'])",
    ]


def test_layering_reports_unknown_area(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    write_module(app_root, "gadgets/thing.py", "")
    assert violations_as_text(app_root) == [
        "app.gadgets → gadgets (unknown area: add it to the rules)"
    ]


def test_worker_may_import_anything_but_api(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    write_module(
        app_root, "worker/loop.py", "from app.store import db\nfrom app.api import health\n"
    )
    write_module(app_root, "store/db.py", "")
    write_module(app_root, "api/health.py", "")
    assert violations_as_text(app_root) == [
        "app.worker.loop → app.api.health (worker may not import api.health)"
    ]


def test_from_core_import_errors_is_allowed_in_domain(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    write_module(app_root, "domain/models.py", "from app.core import errors, types\n")
    write_module(app_root, "core/errors.py", "")
    write_module(app_root, "core/types.py", "")
    assert violations_as_text(app_root) == []


def test_providers_areas_are_split() -> None:
    assert area_of("app.providers.ports") == "providers.ports"
    assert area_of("app.providers.http") == "providers.http"
    assert area_of("app.providers.llm.meta_model_api") == "providers.adapter"
    assert area_of("app") is None


# --- property: the AST walk agrees with a direct table lookup ---------------------------------

_SIMPLE_AREAS = sorted(
    area for area in ALLOWED_INTERNAL_IMPORTS if area not in {"providers.adapter"}
)


def table_allows(importer_area: str, imported_area: str) -> bool:
    """Reference answer, computed straight from the table (a different code path)."""
    if importer_area == imported_area:
        return True
    allowed = ALLOWED_INTERNAL_IMPORTS[importer_area]
    if ANYTHING in allowed:
        return True
    if ANYTHING_EXCEPT_API in allowed:
        return imported_area != "api"
    return imported_area in allowed


@given(
    edges=st.lists(
        st.tuples(st.sampled_from(_SIMPLE_AREAS), st.sampled_from(_SIMPLE_AREAS)), max_size=8
    )
)
def test_property_checker_matches_table(edges: list[tuple[str, str]]) -> None:
    for importer_area, imported_area in edges:
        assert is_allowed(importer_area, imported_area) is table_allows(
            importer_area, imported_area
        )
