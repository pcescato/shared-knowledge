"""Tests for the Shared Knowledge MCP server (MVP scope).

Covers: frontmatter parsing (including tags), search_knowledge,
get_knowledge (success / traversal / missing article), article
validation, the knowledge_article_guidelines MCP prompt, and the
publish_knowledge input contract (server-side validation only - the
server never generates articles, and GitHub submission is tested in
test_github.py / test_integration.py).
"""

import pytest
from pydantic import ValidationError

import server


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------


class TestFrontmatterParsing:
    def test_parses_scalars_and_quoted_strings(self):
        meta = server._parse_frontmatter(
            '---\ntitle: "Quoted Title"\ncategory: DevOps\nsource: "community"\n---\n\nbody'
        )
        assert meta["title"] == "Quoted Title"
        assert meta["category"] == "DevOps"
        assert meta["source"] == "community"

    def test_parses_tag_lists(self):
        meta = server._parse_frontmatter(
            "---\ntags:\n  - caddy\n  - authentik\n  - reverse-proxy\n---\n\nbody"
        )
        assert meta["tags"] == ["caddy", "authentik", "reverse-proxy"]

    def test_parses_existing_article_format(self):
        meta = server._parse_frontmatter(
            '---\ntitle: "T"\ndescription: "D"\ncategory: "DevOps"\n'
            "tags:\n  - a\n  - b\n"
            'source: "community"\ncreated_at: "2026-09-04"\n---\n\nbody'
        )
        assert meta["title"] == "T"
        assert meta["description"] == "D"
        assert meta["category"] == "DevOps"
        assert meta["tags"] == ["a", "b"]
        assert meta["source"] == "community"
        assert meta["created_at"] == "2026-09-04"

    def test_body_without_frontmatter_yields_empty_metadata(self):
        assert server._parse_frontmatter("no frontmatter here") == {}

    def test_real_seed_article_tags_are_a_list(self, knowledge_dir):
        post_id = "devops/caddy-authentik-streamlit"
        result = server.get_knowledge(post_id)
        assert result.metadata["tags"] == [
            "caddy",
            "authentik",
            "streamlit",
            "reverse-proxy",
            "sso",
        ]
        assert result.metadata["category"] == "DevOps"


# ---------------------------------------------------------------------------
# search_knowledge
# ---------------------------------------------------------------------------


class TestSearchKnowledge:
    def test_finds_article_by_body_keyword(self, knowledge_dir):
        output = server.search_knowledge("streamlit authentication")
        titles = [r.title for r in output.results]
        assert "Protecting Streamlit with Caddy and Authentik" in titles

    def test_finds_article_by_tag_keyword(self, knowledge_dir):
        output = server.search_knowledge("postgres")
        assert [r.category for r in output.results] == ["Databases"]

    def test_summary_and_url_are_populated(self, knowledge_dir):
        output = server.search_knowledge("caddy")
        result = output.results[0]
        assert result.summary.startswith("How to protect")
        assert result.url.endswith("caddy-authentik-streamlit.md")


# ---------------------------------------------------------------------------
# search_knowledge relevance ranking
# ---------------------------------------------------------------------------


class TestSearchRanking:
    def test_title_match_outranks_repeated_body_match(self, ranking_dir):
        """One term in a title beats an article mentioning it many times in its body."""
        output = server.search_knowledge("zookeeper")
        assert output.results[0].title == "Zookeeper operations"
        assert output.results[1].title == "Kafka basics"

    def test_tag_match_finds_article(self, knowledge_dir):
        """`sso` appears only in the tags of the Caddy/Authentik article."""
        output = server.search_knowledge("sso")
        assert [r.title for r in output.results] == [
            "Protecting Streamlit with Caddy and Authentik"
        ]

    def test_tag_match_outranks_description_match(self, ranking_dir):
        """Tag weight (6.0) > description weight (4.0) for the same term."""
        output = server.search_knowledge("streamlit")
        assert output.results[0].title == "Protecting Streamlit with Caddy and Authentik"

    def test_multiple_matching_terms_outrank_single_term(self, ranking_dir):
        """An article matching both query terms beats one matching only the first."""
        output = server.search_knowledge("caddy authentik")
        titles = [r.title for r in output.results]
        assert titles.index("Caddy and Authentik") < titles.index("Caddy setup")

    def test_no_results_for_unknown_term(self, knowledge_dir):
        assert server.search_knowledge("quantumphotonic").results == []

    def test_no_results_for_blank_or_stopword_query(self, knowledge_dir):
        assert server.search_knowledge("").results == []
        assert server.search_knowledge("the with for").results == []

    def test_results_capped_at_maximum_after_ranking(self, ranking_dir):
        """12 articles match; only MAX_SEARCH_RESULTS are returned, best first."""
        output = server.search_knowledge("quixotic unicorns")
        assert len(output.results) == server.MAX_SEARCH_RESULTS
        titles = [r.title for r in output.results]
        assert titles == sorted(titles)  # equal scores -> deterministic title order


