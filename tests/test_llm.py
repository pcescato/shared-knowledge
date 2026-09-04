"""Tests for the LLM article-generation pipeline (llm.py + wiring).

No real API calls: the Gemini SDK touchpoint (GeminiProvider._call_gemini)
is stubbed, so these tests exercise prompt building, response parsing and
normalization, provider selection, and the error mapping done by
publish_knowledge.
"""

import json
from unittest.mock import patch

import pytest
from pydantic import ValidationError

import server
from llm import (
    ArticleDraft,
    GeminiProvider,
    ProviderError,
    build_article_prompt,
    generate_article,
)

VALID_RESPONSE = {
    "title": "Protecting Streamlit with Caddy and Authentik",
    "description": "How to protect a Streamlit application using Caddy and Authentik forward authentication.",
    "category": "DevOps",
    "tags": ["Caddy", "authentik", "reverse proxy", "sso"],
    "content": (
        "# Protecting Streamlit with Caddy and Authentik\n\n"
        "## Problem\n\nStreamlit has no built-in authentication.\n\n"
        "## Solution\n\nUse Caddy forward_auth with Authentik.\n\n"
        "## Caveats\n\nWebSockets must be allowed.\n"
    ),
}


def _patch_call(return_value=None, side_effect=None):
    """Stub the single SDK touchpoint, leaving everything else real."""
    return patch.object(
        GeminiProvider, "_call_gemini", return_value=return_value, side_effect=side_effect
    )


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


class TestPrompt:
    def test_contains_core_instruction_and_categories(self):
        prompt = build_article_prompt("excerpt", None, ["AI", "DevOps"])
        assert "rather than summarizing the conversation" in prompt
        assert "AI, DevOps" in prompt
        assert "excerpt" in prompt

    def test_no_language_line_without_hint(self):
        assert "source conversation is in" not in build_article_prompt("x", None, ["AI"])

    def test_language_hint_mentions_source_language(self):
        prompt = build_article_prompt("x", "French", ["AI"])
        assert "French" in prompt
        assert "must still be in English" in prompt

    def test_prompt_forbids_conversation_references(self):
        prompt = build_article_prompt("x", None, ["AI"])
        assert "as I said above" in prompt
        assert "no references to the user" in prompt


# ---------------------------------------------------------------------------
# Response parsing / normalization
# ---------------------------------------------------------------------------


class TestParsing:
    def test_valid_json_response_is_normalized(self):
        with _patch_call(json.dumps(VALID_RESPONSE)):
            article = generate_article("excerpt", None, server.CATEGORIES)
        assert article["title"].startswith("Protecting")
        assert article["tags"] == ["caddy", "authentik", "reverse-proxy", "sso"]

    def test_tags_are_lowercased_and_hyphenated(self):
        with _patch_call(json.dumps(VALID_RESPONSE)):
            article = generate_article("excerpt", None, server.CATEGORIES)
        for tag in article["tags"]:
            assert tag == tag.lower() and " " not in tag

    def test_duplicate_tags_are_removed(self):
        response = {**VALID_RESPONSE, "tags": ["caddy", "Caddy", "caddy "]}
        with _patch_call(json.dumps(response)):
            article = generate_article("excerpt", None, server.CATEGORIES)
        assert article["tags"] == ["caddy"]

    def test_code_fenced_json_is_accepted(self):
        fenced = "```json\n" + json.dumps(VALID_RESPONSE) + "\n```"
        with _patch_call(fenced):
            article = generate_article("excerpt", None, server.CATEGORIES)
        assert article["category"] == "DevOps"

    def test_prose_wrapper_with_valid_json_object_is_accepted(self):
        wrapped = (
            "Here is the article you asked for:\n"
            + json.dumps(VALID_RESPONSE)
            + "\nLet me know if you need changes."
        )
        with _patch_call(wrapped):
            article = generate_article("excerpt", None, server.CATEGORIES)
        assert article["title"].startswith("Protecting")

    def test_malformed_response_raises_provider_error(self):
        with _patch_call("not JSON at all, sorry"), pytest.raises(ProviderError, match="invalid structured output"):
            generate_article("excerpt", None, server.CATEGORIES)

    def test_schema_invalid_payload_raises_provider_error(self):
        response = {**VALID_RESPONSE, "tags": "not-a-list"}
        with _patch_call(json.dumps(response)), pytest.raises(ProviderError, match="invalid structured output"):
            generate_article("excerpt", None, server.CATEGORIES)

    def test_empty_response_raises_provider_error(self):
        with _patch_call(""), pytest.raises(ProviderError, match="empty response"):
            generate_article("excerpt", None, server.CATEGORIES)

    def test_api_failure_is_wrapped_in_provider_error(self):
        with _patch_call(side_effect=RuntimeError("503 upstream")), pytest.raises(ProviderError, match="Gemini API call failed"):
            generate_article("excerpt", None, server.CATEGORIES)

    def test_article_draft_schema_rejects_missing_fields(self):
        with pytest.raises(ValidationError):
            ArticleDraft.model_validate({"title": "only a title"})


# ---------------------------------------------------------------------------
# Configuration / provider selection / errors
# ---------------------------------------------------------------------------


class TestConfiguration:
    def test_missing_api_key_raises_clean_error(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(ProviderError, match="GEMINI_API_KEY is not set"):
            generate_article("excerpt", None, server.CATEGORIES)

    def test_empty_excerpt_raises_clean_error(self):
        with pytest.raises(ProviderError, match="empty conversation excerpt"):
            generate_article("   ", None, server.CATEGORIES)

    def test_unknown_provider_is_rejected(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        with pytest.raises(ProviderError, match="unknown LLM_PROVIDER"):
            generate_article("excerpt", None, server.CATEGORIES)

    def test_model_default_is_gemini_flash(self, monkeypatch):
        monkeypatch.delenv("GEMINI_MODEL", raising=False)
        assert GeminiProvider(api_key="k").model == "gemini-2.5-flash"

    def test_model_env_override(self, monkeypatch):
        monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro")
        assert GeminiProvider(api_key="k").model == "gemini-2.5-pro"


# ---------------------------------------------------------------------------
# publish_knowledge wiring (error mapping, full pipeline with mocks)
# ---------------------------------------------------------------------------


class TestPublishKnowledgeWiring:
    def test_missing_key_maps_to_clean_error(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        output = server.publish_knowledge(
            server.PublishInput(conversation_excerpt="solved problem text")
        )
        assert output.status == "error"
        assert "GEMINI_API_KEY" in output.error

    def test_generation_failure_maps_to_clean_error(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        with _patch_call("totally not JSON"):
            output = server.publish_knowledge(
                server.PublishInput(conversation_excerpt="solved problem text")
            )
        assert output.status == "error"
        assert "invalid structured output" in output.error

    def test_full_pipeline_with_valid_generation_is_rejected_by_github_stub(self, monkeypatch):
        """Generation succeeds -> validation passes -> GitHub stub still TODO."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        with _patch_call(json.dumps(VALID_RESPONSE)):
            output = server.publish_knowledge(
                server.PublishInput(
                    conversation_excerpt="solved problem text", language_hint="French"
                )
            )
        # GitHub integration is out of scope; the stub raises NotImplementedError,
        # which publish_knowledge maps to a clean error.
        assert output.status == "error"
        assert "GitHub API call" in output.error
