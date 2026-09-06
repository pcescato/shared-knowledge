"""
Shared Knowledge MCP - server skeleton (MVP)

Exposes three tools and one prompt, matching the spec's section 6 (MCP
Interface):
  - search_knowledge : find relevant articles in the knowledge base
  - get_knowledge     : fetch one article's full content + metadata
  - publish_knowledge : receive an already-structured article and open a
                         GitHub PR for human review
  - knowledge_article_guidelines (prompt): the structuring rules the
                         caller must follow before publishing

The server performs NO article generation: the caller (the user's AI
assistant, whatever it is) structures the article itself, guided by the
knowledge_article_guidelines prompt, then calls publish_knowledge with
the five required fields. The server only validates (structure + secret
scan) and submits. No LLM call ever happens inside this server.

search_knowledge and get_knowledge work against a local `knowledge/`
folder of Markdown files with YAML frontmatter (good enough for the
demo; swap the naive grep for the public GitHub repo once it exists).
search_knowledge ranks matches with a simple deterministic
field-weighting scheme - see FIELD_WEIGHTS below - no embeddings, no
vector database, no external service. publish_knowledge submits the
article as a GitHub Pull Request through the isolated publisher in
github.py - never by committing to the default branch.

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
from pathlib import Path
from typing import Optional

import frontmatter
from github import PublisherError, create_pull_request
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

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
# knowledge_article_guidelines (MCP prompt)
# --------------------------------------------------------------------------

def _article_guidelines() -> str:
    """The structuring rules the caller must follow before publish_knowledge.

    Pure function of CATEGORIES, kept separate so tests can assert on the
    exact guidance while the prompt stays a thin MCP wrapper.
    """
    return f"""You are preparing a knowledge article for a community knowledge base.
Follow ALL of these rules before calling the publish_knowledge tool.

1. Write the article in English, as native technical documentation -
   not a literal translation, regardless of the language of the
   conversation it comes from.
2. The article must be standalone knowledge, NOT a conversation record:
   no dialogue, no "as I said above", and no references to the user,
   the assistant, or the original conversation.
3. Keep only knowledge reusable by someone else facing the same
   problem; drop small talk, trial-and-error noise and dead ends.
4. Do not invent facts, commands, versions or configuration not
   supported by the source material. Explicitly preserve important
   assumptions, environment details and caveats.
5. Structure the Markdown content as:

   # Title
   ## Problem
   ## Context
   ## Solution
   ## Why it works
   ## Caveats

   "## Problem" and "## Solution" are MANDATORY. Omit "## Context",
   "## Why it works" or "## Caveats" ONLY when genuinely not applicable.
6. The title must concisely describe the problem solved.
7. The description must be a one-sentence standalone summary of the
   article.
8. Choose exactly ONE category, verbatim from this list:
   {", ".join(CATEGORIES)}
9. Provide 3 to 8 tags: lowercase, concise, technically meaningful,
   reusable, hyphens instead of spaces, no unnecessary punctuation.

Once the article is structured, call the publish_knowledge tool with
the five required fields - title, description, category, tags and
content. Do not return the article as JSON anywhere else, do not save
it to a file: publish_knowledge is the only publication path."""


@mcp.prompt()
def knowledge_article_guidelines() -> str:
    """Rules the caller must follow to structure an article before calling publish_knowledge."""
    return _article_guidelines()


# --------------------------------------------------------------------------
# publish_knowledge
# --------------------------------------------------------------------------

class PublishInput(BaseModel):
    """A fully structured article, built by the caller (never by the server)."""

    title: str
    description: str
    category: str
    tags: list[str]
    content: str


class PublishOutput(BaseModel):
    status: str  # "submitted" | "rejected" | "error"
    pull_request: Optional[str] = None
    title: Optional[str] = None
    error: Optional[str] = None


@mcp.tool()
def publish_knowledge(input: PublishInput) -> PublishOutput:
    """Submit an already-structured knowledge article as a GitHub Pull Request
    for human review.

    The CALLER structures the article (follow the knowledge_article_guidelines
    prompt): English, standalone, sections per spec 7.3, category from
    CATEGORIES, 3-8 lowercase hyphenated tags. The server does NOT generate
    or rewrite anything - no LLM is involved - it only:

      1. builds the article record from the five required fields;
      2. validates structure + runs the secret scan (never publish directly);
      3. creates a branch, commits the article, opens a PR.

    The result always signals "submitted for review", never "published".
    """
    article = {
        "title": input.title,
        "description": input.description,
        "category": input.category,
        "tags": list(input.tags),
        "content": input.content,
    }

    problems = _validate_article(article)
    if problems:
        return PublishOutput(status="rejected", error="; ".join(problems))

    try:
        pr_url = _create_pull_request(article)
    except PublisherError as exc:
        # Missing token, API failure, duplicate article path...
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
# External integration - the only one left, isolated:
#   - github.py : PR-based publication workflow (GITHUB_TOKEN)
# --------------------------------------------------------------------------

def _create_pull_request(article: dict) -> str:
    """Submit the article as a GitHub Pull Request and return the PR URL.

    Delegates to github.create_pull_request, which (spec section 14):
      1. creates a unique contribution branch from the default branch;
      2. commits `knowledge/<category>/<slug>.md` with frontmatter
         (title, description, category, tags, source: "community",
         created_at);
      3. opens a Pull Request targeting the default branch.

    CRITICAL: it never commits to the default/production branch - the PR
    is the publication request and only a human merge publishes the
    article. Raises github.PublisherError on missing token, API failure,
    or an already-existing article (clean failure, never overwrites).
    """
    return create_pull_request(article)


if __name__ == "__main__":
    mcp.run()
