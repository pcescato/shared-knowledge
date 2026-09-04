"""Tests for the ElevenLabs audio generation pipeline (scripts/generate_audio.py).

No real API calls: synthesize() is mocked. The tests load the script as a
module (it lives outside the package root) and cover the pure pipeline:
frontmatter stripping, markdown-to-speech conversion, the deterministic
website mapping, idempotent manifest handling, and failure behavior.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "generate_audio.py"
spec = importlib.util.spec_from_file_location("generate_audio", SCRIPT)
generate_audio = importlib.util.module_from_spec(spec)
sys.modules["generate_audio"] = generate_audio
spec.loader.exec_module(generate_audio)

# The script calls sys.exit(main()) under `if __name__ == "__main__"`; when
# loaded via importlib its __name__ is "generate_audio", so main() is called
# directly. argv must not leak pytest's CLI arguments into argparse.
pytest_argv = sys.argv
sys.argv = ["generate_audio"]


def pytest_runtest_teardown(item, nextitem):
    sys.argv = pytest_argv

ARTICLE_MD = """\
---
title: "Protecting Streamlit with Caddy and Authentik"
description: "How to protect a Streamlit application using Caddy and Authentik."
category: "DevOps"
tags:
  - caddy
  - authentik
source: "community"
created_at: "2026-09-04"
---

# Protecting Streamlit with Caddy and Authentik

## Problem

Streamlit has no built-in authentication.

## Solution

