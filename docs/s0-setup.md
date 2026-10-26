# S0 — Account and environment setup

Everything here is done by hand in a browser before Day 1. Tick each item as it's done. Secrets
go into a local `.env` (untracked) or a password manager. **Never paste a token into a commit, an
issue, or a chat.**

## 1. Meta developer app + WhatsApp Cloud API (do first: display-name approval can take a few days)

- [ ] Create or confirm a **Meta Business portfolio** at <https://business.facebook.com>.
- [ ] Start **business verification** (Business settings → Security Center) in parallel. **Nothing
      depends on it.** It only raises the 250/day limit on business-initiated messages
      (plan.md §4.1). Replies to people who message first aren't limited.
- [ ] Buy a **fresh prepaid SIM** for Marg.ai. Don't use your personal number: a number registered
      on the Cloud API can't stay on the WhatsApp app, and moving it loses its chat history.
- [ ] Put up a **one-page public site** (GitHub Pages is enough) describing Marg.ai. Display-name
      review checks that the name matches a real presence.
- [ ] Create an app at <https://developers.facebook.com/apps>: type **Business**, linked to the portfolio.
- [ ] Add the **WhatsApp** product. Meta issues a **test phone number** and a temporary access
      token, which expires after about 24 h.
- [ ] Under WhatsApp → API Setup, add your own phone (and up to 4 testers) as **recipient numbers**.
      The test number can only message these.
- [ ] Send the "hello_world" template from the API Setup page to your phone to confirm it works.
- [ ] **Add the real number:** WhatsApp → API Setup → Add phone number. Use the new SIM, display
      name "Marg.ai", category Education, verify by SMS. Watch for display-name approval. Until
      it's approved, keep using the test number.
- [ ] Create a **permanent token**: Business settings → Users → System users → add a system user
      (Admin), assign the app and the WhatsApp account, then generate a token with
      `whatsapp_business_messaging` and `whatsapp_business_management`.
- [ ] Copy the **App Secret** (App settings → Basic). It's used to verify `X-Hub-Signature-256`.
- [ ] Choose a random **webhook verify token** (any long random string).
- [ ] **Parent nudge template** (submit on Day 1, approval can take time): WhatsApp Manager →
      Message templates → create `aaj_ki_khoj` in Hindi, Hinglish (as `hi`) and English, body
      "Aaj ki khoj taiyaar hai! 2 minute, bachche ke saath." with one quick-reply button
      "Aaj ki khoj batao". Record the category Meta assigns and the per-message price
      (docs/design/s10b-parent-journey.md §4.11).
- [ ] The webhook URL is configured in S3, once the app is deployed: WhatsApp → Configuration →
      Callback URL + verify token, then subscribe to the `messages` field.

## 1b. Content to draft before kickoff (content, not code)

- [ ] ~~Draft activities before kickoff~~ **Moved to after kickoff** (Day 1 evening and Day 2):
      activities are product content, so they're written during the hackathon. Format:
      docs/design/s10b-parent-journey.md §4.3. Line up the reviewers (a parent and, ideally, an
      anganwadi worker or teacher) now.
- [ ] Ask one parent of a 3–8-year-old and one teacher to be field testers from Day 6.

## 1b′. Urgent today (from the Participant Guide)

- [ ] **Request Modal credits** ($100, first 1,000 participants) and **Baseten credits** ($100 + 2M
      TPM, up to 2,000, reviewed by use case: "voice-first WhatsApp coach for rural parents; Muse
      Spark Open for multimodal reflection"). Fireworks is per-team shortlist: request too.
- [ ] **Join the hackathon Discord**, post in #intros, follow #announcements. Questions for the
      Meta team go to #office-hours (weekdays 10–11 AM ET = 19:30–20:30 IST until Nov 1).
- [ ] **Watch the kickoff livestream: Mon Oct 26, 12:00 PM ET = 21:30 IST.**
- [ ] The credit claim link is "coming soon" in the Guide: watch the portal and email. Add a card on
      the Model API **Billing** page and set a **Spend Limit** notification at $150.
- [ ] Create the GitHub repo as **public** (required by the rules) when the first code lands, with
      the full git history so the `pre-kickoff` tag is visible.

## 1c. Day 1 actions from the Official Rules (read 2026-10-26)

- [ ] Accept the Official Rules and waiver in the portal.
- [ ] Claim the $150 Model API credit: find the claim form in the **"Know Before You Go"** email
      (sent to your application address; check spam). It needs your name, that email, and your
      Model API account's **Team ID** (the account needs a payment method on file). Credits arrive
      within ~2 business days and don't expire; anything beyond $150 is charged to the card, so set
      a spending alert.
- [ ] Open the submission form (<https://cerebralvalley.ai/e/meta-ai-developer-hackathon/hackathon/submit>)
      and note every field: video length, repo link, description, track. Record them in `docs/submission/`.
- [ ] Ask on the event Discord: "Can a submission call Meta's MMS-TTS (`facebook/mms-tts-hin`,
      CC-BY-NC 4.0) for Hindi speech, given the Official Rules' open-source licence clause?" Record
      the answer in `docs/decisions/` (decision C8).
- [ ] Demo video consent form (Hindi and English) for the parent who appears: covers public use
      and Meta's perpetual marketing use under the Official Rules; no child's face.

## 2. Meta Model API (after acceptance)

- [ ] Sign in at <https://dev.meta.ai>, create an API key, and set a spend limit if the console offers one.
- [ ] Check which models your key can list (`GET https://api.meta.ai/v1/models`). This happens in S2.

## 3. Hosting and data

- [ ] **Neon** (<https://neon.tech>): create project `marg-ai`, Postgres 16, region closest to India
      (Singapore). Enable the `vector` extension (`CREATE EXTENSION vector;`). Copy the pooled connection string.
- [ ] **Fly.io** (<https://fly.io>) **or Railway** (<https://railway.app>): create an account and
      install the CLI. Pick a region close to India (Singapore). No deploy yet.
- [ ] **Modal** (<https://modal.com>): create an account, `pip install modal`, `modal token new`.
      Claim the hackathon credit after acceptance.
- [ ] **Baseten / Fireworks**: create accounts and claim credits after acceptance. Used for Llama Guard 4 in S2.

## 4. Local machine

- [ ] `uv` installed (`brew install uv`), then Python 3.13 through it: `uv python install 3.13`.
      The system Python on this machine is 3.10, which is too old.
- [ ] `ffmpeg` installed (`brew install ffmpeg`), and check opus support: `ffmpeg -codecs | grep opus`.
- [ ] Docker Desktop running (for local Postgres + pgvector).

## 5. Settings to collect (names the app will read; values stay out of git)

| Setting | Where it comes from |
|---|---|
| `MODEL_API_KEY` | dev.meta.ai console |
| `WHATSAPP_ACCESS_TOKEN` | System-user permanent token |
| `WHATSAPP_PHONE_NUMBER_ID` | WhatsApp → API Setup |
| `WHATSAPP_BUSINESS_ACCOUNT_ID` | WhatsApp → API Setup |
| `WHATSAPP_APP_SECRET` | App settings → Basic |
| `WHATSAPP_VERIFY_TOKEN` | You choose it |
| `DATABASE_URL` | Neon connection string |
| `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` | `modal token new` |
| `LLAMA_GUARD_BASE_URL` / `LLAMA_GUARD_API_KEY` | Chosen host, decided in S2 |
| `USER_HASH_SALT` | Generate: `openssl rand -hex 32` |

These names are provisional. S1 fixes them in `app/core/config.py` and `.env.example`.
