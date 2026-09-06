---
category: AI
created_at: '2026-09-06'
description: An HTTP 400 invalid_uid error from the ElevenLabs Text-to-Speech API
  can mean the voice belongs to the shared Voice Library, which is not usable via
  API on the Free plan.
source: community
tags:
- elevenlabs
- text-to-speech
- api
- http-400
- debugging
- python
title: 'ElevenLabs TTS returns invalid_uid: the voice_id is valid, your plan is the
  problem'
---

## Problem

Calls to the ElevenLabs Text-to-Speech API fail systematically with HTTP 400 and this JSON body:

```json
{"detail":{"type":"invalid_request","code":"bad_request","message":"No ID has been received, make sure to provide it in the request.","status":"invalid_uid"}}
```

The message points at a missing or malformed voice ID, so the obvious checks come first — and all of them pass:

- the API key is valid and correctly sent in the `xi-api-key` header;
- the voice ID is 20 characters long, as expected;
- there is no whitespace, newline or invisible character in the value;
- the ID is correctly interpolated into the request URL.

The request still fails every time, with the same error.

## Solution

Use a voice ID that belongs to your own account instead of one taken from the shared Voice Library.

1. Open the ElevenLabs web interface and go to the **My Voices** tab (not **Voice Library**).
2. If the voice you want lives in the Voice Library, open it and use **Add to my voices** first.
3. Copy the voice ID from **My Voices** and use that value in your API calls.

No other change is needed: the same account, the same API key and the same request code start working immediately.

```python
import os
import requests

VOICE_ID = os.environ["ELEVENLABS_VOICE_ID"]  # taken from "My Voices"

response = requests.post(
    f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}",
    headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
    json={"text": "Hello world", "model_id": "eleven_multilingual_v2"},
    timeout=60,
)
response.raise_for_status()
```

## Why it works

The ElevenLabs Voice Library is the catalogue of community-shared voices. Those voices are browsable and usable from the web interface on any plan, including Free, which makes them look like ordinary voices. Programmatic access to them, however, is reserved for paid plans.

When a Free-plan API key requests a Voice Library voice, the backend does not resolve it to a voice the account owns, so the ID ends up unresolved and the API reports it as `invalid_uid` — an authorization restriction surfaced as a validation error. Adding the voice to **My Voices** makes it a voice the account actually owns, so the lookup succeeds and the plan restriction no longer applies.

## Caveats

- The error message is genuinely misleading: `invalid_uid` and "No ID has been received" describe a malformed request, not a plan limitation. Do not spend time validating the string.
- Historical "premade" voices are not automatically safe. On the account where this was reproduced, even Rachel (`21m00Tcm4TlvDq8ikWAM`) behaved as a Voice Library voice and triggered the same error.
- Having API character quota available (the Free plan includes 10,000 characters per month) does not imply access to every voice. Quota and voice entitlements are separate.
- Plan tiers and Voice Library policies change over time; check the current ElevenLabs pricing and documentation if the behaviour differs.
- The same symptom can still have a mundane cause, such as an empty environment variable producing a request to a URL with no ID at all. Log the exact URL once before concluding it is a plan issue.