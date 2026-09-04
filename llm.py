"""LLM provider isolation for publish_knowledge.

server.py never talks to an LLM SDK directly: it calls generate_article()
below, which builds the provider configured through environment variables.
Swapping Gemini for another provider later means adding a class here and a
branch in the factory - no MCP tool changes required.

Provider (default: Gemini via the official `google-genai` SDK):
  - model and API key come from environment variables (never hard-coded);
  - output is requested as structured JSON constrained by the ArticleDraft
    Pydantic schema (Gemini "structured output"), never loose prose;
  - the category is constrained by the prompt AND re-validated against the
    server's CATEGORIES afterwards (defense in depth, spec section 8);
  - every failure mode (missing key, missing package, API error, empty or
    malformed response, schema-invalid payload) raises ProviderError so
    publish_knowledge() can return a clean MCP-level error instead of
    silently fabricating an article.
"""

import json
import os
import re
from typing import Optional

from pydantic import BaseModel, Field, ValidationError

# ---------------------------------------------------------------------------
# Structured output contract
# ---------------------------------------------------------------------------


class ArticleDraft(BaseModel):
    """Schema sent to the LLM as the structured-output contract."""

    title: str = Field(description="Concise, descriptive title of the article.")
    description: str = Field(
        description="One-sentence standalone summary of the article."
    )
    category: str = Field(
        description="Exactly one category, verbatim from the provided list."
    )
    tags: list[str] = Field(
        description="3-8 lowercase, concise, reusable technical tags."
    )
    content: str = Field(
        description="Full Markdown article body, starting with '# Title'."
    )


class ProviderError(RuntimeError):
    """Raised for any LLM configuration, API, or response-format failure."""


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

# The core instruction, from the functional spec: knowledge extraction, not
# conversation summarization.
CORE_INSTRUCTION = (
    "Extract the reusable knowledge contained in the conversation, rather "
    "than summarizing the conversation itself."
)

PROMPT_TEMPLATE = """\
You are a technical editor for a community knowledge base.

{core_instruction}

Source material (excerpt of a conversation that solved a problem):
<source>
{excerpt}
</source>

Produce a standalone knowledge article that complies with ALL of these rules:
1. Write in English, as native technical documentation - not a literal translation.{language_line}
2. Do not summarize the conversation as a conversation: no dialogue, no "the user asked", no "as I said above", and no references to the user, the assistant, or the original conversation.
3. Keep only knowledge reusable by someone else facing the same problem; drop small talk, trial-and-error noise and dead ends.
4. Do not invent facts, commands, versions or configuration not supported by the source material.
5. Explicitly preserve important assumptions, environment details and caveats found in the source material.
6. Structure the Markdown content as:

   # Title
   ## Problem
   ## Context
   ## Solution
   ## Why it works
   ## Caveats

   "## Problem" and "## Solution" are mandatory. Omit "## Context",
   "## Why it works" or "## Caveats" only when genuinely not applicable.
7. The title must concisely describe the problem solved.
8. The description must be a one-sentence standalone summary of the article.
9. Choose exactly one category, taken verbatim from this list:
   {categories}
10. Generate 3 to 8 tags: lowercase, concise, technically meaningful, reusable; hyphens instead of spaces; no unnecessary punctuation.

Respond ONLY with JSON matching the provided schema.
"""


def build_article_prompt(excerpt: str, language_hint: Optional[str], categories: list[str]) -> str:
    """Build the article-generation prompt (pure function, unit-testable)."""
    language_line = (
        f"\n   The source conversation is in {language_hint!r}; the article must still be in English."
        if language_hint
        else ""
    )
    return PROMPT_TEMPLATE.format(
        core_instruction=CORE_INSTRUCTION,
        excerpt=excerpt.strip(),
        language_line=language_line,
        categories=", ".join(categories),
    )


# ---------------------------------------------------------------------------
# Gemini provider (isolated - the only module aware of the Gemini SDK)
# ---------------------------------------------------------------------------


