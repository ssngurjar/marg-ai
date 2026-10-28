# Spike F: SAM 3.1 activity photos (s02 §4.6a, decision C7)

Run 2026-10-28 with `scripts/spikes/image_eval.py photos`, on **15 synthetic test photos** made
with Muse Image (realistic village photos; adults only, never a child; checked by eye, counts
confirmed by eye). The photos and raw results stay outside the repo. Real village photos
(`samples.md` set B) replace them when they arrive; until then this proves the call format and
gives a first reading, not a field accuracy.

## How SAM 3.1 is called (verified)

- `POST /v1/responses`, `model: sam-3.1`, one user message with an `input_text` (one noun phrase,
  e.g. `leaf`) and an `input_image` (a base64 `data:` URL; a 1024 px JPEG works).
- `metadata: {"include_confidence": "true", "mask_encoding": "one_bit"}`.
- The answer is in `output_text`: one `<|box;…|>` token per object found, with `c=<confidence>`
  among its fields. No token means nothing found. One phrase per call.
- No detection came back below a confidence of 0.68, so the API already applies its own threshold.

## Results

| Test | Result |
|---|---|
| Counting (7 leaves, 5 stones, 4 marigolds, 6 buttons) | **4/4 exact**; confidences 0.93–0.97 |
| Person check on 6 people photos: a face, a hand only, a face cut off at the edge, a person far away, hands and shoulders only, a poster of a face | **6/6 caught** by `person` (0.85–0.97) |
| False alarms on 9 object photos (leaves, stones, dough, a drawing, an empty courtyard, the 4 count photos) | **0** for `person`, `face` and `hand` |
| Latency per call (49 calls, 4 in flight) | p50 **1.8 s**, p95 **2.6 s** |
| Cost | $2.50 per 1,000 calls (s02); a photo needs 2 person-check calls and 1–3 count calls, about $0.01 |

## Against the go/fallback table (s02 §4.6a)

- Person recall 100% with ≤ 1 false person on object photos: **met** (on synthetic photos).
- Counts within ±1 on 3 of 4: **met** (4 of 4 exact).

## Finding that conflicts with the design

**A hand alone counts as a person.** s10b §4.14 says "hand alone is allowed: holding leaves is
normal". SAM's `person` phrase fires on the hand-only photo (0.93), and on the hands-and-shoulders
photo it also reports a `face` (0.89) although no face is in the frame. So "reject on person or
face, allow a hand" can't be implemented as written: with the `person` phrase, every photo with a
hand in it is rejected. **Decided (owner, 2026-10-28):** any person refuses the photo, a hand
included; the person check asks for `person` and `face` (s10b decisions log).

## Still to do with real photos

Run the same script over `samples.md` set B (20 photos) and record the results here. The bar is
the same: no person photo may be missed.
