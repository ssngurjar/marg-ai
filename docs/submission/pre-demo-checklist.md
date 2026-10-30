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
  (no message waiting a minute), model API, safety, ffmpeg (and the ML sidecar when voice
  replies are on).
- [ ] `/status` for the last 24 h: success rate ≥ 98%, p95 within the smoke-test numbers
  (`docs/load/2026-10-28-smoke-test.md`).
- [ ] `VOICE_REPLIES_ENABLED=false` unless the organisers have cleared MMS-TTS; if it's on, the
      ML sidecar (`make sidecar`) is running and stays up through judging.
- [ ] The corpus is ingested (`marg ingest-corpus --yes` on prod): 53 documents, verified from India.
- [ ] **Production is running again** (scaled to 0 on 2026-10-30 to save Neon compute hours):
  `~/.fly/bin/fly scale count 1 -a marg-ai --yes`, then `/readyz` is `200`. The WhatsApp
  webhook points at `https://marg-ai.fly.dev/webhooks/whatsapp`, not a tunnel.
- [ ] **On Nov 8:** Neon console → Billing: the project's CU-hours this month. Free is 100;
  production uses ~6 a day. To run until the community vote ends (Nov 16) and it won't last,
  move to Neon's Launch plan ($0.106 per CU-hour).
- [ ] **On Nov 4, before judging:** raise the per-IP demo limit so judges and testers sharing one
  network don't share 90 messages an hour: `~/.fly/bin/fly secrets set DEMO_IP_RATE_LIMIT_PER_HOUR=300 -a marg-ai`
  (owner decision 2026-10-30; the $5/day web cap stays).
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
