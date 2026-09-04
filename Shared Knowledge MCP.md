# Shared Knowledge MCP
## Functional & Technical Specification — MVP

> **Turn solved problems into shared knowledge.**

### 1. Overview

Shared Knowledge MCP is a community-driven knowledge base built around AI-assisted problem solving.

When an AI assistant such as ChatGPT, Claude, or another MCP-compatible client helps a user solve a problem, the user can explicitly ask the assistant to **share the solution with the community**.

The MCP server transforms the relevant part of the conversation into a concise, self-contained knowledge article, automatically written in English and classified with a controlled category and generated tags.

The contribution is submitted to a GitHub repository as a Pull Request. Human maintainers review and approve the contribution before it becomes part of the public knowledge base.

The approved Markdown content is then automatically published as a static documentation website using Astro and Starlight, hosted on GitHub Pages.

### 2. Motivation

AI assistants are increasingly becoming the first place where people solve technical and non-technical problems.

However, a large amount of useful knowledge produced during these conversations remains locked inside private conversations.

The project introduces a simple mechanism to turn individual problem solving into collective knowledge:

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

The fundamental principle is:

> **The conversation remains private.  
> The knowledge extracted from it can be shared.**

Sharing is always explicit and voluntary.

---

# 3. Goals

The MVP must:

- provide an MCP server usable by AI assistants;
- allow users to search the shared knowledge base;
- allow users to submit a solution for publication;
- automatically transform the submitted content into a standalone knowledge article;
- generate the article in English;
- automatically assign a category;
- automatically generate relevant tags;
- enforce a consistent Markdown/frontmatter structure;
- submit contributions through GitHub Pull Requests;
- keep human review as the final publication authority;
- publish approved content as a static documentation website;
- provide useful navigation and search;
- require no dedicated application database.

# 4. Non-Goals

The MVP deliberately does **not** attempt to provide:

- user accounts;
- user profiles;
- reputation or karma;
- voting;
- comments;
- social networking;
- real-time collaboration;
- a custom administration interface;
- a vector database;
- a proprietary RAG platform;
- automatic publication without human review;
- storage of complete AI conversations;
- analytics or user tracking.

These features may be considered in future versions but are outside the scope of the challenge.

---

# 5. Core User Stories

## 5.1 Search existing knowledge

As a user interacting with an AI assistant,

I want the assistant to search the community knowledge base before solving a problem from scratch,

so that existing solutions can be reused or considered.

Example:

```text
User:
How do I configure Caddy with Authentik to protect a Streamlit application?

AI:
I found a relevant community solution covering Caddy,
Authentik and forward authentication.
```

The AI may then use the retrieved knowledge as contextual information.

---

## 5.2 Share a solution

After solving a problem with an AI assistant, the user can say:

```text
Share this solution with the community.
```

The AI invokes the MCP publication tool.

The MCP:

1. extracts the relevant knowledge;
2. removes conversational noise;
3. produces a standalone explanation;
4. translates it into English if necessary;
5. determines the category;
6. generates tags;
7. validates the resulting structure;
8. creates a GitHub Pull Request.

---

## 5.3 Review a contribution

A maintainer receives a standard GitHub Pull Request.

The contribution contains:

- the generated Markdown article;
- metadata;
- the proposed category;
- generated tags.

The maintainer can:

- merge the Pull Request;
- close it;
- request changes.

Only merged contributions become publicly available.

---

## 5.4 Discover shared knowledge

A visitor can browse the public knowledge base by:

- category;
- tags;
- topic;
- search query.

The documentation website provides the primary human-facing interface.

---

# 6. MCP Interface

The MVP exposes three primary MCP tools.

## `search_knowledge`

Search the shared knowledge base.

### Input

```json
{
  "query": "Caddy Authentik Streamlit forward authentication"
}
```

### Output

A concise list of relevant articles:

```json
{
  "results": [
    {
      "title": "Protecting Streamlit with Caddy and Authentik",
      "category": "DevOps",
      "url": "...",
      "summary": "..."
    }
  ]
}
```

The search implementation may initially use GitHub repository content or a lightweight generated index.

No vector database is required for the MVP.

---

## `publish_knowledge`

Create a community contribution from the current conversation.

### Input

The MCP receives the relevant conversation context supplied by the AI client.

The user must explicitly request publication.

