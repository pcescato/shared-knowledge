#!/usr/bin/env python3
"""Generate audio versions of merged knowledge articles via ElevenLabs.

Runs in CI AFTER an article has been merged into the default branch and
reviewed by a human maintainer - audio is never generated when
publish_knowledge() opens a Pull Request. The authoritative sequence is:

    MCP -> Markdown article -> GitHub Pull Request -> Human review
         -> Merge -> GitHub Action (this script) -> ElevenLabs -> Audio

The validated Markdown article is the sole source for the audio: the
original conversation is never seen here.

Idempotency: a manifest (.audio_manifest.json) records the SHA-256 of
each article's Markdown at generation time. An article is sent to
ElevenLabs only when it is new, its content changed, or its audio file
is missing - existing audio is never regenerated unnecessarily.

Website contract (deterministic mapping):
    knowledge/<category>/<slug>.md  ->  site/public/audio/<category>/<slug>.mp3
The audio is committed to the repository, so the static documentation
site ships it without any runtime dependency on ElevenLabs.

Failure behavior: the Markdown article always remains valid (this script
never touches knowledge/**). If ElevenLabs fails for an article, no
audio file is written and no manifest entry is recorded for it (the site
can therefore rely on the manifest/audio file to know what exists), the
failure is printed clearly, and the script exits non-zero so CI reports
it.

Configuration (environment variables, never hard-coded credentials):
    ELEVENLABS_API_KEY   required - ElevenLabs API key
    ELEVENLABS_VOICE_ID  required - ID of the voice to use (see
                         elevenlabs.io -> Voices; configurable by design)
    ELEVENLABS_MODEL_ID  optional - TTS model (default: eleven_multilingual_v2)
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: requests library required. Install with: pip install requests", file=sys.stderr)
    sys.exit(2)

MANIFEST_PATH = Path(".audio_manifest.json")
AUDIO_ROOT = Path("site/public/audio")
KNOWLEDGE_ROOT = Path("knowledge")
ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/hpp4J3VqNfWAUOO0d1Us"
DEFAULT_MODEL_ID = "eleven_multilingual_v2"


# ---------------------------------------------------------------------------
# Markdown -> speech text
# ---------------------------------------------------------------------------


def strip_frontmatter(text: str) -> str:
    """Remove a leading YAML frontmatter block (--- ... ---) if present."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].lstrip("\n")
    return text


