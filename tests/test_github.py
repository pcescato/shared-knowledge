"""Tests for the GitHub publication workflow (github.py + wiring).

No real GitHub API calls: httpx transport is stubbed per test with
scripted responses, so the full sequence (default branch -> ref ->
duplicate check -> branch creation -> file commit -> PR) is exercised
without network access.
"""

from unittest.mock import patch

import pytest

import server
from github import (
    GitHubClient,
    PublisherError,
    article_path,
    build_frontmatter,
    create_pull_request,
    slugify,
)

ARTICLE = {
    "title": "Protecting Streamlit with Caddy and Authentik",
    "description": "How to protect a Streamlit application using Caddy and Authentik forward authentication.",
    "category": "DevOps",
    "tags": ["caddy", "authentik", "reverse-proxy", "sso"],
    "content": (
        "# Protecting Streamlit with Caddy and Authentik\n\n"
        "## Problem\n\nStreamlit has no built-in authentication.\n\n"
        "## Solution\n\nUse Caddy forward_auth with Authentik.\n"
    ),
}


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = "" if json_data is not None else ""

    def json(self):
        return self._json


def _patch_request(responses):
    """Stub the HTTP boundary (GitHubClient._send) with scripted responses."""
    if isinstance(responses, list):
        iterator = iter(responses)

        def side_effect(method, url, **kwargs):
            return next(iterator)
    else:
        def side_effect(method, url, **kwargs):
            return responses
    return patch.object(GitHubClient, "_send", side_effect=side_effect), responses


def _happy_path_responses(pr_url="https://github.com/pcescato/shared-knowledge/pull/42"):
    return [
        FakeResponse(200, {"default_branch": "main"}),          # get_default_branch
        FakeResponse(200, {"object": {"sha": "abc123"}}),       # get_ref(main)
        FakeResponse(404, {"message": "Not Found"}),            # get_file_sha -> absent
        FakeResponse(201, {"ref": "refs/heads/contribution"}),  # create_branch
        FakeResponse(201, {"commit": {"sha": "def456"}}),       # create_or_update_file
        FakeResponse(201, {"html_url": pr_url}),                # create_pull_request
    ]


# ---------------------------------------------------------------------------
# Slug / path
# ---------------------------------------------------------------------------


class TestSlugAndPath:
    def test_slug_is_deterministic_and_safe(self):
        assert slugify("Protecting Streamlit with Caddy & Authentik!") == \
            "protecting-streamlit-with-caddy-authentik"
        assert slugify("  Héllo   Wörld  ") == "hello-world"
        assert slugify("!!!") == "article"
        assert slugify("x" * 200, max_length=40) == "x" * 40
        assert slugify("Protecting Streamlit with Caddy and Authentik", max_length=40) == \
            "protecting-streamlit-with-caddy-and-auth"

    def test_article_path_uses_category_subfolder(self):
        assert article_path("DevOps", "My Title!") == "knowledge/devops/my-title.md"

    def test_target_path_required_by_task(self):
        path = article_path(ARTICLE["category"], ARTICLE["title"])
        assert path == "knowledge/devops/protecting-streamlit-with-caddy-and-authentik.md"


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------


class TestFrontmatter:
    def test_contains_all_required_fields(self):
        from datetime import date

        file_body = build_frontmatter(ARTICLE, created_at=date(2026, 9, 4))
        assert file_body.startswith("---\n")
        for expected in (
            'title: Protecting Streamlit with Caddy and Authentik',
            "description: How to protect a Streamlit",
            "category: DevOps",
            "source: community",
            "created_at: '2026-09-04'",
        ):
            assert expected in file_body
        assert "- caddy" in file_body and "- sso" in file_body
        assert file_body.rstrip().endswith("Use Caddy forward_auth with Authentik.")
        assert "## Problem" in file_body and "## Solution" in file_body

    def test_round_trips_through_python_frontmatter(self):
        import frontmatter as fm

        post = fm.loads(build_frontmatter(ARTICLE))
        assert post.metadata["category"] == "DevOps"
        assert post.metadata["tags"] == ["caddy", "authentik", "reverse-proxy", "sso"]
        assert post.metadata["source"] == "community"
        assert "## Solution" in post.content


# ---------------------------------------------------------------------------
# Full workflow
# ---------------------------------------------------------------------------