Use **Caddy** forward_auth with [Authentik](https://example.com).

```caddy
example.com {
    reverse_proxy streamlit:8501
}
```

## Caveats

- WebSockets must be allowed.
"""


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    """A temp repo layout: one article, manifest path and audio root inside it."""
    knowledge = tmp_path / "knowledge" / "devops"
    knowledge.mkdir(parents=True)
    article = knowledge / "caddy-authentik-streamlit.md"
    article.write_text(ARTICLE_MD, encoding="utf-8")

    monkeypatch.setattr(generate_audio, "MANIFEST_PATH", tmp_path / ".audio_manifest.json")
    monkeypatch.setattr(generate_audio, "AUDIO_ROOT", tmp_path / "site/public/audio")
    monkeypatch.setattr(generate_audio, "KNOWLEDGE_ROOT", tmp_path / "knowledge")
    return tmp_path, article


class TestMarkdownToSpeech:
    def test_frontmatter_is_removed(self):
        speech = generate_audio.markdown_to_speech(ARTICLE_MD)
        assert "frontmatter" not in speech
        assert "created_at" not in speech
        assert "caddy-authentik" not in speech.split("Protecting")[0]

    def test_code_blocks_are_not_spoken(self):
        speech = generate_audio.markdown_to_speech(ARTICLE_MD)
        assert "reverse_proxy streamlit" not in speech
        assert "Code example omitted" in speech

    def test_links_keep_text_lose_urls(self):
        speech = generate_audio.markdown_to_speech(ARTICLE_MD)
        assert "Authentik" in speech
        assert "https://example.com" not in speech

    def test_markdown_formatting_is_stripped_but_identifiers_kept(self):
        speech = generate_audio.markdown_to_speech(ARTICLE_MD)
        assert "**" not in speech and "##" not in speech
        assert "Caddy forward_auth" in speech  # underscores in identifiers survive

    def test_output_is_nonempty_plain_text(self):
        speech = generate_audio.markdown_to_speech(ARTICLE_MD)
        assert speech.strip()
        assert not speech.lstrip().startswith("---")


class TestWebsiteContract:
    def test_deterministic_audio_mapping(self, workspace):
        tmp_path, article = workspace
        audio = generate_audio.audio_path_for(article)
        assert audio == tmp_path / "site/public/audio/devops/caddy-authentik-streamlit.mp3"
        assert audio.parent == tmp_path / "site/public/audio/devops"

    def test_mapping_is_stable_across_calls(self, workspace):
        _, article = workspace
        assert generate_audio.audio_path_for(article) == generate_audio.audio_path_for(article)


class TestIdempotency:
    def test_second_run_skips_unchanged_article(self, workspace, monkeypatch):
        tmp_path, article = workspace
        monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
        monkeypatch.setenv("ELEVENLABS_VOICE_ID", "v")

        calls = []

        def fake_synthesize(text, api_key, voice_id, model_id):
            calls.append(text)
            return b"mp3-bytes"

        monkeypatch.setattr(generate_audio, "synthesize", fake_synthesize)

        assert generate_audio.main() == 0
        assert generate_audio.main() == 0
        assert len(calls) == 1  # generated once, then skipped
        assert (tmp_path / "site/public/audio/devops/caddy-authentik-streamlit.mp3").exists()

    def test_changed_article_is_regenerated(self, workspace, monkeypatch):
        tmp_path, article = workspace
        monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
        monkeypatch.setenv("ELEVENLABS_VOICE_ID", "v")
        monkeypatch.setattr(generate_audio, "synthesize", lambda *a: b"mp3")

        generate_audio.main()
        article.write_text(ARTICLE_MD + "\nAn extra caveat.\n", encoding="utf-8")
        calls = []
        monkeypatch.setattr(
            generate_audio, "synthesize", lambda *a: calls.append(a) or b"mp3-2"
        )
        generate_audio.main()
        assert len(calls) == 1  # content changed -> regenerated

    def test_missing_audio_file_triggers_regeneration(self, workspace, monkeypatch):
        tmp_path, article = workspace
        monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
        monkeypatch.setenv("ELEVENLABS_VOICE_ID", "v")
        calls = []
        monkeypatch.setattr(
            generate_audio, "synthesize", lambda *a: calls.append(a) or b"mp3"
        )
        generate_audio.main()
        # Manifest claims audio exists, but the file was removed.
        (tmp_path / "site/public/audio/devops/caddy-authentik-streamlit.mp3").unlink()
        generate_audio.main()
        assert len(calls) == 2


class TestFailureBehavior:
    def test_api_failure_keeps_article_and_reports(self, workspace, monkeypatch, capsys):
        tmp_path, article = workspace
        monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
        monkeypatch.setenv("ELEVENLABS_VOICE_ID", "v")

        def boom(*a, **k):
            raise OSError("503 upstream")

        monkeypatch.setattr(generate_audio, "synthesize", boom)
        assert generate_audio.main() == 1  # clear failure exit code
        assert "unaffected" in capsys.readouterr().err  # clear failure report

        # The Markdown article is untouched and valid.
        assert article.read_text(encoding="utf-8") == ARTICLE_MD
        # No audio was claimed for the article.
        assert not (tmp_path / "site/public/audio/devops").exists()
        manifest = json.loads((tmp_path / ".audio_manifest.json").read_text())
        assert "knowledge/devops/caddy-authentik-streamlit.md" not in manifest

    def test_missing_credentials_fail_fast(self, monkeypatch, capsys):
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
        assert generate_audio.main() == 2
        assert "ELEVENLABS_API_KEY" in capsys.readouterr().err


class TestManifestFormat:
    def test_manifest_records_hash_audio_and_timestamp(self, workspace, monkeypatch):
        tmp_path, _ = workspace
        monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
        monkeypatch.setenv("ELEVENLABS_VOICE_ID", "v")
        monkeypatch.setattr(generate_audio, "synthesize", lambda *a: b"mp3")
        generate_audio.main()
        manifest = json.loads((tmp_path / ".audio_manifest.json").read_text())
        entry = manifest["knowledge/devops/caddy-authentik-streamlit.md"]
        assert entry["hash"] == generate_audio.content_hash(ARTICLE_MD)
        assert entry["audio"] == "site/public/audio/devops/caddy-authentik-streamlit.mp3"
        assert "generated_at" in entry
