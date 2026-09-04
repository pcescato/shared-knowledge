"""
Shared Knowledge MCP - server skeleton (MVP)

Exposes three tools, matching the spec's section 6 (MCP Interface):
  - search_knowledge : find relevant articles in the knowledge base
  - get_knowledge     : fetch one article's full content + metadata
  - publish_knowledge : turn a solved-problem conversation excerpt into a
                         structured English article and open a GitHub PR

search_knowledge and get_knowledge already work against a local
`knowledge/` folder of Markdown files with YAML frontmatter (good enough
for the demo; swap the naive grep for the public GitHub repo once it
exists). publish_knowledge is fully wired except for the two external
calls left as TODOs: the LLM call (Gemini / Google AI) and the GitHub
API call to open the Pull Request - those are the pieces to fill in
this weekend.

Run for local testing with the MCP dev inspector:
    mcp dev server.py

Or point a Claude Desktop / claude.ai connector config at this script.
"""

import glob
import os
import re
from datetime import date
from typing import Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

mcp = FastMCP("shared-knowledge")

# Controlled vocabulary - spec section 8. Categories are not user-defined.
CATEGORIES = [
    "AI",
    "Backend",
    "Cloud",
    "Databases",
    "DevOps",
    "Frontend",
    "Hardware",
    "Linux",
    "Security",
    "Web Development",
    "Programming",
    "Open Source",
    "Tools",
    "Other",
]

KNOWLEDGE_DIR = os.environ.get("KNOWLEDGE_DIR", "./knowledge")

REQUIRED_SECTIONS = ["## Problem", "## Solution"]

# Patterns for the pre-moderation secret scan (spec section 18).
# Deliberately conservative - false positives are cheap (a maintainer
# double-checks in the PR review), false negatives are not.
SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),               # generic API-key shape
    re.compile(r"ghp_[a-zA-Z0-9]{20,}"),               # GitHub PAT
    re.compile(r"AIza[0-9A-Za-z\-_]{35}"),             # Google API key
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"), # PEM private key
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # email
]


# --------------------------------------------------------------------------
# search_knowledge
# --------------------------------------------------------------------------

class SearchResult(BaseModel):
    title: str
    category: str
    url: str
    summary: str


class SearchOutput(BaseModel):
    results: list[SearchResult]


@mcp.tool()
def search_knowledge(query: str) -> SearchOutput:
    """Search the shared knowledge base for articles relevant to `query`.

    MVP implementation: naive keyword match over local Markdown files
    (frontmatter title/description/category + body). No vector database
    needed for the MVP, per spec section 7 goals.
    """
    terms = [t.lower() for t in query.split() if t]
    results: list[SearchResult] = []

    for path in glob.glob(os.path.join(KNOWLEDGE_DIR, "**", "*.md"), recursive=True):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if terms and not any(term in content.lower() for term in terms):
            continue
        meta = _parse_frontmatter(content)
        results.append(
            SearchResult(
                title=meta.get("title", os.path.basename(path)),
                category=meta.get("category", "Other"),
                url=path,
                summary=meta.get("description", ""),
            )
        )

    return SearchOutput(results=results[:10])


# --------------------------------------------------------------------------
# get_knowledge
# --------------------------------------------------------------------------

class GetKnowledgeOutput(BaseModel):
    id: str
    content: str
    metadata: dict


@mcp.tool()
def get_knowledge(id: str) -> GetKnowledgeOutput:
    """Retrieve the full content and metadata of a known article.

    `id` is the article's file path (as returned by search_knowledge) or
    a bare slug resolved against KNOWLEDGE_DIR.
    """
    path = id if id.endswith(".md") else os.path.join(KNOWLEDGE_DIR, f"{id}.md")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return GetKnowledgeOutput(id=id, content=content, metadata=_parse_frontmatter(content))


# --------------------------------------------------------------------------
# publish_knowledge
# --------------------------------------------------------------------------

