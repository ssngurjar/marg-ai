# 0008 — Pin the WhatsApp Graph API to v26.0

- **Date:** 2026-10-27
- **Step:** S3 (docs/design/s03-whatsapp-ingress-auth.md §4.11)
- **Status:** accepted (owner, S3 design review)

## Context

Every Graph API call goes to a versioned URL. An unversioned URL silently follows Meta's
default, so a version change Meta makes could alter request or webhook shapes in the middle of
the hackathon without a code change on our side.

## Decision

`WHATSAPP_GRAPH_BASE_URL=https://graph.facebook.com/v26.0`, the current version in the App
Dashboard on Day 1. The value lives in settings (`.env`, `.env.example`), never in code.

Checked on this version on 2026-10-27:

- the `hello_world` template send to the owner's registered test recipient
- the webhook handshake, signed `messages` webhooks (text, voice note, sticker) and an
  `account_update` webhook
- a free-form text reply (`app.cli whatsapp reply-latest`)
- `GET` / `POST /{WABA_ID}/subscribed_apps`

## Consequences

- Meta supports each version for roughly two years, so one pin covers the project.
- Moving to a newer version is a deliberate change: update the setting, re-run the S3 exit check,
  and add a new decision note.
- The error codes in s03 §4.10 were checked against Meta's error-code reference for this version.
