---
title: Shared Knowledge
description: A community knowledge base built around AI-assisted problem solving - solved problems, shared on purpose.
template: splash
hero:
  tagline: Solved problems, shared on purpose.
  actions:
    - text: Browse by category
      link: /devops/
      icon: book
    - text: All articles
      link: /articles/
      icon: list
---

:::note[The idea]
AI makes it increasingly easy to solve individual problems — and every solved problem is potentially reusable knowledge. Shared Knowledge turns that knowledge into a public, versioned, human-reviewed documentation site.
:::

The pipeline is deliberately simple:

```text
Private conversation → AI-assisted solution → user chooses to share
→ MCP structures the knowledge → GitHub Pull Request → human review
→ merge → published here (with an optional audio version)
```

**The conversation remains private. The knowledge extracted from it can be shared.** Sharing is always explicit and voluntary; nothing is published without human review.

> **Don't just get the answer. Give the answer back.**

## Browse the knowledge base

- **By category** — use the sidebar (AI, Backend, Databases, DevOps, …) to browse the controlled category vocabulary. Every article belongs to exactly one category.
- **By tag** — the [tags index](/tags/) lists every generated tag.
- **By search** — use the search field in the header for full-text search across all articles.
- **By ear** — articles with a recorded version show a *Listen to this article* player.

## For contributors

The primary way to contribute is through your AI assistant: solve a problem, then say *"Share this solution with the community."* Your assistant submits a Pull Request; a human maintainer reviews it before publication. You can also add an article manually under `knowledge/<category>/` in the [repository](https://github.com/pcescato/shared-knowledge).
