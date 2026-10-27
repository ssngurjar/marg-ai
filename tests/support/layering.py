"""Import-graph checker for the layering rules in docs/design/s01-scaffold.md §4.12.

Walks every module under `app/`, collects its imports (including those under TYPE_CHECKING),
and reports each import the rules forbid. Kept out of `app/` because it's a test tool.
"""

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

ANYTHING = "*"
ANYTHING_EXCEPT_API = "*-api"

ALLOWED_INTERNAL_IMPORTS: dict[str, frozenset[str]] = {
    "domain": frozenset({"core.errors", "core.types"}),
    # constants: reviewed copy and catalogues (owner, 2026-10-27: S8 onboarding copy)
    "layers": frozenset(
        {"domain", "providers.ports", "prompts", "rag", "constants", "core.errors", "core.types"}
    ),
    "pipeline": frozenset(
        {"domain", "layers", "providers.ports", "safety", "store", "telemetry", "core", "constants"}
    ),
    "safety": frozenset({"domain", "providers.ports", "prompts", "core", "constants"}),
    "telemetry": frozenset({"domain", "providers.ports", "prompts", "store", "core"}),
    "rag": frozenset({"domain", "providers.ports", "store", "core"}),
    "audio": frozenset({"domain", "core"}),
    # providers.ports: the registry renders GenerationRequests (s05 §4.3)
    "prompts": frozenset({"domain", "core", "providers.ports"}),
    "channels": frozenset({"domain", "providers.ports", "providers.http", "core", "constants"}),
    "providers.ports": frozenset({"domain", "core.errors", "core.types"}),
    "providers.http": frozenset({"core"}),
    "providers.adapter": frozenset(
        {"domain", "providers.ports", "providers.http", "core", "audio", "constants"}
    ),
    # pipeline.reply_parts_builder only: the outbox insert accepts nothing but a sealed
    # ReplyDelivery (s04 log)
    "store": frozenset({"domain", "core", "pipeline.reply_parts_builder"}),
    # reviewed copy and external-API limits; read by the layers that send or check replies
    "constants": frozenset({"domain", "core"}),
    "api": frozenset({"domain", "channels", "store", "core", "pipeline", "telemetry", "constants"}),
    "core": frozenset({"core"}),
    "worker": frozenset({ANYTHING_EXCEPT_API}),
    "evals": frozenset({ANYTHING_EXCEPT_API}),
    "wiring": frozenset({ANYTHING}),
    "main": frozenset({ANYTHING}),
    "cli": frozenset({ANYTHING}),
}
"""Which areas each area may import, besides itself."""

RESTRICTED_LIBRARIES: dict[str, frozenset[str]] = {
    "openai": frozenset({"providers"}),
    "httpx": frozenset({"providers", "channels"}),
    "sqlalchemy": frozenset({"store", "wiring", "main", "worker", "cli"}),
    "asyncpg": frozenset({"store", "wiring", "main", "worker", "cli"}),
    "fastapi": frozenset({"api", "main", "wiring"}),
    "starlette": frozenset({"api", "main", "wiring"}),
    "jinja2": frozenset({"prompts"}),
    "yaml": frozenset({"layers", "rag", "evals", "cli"}),
    "cryptography": frozenset({"core"}),
    "pgvector": frozenset({"store"}),
    "structlog": frozenset({"core"}),
}
"""Third-party libraries that only some areas may import (by top-level package)."""


@dataclass(frozen=True, slots=True)
class Violation:
    importer: str  # module name, e.g. "app.domain.models"
    imported: str  # module or library name
    rule: str  # why it's forbidden

    def __str__(self) -> str:
        return f"{self.importer} → {self.imported} ({self.rule})"


