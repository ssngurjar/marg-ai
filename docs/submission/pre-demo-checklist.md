# Pre-demo checklist (s16 §4.8)

Run the day before submission and again before the finals. Every item is yes or no; a "no" is
fixed or written down with its workaround before going on.

## Accounts and access
- [ ] WhatsApp: a permanent system-user token in `.env` (the temporary one expires in 24 h).
  There's no readiness probe for it (the messaging token can't read any object), so: send
  "Hi" from your phone and get the consent message back.
- [ ] The display name is approved for the number, or the fallback in plan.md §4.1 is ready.
- [ ] The webhook is subscribed to `messages`.
- [ ] Model API spend limit and credits cover the judging window (Nov 4–9).

## Service health
- [ ] `/readyz` is `200`, every probe passing: database, schema (newest migration), queue
  (no message waiting a minute), model API, safety, voice server, ffmpeg.
- [ ] `/status` for the last 24 h: success rate ≥ 98%, p95 within the smoke-test numbers
  (`docs/load/2026-10-28-smoke-test.md`).
- [ ] The ML sidecar (`make sidecar`: Kokoro voice and `/embed`) is running and stays up through judging.
- [ ] The corpus is ingested (`marg ingest-corpus`): 50 documents, verified from India.
- [ ] Nudge template approved in WhatsApp Manager in all three languages, or
  `NUDGES_ENABLED=false`.
- [ ] Activities loaded at startup: the 10 reviewed ones (exception E3).

## Safety and data
- [ ] `marg eval --file crisis.yaml --file adversarial.yaml` passes both hard gates on the build
  being shown.
- [ ] The crisis helpline numbers in `app/safety/crisis.py` are checked against their official
  pages again.
- [ ] Test users removed with "mera data hatao" (or `/demo` Reset); their rows are gone.
- [ ] Logs from the last day searched for 10-digit numbers: none found.

## Demo paths
- [ ] `/demo` works from a phone on mobile data and from a laptop, in a private window; the trace
  fills in live.
- [ ] `DEMO_RATE_LIMIT_PER_HOUR` and `DAILY_COST_CAP_USD` set for the judging window.
- [ ] The `wa.me` link and QR code in the submission open the right number.
- [ ] The fallback video is recorded, in case live WhatsApp fails during the finals.
- [ ] The newest eval scorecard in the README matches the commit being shown.

## Recovery
- [ ] A database backup (`pg_dump`) taken before submission.
- [ ] How to restart: `make up` (or the api and `make worker`); a turn cut off by a restart is
  answered once after it (s04 takeover, tested).
