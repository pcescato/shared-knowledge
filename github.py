"""GitHub publication provider for publish_knowledge.

server.py never talks to the GitHub REST API directly: it calls
create_pull_request() below. Swapping the transport or the forge later
means changing this module only - no MCP tool changes required.

Repository of record: pcescato/shared-knowledge (the GitHub repository is
the source of truth for community knowledge).

Workflow implemented here (spec section 14, steps 6-8):
  1. resolve the repository's default branch (never hard-coded);
  2. create a unique contribution branch from that default branch;
  3. build the Markdown file with valid YAML frontmatter
     (title, description, category, tags, source: "community", created_at);
  4. commit it to the contribution branch at knowledge/<category>/<slug>.md;
  5. open a Pull Request targeting the default branch and return its URL.

Critical publication rule: this module NEVER pushes to the default branch.
The Pull Request is the publication request; only a human maintainer
merging it makes the contribution eligible for publication (spec section 11).

Authentication: a GitHub token is read from the GITHUB_TOKEN environment
variable (never hard-coded, never included in commits). Minimum token
permissions:
  - fine-grained PAT: "Contents: read and write" + "Pull requests: write"
    on pcescato/shared-knowledge only;
  - classic PAT: "repo" scope.
Anything more privileged is unnecessary and should not be granted.

Errors: every failure (missing token, unexpected API status, duplicate
article path) raises PublisherError so publish_knowledge() can return a
clean MCP-level error.
"""

import base64
import json
import os
import re
import unicodedata
from datetime import date
from typing import Any, Optional

import frontmatter
import httpx

DEFAULT_REPO = "pcescato/shared-knowledge"
GITHUB_API = "https://api.github.com"

# The source field of every community contribution (spec section 10).
SOURCE = "community"


class PublisherError(RuntimeError):
    """Raised for any GitHub configuration, API, or duplicate-path failure."""


# ---------------------------------------------------------------------------
# Slug / path / frontmatter helpers
# ---------------------------------------------------------------------------


def slugify(text: str, max_length: int = 80) -> str:
    """Deterministic, filesystem-safe slug from a title or category.

    ASCII-folded, lowercased, non-alphanumerics collapsed to single
    hyphens, trimmed; falls back to "article" if nothing survives.
    """
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (text[:max_length].rstrip("-")) or "article"


def article_path(category: str, title: str) -> str:
    """Repository-relative path for an article: knowledge/<category>/<slug>.md."""
    return f"knowledge/{slugify(category)}/{slugify(title)}.md"


def build_frontmatter(article: dict, created_at: Optional[date] = None) -> str:
    """Serialize the full article file with valid YAML frontmatter.

    Fields: title, description, category, tags, source ("community"),
    created_at (ISO date). Uses python-frontmatter's YAML serializer so
    strings are always correctly quoted/escaped.
    """
    post = frontmatter.Post(
        content=article["content"],
        handler=frontmatter.YAMLHandler(),
        **{
            "title": article["title"],
            "description": article["description"],
            "category": article["category"],
            "tags": list(article["tags"]),
            "source": SOURCE,
            "created_at": (created_at or date.today()).isoformat(),
        },
    )
    return frontmatter.dumps(post)


# ---------------------------------------------------------------------------
# GitHub REST transport
# ---------------------------------------------------------------------------