def module_name(app_root: Path, file_path: Path) -> str:
    """`<root>/app/layers/mentor.py` → `app.layers.mentor`; `__init__.py` names its package."""
    relative = file_path.relative_to(app_root.parent).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def area_of(app_module: str) -> str | None:
    """The layering area of an `app.*` module, or None for the `app` package itself."""
    parts = app_module.split(".")
    if len(parts) < 2:  # "app" plus at least one segment
        return None
    top = parts[1]
    if top != "providers":
        return top
    if len(parts) < 3:  # the providers package itself
        return "providers.ports"
    return f"providers.{parts[2]}" if parts[2] in {"ports", "http"} else "providers.adapter"


def qualified_target(app_module: str) -> str:
    """What an import points at, for matching against the allowed list (e.g. `core.errors`)."""
    return ".".join(app_module.split(".")[1:])


def is_allowed(importer_area: str, target: str) -> bool:
    """Whether `importer_area` may import the `app.*` module whose qualified name is `target`."""
    target_area = area_of(f"app.{target}")
    if target_area == importer_area:
        return True
    allowed = ALLOWED_INTERNAL_IMPORTS.get(importer_area, frozenset())
    if ANYTHING in allowed:
        return True
    if ANYTHING_EXCEPT_API in allowed:
        return target_area != "api"
    for entry in allowed:
        if target == entry or target.startswith(f"{entry}."):
            return True
        if target_area == entry:
            return True
    return False


def library_allowed(importer_area: str, library: str) -> bool:
    allowed_areas = RESTRICTED_LIBRARIES.get(library)
    if allowed_areas is None:
        return True
    return any(
        importer_area == area or importer_area.startswith(f"{area}.") for area in allowed_areas
    )


def imports_of(source: str, importer: str, *, is_package: bool) -> Iterator[str]:
    """Absolute names of everything `importer` imports, including TYPE_CHECKING blocks."""
    package = importer if is_package else importer.rpartition(".")[0]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from(node, package)
            if base == "app" or base.startswith("app."):
                # `from app.core import errors` imports app.core.errors; for a name that isn't a
                # module (`from app.core.errors import ConfigError`) the longer path still starts
                # with the module path, which is what the prefix-based rules match on.
                for alias in node.names:
                    yield base if alias.name == "*" else f"{base}.{alias.name}"
            else:
                yield base


def _resolve_from(node: ast.ImportFrom, package: str) -> str:
    if node.level == 0:
        return node.module or ""
    package_parts = package.split(".")
    anchor = package_parts[: len(package_parts) - (node.level - 1)]
    return ".".join([*anchor, node.module] if node.module else anchor)


def check_layering(app_root: Path) -> list[Violation]:
    """Every forbidden import under `app_root` (the `app/` directory)."""
    violations: list[Violation] = []
    unknown_areas_reported: set[str] = set()
    for file_path in sorted(app_root.rglob("*.py")):
        importer = module_name(app_root, file_path)
        importer_area = area_of(importer)
        if importer_area is None:
            continue
        if importer_area not in ALLOWED_INTERNAL_IMPORTS:
            if importer_area not in unknown_areas_reported:
                unknown_areas_reported.add(importer_area)
                violations.append(
                    Violation(
                        f"app.{importer_area}", importer_area, "unknown area: add it to the rules"
                    )
                )
            continue
        source = file_path.read_text(encoding="utf-8")
        is_package = file_path.name == "__init__.py"
        for imported in imports_of(source, importer, is_package=is_package):
            violations.extend(_check_one(importer, importer_area, imported))
    return violations


def _check_one(importer: str, importer_area: str, imported: str) -> list[Violation]:
    if imported == "app" or imported.startswith("app."):
        if area_of(imported) is None:
            return []
        target = qualified_target(imported)
        if is_allowed(importer_area, target):
            return []
        return [Violation(importer, imported, f"{importer_area} may not import {target}")]
    library = imported.split(".", maxsplit=1)[0]
    if library_allowed(importer_area, library):
        return []
    return [
        Violation(
            importer,
            imported,
            f"{library} is only allowed in {sorted(RESTRICTED_LIBRARIES[library])}",
        )
    ]
