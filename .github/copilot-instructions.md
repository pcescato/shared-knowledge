# Copilot Instructions for Shared Knowledge MCP

## Quick Start

**What this project does:** An MCP (Model Context Protocol) server that lets AI assistants search a community knowledge base and publish solved problems as GitHub Pull Requests for human review.

**Main entry points:**
- `server.py` (381 lines) — MCP FastMCP server with three tools: `search_knowledge`, `get_knowledge`, `publish_knowledge`
- `github.py` (300 lines) — GitHub API integration for creating PRs; reads `GITHUB_TOKEN` from environment
- `llm.py` (249 lines) — LLM provider abstraction; default is Gemini via `google-genai` SDK

## Build, Test & Lint Commands

### Running tests
```bash
# Run all tests
pytest

# Run a single test file
pytest tests/test_server.py

# Run a single test class
pytest tests/test_server.py::TestFrontmatterParsing

# Run a single test
pytest tests/test_server.py::TestSearchRanking::test_title_match_outranks_repeated_body_match

# Run with verbose output
pytest -v
```

### Testing the MCP server locally
```bash
# Launch the MCP dev inspector (interactive)
mcp dev server.py
```

### No linter currently configured
The project has no `ruff`, `black`, or other linting tool set up yet. Code follows PEP 8 informally.

## Project Architecture

### Three components

| Component | Technology | Role |
|---|---|---|
| **MCP Server** | Python + FastMCP | Interact with AI clients; search knowledge base; generate & validate articles; GitHub PR integration |
| **Knowledge Base** | GitHub + Markdown + Git | Source of truth — Git provides version control, attribution, review, history |
| **Documentation Site** | Astro + Starlight | Static site built from `knowledge/` directory; audio artifacts from ElevenLabs workflow |

### Core workflow (publish_knowledge)

```
User solves problem with AI
    ↓
User requests: "Share this solution"
    ↓
publish_knowledge() called
    ↓
LLM generates structured article (ArticleDraft Pydantic model)
    ↓
_validate_article() checks content + metadata
    ↓
_scan_secrets() blocks API keys, tokens, PEM keys, emails
    ↓
create_pull_request() on GitHub (never commits to main)
    ↓
Human review + merge
    ↓
Site deployment (deploy.yml) + audio generation (audio.yml)
```

### Module responsibilities

**server.py**
- Exposes three MCP tools: `search_knowledge`, `get_knowledge`, `publish_knowledge`
- Implements search with deterministic field weighting (title: 8.0, tags: 6.0, description: 4.0, category: 2.0, body: 1.0)
- Article validation enforces `REQUIRED_SECTIONS = ["## Problem", "## Solution"]`
- Path traversal protection on `get_knowledge()` (validates `id` stays inside `KNOWLEDGE_DIR`)

**github.py**
- Wraps GitHub REST API; never called directly by server.py
- Reads `GITHUB_TOKEN` from environment (fine-grained PAT minimum: contents read/write + PR write on `pcescato/shared-knowledge`)
- Creates unique contribution branch from default branch
- Commits Markdown with YAML frontmatter to `knowledge/<category>/<slug>.md`
- Opens PR; returns PR URL or raises `PublisherError`
- **Critical:** never pushes to main/default branch

**llm.py**
- Provider abstraction — swap LLM without changing server.py
- Default: Gemini via `google-genai` SDK (reads `GOOGLE_API_KEY` from environment)
- Requests structured JSON output constrained by `ArticleDraft` Pydantic schema
- Category validation happens twice: in LLM prompt AND re-validated against `server.CATEGORIES`
- Every error (missing key, malformed response, invalid schema) raises `ProviderError`

### Configuration

**Environment variables**
- `KNOWLEDGE_DIR` — path to local knowledge base folder (default: `./knowledge/`)
- `GITHUB_TOKEN` — GitHub personal access token (required to publish)
- `GOOGLE_API_KEY` — Gemini API key (required for publish_knowledge)
- `GITHUB_REPOSITORY` — full repo path (default: `pcescato/shared-knowledge`)