class GeminiProvider:
    """Gemini implementation of the article-generation provider."""

    name = "gemini"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        self.temperature = 0.2

    def _call_gemini(self, prompt: str) -> str:
        """Single SDK touchpoint: send the prompt, return the raw JSON text.

        Isolated in one method so tests can stub it without the SDK and so a
        future SDK migration touches exactly one function. The API-key check
        lives here too: it is the first thing that runs before the SDK is
        imported, so a missing key is a clean configuration error.
        Error wrapping and empty-response handling belong to generate_article().
        """
        if not self.api_key:
            raise ProviderError(
                "GEMINI_API_KEY is not set; cannot call the Gemini API"
            )
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise ProviderError(
                "the Gemini provider requires the 'google-genai' package; "
                "install it with: pip install 'shared-knowledge-mcp[gemini]'"
            ) from exc

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ArticleDraft,  # structured output: no loose prose
            temperature=self.temperature,
        )
        client = genai.Client(api_key=self.api_key)
        response = client.models.generate_content(
            model=self.model, contents=prompt, config=config
        )
        return getattr(response, "text", None)

    @staticmethod
    def _strip_code_fence(raw: str) -> str:
        """Strip a Markdown code fence some Gemini models wrap around JSON."""
        match = re.fullmatch(r"```(?:json)?\s*\n(.*?)\n?\s*```", raw.strip(), re.DOTALL)
        return match.group(1) if match else raw

    def _parse_response(self, raw: str) -> dict:
        """Validate and normalize the structured JSON response."""
        text = self._strip_code_fence(raw)
        try:
            draft = ArticleDraft.model_validate_json(text)
        except (ValidationError, ValueError):
            # Fallback: some models occasionally answer in prose despite the
            # structured-output config. Accept it only if it contains a
            # parseable JSON object that fully matches the schema - otherwise
            # fail cleanly rather than fabricate an article.
            try:
                start, end = text.find("{"), text.rfind("}")
                if start == -1 or end <= start:
                    raise ValueError("no JSON object found in the response")
                draft = ArticleDraft.model_validate(json.loads(text[start : end + 1]))
            except (ValueError, ValidationError) as exc:
                raise ProviderError(
                    f"Gemini returned invalid structured output: {exc}"
                ) from exc
        return _normalize_article(draft.model_dump())

    def generate_article(
        self, excerpt: str, language_hint: Optional[str], categories: list[str]
    ) -> dict:
        """Turn a conversation excerpt into a validated article dict."""
        prompt = build_article_prompt(excerpt, language_hint, categories)
        try:
            raw = self._call_gemini(prompt)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Gemini API call failed: {exc}") from exc
        if not raw or not raw.strip():
            raise ProviderError("Gemini returned an empty response")
        return self._parse_response(raw)


# ---------------------------------------------------------------------------
# Normalization + factory / public seam
# ---------------------------------------------------------------------------


def _normalize_article(article: dict) -> dict:
    """Light, deterministic cleanup of LLM output (formatting only)."""
    article["title"] = article["title"].strip()
    article["description"] = article["description"].strip()
    article["content"] = article["content"].strip()

    # Tags: lowercase, spaces -> hyphens, strip punctuation edges, dedupe.
    normalized: list[str] = []
    for tag in article.get("tags", []):
        tag = re.sub(r"\s+", "-", str(tag).strip().lower()).strip("-.")
        if tag and tag not in normalized:
            normalized.append(tag)
    article["tags"] = normalized
    return article


def _build_provider() -> GeminiProvider:
    """Provider factory - add branches here to support other providers."""
    name = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()
    if name != "gemini":
        raise ProviderError(
            f"unknown LLM_PROVIDER {name!r}; supported providers: 'gemini'"
        )
    return GeminiProvider()


def generate_article(
    excerpt: str, language_hint: Optional[str], categories: list[str]
) -> dict:
    """Public seam used by server._generate_article.

    Raises ProviderError on missing configuration, API failure, or malformed
    responses - never returns a fabricated article.
    """
    if not excerpt or not excerpt.strip():
        raise ProviderError("empty conversation excerpt: nothing to extract")
    return _build_provider().generate_article(excerpt, language_hint, categories)