### Processing

The MCP instructs the configured LLM to produce a structured article:

```json
{
  "title": "...",
  "description": "...",
  "category": "...",
  "tags": [],
  "content": "..."
}
```

The MCP validates the generated structure before creating the contribution.

### Output

```json
{
  "status": "submitted",
  "pull_request": "...",
  "title": "..."
}
```

The result must make it clear that the content has been **submitted for review**, not published automatically.

---

## `get_knowledge`

Retrieve a specific knowledge article.

This allows an AI assistant to retrieve the complete content of a known article after discovering it through search.

### Input

```json
{
  "id": "..."
}
```

### Output

The article content and metadata.

---

# 7. Content Generation Rules

All published content must comply with the following rules.

## 7.1 Language

The canonical language of the knowledge base is **English**.

The source conversation may be in any language.

The MCP must generate the final article in English.

The result should read as native technical documentation rather than as a literal translation.

---

## 7.2 Standalone Knowledge

The generated article must be understandable without access to the original conversation.

It must not contain:

- references such as "as I said above";
- references to the user;
- references to the AI conversation;
- personal information;
- unnecessary conversational dialogue;
- irrelevant trial-and-error;
- unsupported claims presented as facts.

---

## 7.3 Required Structure

Each article should follow this general structure:

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

Sections may be omitted when they are genuinely not applicable.

---

# 8. Classification

Each contribution must receive exactly one primary category.

The initial controlled vocabulary is:

```text
AI
Backend
Cloud
Databases
DevOps
Frontend
Hardware
Linux
Security
Web Development
Programming
Open Source
Tools
Other
```

The MCP/LLM must select the most appropriate existing category.

Categories are **not user-defined**.

This prevents uncontrolled category proliferation.

---

# 9. Tags

Tags are automatically generated from the content.

Example:

```yaml
tags:
  - caddy
  - authentik
  - reverse-proxy
  - sso
  - docker
```

The generation process should prefer existing tags when appropriate.

A new tag may only be introduced when an existing tag cannot accurately describe the subject.

Tags must be:

- lowercase;
- concise;
- technically meaningful;
- reusable;
- free of unnecessary punctuation.

---

# 10. Article Metadata

Each article uses standardized frontmatter.

Example:

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

The metadata is generated and validated by the MCP.

The user does not directly control the category or tags.

---

# 11. Moderation

Community contributions must never be published directly to the production branch.

Every contribution creates a Pull Request.

This provides:

- human moderation;
- attribution;
- version history;
- auditability;
- the ability to correct or revert content;
- protection against automated spam.

## Automated pre-moderation

Before creating the Pull Request, the MCP should perform basic validation.

Possible rejection conditions include:

- empty or meaningless content;
- obvious spam;
- promotional content;
- personal information;
- offensive or abusive content;
- content unrelated to knowledge sharing;
- malformed metadata;
- excessively long content;
- obvious duplicate content.

AI-based moderation is advisory.

**Human maintainers remain the final authority.**

---

# 12. Privacy

The project must not publish complete AI conversations.

Only the generated knowledge article is submitted.

The publication process is explicitly user-triggered.

The system should therefore follow this principle:

> **Private conversation, public knowledge.**

The MCP should avoid including:

- names;
- email addresses;
- credentials;
- API keys;
- tokens;
- private URLs;
- internal infrastructure details;
- other sensitive information.

The generated content must be reviewed before publication.

---

# 13. Repository Structure

A possible repository structure:

```text
shared-knowledge/
│
├── knowledge/
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
│
├── src/
│   └── mcp/
│
├── site/
│   └── ...
│
├── .github/
│   └── workflows/
│       └── deploy.yml
│
├── README.md
└── package.json
```

The exact implementation structure may differ as long as the separation between MCP code, knowledge content and documentation site remains clear.

---

# 14. Publication Workflow

The complete publication workflow is:

```text
1. User solves a problem with an AI assistant
                    ↓
2. User explicitly requests:
   "Share this solution with the community"
                    ↓
3. AI invokes publish_knowledge
                    ↓
4. MCP generates structured English content
                    ↓
5. MCP validates content and metadata
                    ↓
6. MCP creates a GitHub branch
                    ↓
7. MCP commits the Markdown article
                    ↓
8. MCP opens a Pull Request
                    ↓
9. Human maintainer reviews the contribution
                    ↓
10. Pull Request is merged
                    ↓
11. GitHub Actions builds the website
                    ↓
12. Astro/Starlight deploys to GitHub Pages
```

