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
exists). search_knowledge ranks matches with a simple deterministic
field-weighting scheme - see FIELD_WEIGHTS below - no embeddings, no
vector database, no external service. publish_knowledge generates the
article through the isolated LLM provider in llm.py (Gemini by default,
see that module) - the GitHub API call to open the Pull Request is the
remaining TODO.

get_knowledge resolves `id` inside KNOWLEDGE_DIR and refuses anything
that escapes it (path traversal) or that does not exist - it returns a
clean MCP-level error instead of a raw FileNotFoundError.

Run for local testing with the MCP dev inspector:
    mcp dev server.py

Or point a Claude Desktop / claude.ai connector config at this script.
"""

import glob
import os
import re
from datetime import date
from pathlib import Path
from typing import Optional

import frontmatter
from llm import ProviderError, generate_article
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

mcp = FastMCP("shared-knowledge")

# Search result cap. Applied AFTER relevance ranking (spec: results are
# sorted by relevance first, then truncated).
MAX_SEARCH_RESULTS = 10

# Lightweight relevance weights for search_knowledge (deterministic,
# dependency-light ranking - no embeddings, no vector database).
#
# Each query term contributes, at most once per article:
#   weight  where it matched
#   ------  ---------------------------------
#   8.0     title (frontmatter)
#   6.0     tags (frontmatter list)
#   4.0     description (frontmatter)
#   2.0     category (frontmatter)
#   1.0     body (Markdown content)
#
# A term matching in several fields adds each field's weight once (e.g. a
# term in title AND body scores 9.0), so multi-field matches outrank
# single-field matches and multi-term queries outrank single-term ones.
# Scores are only compared against each other; the absolute values carry
# no meaning outside this module.
FIELD_WEIGHTS = {
    "title": 8.0,
    "tags": 6.0,
    "description": 4.0,
    "category": 2.0,
    "body": 1.0,
}

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

# Pre-moderation limits - spec section 11 ("empty or meaningless content",
# "excessively long content") without any external moderation API.
MAX_CONTENT_LENGTH = 50_000

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

    MVP implementation: dependency-light keyword search over local Markdown
    files (frontmatter title/tags/description/category + body), ranked by a
    deterministic field-weighting scheme (see FIELD_WEIGHTS). Results are
    sorted by relevance (highest first, ties broken by title) before the
    MAX_SEARCH_RESULTS limit is applied. No vector database, per spec
    section 7 goals.
    """
    terms = _tokenize(query)
    if not terms:
        return SearchOutput(results=[])

    scored: list[tuple[float, str, SearchResult]] = []

    for path in glob.glob(os.path.join(KNOWLEDGE_DIR, "**", "*.md"), recursive=True):
        post = frontmatter.load(path)
        fields = _searchable_fields(post)
        score = 0.0
        matched = False
        for term in terms:
            for field, text in fields.items():
                if term in text:
                    score += FIELD_WEIGHTS[field]
                    matched = True
        if matched:
            scored.append(
                (score, str(post.get("title", "")).lower(),
                 SearchResult(
                     title=post.get("title", os.path.basename(path)),
                     category=post.get("category", "Other"),
                     url=path,
                     summary=post.get("description", ""),
                 ))
            )

    # Sort by relevance (desc), then title (asc) for deterministic ties.
    scored.sort(key=lambda item: (-item[0], item[1]))
    return SearchOutput(results=[result for _, _, result in scored[:MAX_SEARCH_RESULTS]])


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

    The resolved path must stay inside KNOWLEDGE_DIR: traversal attempts
    (e.g. "../../etc/passwd" or absolute paths outside the knowledge
    base) raise a clean MCP-level ValueError instead of reading arbitrary
    files. A nonexistent article raises ValueError as well, rather than
    leaking a raw FileNotFoundError to the MCP client.
    """
    base = Path(KNOWLEDGE_DIR).resolve()
    candidate = Path(id if id.endswith(".md") else f"{id}.md")
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(base):
        raise ValueError(
            f"invalid article id {id!r}: path escapes the knowledge base"
        )
    if not resolved.is_file():
        raise ValueError(f"article not found: {id!r}")

    post = frontmatter.load(resolved)
    return GetKnowledgeOutput(
        id=id,
        content=frontmatter.dumps(post),
        metadata=post.metadata,
    )


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
    except ProviderError as exc:
        # Missing key, API failure, malformed/invalid structured output...
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
    if not article.get("description"):
        problems.append("missing description")

    content = article.get("content", "")
    if not content.strip():
        problems.append("empty content")
    if len(content) > MAX_CONTENT_LENGTH:
        problems.append(f"content exceeds {MAX_CONTENT_LENGTH} characters")
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
    """Deprecated shim kept for compatibility - use frontmatter.load() directly."""
    return frontmatter.loads(content).metadata


def _tokenize(query: str) -> list[str]:
    """Split a query into lowercase search terms.

    Normalization: lowercase, split on whitespace AND punctuation (so
    "caddy, authentik" or "reverse-proxy:" become separate terms), drop
    short English stop words that would otherwise match almost every
    article. Repeated terms are kept - they slightly boost multi-field
    emphasis but never break determinism.
    """
    stop_words = {"the", "a", "an", "of", "to", "for", "and", "or", "in", "on", "with", "is"}
    tokens = re.split(r"[^\w\-]+", query.lower())
    return [t for t in tokens if len(t) >= 2 and t not in stop_words]


def _searchable_fields(post: frontmatter.Post) -> dict[str, str]:
    """Extract the text of each weighted field from a frontmatter post."""
    tags = post.get("tags") or []
    if not isinstance(tags, (list, tuple)):
        tags = [tags]
    return {
        "title": str(post.get("title", "")).lower(),
        "tags": " ".join(str(t) for t in tags).lower(),
        "description": str(post.get("description", "")).lower(),
        "category": str(post.get("category", "")).lower(),
        "body": post.content.lower(),
    }


# --------------------------------------------------------------------------
# External calls - the LLM side is done (llm.py); the GitHub API call to
# open the Pull Request is the remaining piece.
# --------------------------------------------------------------------------

def _generate_article(excerpt: str, language_hint: Optional[str]) -> dict:
    """Turn the excerpt into a structured article via the isolated LLM provider.

    Delegates to llm.generate_article (Gemini by default, selected through
    LLM_PROVIDER). Must return:
        {
          "title": str,
          "description": str,
          "category": str,   # one of CATEGORIES
          "tags": list[str],
          "content": str,    # full Markdown body, sections per spec 7.3
        }

    The prompt enforces: English output, standalone article (no "as I said
    above", no references to the user or the conversation), category chosen
    from CATEGORIES only (re-validated afterwards), tags lowercase and
    reusable. Raises llm.ProviderError on configuration, API, or response
    errors - publish_knowledge maps that to a clean MCP-level error and
    never fabricates an article.
    """
    return generate_article(excerpt, language_hint, CATEGORIES)


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
