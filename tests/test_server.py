"""Tests for the Shared Knowledge MCP server (MVP scope).

Covers: frontmatter parsing (including tags), search_knowledge,
get_knowledge (success / traversal / missing article), and article
validation. publish_knowledge's external calls (Gemini, GitHub API) are
intentionally not implemented and not tested here.
"""

import pytest

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