class GitHubClient:
    """Minimal GitHub REST client for the contribution workflow.

    Only the endpoints needed here are wrapped. All requests carry the
    token from the environment; the token is never logged, returned, or
    written into any commit.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        repo: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.repo = repo or os.environ.get("GITHUB_REPO", DEFAULT_REPO)
        self.base_url = base_url or GITHUB_API

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _request(
        self, method: str, url: str, *, json_body: Optional[dict] = None,
        params: Optional[dict] = None, allow_404: bool = False,
    ) -> httpx.Response:
        """Send the request and translate error statuses into PublisherError.

        Transport and status policy are deliberately separated: tests stub
        _send (the HTTP boundary) while this status handling always runs.
        """
        response = self._send(
            method, url, json_body=json_body, params=params
        )
        if response.status_code == 404 and allow_404:
            return response
        if response.status_code >= 400:
            # Include the API's message for debuggability - it never contains
            # our credentials.
            try:
                detail = response.json().get("message", response.text)
            except (json.JSONDecodeError, ValueError):
                detail = response.text
            raise PublisherError(
                f"GitHub API error {response.status_code} on {method} {url}: {detail}"
            )
        return response

    def _send(
        self, method: str, url: str, *, json_body: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> httpx.Response:
        """Single HTTP boundary: perform the request, wrap network errors."""
        try:
            return httpx.request(
                method,
                f"{self.base_url}{url}",
                headers=self._headers(),
                json=json_body,
                params=params,
                timeout=30.0,
            )
        except httpx.HTTPError as exc:
            raise PublisherError(f"GitHub API request failed: {exc}") from exc

    # -- endpoints ---------------------------------------------------------

    def get_default_branch(self) -> str:
        response = self._request("GET", f"/repos/{self.repo}")
        return response.json()["default_branch"]

    def get_ref(self, branch: str) -> Optional[str]:
        """Head commit SHA of `branch`, or None if the branch doesn't exist."""
        response = self._request(
            "GET", f"/repos/{self.repo}/git/ref/heads/{branch}", allow_404=True
        )
        if response.status_code == 404:
            return None
        return response.json()["object"]["sha"]

    def create_branch(self, branch: str, from_sha: str) -> None:
        self._request(
            "POST",
            f"/repos/{self.repo}/git/refs",
            json_body={"ref": f"refs/heads/{branch}", "sha": from_sha},
        )

    def get_file_sha(self, path: str, ref: str) -> Optional[str]:
        """Blob SHA of `path` on `ref`, or None if the file doesn't exist."""
        response = self._request(
            "GET",
            f"/repos/{self.repo}/contents/{path}",
            params={"ref": ref},
            allow_404=True,
        )
        if response.status_code == 404:
            return None
        return response.json().get("sha")

    def create_or_update_file(
        self, path: str, branch: str, content_markdown: str, message: str, sha: Optional[str]
    ) -> None:
        body: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content_markdown.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        self._request("PUT", f"/repos/{self.repo}/contents/{path}", json_body=body)

    def delete_branch(self, branch: str) -> None:
        """Best-effort branch deletion (used to roll back failed runs)."""
        try:
            self._request(
                "DELETE", f"/repos/{self.repo}/git/refs/heads/{branch}", allow_404=True
            )
        except PublisherError:
            pass  # rollback is best-effort; the original error is what matters

    def create_pull_request(self, branch: str, base: str, title: str, body: str) -> str:
        response = self._request(
            "POST",
            f"/repos/{self.repo}/pulls",
            json_body={"title": title, "head": branch, "base": base, "body": body},
        )
        html_url = response.json().get("html_url")
        if not html_url:
            raise PublisherError("GitHub API returned a Pull Request without a URL")
        return html_url


# ---------------------------------------------------------------------------
# Publication workflow
# ---------------------------------------------------------------------------


def create_pull_request(article: dict) -> str:
    """Publish `article` as a Pull Request and return the PR URL.

    Raises PublisherError on missing token, API failure, or if the article
    already exists on the default branch (duplicate handling: fail cleanly,
    never silently overwrite). Never commits to the default branch.
    """
    if not os.environ.get("GITHUB_TOKEN"):
        raise PublisherError("GITHUB_TOKEN is not set; cannot open the Pull Request")
    if not article.get("content", "").strip():
        raise PublisherError("refusing to publish an empty article")

    client = GitHubClient()

    base_branch = client.get_default_branch()
    base_sha = client.get_ref(base_branch)
    if not base_sha:
        raise PublisherError(f"default branch {base_branch!r} has no head commit")

    path = article_path(article["category"], article["title"])
    branch = f"knowledge/contribution-{date.today().isoformat()}-{slugify(article['title'], 40)}"

    # Duplicate handling: the source of truth for existing articles is the
    # default branch. Fail cleanly instead of overwriting.
    if client.get_file_sha(path, base_branch) is not None:
        raise PublisherError(f"article already exists at {path!r}; refusing to overwrite")

    # From here on a contribution branch is created - roll it back on failure
    # so a crashed run never leaves an orphan branch behind.
    try:
        client.create_branch(branch, base_sha)
        client.create_or_update_file(
            path,
            branch,
            build_frontmatter(article),
            message=f"Add knowledge article: {article['title']}",
            sha=None,
        )
        pr_url = client.create_pull_request(
            branch,
            base_branch,
            title=article["title"],
            body=(
                "Community contribution generated by the Shared Knowledge MCP.\n\n"
                f"- **Path:** `{path}`\n"
                f"- **Category:** {article['category']}\n"
                f"- **Tags:** {', '.join(article['tags'])}\n\n"
                "This Pull Request is the publication request: merging it makes "
                "the article eligible for publication on the documentation site."
            ),
        )
    except PublisherError:
        client.delete_branch(branch)
        raise

    return pr_url
