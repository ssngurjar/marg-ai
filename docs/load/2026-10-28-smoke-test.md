# Smoke test, 2026-10-28 (s16 §4.6, exception E4)

Ten visitors at once through `/demo`, each playing the parent journey a judge would: hello,
consent, the parent role, their child ("Meri beti Munni 5 saal ki hai"), the first khoj. Each
waits for every reply before sending the next message. Real models and safety (Muse Spark 1.3,
Muse Spark Open, Llama Guard 4); a throwaway database on the test Postgres; one api process
running the worker in-process (`RUN_WORKER_IN_API=true`) on a MacBook. Not a staging load test
(E4): no WhatsApp traffic, no voice notes, no duplicate webhooks (those are covered by the
integration suite).

Command: `.venv/bin/python -m scripts.load.web_smoke --target http://127.0.0.1:8013
--database-url <the server's database> --users 10`

| Criterion | Result | Target |
|---|---|---|
| Messages never answered | 0 | 0 |
| Completed turns with no reply | 0 | 0 |
| Fallback replies (holding, try again) | 0 of 50 | ≤ 2% |
| Wait for a reply, p50 / p95 | 4.2 s / 14.9 s | ≤ 6 s / ≤ 12 s (text) |
| Visitor problems | 0 | 0 |

50 replies for 50 messages, $0.184 for the run.

| Step | p50 ms | p95 ms | count |
|---|---|---|---|
| safety_in | 1492 | 2615 | 30 |
| safety_out | 534 | 2335 | 20 |
| generate | 0 | 7947 | 60 |

(Onboarding turns generate nothing, hence the 0 ms medians; buttons skip the input check.)

**Finding:** p95 is over the 12 s target. The slow turns are the first khoj: personalising the
activity takes up to ~8 s with ten people at once, after the input check (~2.6 s at p95) and
the 1 s burst wait. Every reply still arrived well inside the 25 s turn budget, and nothing was
lost, doubled or left silent. Options, for the owner: accept it for the demo (one judge at a
time sees ~4 s); shorten `TURN_DEBOUNCE_MS` to 500 ms (s04 open question 1); or run the
personalisation on Muse Spark Open with a tighter cap.
