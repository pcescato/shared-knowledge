"""End-to-end integration tests for the complete MVP loop.

Covers the two loops from the spec with the external boundary stubbed
(GitHub HTTP boundary; the server performs no LLM call at all):

  publish loop:
    publish_knowledge (caller-provided structured article) -> validation +
    secret scan -> _create_pull_request (GitHub stub) -> "submitted"

  retrieval loop:
    knowledge/ on disk -> search_knowledge -> get_knowledge (reused in a
    new conversation)

These tests deliberately exercise the real server module (only the
network boundary is stubbed) so wiring mistakes - not unit-level
regressions - are what they catch.
"""

from unittest.mock import patch

import server
from github import GitHubClient
from tests.test_github import ARTICLE, FakeResponse


def _publish_responses(pr_number: int):
    return [
        FakeResponse(200, {"default_branch": "main"}),        # get_default_branch
        FakeResponse(200, {"object": {"sha": "abc123"}}),     # get_ref
        FakeResponse(404, {}),                                # duplicate check
        FakeResponse(201, {"ref": "refs/heads/branch"}),      # create branch
        FakeResponse(201, {"commit": {"sha": "def456"}}),     # commit file
        FakeResponse(
            201,
            {"html_url": f"https://github.com/pcescato/shared-knowledge/pull/{pr_number}"},
        ),
    ]


def _structured_article(**overrides) -> dict:
    """A structured article matching the PublishInput contract, for mutation."""
    article = {
        "title": ARTICLE["title"],
        "description": ARTICLE["description"],
        "category": ARTICLE["category"],
        "tags": ARTICLE["tags"],
        "content": ARTICLE["content"],
    }
    article.update(overrides)
    return article


def _publish(article: dict) -> server.PublishOutput:
    return server.publish_knowledge(
        server.PublishInput(
            title=article["title"],
            description=article["description"],
            category=article["category"],
            tags=article["tags"],
            content=article["content"],
        )
    )


class TestPublishLoop:
    def test_full_publish_pipeline_submitted(self, monkeypatch):
        """Validation passes, PR opens -> status 'submitted'."""
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")

        responses = _publish_responses(1)
        with patch.object(
            GitHubClient, "_send", side_effect=lambda m, u, **k: responses.pop(0)
        ):
            output = _publish(_structured_article())

        assert output.status == "submitted"
        assert output.pull_request == "https://github.com/pcescato/shared-knowledge/pull/1"
        assert output.title == "Protecting Streamlit with Caddy and Authentik"

    def test_publication_is_never_direct(self, monkeypatch):
        """The only GitHub write calls are branch/commit/PR on a contribution
        branch - the default branch is only ever read."""
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")

        writes = []
        responses = _publish_responses(2)

        def spy(method, url, **kwargs):
            if method in ("POST", "PUT", "DELETE"):
                writes.append((method, url, kwargs.get("json_body", {})))
            return responses.pop(0)

        with patch.object(GitHubClient, "_send", side_effect=spy):
            output = _publish(_structured_article())
        assert output.status == "submitted"
        # No write may target the default branch: the PUT carries the branch,
        # the POSTs create the branch and the PR.
        commit = next(body for m, _, body in writes if m == "PUT")
        assert commit["branch"].startswith("knowledge/contribution-")
        assert commit["branch"] != "main"
        pr = next(body for m, u, body in writes if m == "POST" and u.endswith("/pulls"))
        assert pr["base"] == "main" and pr["head"].startswith("knowledge/contribution-")

    def test_secret_in_structured_content_is_rejected_before_pr(self, monkeypatch):
        """The secret scan runs before submission: no branch, no PR, status 'rejected'."""
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")

        secret_article = _structured_article(
            content=ARTICLE["content"]
            + "\nUse sk-abcdefghijklmnopqrstuvwx as the API key.\n"
        )
        with patch.object(
            GitHubClient, "_send",
            side_effect=AssertionError("GitHub must not be called for rejected content"),
        ):
            output = _publish(secret_article)
        assert output.status == "rejected"
        assert "secret" in output.error


class TestPromptContract:
    def test_guidelines_prompt_is_registered_with_required_rules(self):
        """knowledge_article_guidelines must be exposed as an MCP prompt and
        carry the key structuring rules (categories, mandatory sections,
        no conversation references, publication path)."""
        import asyncio

        async def _read():
            prompts = await server.mcp.list_prompts()
            return [p.name for p in prompts]

        names = asyncio.run(_read())
        assert "knowledge_article_guidelines" in names

        text = server._article_guidelines()
        assert "English" in text
        assert "## Problem" in text and "## Solution" in text
        for category in ("DevOps", "Databases", "Other"):
            assert category in text
        assert "publish_knowledge" in text
        assert "conversation" in text  # the rule forbids conversation references


class TestRetrievalLoop:
    def test_search_then_get_reuses_existing_knowledge(self, knowledge_dir):
        """AI client loop: search finds the article, get_knowledge returns it."""
        found = server.search_knowledge("authentik forward authentication")
        assert found.results, "search must find the seeded article"
        best = found.results[0]

        article = server.get_knowledge(best.url if best.url.endswith(".md") else best.title)
        assert "## Solution" in article.content
        assert article.metadata["category"] == "DevOps"
        assert "caddy" in article.metadata["tags"]

    def test_search_and_get_agree_on_identity(self, knowledge_dir):
        """get_knowledge accepts the id shape implied by search results."""
        result = server.search_knowledge("postgres isolation")
        assert result.results
        url = result.results[0].url  # knowledge/<category>/<slug>.md (or absolute)
        assert url.endswith(".md") and "/" in url
        fetched = server.get_knowledge(url)
        assert fetched.metadata["title"]
