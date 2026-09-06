# Shared Knowledge MCP

> **Turn solved problems into shared knowledge.**
> *Don't just get the answer. Give the answer back.*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Status: MVP skeleton](https://img.shields.io/badge/status-MVP%20skeleton-orange)

**Shared Knowledge MCP** is a community-driven knowledge base built around AI-assisted problem solving. It is an [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server that lets any MCP-compatible AI assistant (Claude, ChatGPT/Codex, Cursor, …) **search** a shared knowledge base before solving a problem from scratch, and **publish** a freshly solved problem as a community knowledge article — submitted as a GitHub Pull Request for human review, then published as a static documentation website.

The core principle:

> **The conversation remains private. The knowledge extracted from it can be shared.**
> Sharing is always explicit and voluntary — nothing is ever published without the user asking for it.

```text
Private conversation
        ↓
AI-assisted solution
        ↓
User chooses to share
        ↓
Caller structures the article (guidelines prompt)
        ↓
GitHub Pull Request
        ↓
Human review
        ↓
Shared knowledge base
        ↓
Available to the next user
```

---

## Table of Contents

- [How it works](#how-it-works)
- [MCP tools](#mcp-tools)
- [Installation](#installation)
- [Usage](#usage)
  - [Run the server](#run-the-server)
  - [Connect an MCP client](#connect-an-mcp-client)
  - [Example conversation](#example-conversation)
- [Configuration](#configuration)
- [Content pipeline](#content-pipeline)
- [Classification & tags](#classification--tags)
- [Article format](#article-format)
- [Moderation & privacy](#moderation--privacy)
- [Audio versions (ElevenLabs)](#audio-versions-elevenlabs)
- [Public website](#public-website)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## How it works

The project has three logical components:

| Component | Technology | Role |
|---|---|---|
| **MCP Server** | Python + [FastMCP](https://github.com/modelcontextprotocol/python-sdk) | Interaction with AI clients, validation, GitHub integration, knowledge search. The server performs **no LLM call**: the caller structures the article itself |
| **Knowledge Repository** | GitHub (Markdown + Git) | Source of truth. No database: Git provides version control, attribution, review, history and rollback |
| **Documentation Website** | Astro + Starlight + GitHub Pages | Static public interface, generated from the knowledge repository |

```text
1. User solves a problem with an AI assistant
                    ↓
2. User explicitly requests: "Share this solution with the community"
                    ↓
3. AI structures the article itself (knowledge_article_guidelines prompt)
                    ↓
4. AI invokes publish_knowledge with the five required fields
                    ↓
5. MCP validates content and metadata + secret scan
                    ↓
6. MCP creates a GitHub branch, commits the Markdown article
                    ↓
7. MCP opens a Pull Request
                    ↓
8. Human maintainer reviews the contribution
                    ↓
9. Pull Request is merged
                    ↓
10. GitHub Actions builds the site → Astro/Starlight → GitHub Pages
```

**AI structures; humans decide.** The structuring happens in the caller's assistant (guided by the `knowledge_article_guidelines` prompt), never inside the server; only merged contributions become publicly available. The published article is also the source of truth for its audio version — audio is generated from the validated Markdown after human review, never before.

## MCP tools & prompts

The server exposes three tools and one prompt:

### `search_knowledge`

Search the shared knowledge base for articles relevant to a query.

**Input:**

```json
{ "query": "Caddy Authentik Streamlit forward authentication" }
```

**Output:**

```json
{
  "results": [
    {
      "title": "Protecting Streamlit with Caddy and Authentik",
      "category": "DevOps",
      "url": "knowledge/devops/caddy-authentik-streamlit.md",
      "summary": "How to protect a Streamlit application using Caddy and Authentik forward authentication."
    }
  ]
}
```

Implementation: dependency-light keyword search over the local `knowledge/` folder (frontmatter title/tags/description/category + body), ranked by a deterministic field-weighting scheme — a query term scores 8 in the title, 6 in tags, 4 in the description, 2 in the category and 1 in the body, and scores accumulate per term and field. Results are sorted by relevance (highest first, ties broken by title) before the 10-result limit is applied. No embeddings, vector database or external service involved.

### `get_knowledge`

Retrieve the full content and metadata of a known article (discovered via `search_knowledge`).

**Input:**

```json
{ "id": "devops/caddy-authentik-streamlit" }
```

**Output:** the raw Markdown (`content`) and parsed frontmatter (`metadata`).

### `knowledge_article_guidelines` (prompt)

An MCP prompt returning the structuring rules the caller must follow **before** calling `publish_knowledge`: English only, standalone article (no references to the user, the assistant or the conversation), Markdown structure with mandatory `## Problem` and `## Solution` sections (`## Context` / `## Why it works` / `## Caveats` omitted only when genuinely not applicable), exactly one category from `CATEGORIES`, and 3–8 lowercase hyphenated tags. The prompt ends by instructing the caller to pass the five fields straight to `publish_knowledge` — there is no other publication path.

### `publish_knowledge`

Submit an **already-structured** knowledge article as a GitHub Pull Request. The server does **not** generate, translate or rewrite anything — no LLM is involved. The caller (the user's AI assistant, guided by the `knowledge_article_guidelines` prompt) structures the article and provides the five required fields:

**Input (all fields required):**

```json
{
  "title": "Protecting Streamlit with Caddy and Authentik",
  "description": "How to protect a Streamlit application using Caddy and Authentik forward authentication.",
  "category": "DevOps",
  "tags": ["caddy", "authentik", "streamlit", "reverse-proxy", "sso"],
  "content": "# Protecting Streamlit with Caddy and Authentik\n\n## Problem\n…\n\n## Solution\n…"
}
```

- `title`: concise description of the problem solved;
- `description`: one-sentence standalone summary;
- `category`: exactly one value from the [controlled vocabulary](#classification--tags);
- `tags`: 3–8 lowercase, hyphenated, reusable tags;
- `content`: full Markdown body with the required sections.

**Output:**

```json
{ "status": "submitted", "pull_request": "https://github.com/…/pull/42", "title": "…" }
```

`status` is one of `submitted`, `rejected` (failed pre-moderation validation) or `error`. The result always signals **"submitted for review"**, never "published".

## Installation

Requirements:

- Python 3.10+
- For `publish_knowledge`: a GitHub token — see [Configuration](#configuration)

Dependencies (`mcp`, `pydantic`, `python-frontmatter`, `httpx`) are declared in `pyproject.toml`. Install the project in editable mode with its dev tools:

```bash
git clone https://github.com/pcescato/shared-knowledge.git
cd shared-knowledge
pip install -e . --group dev
```

To use `publish_knowledge`, install the publishing extra (GitHub publication):

```bash
pip install -e '.[publishing]' --group dev
```

> Using `pip` < 25.1 or another tool? The equivalent is `pip install -e . && pip install pytest` (or `uv sync --dev` with [uv](https://docs.astral.sh/uv/)).

A small seed knowledge base already lives in [`knowledge/`](knowledge/) so `search_knowledge` / `get_knowledge` work out of the box.

## Usage

### Run the server

Local testing with the MCP dev inspector:

```bash
mcp dev server.py
```

Or run it directly:

```bash
python server.py
```

### Connect an MCP client

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "shared-knowledge": {
      "command": "python",
      "args": ["/absolute/path/to/server.py"]
    }
  }
}
```

Or point a **claude.ai / other MCP-compatible connector** config at the same script.

### Example conversation

```text
User:  How do I configure Caddy with Authentik to protect a Streamlit application?
AI:    I found a relevant community solution covering Caddy, Authentik and forward authentication.
       (the assistant called search_knowledge and uses the retrieved article as context)

…the assistant solves a new variant of the problem…

User:  Share this solution with the community.
AI:    (loads the knowledge_article_guidelines prompt, structures the article itself,
       then calls publish_knowledge with title/description/category/tags/content)
       The article has been submitted as a Pull Request for review — it is not published yet.
```

## Configuration

| Environment variable | Default | Description |
|---|---|---|
| `KNOWLEDGE_DIR` | `./knowledge` | Root folder of the local Markdown knowledge base used by `search_knowledge` / `get_knowledge` |
| `GITHUB_TOKEN` | — | **Required for `publish_knowledge`.** GitHub token used to create the contribution branch, commit the article and open the Pull Request. Minimum permissions: fine-grained PAT with **Contents: read and write** + **Pull requests: write** on `pcescato/shared-knowledge` only (classic PAT: `repo` scope) |
| `GITHUB_REPO` | `pcescato/shared-knowledge` | Repository of record — the source of truth for community knowledge |

No credentials are hard-coded: everything is read from environment variables. The server performs no LLM call: articles arrive already structured from the caller, and any structuring or validation failure surfaces as a clean `rejected`/`error` result from `publish_knowledge` rather than a fabricated article.

### Publication workflow (GitHub)

The publication side is isolated in [`github.py`](github.py). When `publish_knowledge` reaches the submission step, it:

1. creates a unique contribution branch (`knowledge/contribution-YYYY-MM-DD-<slug>`) from the repository's default branch;
2. commits the article to `knowledge/<category>/<slug>.md` with YAML frontmatter (`title`, `description`, `category`, `tags`, `source: community`, `created_at`);
3. opens a Pull Request targeting the default branch and returns its URL.

**The tool never commits to the default branch** — the Pull Request *is* the publication request, and only a human maintainer merging it makes the contribution eligible for publication. If an article already exists at the target path, the submission fails cleanly instead of overwriting it. A failed run rolls back its contribution branch.

GitHub authentication credentials used by the MCP must never be committed to the repository.

## Content pipeline

When `publish_knowledge` is invoked, the caller has already structured the article (guided by the `knowledge_article_guidelines` prompt); the MCP then:

1. **Builds** the article record from the five required fields (no generation, no LLM call);
2. **Validates** the structure (required sections, category, tags) and runs the **secret scan**;
3. **Creates** a branch, commits `knowledge/<category>/<slug>.md` and opens a Pull Request.

### Required article structure

```markdown
# Title

## Problem
What problem is being solved?

## Context
Relevant environment, constraints and assumptions.

## Solution
The proposed solution.

## Why it works
A concise explanation of the underlying reasoning.

## Caveats
Important limitations, assumptions or things to verify.
```

The MCP enforces `## Problem` and `## Solution`; the other sections may be omitted when genuinely not applicable. The full structuring rules are exposed to callers through the `knowledge_article_guidelines` prompt.

## Classification & tags

Every article gets **exactly one primary category**, chosen by the caller (the user's AI assistant) from a fixed controlled vocabulary (categories are **not user-defined**, which prevents uncontrolled proliferation):

`AI` · `Backend` · `Cloud` · `Databases` · `DevOps` · `Frontend` · `Hardware` · `Linux` · `Security` · `Web Development` · `Programming` · `Open Source` · `Tools` · `Other`

Tags are chosen by the caller from the content, preferring existing tags when appropriate (a new tag only when no existing one fits). Tags must be lowercase, concise, technically meaningful, reusable and free of unnecessary punctuation.

## Article format

Each article uses standardized YAML frontmatter, built from the caller-provided fields and validated by the MCP (the user does not directly control category or tags):

```yaml
---
title: "Protecting Streamlit with Caddy and Authentik"
description: "How to protect a Streamlit application using Caddy and Authentik forward authentication."
category: "DevOps"
tags:
  - caddy
  - authentik
  - streamlit
  - reverse-proxy
  - sso
source: "community"
created_at: "2026-09-04"
---
```

## Moderation & privacy

**Contributions are never published directly to the production branch.** Every contribution is a Pull Request, which provides human moderation, attribution, version history, auditability and rollback, and protects against automated spam.

### Automated pre-moderation (advisory)

Before creating the Pull Request, the MCP performs basic validation. Rejection conditions include:

- empty or meaningless content;
- obvious spam or promotional content;
- personal information (the secret scan flags API keys — `sk-…`, `ghp_…`, `AIza…`, PEM private keys — and email addresses);
- offensive or abusive content;
- content unrelated to knowledge sharing;
- malformed metadata (unknown category, missing title/tags, missing required sections);
- excessively long content;
- obvious duplicate content.

AI-based moderation is advisory. **Human maintainers remain the final authority.**

### Privacy

The project never publishes complete AI conversations — only the structured knowledge article submitted by the caller. Publication is explicitly user-triggered. Submitted content is scanned to avoid including names, email addresses, credentials, API keys, tokens, private URLs or internal infrastructure details.

> **Private conversation, public knowledge.**

## Audio versions (ElevenLabs)

Every published article can have an audio version, so the shared knowledge can also be *listened to*.

> **The published article is the source of truth; ElevenLabs gives that validated knowledge a voice.**

### Why audio is generated after human review

Audio is **never** generated when `publish_knowledge()` opens the Pull Request. The authoritative sequence is:

```text
MCP → Markdown article → GitHub Pull Request → Human review → Merge
     → GitHub Action → ElevenLabs → Audio artifact
```

Generating audio only after a maintainer merges the article means the spoken version is always derived from **validated, approved content** — never from an unreviewed submission. The final Markdown article is the sole source for the speech text; the original conversation is never involved.

### How it works

The [`.github/workflows/audio.yml`](.github/workflows/audio.yml) workflow runs when knowledge articles land on the default branch. A small script ([`scripts/generate_audio.py`](scripts/generate_audio.py)):

1. strips the YAML frontmatter and converts the Markdown body into clean spoken text (no code blocks, no link URLs, no markup);
2. sends that text to ElevenLabs;
3. saves the audio at a **deterministic path** mirroring the article:

```text
knowledge/<category>/<slug>.md  →  site/public/audio/<category>/<slug>.mp3
```

4. records a content hash in `.audio_manifest.json`.

The audio files and the manifest are committed to the repository, so the static site simply ships them. Generation is **idempotent**: only new or changed articles are sent to ElevenLabs (manifest hash + audio file presence), never every article on every deployment. If ElevenLabs fails for an article, the Markdown article remains valid, no audio is claimed for it (nothing is committed for that article), and the workflow fails loudly with a clear report.

### Configuration

Configure these as **repository secrets** (Settings → Secrets and variables → Actions) — never committed to the repository:

| Secret | Required | Description |
|---|---|---|
| `ELEVENLABS_API_KEY` | yes | ElevenLabs API key ([elevenlabs.io](https://elevenlabs.io)) |
| `ELEVENLABS_VOICE_ID` | yes | ID of the voice to use — deliberately configurable, not hard-coded (pick one in your ElevenLabs voice library) |
| `ELEVENLABS_MODEL_ID` | no | TTS model (defaults to `eleven_multilingual_v2`) |

## Public website

The public knowledge base lives in [`site/`](site/) and is built with **Astro + Starlight** as a fully static website — no runtime application server, no database. It provides a homepage, category navigation, an all-articles index, tags, built-in full-text search (Pagefind), a responsive documentation layout and article pages with an optional *Listen to this article* audio player.

The Markdown knowledge repository remains the **source of truth**: the site reads `knowledge/**/*.md` directly through a content collection — no article content is duplicated inside the website. URLs are stable and human-readable:

```text
knowledge/<category>/<slug>.md  →  /<category>/<slug>/
                                →  /audio/<category>/<slug>.mp3   (when audio exists)
```

Deployment targets **GitHub Pages** as a project page (`https://pcescato.github.io/shared-knowledge/`); the Astro `base` is already configured for it. The [`deploy.yml`](.github/workflows/deploy.yml) workflow builds `site/` (articles + audio included), verifies every knowledge article has a built page, and publishes `site/dist/` to Pages. It runs only on changes that are already on the default branch — i.e. after human review.

> **The published article is the source of truth for its audio version.** Audio is regenerated only when the merged article changes, never ahead of review.

### Local development

```bash
cd site
npm install
npm run dev       # dev server with hot reload
npm run build     # static build to site/dist/
npm run preview   # preview the production build locally
```

## Repository structure

```text
shared-knowledge-mcp/
├── server.py                  # MCP server (search / get / publish tools + guidelines prompt)
├── github.py                  # Isolated GitHub publisher (branch → commit → PR)
├── Shared Knowledge MCP.md    # Functional & technical specification
├── pyproject.toml             # Packaging & dependencies (Python 3.10+)
├── tests/                     # pytest suite (frontmatter, search, get_knowledge, validation, prompt contract)
├── scripts/
│   └── generate_audio.py      # ElevenLabs TTS for merged articles (CI)
├── .github/workflows/
│   └── audio.yml              # Audio generation after merge (human review first)
├── knowledge/                 # Markdown knowledge base (YAML frontmatter)
│   ├── ai/
│   ├── backend/
│   ├── cloud/
│   ├── databases/
│   ├── devops/
│   ├── frontend/
│   ├── hardware/
│   ├── linux/
│   ├── open-source/
│   ├── programming/
│   ├── security/
│   ├── tools/
│   └── web-development/
├── site/                      # Astro + Starlight public knowledge base
│   ├── astro.config.mjs       # Starlight config (base path, sidebar, Pagefind)
│   ├── src/pages/             # Homepage, category/tag/article pages
│   ├── src/lib/knowledge.js   # URL/audio contract helpers (mirrors slugify)
│   └── public/audio/          # ElevenLabs artifacts (generated, committed)
├── .github/workflows/
│   ├── audio.yml              # Audio generation after merge (human review first)
│   └── deploy.yml             # Build site/ and publish to GitHub Pages
├── README.md
└── LICENSE
```

## Roadmap

The MVP deliberately excludes user accounts, profiles, reputation, voting, comments, social features, a custom admin interface, vector databases, automatic publication without review, conversation storage and analytics. Future possibilities (explicitly out of MVP scope) include:

- semantic / vector search and duplicate detection (existing-article paths currently fail the submission cleanly);
- article relationships and knowledge freshness detection;
- automatic link checking and quality scoring;
- multiple language views;
- contributor attribution and community corrections;
- federated knowledge repositories;
- support for additional AI clients;
- automated knowledge consolidation.

## Contributing

### As a knowledge contributor

The primary contribution path is **through your AI assistant**: solve a problem, then say *"Share this solution with the community."* The article lands as a Pull Request that maintainers review before publication.

You can also open a Pull Request manually: add a Markdown article under `knowledge/<category>/` following the [article format](#article-format).

### As a code contributor

1. Fork the repository and create a feature branch;
2. Make your changes (the external integration — [`github.py`](github.py) — is small and self-contained, a good place to start);
3. Run the test suite: `pytest`;
4. Test the server locally with `mcp dev server.py`;
5. Open a Pull Request.

## License

[MIT](LICENSE) © Pascal CESCATO