# ---------------------------------------------------------------------------
# get_knowledge
# ---------------------------------------------------------------------------


class TestGetKnowledge:
    def test_returns_content_and_metadata(self, knowledge_dir):
        result = server.get_knowledge("devops/caddy-authentik-streamlit")
        assert result.id == "devops/caddy-authentik-streamlit"
        assert "## Solution" in result.content
        assert result.metadata["title"] == "Protecting Streamlit with Caddy and Authentik"
        assert result.metadata["tags"] == ["caddy", "authentik", "streamlit", "reverse-proxy", "sso"]

    def test_appends_md_extension_for_bare_slug(self, knowledge_dir):
        result = server.get_knowledge("databases/postgres-isolation-levels")
        assert "READ COMMITTED" in result.content

    def test_accepts_absolute_path_inside_knowledge_dir(self, knowledge_dir):
        result = server.get_knowledge(str(knowledge_dir / "devops" / "caddy-authentik-streamlit.md"))
        assert result.metadata["category"] == "DevOps"

    @pytest.mark.parametrize(
        "bad_id",
        [
            "../outside.md",
            "../../etc/passwd",
            "devops/../../../etc/passwd",
            "/etc/passwd",
            str(__file__),  # absolute path inside the project but outside KNOWLEDGE_DIR
        ],
    )
    def test_rejects_path_traversal(self, knowledge_dir, bad_id):
        with pytest.raises(ValueError, match="escapes the knowledge base"):
            server.get_knowledge(bad_id)

    def test_missing_article_raises_clean_error(self, knowledge_dir):
        with pytest.raises(ValueError, match="article not found"):
            server.get_knowledge("devops/does-not-exist")


# ---------------------------------------------------------------------------
# Article validation (publish pipeline pre-moderation)
# ---------------------------------------------------------------------------


class TestValidateArticle:
    def test_valid_article_passes(self, valid_article):
        assert server._validate_article(valid_article) == []

    def test_unknown_category_is_rejected(self, valid_article):
        valid_article["category"] = "NotACategory"
        problems = server._validate_article(valid_article)
        assert any("unknown category" in p for p in problems)

    def test_missing_title_is_rejected(self, valid_article):
        valid_article["title"] = ""
        assert any("missing title" in p for p in server._validate_article(valid_article))

    def test_missing_description_is_rejected(self, valid_article):
        valid_article["description"] = ""
        assert any("missing description" in p for p in server._validate_article(valid_article))

    def test_missing_tags_are_rejected(self, valid_article):
        valid_article["tags"] = []
        assert any("missing tags" in p for p in server._validate_article(valid_article))

    def test_missing_required_sections_are_rejected(self, valid_article):
        valid_article["content"] = "# Title\n\nSome text without sections."
        problems = server._validate_article(valid_article)
        assert any("## Problem" in p and "## Solution" in p for p in problems)

    def test_empty_content_is_rejected(self, valid_article):
        valid_article["content"] = "   "
        assert any("empty content" in p for p in server._validate_article(valid_article))

    def test_oversized_content_is_rejected(self, valid_article):
        valid_article["content"] = "x" * (server.MAX_CONTENT_LENGTH + 1)
        assert any("exceeds" in p for p in server._validate_article(valid_article))

    def test_api_key_like_content_is_flagged(self, valid_article):
        valid_article["content"] = "## Problem\n\n## Solution\n\nUse sk-abcdefghijklmnopqrstuvwx as key."
        assert any("secret" in p for p in server._validate_article(valid_article))

    def test_pem_private_key_is_flagged(self, valid_article):
        valid_article["content"] = "## Problem\n\n## Solution\n\n-----BEGIN RSA PRIVATE KEY-----"
        assert any("secret" in p for p in server._validate_article(valid_article))


