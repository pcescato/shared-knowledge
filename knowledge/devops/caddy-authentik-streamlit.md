---
title: "Protecting Streamlit with Caddy and Authentik"
description: "How to protect a Streamlit application using Caddy and Authentik forward authentication."
category: "DevOps"
tags:
  - caddy
  - authentik
  - streamlit
  - reverse-proxy
  - sso
source: "community"
created_at: "2026-09-04"
---

# Protecting Streamlit with Caddy and Authentik

## Problem

Streamlit applications have no built-in authentication mechanism. When exposed behind
a reverse proxy, the whole application is either public or unreachable.

## Context

- Streamlit runs in Docker and listens on port 8501.
- Authentik provides single sign-on and issues JWTs.
- Caddy 2 performs automatic TLS and supports forward authentication.

## Solution

Put Caddy in front of Streamlit and enable Authentik's `forward_auth` directive so that
every request is validated against Authentik before reaching the application:

```caddy
example.com {
    forward_auth authentik:9000 {
        path /outpost.goauthentik.io/auth
    }
    reverse_proxy streamlit:8501
}
```

## Why it works

Caddy consults Authentik on every request before proxying. Unauthenticated users are
redirected to the Authentik login page, and only requests carrying a valid session
reach Streamlit.

## Caveats

- WebSocket upgrades used by Streamlit must be allowed by the proxy (Caddy handles
  this automatically for `reverse_proxy`).
- The Authentik outpost must share a Docker network with Caddy.