class PublishInput(BaseModel):
    conversation_excerpt: str = Field(
        ..., description="The relevant part of the conversation to turn into an article."
    )
    language_hint: Optional[str] = Field(
        None, description="Source language of the conversation, if known."
    )


class PublishOutput(BaseModel):
    status: str  # "submitted" | "rejected" | "error"
    pull_request: Optional[str] = None
    title: Optional[str] = None
    error: Optional[str] = None


@mcp.tool()
def publish_knowledge(input: PublishInput) -> PublishOutput:
    """Turn a solved-problem conversation excerpt into a standalone English
    knowledge article and submit it as a GitHub Pull Request for human review.

    Pipeline (spec section 5.2):
      1. generate {title, description, category, tags, content} via the LLM
      2. validate structure + run the secret scan (never publish directly)
      3. create a branch, commit the article, open a PR
    The result always signals "submitted for review", never "published".
    """
    try:
        article = _generate_article(input.conversation_excerpt, input.language_hint)
    except NotImplementedError as exc:
        return PublishOutput(status="error", error=str(exc))
    except Exception as exc:  # noqa: BLE001 - surface any generation failure to the caller
        return PublishOutput(status="error", error=f"generation failed: {exc}")

    problems = _validate_article(article)
    if problems:
        return PublishOutput(status="rejected", error="; ".join(problems))

    try:
        pr_url = _create_pull_request(article)
    except NotImplementedError as exc:
        return PublishOutput(status="error", error=str(exc))
    except Exception as exc:  # noqa: BLE001
        return PublishOutput(status="error", error=f"PR creation failed: {exc}")

    return PublishOutput(status="submitted", pull_request=pr_url, title=article["title"])


def _validate_article(article: dict) -> list[str]:
    """Pre-moderation checks (spec section 11) - advisory, a human still reviews the PR."""
    problems: list[str] = []

    if article.get("category") not in CATEGORIES:
        problems.append(f"unknown category: {article.get('category')!r}")
    if not article.get("title"):
        problems.append("missing title")

    content = article.get("content", "")
    missing_sections = [s for s in REQUIRED_SECTIONS if s not in content]
    if missing_sections:
        problems.append(f"missing required section(s): {', '.join(missing_sections)}")

    if _looks_like_secret(content):
        problems.append("possible secret or personal information detected in content")

    if not article.get("tags"):
        problems.append("missing tags")

    return problems


def _looks_like_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def _parse_frontmatter(content: str) -> dict:
    """Minimal YAML-frontmatter reader for the MVP - swap for `python-frontmatter` when there's time."""
    if not content.startswith("---"):
        return {}
    try:
        _, fm, _ = content.split("---", 2)
    except ValueError:
        return {}
    meta: dict = {}
    for line in fm.strip().splitlines():
        if ":" in line and not line.strip().startswith("-"):
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip().strip('"')
    return meta


# --------------------------------------------------------------------------
# External calls - fill these in during the Saturday-night session.
# --------------------------------------------------------------------------

def _generate_article(excerpt: str, language_hint: Optional[str]) -> dict:
    """Call Gemini (Google AI) to turn the excerpt into a structured article.

    Must return:
        {
          "title": str,
          "description": str,
          "category": str,   # one of CATEGORIES
          "tags": list[str],
          "content": str,    # full Markdown body, sections per spec 7.3
        }

    Prompt should enforce: English output, standalone (no "as I said
    above", no references to the user or the conversation), category
    chosen from CATEGORIES only, tags lowercase and reused where possible.
    """
    raise NotImplementedError("TODO: wire the Gemini API call here")


def _create_pull_request(article: dict) -> str:
    """Create a branch, commit `knowledge/<category>/<slug>.md`, and open a PR.

    `article["content"]` should already include the frontmatter block
    (title, description, category, tags, source: "community",
    created_at: today's date) before being written to disk / committed.
    Returns the PR URL.
    """
    raise NotImplementedError("TODO: wire the GitHub API call here")


if __name__ == "__main__":
    mcp.run()