# ---------------------------------------------------------------------------
# knowledge_article_guidelines (MCP prompt)
# ---------------------------------------------------------------------------


class TestKnowledgeArticleGuidelines:
    def test_prompt_is_registered_as_mcp_prompt(self):
        """The prompt is exposed through the MCP server's prompt registry."""
        import asyncio

        async def _list():
            return [p.name for p in await server.mcp.list_prompts()]

        assert "knowledge_article_guidelines" in asyncio.run(_list())

    def test_prompt_text_contains_the_key_rules(self):
        text = server._article_guidelines()
        # English-only requirement
        assert "English" in text
        # Mandatory sections + optional-when-not-applicable rule
        assert "## Problem" in text and "## Solution" in text
        assert "## Context" in text and "## Why it works" in text and "## Caveats" in text
        assert "MANDATORY" in text
        # Every exact category from the controlled vocabulary is listed
        for category in server.CATEGORIES:
            assert category in text
        # Tags rules
        assert "3 to 8 tags" in text
        # No conversation references rule (phrased as an interdiction)
        assert "no references to the user" in text
        assert "as I said above" in text
        # Ends with the explicit call-to-action: publish, nothing else
        assert text.rstrip().endswith("publish_knowledge is the only publication path.")
        assert "publish_knowledge" in text
        # No h1 in the content: the page title comes from frontmatter, a
        # leading "#" in the body would duplicate it on the rendered page.
        assert "NEVER start with a top-level h1" in text
        assert "# Title" not in text
        assert not any(
            line.strip() == "# Title" for line in text.splitlines()
        )
        # The structure example starts directly at the h2 sections.
        structure = text.split("Structure the Markdown content as:")[1]
        assert structure.lstrip().startswith("## Problem")

    def test_prompt_does_not_mention_the_server_generating_articles(self):
        """The guidelines describe caller-side structuring, not server-side generation."""
        text = server._article_guidelines().lower()
        assert "gemini" not in text
        assert "llm" not in text


# ---------------------------------------------------------------------------
# PublishInput contract (structured fields, all required)
# ---------------------------------------------------------------------------


class TestPublishInputContract:
    def _valid_kwargs(self):
        return {
            "title": "A valid article",
            "description": "A short description.",
            "category": "DevOps",
            "tags": ["caddy"],
            "content": "# A valid article\n\n## Problem\n\nSomething breaks.\n\n## Solution\n\nDo the thing.\n",
        }

    def test_all_five_fields_are_required(self):
        for field in ("title", "description", "category", "tags", "content"):
            kwargs = self._valid_kwargs()
            del kwargs[field]
            with pytest.raises(ValidationError):
                server.PublishInput(**kwargs)

    def test_conversation_excerpt_no_longer_exists(self):
        """conversation_excerpt and language_hint were removed from the contract."""
        assert "conversation_excerpt" not in server.PublishInput.model_fields
        assert "language_hint" not in server.PublishInput.model_fields

    def test_incomplete_input_is_rejected_and_never_reaches_github(self, monkeypatch):
        """A structurally incomplete article (missing category) is rejected
        cleanly by PublishInput/_validate_article - GitHub is never called."""
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")

        def _fail(**kwargs):
            raise AssertionError("GitHub must not be called for an incomplete article")

        monkeypatch.setattr(server, "create_pull_request", _fail)

        # Without the category, the model itself refuses to build.
        kwargs = self._valid_kwargs()
        del kwargs["category"]
        with pytest.raises(ValidationError):
            server.PublishInput(**kwargs)

        # And with an invalid category, validation rejects before submission.
        output = server.publish_knowledge(
            server.PublishInput(**{**self._valid_kwargs(), "category": "NotACategory"})
        )
        assert output.status == "rejected"
        assert "unknown category" in output.error
        assert output.pull_request is None