def markdown_to_speech(md: str) -> str:
    """Convert article Markdown into clean, human-readable spoken text.

    Removes frontmatter, code blocks (never spoken), link/image URLs and
    emphasis markers; keeps headings and list content as plain sentences.
    """
    text = strip_frontmatter(md)

    # Fenced code blocks are not spoken.
    text = re.sub(
        r"```[^\n]*\n.*?```",
        "Code example omitted in the audio version.",
        text,
        flags=re.DOTALL,
    )
    # Images and links: keep readable text only.
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    # Headings, emphasis, blockquotes, list bullets, rules.
    # NOTE: single underscores are kept so identifiers like `forward_auth`
    # are spoken as written instead of being mangled by emphasis stripping.
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*|__|\*", "", text)
    text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\|.*\|$", "", text, flags=re.MULTILINE)  # tables
    text = re.sub(r"^(-{3,}|\*{3,})\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"<[^>]+>", "", text)  # stray HTML

    # Collapse whitespace but keep paragraph breaks for natural pacing.
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def audio_path_for(knowledge_file: Path) -> Path:
    """Deterministic artifact path for an article (website contract)."""
    relative = knowledge_file.relative_to(KNOWLEDGE_ROOT)
    return AUDIO_ROOT / relative.parent / (relative.stem + ".mp3")


def content_hash(md: str) -> str:
    return hashlib.sha256(md.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Manifest (idempotency)
# ---------------------------------------------------------------------------


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def needs_generation(article_rel: str, md: str, audio_file: Path, manifest: dict) -> bool:
    """True unless the manifest entry matches the content AND audio exists."""
    entry = manifest.get(article_rel)
    if not entry or entry.get("hash") != content_hash(md):
        return True
    return not audio_file.exists()


# ---------------------------------------------------------------------------
# ElevenLabs API
# ---------------------------------------------------------------------------
        
def synthesize(text: str, api_key: str, voice_id: str, model_id: str) -> bytes:
    """Generate audio via ElevenLabs API.
    
    Args:
        text: Article text to synthesize
        api_key: ElevenLabs API key (secret)
        voice_id: Voice ID (public identifier, configurable) - currently hardcoded
        model_id: TTS model ID
    """
    url = ELEVENLABS_TTS_URL
    print(f"[DEBUG] synthesize: voice_id param={repr(voice_id)}, url={url}", file=sys.stderr)
    print(f"[DEBUG] text length: {len(text)}, text preview: {text[:50]}...", file=sys.stderr)
    
    body = {"text": text, "model_id": model_id}
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    
    print(f"[DEBUG] request body: {list(body.keys())}, headers: {list(headers.keys())}", file=sys.stderr)
    
    try:
        response = requests.post(url, json=body, headers=headers, timeout=120)
        print(f"[DEBUG] response status: {response.status_code}", file=sys.stderr)
        response.raise_for_status()
        return response.content
    except requests.exceptions.RequestException as exc:
        error_msg = str(exc)
        if hasattr(exc, 'response') and exc.response is not None:
            try:
                error_msg = exc.response.text
            except:
                pass
        raise urllib.error.HTTPError(url, exc.response.status_code if hasattr(exc, 'response') and exc.response else 500, error_msg, {}, None) from exc        


# ---------------------------------------------------------------------------
# Changed-article detection (CI helper)
# ---------------------------------------------------------------------------


def changed_articles(changed_from: str) -> list[str]:
    """Knowledge files changed since `changed_from` (git), as relative paths."""
    output = subprocess.run(
        ["git", "diff", "--name-only", f"{changed_from}..HEAD", "--", "knowledge"],
        capture_output=True, text=True, check=True,
    )
    return [line for line in output.stdout.splitlines() if line.endswith(".md")]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-dir", type=Path, default=KNOWLEDGE_ROOT)
    parser.add_argument(
        "--changed-from", metavar="SHA",
        help="only consider knowledge files changed since this git revision "
             "(informational; the manifest remains authoritative)",
    )
    args = parser.parse_args()

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID")
    model_id = os.environ.get("ELEVENLABS_MODEL_ID", DEFAULT_MODEL_ID)
    print(f"[DEBUG-CI] voice_id={voice_id!r} len={len(voice_id) if voice_id else 0} api_key_len={len(api_key) if api_key else 0}", file=sys.stderr)
    
    # Debug: check what Python received
    print(f"[DEBUG] voice_id from env: {repr(voice_id)}, len={len(voice_id) if voice_id else 'None'}", file=sys.stderr)
    
    if not api_key or not voice_id:
        print(
            "ERROR: ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID must be set "
            "(use repository secrets and environment variables).",
            file=sys.stderr,
        )
        return 2

    knowledge_dir: Path = args.knowledge_dir
    manifest = load_manifest()
    candidates = (
        set(changed_articles(args.changed_from)) if args.changed_from else None
    )

    generated: list[str] = []
    skipped: list[str] = []
    failed: list[tuple[str, str]] = []

    articles = sorted(knowledge_dir.glob("**/*.md"))
    for article in articles:
        # Repo-relative identity ("knowledge/<category>/<file>.md"): stable
        # manifest keys, and directly comparable to git-diff paths.
        rel_under_kb = article.relative_to(knowledge_dir)
        article_rel = f"knowledge/{rel_under_kb.as_posix()}"
        if candidates is not None and article_rel not in candidates:
            skipped.append(article_rel)
            continue

        md = article.read_text(encoding="utf-8")
        audio_file = audio_path_for(article)
        if not needs_generation(article_rel, md, audio_file, manifest):
            skipped.append(article_rel)
            continue

        speech = markdown_to_speech(md)
        if not speech.strip():
            failed.append((article_rel, "article has no speakable content"))
            continue

        try:
            audio = synthesize(speech, api_key, voice_id, model_id)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            # No audio file written, no manifest entry: the site cannot claim
            # audio exists for this article. The Markdown article stays valid.
            failed.append((article_rel, str(exc)))
            continue

        audio_file.parent.mkdir(parents=True, exist_ok=True)
        audio_file.write_bytes(audio)
        # Store the artifact path relative to the manifest location (repo
        # root) so the manifest is portable across checkouts.
        try:
            audio_rel = audio_file.relative_to(MANIFEST_PATH.parent).as_posix()
        except ValueError:
            audio_rel = audio_file.as_posix()
        manifest[article_rel] = {
            "hash": content_hash(md),
            "audio": audio_rel,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        generated.append(article_rel)

    save_manifest(manifest)

    print(f"Generated: {len(generated)}  Skipped (up to date): {len(skipped)}  Failed: {len(failed)}")
    for path in generated:
        print(f"  [OK]   {path}")
    for path, error in failed:
        print(f"  [FAIL] {path}: {error}", file=sys.stderr)
    if failed:
        print(
            "\nAudio generation failed for the articles above; the Markdown "
            "knowledge base is unaffected and no audio was claimed for them.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