class TestPublishWorkflow:
    def test_returns_pr_url(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        patcher, _ = _patch_request(_happy_path_responses())
        with patcher:
            url = create_pull_request(ARTICLE)
        assert url == "https://github.com/pcescato/shared-knowledge/pull/42"

    def test_branch_created_from_default_branch(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        calls = []
        responses = _happy_path_responses()

        def spy(method, url, **kwargs):
            calls.append((method, url))
            return responses[len(calls) - 1]

        with patch.object(GitHubClient, "_send", side_effect=spy):
            create_pull_request(ARTICLE)
        assert ("GET", "/repos/pcescato/shared-knowledge") in calls
        assert ("POST", "/repos/pcescato/shared-knowledge/git/refs") in calls
        assert ("POST", "/repos/pcescato/shared-knowledge/pulls") in calls

    def test_article_committed_not_default_branch(self, monkeypatch):
        """The commit must target the contribution branch, never the default one."""
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        calls = []
        responses = _happy_path_responses()

        def spy(method, url, **kwargs):
            calls.append(kwargs)
            return responses[len(calls) - 1]

        with patch.object(GitHubClient, "_send", side_effect=spy):
            create_pull_request(ARTICLE)
        commit_call = calls[4]
        assert commit_call["json_body"]["branch"].startswith("knowledge/contribution-")
        assert commit_call["json_body"]["branch"] != "main"

    def test_pr_targets_default_branch(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        calls = []
        responses = _happy_path_responses()

        def spy(method, url, **kwargs):
            calls.append(kwargs)
            return responses[len(calls) - 1]

        with patch.object(GitHubClient, "_send", side_effect=spy):
            create_pull_request(ARTICLE)
        pr_body = calls[5]["json_body"]
        assert pr_body["base"] == "main"
        assert pr_body["head"].startswith("knowledge/contribution-")

    def test_commit_payload_contains_full_article_file(self, monkeypatch):
        """The committed content must be the frontmatter + Markdown body."""
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        import base64

        calls = []
        responses = _happy_path_responses()

        def spy(method, url, **kwargs):
            calls.append(kwargs)
            return responses[len(calls) - 1]

        with patch.object(GitHubClient, "_send", side_effect=spy):
            create_pull_request(ARTICLE)
        commit_call = calls[4]
        assert commit_call["json_body"]["message"].startswith("Add knowledge article:")
        decoded = base64.b64decode(commit_call["json_body"]["content"]).decode()
        assert "source: community" in decoded
        assert "created_at:" in decoded
        assert "## Solution" in decoded


# ---------------------------------------------------------------------------
# Duplicate handling & failures
# ---------------------------------------------------------------------------


class TestFailures:
    def test_existing_article_fails_cleanly(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        responses = [
            FakeResponse(200, {"default_branch": "main"}),
            FakeResponse(200, {"object": {"sha": "abc123"}}),
            FakeResponse(200, {"sha": "existing-blob"}),  # file already exists
        ]
        patcher, _ = _patch_request(responses)
        with patcher, pytest.raises(PublisherError, match="already exists"):
            create_pull_request(ARTICLE)

    def test_missing_token_fails_cleanly(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with pytest.raises(PublisherError, match="GITHUB_TOKEN is not set"):
            create_pull_request(ARTICLE)

    def test_empty_article_refused(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        with pytest.raises(PublisherError, match="empty article"):
            create_pull_request({**ARTICLE, "content": "   "})

    def test_api_failure_is_wrapped(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        responses = [
            FakeResponse(200, {"default_branch": "main"}),
            FakeResponse(500, {"message": "boom"}),
        ]
        patcher, _ = _patch_request(responses)
        with patcher, pytest.raises(PublisherError, match="GitHub API error 500"):
            create_pull_request(ARTICLE)

    def test_failed_pr_creation_rolls_back_branch(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        deleted = []
        monkeypatch.setattr(
            GitHubClient, "delete_branch", lambda self, b: deleted.append(b)
        )
        responses = [
            FakeResponse(200, {"default_branch": "main"}),
            FakeResponse(200, {"object": {"sha": "abc123"}}),
            FakeResponse(404),
            FakeResponse(201),
            FakeResponse(201),
            FakeResponse(422, {"message": "Validation Failed"}),  # PR creation fails
        ]
        patcher, _ = _patch_request(responses)
        with patcher, pytest.raises(PublisherError, match="422"):
            create_pull_request(ARTICLE)
        assert deleted and deleted[0].startswith("knowledge/contribution-")

    def test_publish_knowledge_maps_publisher_error(self, monkeypatch):
        """End-to-end wiring: PublisherError becomes a clean MCP-level error."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        from unittest.mock import patch as _patch

        with _patch("server.create_pull_request", side_effect=PublisherError("GITHUB_TOKEN is not set")):
            output = server.publish_knowledge(
                server.PublishInput(
                    title=ARTICLE["title"],
                    description=ARTICLE["description"],
                    category=ARTICLE["category"],
                    tags=ARTICLE["tags"],
                    content=ARTICLE["content"],
                )
            )
        assert output.status == "error"
        assert "GITHUB_TOKEN" in output.error

    def test_publish_knowledge_full_success(self, monkeypatch):
        """Validation + publication succeed end to end."""
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        from unittest.mock import patch as _patch

        with _patch("server.create_pull_request", return_value="https://github.com/pcescato/shared-knowledge/pull/7"):
            output = server.publish_knowledge(
                server.PublishInput(
                    title=ARTICLE["title"],
                    description=ARTICLE["description"],
                    category=ARTICLE["category"],
                    tags=ARTICLE["tags"],
                    content=ARTICLE["content"],
                )
            )
        assert output.status == "submitted"
        assert output.pull_request.endswith("/pull/7")
        assert output.title == ARTICLE["title"]
