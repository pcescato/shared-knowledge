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
MCP structures the knowledge
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
- [Public website](#public-website)
- [Repository structure](#repository-structure)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## How it works

The project has three logical components:

| Component | Technology | Role |
|---|---|---|
| **MCP Server** | Python + [FastMCP](https://github.com/modelcontextprotocol/python-sdk) | Interaction with AI clients, content generation, validation, classification, tag generation, GitHub integration, knowledge search |
| **Knowledge Repository** | GitHub (Markdown + Git) | Source of truth. No database: Git provides version control, attribution, review, history and rollback |
| **Documentation Website** | Astro + Starlight + GitHub Pages | Static public interface, generated from the knowledge repository |

```text
1. User solves a problem with an AI assistant
                    ↓
2. User explicitly requests: "Share this solution with the community"
                    ↓
3. AI invokes publish_knowledge
                    ↓
4. MCP generates structured English content (LLM call)
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

**AI structures; humans decide.** Only merged contributions become publicly available.

## MCP tools

The server exposes three tools:

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

MVP implementation: naive keyword match over the local `knowledge/` folder (frontmatter title/description/category + body). No vector database is required.

### `get_knowledge`

Retrieve the full content and metadata of a known article (discovered via `search_knowledge`).

**Input:**

```json
{ "id": "devops/caddy-authentik-streamlit" }
```

**Output:** the raw Markdown (`content`) and parsed frontmatter (`metadata`).

### `publish_knowledge`

Turn the relevant part of the current conversation into a standalone English knowledge article and submit it as a GitHub Pull Request.

**Input:**

```json
{
  "conversation_excerpt": "…the relevant part of the conversation…",
  "language_hint": "fr"
}
```

`language_hint` is optional — the article is always generated in **English**, whatever the source language.

**Output:**

```json
{ "status": "submitted", "pull_request": "https://github.com/…/pull/42", "title": "…" }
```

`status` is one of `submitted`, `rejected` (failed pre-moderation validation) or `error`. The result always signals **"submitted for review"**, never "published".

## Installation

Requirements:

- Python 3.10+
- The [`mcp` Python SDK](https://github.com/modelcontextprotocol/python-sdk) (`pip install "mcp[cli]"`) and `pydantic`
- For `publish_knowledge` (once wired): a Gemini (Google AI) API key and a GitHub token — see [Configuration](#configuration)

```bash
git clone https://github.com/<owner>/shared-knowledge-mcp.git
cd shared-knowledge-mcp
pip install "mcp[cli]" pydantic
```

Seed a local knowledge base so `search_knowledge` / `get_knowledge` have something to work with:

```bash
mkdir -p knowledge/devops
cat > knowledge/devops/caddy-authentik-streamlit.md <<'EOF'
---
title: "Protecting Streamlit with Caddy and Authentik"
description: "How to protect a Streamlit application using Caddy and Authentik forward authentication."
category: "DevOps"
tags:
  - caddy
  - authentik
  - reverse-proxy
  - sso
source: "community"
created_at: "2026-09-04"
---

# Protecting Streamlit with Caddy and Authentik

## Problem

Streamlit applications have no built-in authentication…

## Solution

Use Caddy as a reverse proxy with Authentik forward authentication…
EOF
```

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
AI:    (calls publish_knowledge with the relevant conversation excerpt)
       The article has been submitted as a Pull Request for review — it is not published yet.
```

## Configuration

| Environment variable | Default | Description |
|---|---|---|
| `KNOWLEDGE_DIR` | `./knowledge` | Root folder of the local Markdown knowledge base used by `search_knowledge` / `get_knowledge` |
| *(LLM credentials)* | — | API key for the Gemini (Google AI) call used by `_generate_article` |
| *(GitHub credentials)* | — | Token used by `_create_pull_request`; must be stored **outside** the repository and scoped to the minimum permissions needed to create branches, commits and Pull Requests |

GitHub authentication credentials used by the MCP must never be committed to the repository.

## Content pipeline

When `publish_knowledge` is invoked, the MCP:

1. **Extracts** the relevant knowledge from the conversation excerpt;
2. **Removes** conversational noise (no "as I said above", no references to the user, the AI or the conversation, no trial-and-error);
3. **Produces** a standalone explanation readable without the original conversation;
4. **Translates** it into English — as native technical documentation, not a literal translation;
5. **Determines** the category from the controlled vocabulary;
6. **Generates** tags;
7. **Validates** the resulting structure (required sections, category, tags) and runs the **secret scan**;
8. **Creates** a branch, commits `knowledge/<category>/<slug>.md` and opens a Pull Request.

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

The MVP enforces `## Problem` and `## Solution`; the other sections may be omitted when genuinely not applicable.

## Classification & tags

Every article gets **exactly one primary category**, chosen by the MCP/LLM from a fixed controlled vocabulary (categories are **not user-defined**, which prevents uncontrolled proliferation):

`AI` · `Backend` · `Cloud` · `Databases` · `DevOps` · `Frontend` · `Hardware` · `Linux` · `Security` · `Web Development` · `Programming` · `Open Source` · `Tools` · `Other`

Tags are generated from the content, preferring existing tags when appropriate (a new tag only when no existing one fits). Tags must be lowercase, concise, technically meaningful, reusable and free of unnecessary punctuation.

## Article format

Each article uses standardized YAML frontmatter, generated and validated by the MCP (the user does not directly control category or tags):

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

The project never publishes complete AI conversations — only the generated knowledge article. Publication is explicitly user-triggered. Generated content is scanned to avoid including names, email addresses, credentials, API keys, tokens, private URLs or internal infrastructure details.

> **Private conversation, public knowledge.**

## Public website

The public knowledge base is a fully static **Astro + Starlight** website deployed to **GitHub Pages** by GitHub Actions on every merge to the production branch — no runtime application server, no dedicated hosting. It provides a homepage, category and article navigation, tags, full-text search and a responsive documentation layout.

## Repository structure

```text
shared-knowledge-mcp/
├── server.py                  # MCP server (search / get / publish tools)
├── Shared Knowledge MCP.md    # Functional & technical specification
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
├── site/                      # Astro + Starlight documentation website
├── .github/workflows/         # deploy.yml — build & publish to GitHub Pages
├── README.md
└── LICENSE
```

## Roadmap

The MVP deliberately excludes user accounts, profiles, reputation, voting, comments, social features, a custom admin interface, vector databases, automatic publication without review, conversation storage and analytics. Future possibilities (explicitly out of MVP scope) include:

- semantic / vector search and duplicate detection;
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
2. Make your changes (the two remaining TODOs in `server.py` — `_generate_article` and `_create_pull_request` — are a great place to start);
3. Test locally with `mcp dev server.py`;
4. Open a Pull Request.

## License

[MIT](LICENSE) © Pascal CESCATO
