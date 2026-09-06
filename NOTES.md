# Notes — project status (2026-09-05, day before submission)

This file replaces the 2026-09-04 version, which is entirely outdated: it
described a state where `publish_knowledge` was not implemented. That is no
longer the case.

## ✅ Verified tonight (real execution, not just code review)

- **91 tests run with `pytest -v`: all passing** (`pytest.ini_options` in
  `pyproject.toml`, venv environment with the project's dependencies).
- **Astro/Starlight build successful** (`npm run build`, 28 pages generated,
  consistent layout between the home page and article/category pages).
- `publish_knowledge` is fully implemented: the caller (the user's AI
  assistant) structures the article itself — guided by the
  `knowledge_article_guidelines` MCP prompt — and the server only validates
  (structure + secret scan) and submits a GitHub Pull Request (`github.py`),
  never a direct commit to the default branch.
  *(Historical note, 2026-09-06: the internal Gemini generation path — former
  `llm.py`, `GEMINI_API_KEY`, `LLM_PROVIDER` — was removed on purpose. The
  server now performs no LLM call at all; that was a deliberate design
  decision, documented in README.md.)*
- `get_knowledge` guards against path traversal (`Path.resolve()` +
  `is_relative_to()`), tested against 5 cases.
- Frontmatter parsing delegates to the real `python-frontmatter` library
  (tag lists handled correctly) — no longer a hand-rolled parser.

## 🔧 Fixed tonight

- `pyproject.toml`: `httpx` was declared as an optional dependency
  (`[project.optional-dependencies]`) while `github.py` imports it
  unconditionally — a plain `pip install` without the extra crashed the
  server on startup. Moved to the main dependencies.
- Astro layout: article/category pages were using a minimal "standalone"
  layout instead of `StarlightPage` — fixed to align sidebar, search, and
  syntax highlighting with the home page.

## ⚠️ Not verified — worth knowing before demoing publicly

- **The GitHub Actions audio-generation workflow (`generate_audio.py` →
  ElevenLabs) has not been triggered under real conditions** (push to main
  after a merge). The logic is unit-tested (13 tests in
  `test_generate_audio.py`, all passing with the ElevenLabs API mocked), but
  never run against the real API.
- The GitHub Pages deployment itself (the CI workflow, not just the local
  build) has not been observed in action.

## Process note

An automated review (Copilot CLI) flagged a GitHub authentication bug that
did not correspond to any actual line of code — checked and dismissed on
2026-09-04. That review's findings were treated as unreliable by default from
that point on; only the items above were confirmed through manual code
reading and/or real execution.