---

# 15. Static Website

The public knowledge base is implemented using **Astro + Starlight**.

The website should provide:

- homepage;
- category navigation;
- article navigation;
- tags;
- full-text search;
- responsive documentation layout;
- links to source contributions where appropriate.

The website is entirely static.

No runtime application server is required for the public knowledge base.

---

# 16. Deployment

Deployment is handled by GitHub Actions.

On every merge to the production branch:

```text
GitHub
   ↓
GitHub Actions
   ↓
Install dependencies
   ↓
Build Astro/Starlight
   ↓
Deploy
   ↓
GitHub Pages
```

The MVP therefore requires no dedicated hosting infrastructure.

---

# 17. Technical Architecture

The MVP consists of three logical components.

## MCP Server

Responsible for:

- interaction with AI clients;
- content generation;
- validation;
- classification;
- tag generation;
- GitHub integration;
- knowledge search.

Possible implementation:

```text
Python
FastAPI / MCP SDK
GitHub API
LLM API
```

The implementation language is not strictly mandated.

---

## Knowledge Repository

GitHub is the source of truth.

Markdown files represent the knowledge articles.

Git provides:

- version control;
- attribution;
- review;
- history;
- rollback;
- contribution workflow.

No database is required for the MVP.

---

## Documentation Website

```text
Astro
+
Starlight
+
GitHub Pages
```

The site is generated directly from the Markdown knowledge repository.

---

# 18. Security Considerations

The MCP must never commit secrets supplied by the conversation.

Before publication, generated content should be checked for patterns resembling:

- API keys;
- passwords;
- access tokens;
- private keys;
- authentication headers;
- personal email addresses.

GitHub authentication credentials used by the MCP must be stored outside the repository.

The GitHub token must have the minimum permissions necessary to create branches, commits and Pull Requests.

---

# 19. MVP Success Criteria

The MVP is considered successful when the following demonstration can be completed:

### Step 1 — Solve

A user asks an AI assistant a real technical question.

### Step 2 — Share

The user says:

```text
Share this solution with the community.
```

### Step 3 — Generate

The MCP produces:

- an English article;
- one category;
- relevant tags;
- standardized metadata.

### Step 4 — Submit

The MCP creates a GitHub Pull Request.

### Step 5 — Moderate

A maintainer reviews and merges the Pull Request.

### Step 6 — Publish

GitHub Actions automatically builds and deploys the documentation site.

### Step 7 — Reuse

A second AI conversation searches the community knowledge base and retrieves the published solution.

The complete loop must work end-to-end.

---

# 20. Design Principles

The MVP follows a small number of principles.

### 1. Sharing is voluntary

Nothing is published unless the user explicitly asks for it.

### 2. Conversations remain private

Only the generated knowledge is shared.

### 3. AI structures; humans decide

AI generates and classifies content.

Humans retain publication authority.

### 4. Git is the database

The knowledge base should remain human-readable, versioned and forkable.

### 5. Static by default

The public website does not need a backend.

### 6. Community before platform

The project should facilitate knowledge sharing rather than create another social network.

### 7. Keep it small

The MVP should demonstrate the complete idea without attempting to solve every problem surrounding community knowledge management.

---

# 21. Future Possibilities

The architecture intentionally leaves room for future evolution.

Potential extensions include:

- semantic/vector search;
- duplicate detection;
- article relationships;
- knowledge freshness detection;
- automatic link checking;
- article quality scoring;
- multiple language views;
- contributor attribution;
- community corrections;
- federated knowledge repositories;
- support for additional AI clients;
- automated knowledge consolidation.

These features are explicitly outside the MVP.

---

# 22. The Core Idea

The project is based on a simple observation:

> **AI makes it increasingly easy to solve individual problems.**

But every solved problem represents potentially reusable knowledge.

Today, that knowledge often disappears inside a private conversation.

Shared Knowledge MCP provides a mechanism to turn it into something that can benefit someone else.

```text
One person asks.
One person learns.
One person shares.
Someone else benefits.
```

Or, more simply:

> **Don't just get the answer. Give the answer back.**