**Categories** (server.py, `CATEGORIES` constant)
Currently: DevOps, Databases, Hardware, Linux, Web Development, Backend

**Search ranking** (server.py, `FIELD_WEIGHTS`)
- Title: 8.0
- Tags: 6.0
- Description: 4.0
- Category: 2.0
- Body: 1.0

Results capped at 10 articles (deterministic, no embeddings).

## Key Conventions & Patterns

### Article format (frontmatter + Markdown)
```markdown
---
title: "Descriptive title"
description: "One-sentence summary"
category: "DevOps"
tags:
  - tag1
  - tag2
tags:
source: "community"
created_at: "YYYY-MM-DD"
---

# Title

## Problem

...

## Solution

...

## Why it works

...

## Caveats

...
```

**Frontmatter parsing:** Custom lightweight hand-rolled parser in `_parse_frontmatter()` (spec section 7). Supports:
- Scalars: `key: value` or `key: "quoted value"`
- YAML lists: `tags:\n  - item1\n  - item2`
- No nested objects; no list support outside `tags`

### Secret scanning (github.py, `_scan_secrets()`)
Blocks commits if they contain:
- Generic API key patterns (`api_key=`, `api-key:`, etc.)
- GitHub PATs (`ghp_`, `ghs_`, `ghu_`)
- Google service account keys (JSON with `private_key`)
- PEM-encoded private keys (`-----BEGIN.*PRIVATE KEY-----`)
- Email addresses (basic pattern)

Conservative by design — false positives are cheap in PR review.

### Error handling
- `PublisherError` — raised by github.py; returned to MCP client as error status
- `ProviderError` — raised by llm.py; returned to MCP client as error status
- FileNotFoundError from `get_knowledge()` — caught and converted to clean MCP error

### Tests & fixtures
- Tests use pytest with temporary knowledge directories (conftest.py fixtures)
- `knowledge_dir` fixture — seeded with two sample articles in `devops/` and `databases/`
- `ranking_dir` fixture — extended with 17 articles for search relevance testing
- `valid_article` fixture — returns a dict that passes `_validate_article()` for mutation testing

## Deployment Workflows

### deploy.yml (GitHub Pages)
- Triggered by pushes to main affecting `knowledge/`, `site/`, or the workflow itself
- Builds Astro/Starlight site from `knowledge/` + pre-committed audio assets
- Verifies all `.md` articles have corresponding `.html` pages
- Verifies audio `.mp3` files are copied into the build
- Deploys to GitHub Pages

### audio.yml (ElevenLabs audio generation)
- Triggered after a merge (article reviewed by human)
- Uses `scripts/generate_audio.py` to generate `.mp3` for new/changed articles
- Reads `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` from secrets
- Commits audio artifacts back to main so the site ships them without runtime dependency

## Related Spec & Documentation

- **Shared Knowledge MCP.md** — Authoritative specification (7000+ lines); defines MCP interface, article format, validation rules, publication workflow, categories, secret scanning, moderation, privacy model
- **NOTES.md** — Side notes from README generation; lists warnings and open questions (e.g., publish_knowledge is not yet wired, article structure validator is stricter than enforced)
- **README.md** — User-facing overview; installation, usage, configuration, architecture

## Known TODOs & Limitations

- `publish_knowledge` is **not fully functional yet** — `_generate_article()` and `_create_pull_request()` raise `NotImplementedError`. Search and fetch tools work.
- `search_knowledge` has no ranking by relevance snippet — returns frontmatter `description` only, even for body matches
- Frontmatter parser is hand-rolled — no nested objects, no list support outside `tags`
- Path traversal check in `get_knowledge()` is basic — should be hardened before exposing to third-party clients
- Duplicate detection is not implemented — deferred to maintainer review in PR
- Article structure validator enforces only `["## Problem", "## Solution"]` (2 sections), but spec lists 5 sections and says omit only if not applicable — mismatch is intentional MVP simplification

---

**Repository:** pcescato/shared-knowledge | **License:** MIT
