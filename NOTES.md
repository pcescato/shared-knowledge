# Notes from the README generation — 2026-09-04

Side notes produced while writing `README.md` from `Shared Knowledge MCP.md` and `server.py`. These are observations, questions and warnings — no code was changed.

---

## ⚠️ Warnings

### 1. `publish_knowledge` is not functional yet

`_generate_article()` (LLM call to Gemini) and `_create_pull_request()` (GitHub API call) both raise `NotImplementedError`. Until they are wired, the publish flow returns `status: "error"` with the TODO message. The README describes the *target* behavior, so it currently documents slightly more than the code delivers — it flags the two TODOs in the Contributing section, but consider adding a "Status / Roadmap" banner at the top of the README once you're closer to a release.

### 2. The spec's required article structure is stricter than the validator

The spec (section 7.3) defines five sections (Problem, Context, Solution, Why it works, Caveats) and says sections may be omitted when genuinely not applicable — but the code's `REQUIRED_SECTIONS = ["## Problem", "## Solution"]` only enforces two. That's a reasonable MVP simplification, but the mismatch should eventually be reconciled (either documented or enforced), otherwise LLM output may silently drop sections the spec considers important.

### 3. `search_knowledge` results have no ranking or snippet

The search is a naive "term appears anywhere in the file" match — every matching file is returned equally (capped at 10), and `summary` is just the frontmatter `description`. That's fine for the demo, but the README's search example implies relevance. Consider sorting by term frequency before the cap, or at least mentioning the limitation in the README (I kept the README neutral on this).

### 4. `get_knowledge` is path-traversal friendly

`id` is used directly to build a file path (`os.path.join(KNOWLEDGE_DIR, f"{id}.md")`) with no normalization/sandboxing. In a local dev tool this is low risk, but before exposing the server to third-party clients, validate that the resolved path stays inside `KNOWLEDGE_DIR`. Nonexistent paths also surface as raw `FileNotFoundError` exceptions to the MCP client.

### 5. The secret scan is intentionally conservative — keep it that way

The regex list covers generic API-key shapes, GitHub PATs, Google keys, PEM keys and emails. Good defaults, but it won't catch passwords in config snippets, AWS keys (`AKIA…`), Slack tokens, JWTs, or `Authorization:` headers in general. Since false positives are cheap in PR review, err on adding more patterns rather than fewer.

### 6. License/copyright note

The LICENSE is MIT © Pascal CESCATO (2026). I attributed it accordingly at the bottom of the README. Check the repo name/owner placeholder (`<owner>/shared-knowledge-mcp.git`) in the README's clone command and the badges before publishing.

---

## ❓ Questions

1. **GitHub repository of record** — the README clone URL and `knowledge/` URLs are placeholders. What is the actual GitHub org/repo where articles will be PR'd?
2. **Site location** — the spec puts the Astro/Starlight site in `site/`, but no `site/` folder or `package.json` exists yet. Should the README link a live URL once GitHub Pages is up?
3. **LLM provider** — `server.py` says "Gemini (Google AI)" in the TODO, while the spec only says "the configured LLM". Is Gemini a hard requirement or just the current choice?
4. **Duplicate detection** — the spec lists "obvious duplicate content" as a rejection condition, but there's no duplicate check in `_validate_article`. Planned, or deferred to maintainer review?
5. **Language of the spec file** — `Shared Knowledge MCP.md` is the authoritative spec; should it stay at the repo root (it's linked from nowhere at the moment), or move to `docs/` with a README link?

---

## 📝 Observations (for information)

- The repo currently contains only `server.py`, the spec, and the LICENSE — there are no tests, no `requirements.txt`/`pyproject.toml`, and no CI workflow yet. Adding a `pyproject.toml` (with `mcp[cli]` and `pydantic` as dependencies) would make installation instructions reproducible.
- `search_knowledge` returns local file paths as `url`. Once the public GitHub repo exists, these should become `github.com/.../blob/main/...` (or the published site) URLs so clients can link to articles.
- `_parse_frontmatter` is a minimal hand-rolled parser (no list support — `tags:` entries are ignored). Fine for MVP; the code comment already suggests `python-frontmatter`.
- The spec's controlled categories include `Databases`, `Hardware`, `Linux`, etc., but the spec's sample repository structure omits some of them (`databases/`, `linux/`, `web-development/` present; mismatch is minor but worth aligning when the `knowledge/` tree is created).
