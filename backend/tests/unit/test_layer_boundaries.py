"""Enforce the dependency rule: dependencies point inward.

This is a test rather than a review convention. The domain layer holds the business rules
and security invariants; it depends on nothing external. The application layer orchestrates
use cases through domain ports and likewise touches no framework or vendor SDK.

Passes vacuously until there is code in these directories, and becomes load-bearing from
that point on.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Top-level modules that inner layers must never import. Matching is on the first
# dotted component, so "sqlalchemy.orm" is caught by "sqlalchemy".
FORBIDDEN_INWARD_IMPORTS = frozenset(
    {
        # Web framework and serving
        "fastapi",
        "starlette",
        "sse_starlette",
        "uvicorn",
        # Validation and settings. Deliberate: the domain uses stdlib dataclasses so it
        # depends on nothing outside the standard library. Pydantic would bring
        # serialisation with it, and entities that already serialise leak outward into
        # API responses, which quietly erases the presentation boundary.
        "pydantic",
        "pydantic_settings",
        # Persistence
        "sqlalchemy",
        "alembic",
        "psycopg",
        "psycopg2",
        "pgvector",
        "neo4j",
        # Network and storage clients
        "httpx",
        "httpx2",
        "requests",
        "aioboto3",
        "boto3",
        # Document processing
        "pypdf",
        "pdfplumber",
        "pypdfium2",
        "PIL",
        "cv2",
        "paddle",
        "paddleocr",
        "paddlex",
        # Model runtimes and provider SDKs
        "torch",
        "transformers",
        "sentence_transformers",
        "ollama",
        "openai",
        "anthropic",
        "google",
    }
)

# Layers subject to the rule, innermost first.
INNER_LAYERS = ("domain", "application")


def _iter_modules(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if p.name != "__init__.py" or p.stat().st_size > 0)


def _imported_roots(source: Path) -> set[str]:
    """Top-level module names imported by a Python file."""
    tree = ast.parse(source.read_text(encoding="utf-8-sig"), filename=str(source))
    roots: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        # node.level > 0 is a relative import, which is always internal
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])

    return roots


@pytest.mark.parametrize("layer", INNER_LAYERS)
def test_layer_directory_exists(app_root: Path, layer: str) -> None:
    """Guard against the rule passing vacuously because a directory was renamed."""
    assert (app_root / layer).is_dir(), (
        f"app/{layer}/ is missing — the boundary test would pass vacuously"
    )


@pytest.mark.parametrize("layer", INNER_LAYERS)
def test_inner_layer_has_no_outward_imports(app_root: Path, layer: str) -> None:
    """No file in an inner layer may import a framework, driver or vendor SDK."""
    violations: list[str] = []

    for module in _iter_modules(app_root / layer):
        forbidden = _imported_roots(module) & FORBIDDEN_INWARD_IMPORTS
        if forbidden:
            relative = module.relative_to(app_root.parent)
            violations.append(f"  {relative}  imports  {', '.join(sorted(forbidden))}")

    assert not violations, (
        f"Dependency rule violated in app/{layer}/ — dependencies must point inward:\n"
        + "\n".join(violations)
    )


def test_domain_does_not_import_application(app_root: Path) -> None:
    """The domain is the innermost layer; it may not reach outward to use cases."""
    outward = ("app.application", "app.api", "app.infrastructure")
    violations: list[str] = []

    for module in _iter_modules(app_root / "domain"):
        tree = ast.parse(module.read_text(encoding="utf-8-sig"), filename=str(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(outward):
                violations.append(f"  {module.relative_to(app_root.parent)} -> {node.module}")

    assert not violations, "Domain reaches outward:\n" + "\n".join(violations)
