"""Fixtures for the Shared Knowledge MCP test suite.

Builds a temporary knowledge directory with two seeded articles and points
KNOWLEDGE_DIR at it, so the MCP tools can be exercised without touching the
repository's own `knowledge/` folder.
"""

import importlib
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import server  # noqa: E402


def _write_article(path: Path, frontmatter: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}\n---\n\n{body}\n", encoding="utf-8")


@pytest.fixture()
def knowledge_dir(tmp_path, monkeypatch):
    """A temporary knowledge base with two articles, wired into server.KNOWLEDGE_DIR."""
    base = tmp_path / "kb"
    _write_article(
        base / "devops" / "caddy-authentik-streamlit.md",
        'title: "Protecting Streamlit with Caddy and Authentik"\n'
        'description: "How to protect a Streamlit application using Caddy and Authentik forward authentication."\n'
        'category: "DevOps"\n'
        "tags:\n"
        "  - caddy\n"
        "  - authentik\n"
        "  - streamlit\n"
        "  - reverse-proxy\n"
        "  - sso\n"
        'source: "community"\n'
        'created_at: "2026-09-04"\n',
        "# Protecting Streamlit with Caddy and Authentik\n\n"
        "## Problem\n\nStreamlit applications have no built-in authentication.\n\n"
        "## Solution\n\nUse Caddy forward_auth with Authentik.\n",
    )
    _write_article(
        base / "databases" / "postgres-isolation-levels.md",
        'title: "Choosing a Postgres isolation level for read-heavy APIs"\n'
        'description: "How to pick a transaction isolation level for read-heavy APIs."\n'
        'category: "Databases"\n'
        "tags:\n"
        "  - postgres\n"
        "  - transactions\n"
        'source: "community"\n'
        'created_at: "2026-09-04"\n',
        "# Choosing a Postgres isolation level\n\n"
        "## Problem\n\nRead consistency across queries.\n\n"
        "## Solution\n\nUse READ COMMITTED by default.\n",
    )

    monkeypatch.setattr(server, "KNOWLEDGE_DIR", str(base))
    importlib.reload(server)
    monkeypatch.setattr(server, "KNOWLEDGE_DIR", str(base))
    yield base


@pytest.fixture()
def valid_article() -> dict:
    """An article dict that passes _validate_article, for mutation in tests."""
    return {
        "title": "A valid article",
        "description": "A short description.",
        "category": "DevOps",
        "tags": ["caddy"],
        "content": (
            "# A valid article\n\n## Problem\n\nSomething breaks.\n\n"
            "## Solution\n\nDo the thing.\n"
        ),
    }
