# Connecting the real WhatsApp Cloud API (Meta) – step by step

> **Status: built and tested against simulated Meta traffic only. NOT yet verified against Meta's real servers.**
> Everything in this guide that talks to Meta has been exercised with correctly signed sample webhooks, a fake Graph API and a local HTTP server – but I had no Meta account to test against. **Step 9 is the live test. Until it passes on your phone, treat the integration as unproven.** Two commands in this repo (`python -m backend.whatsapp_check …`) do most of the verifying for you.

**Keeping the demo:** nothing here changes the simulated mode. With `WHATSAPP_MODE=simulated` (the default) the app works exactly as before, with no Meta account. Switch modes by editing one line in `.env` and restarting.

```
 Patient's phone ──► Meta (WhatsApp) ──POST /whatsapp/webhook──► your tunnel ──► this app (port 8000)
                                                                                   │ verify signature · skip duplicates
 Patient's phone ◄── Meta ◄──────────── Graph API (send message) ◄─────────────────┤ classify → RAG → verify
                                                                                   │ safe?  → reply automatically
                                                                                   └ unsure → dashboard → receptionist approves → reply
```

## What I confirmed in Meta's documentation, and what I did not

| Confirmed in Meta's docs (developers.facebook.com) | From my own knowledge – check on screen |
|---|---|
| The GET handshake: `hub.mode=subscribe`, `hub.verify_token`, `hub.challenge`; answer with the challenge, 403 if the token is wrong | The exact labels and layout of the **API Setup** page (Meta redesigns it often) |
| Every POST is signed with your **App Secret** in the `X-Hub-Signature-256` header (`sha256=` + HMAC-SHA256 of the **raw** body) | Temporary access tokens last about **24 hours** |
| Always answer **200**; failed deliveries are retried for **up to 36 hours**, so you must de-duplicate | A test number can message only a **small list of verified recipients** (I recall 5) |
| Dashboard path: **WhatsApp → Configuration → Edit**, then subscribe to the **`messages`** webhook field | Error **131047** = outside the 24-hour window; **131030** = recipient not on the allowed list (confirmed only by third-party guides) |
| The send request: `POST …/{phone-number-id}/messages` with `messaging_product`, `recipient_type`, `to`, `type: "text"`, `text.body` (max 4096 characters) | The System User steps for a permanent token (Part B, step 8) |
| Current Graph API version is v26.0 (v25.0, the default here, is also supported) | |

If a label on your screen differs from this guide, look for the closest match and trust the screen.

## What you need

* A Facebook account and a **Meta developer account** (developers.facebook.com).
* A phone with WhatsApp (your own, for testing).
* A **public HTTPS address** that reaches your laptop – a *tunnel*. This guide uses ngrok; Cloudflare Tunnel works too. Meta cannot reach `localhost`.
* This app installed and running (`python run.py`).

---

## Part A – Create the Meta app

1. Go to **https://developers.facebook.com** → **My Apps** → **Create App**.
2. Choose the use case **"Connect with customers through WhatsApp"** (it may also appear as "Other" → "Business"). Give the app a name, e.g. *Clinic Assistant (test)*, and create it. If asked, create or choose a **Meta Business portfolio**.
3. In the app, open the **WhatsApp** section → **API Setup** (it may be called "Quickstart").

On that page Meta provides (for free, for testing) a **test phone number**. Note down:

| What you see on screen | Goes into `.env` as |
|---|---|
| **Phone number ID** (a long number, *not* the phone number itself) | `WHATSAPP_PHONE_NUMBER_ID` |
| **Temporary access token** (button *Generate / Copy*; lasts ~24 hours) | `WHATSAPP_ACCESS_TOKEN` |
| *(also shown, not needed by the app)* WhatsApp Business Account ID, the test number itself | – |

4. **Add yourself as a test recipient.** On the same page find the **To** field → **Manage phone number list** (or similar) → add **your own mobile number** in international format → Meta sends a code to your WhatsApp → enter it. Only numbers on this list can receive messages from the test number. Add every phone you want to test with.
5. **App Secret:** **App settings → Basic → App secret → Show** (you may have to re-enter your Facebook password). Copy it. It goes into `WHATSAPP_APP_SECRET`. *It is different from the access token. Never share either.*

## Part B – Configure this app

6. Invent a **verify token** – any long random phrase that only you know. For example:
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(24))"
   ```
   This is **not** something Meta gives you. You choose it, put it in `.env`, and type the *same* text into Meta's dashboard in Part D.

7. Create your `.env` file (it is listed in `.gitignore`, so it is never committed):
   ```bash
   cd Dental-Clinic-AI
   cp .env.example .env
   ```
   Edit `.env` and fill in these lines (no quotes, no spaces around `=`):
   ```
   WHATSAPP_MODE=cloud
   WHATSAPP_VERIFY_TOKEN=<the phrase from step 6>
   WHATSAPP_APP_SECRET=<from step 5>
   WHATSAPP_ACCESS_TOKEN=<from step 3>
   WHATSAPP_PHONE_NUMBER_ID=<from step 3>
   WHATSAPP_ALLOWED_SENDERS=<your own number, digits only, e.g. 919876543210>
   ```
   `WHATSAPP_ALLOWED_SENDERS` is a safety net for the first tests: the assistant ignores everyone else. Leave it empty later.

8. *(Later, for more than 24 hours)* The temporary token expires daily. For a permanent one, in **Meta Business Suite → Business settings → Users → System users**, add a system user, give it your app and WhatsApp account, and generate a token with the WhatsApp messaging permissions (`whatsapp_business_messaging`, `whatsapp_business_management`). Put it in `WHATSAPP_ACCESS_TOKEN`.

9. Start the app and check the token (this sends nothing to anyone):
   ```bash
   python run.py
   ```
   In a **second terminal**:
   ```bash
   cd Dental-Clinic-AI
   source .venv/bin/activate
   python -m backend.whatsapp_check
   ```
   You want to see `[OK]` on all lines, including *"Meta accepted the token. Number: …, name: …"*. If the token line fails, the message says why (expired token, wrong phone-number id…). The banner printed by `run.py` also lists any setting still missing.

## Part C – Make your laptop reachable: the tunnel

10. Install and start ngrok (free account at ngrok.com):
    ```bash
    brew install ngrok/ngrok/ngrok
    ngrok config add-authtoken <your ngrok token>
    ngrok http 8000
    ```
    ngrok prints a line like `Forwarding https://abcd-1234.ngrok-free.app -> http://localhost:8000`. **That `https://…` address is your public base URL.** (On the free plan it changes every time you restart ngrok – then you must update it in Meta, Part D.)

11. **Safety, read this:** the dashboard and the knowledge-base editor have **no login**. The app therefore refuses *everything* except the webhook (`/whatsapp/webhook`) and `/healthz` for any request that arrives through a tunnel or proxy, so a stranger who finds your ngrok address cannot open your dashboard or delete data. You use the dashboard on the laptop itself, at **http://127.0.0.1:8000/dashboard/** – *not* through the ngrok address. (`ALLOW_PUBLIC_DASHBOARD=true` removes this protection; don't.)

12. Check that the tunnel reaches the app and the secrets are right – **before** touching Meta's dashboard:
    ```bash
    python -m backend.whatsapp_check --probe https://abcd-1234.ngrok-free.app
    ```
    It performs a verification handshake with your token, sends a correctly signed (harmless) event, and a badly signed one that must be refused. Expect `[OK]` on all four lines. It creates no patient message and sends nothing to WhatsApp.

## Part D – Tell Meta where to send messages

13. In the Meta app dashboard: **WhatsApp → Configuration**. In the **Webhook** section press **Edit** and fill in:

    | Field | Value |
    |---|---|
    | **Callback URL** | `https://abcd-1234.ngrok-free.app/whatsapp/webhook` ← your ngrok address **plus `/whatsapp/webhook`** |
    | **Verify token** | exactly the phrase from `WHATSAPP_VERIFY_TOKEN` |

    Press **Verify and save**. Meta sends the handshake (GET) to your URL. The dashboard should accept it. If it fails, see *Troubleshooting*.

14. Still on **Configuration → Webhook fields** press **Manage** and **subscribe to `messages`** (toggle on). Without this Meta verifies your URL but sends you nothing.

15. *(Optional)* Next to the `messages` field there is a **Test** link; it sends a sample notification to your URL. The sample comes from a made-up phone number, so the app will process it but the *reply* to that fake number will fail ("not on the allowed list"). That is expected and proves the receiving side works: you will see the message appear in the dashboard.

## Part E – The live test (this decides whether it works)

16. From **your own phone**, open WhatsApp and send a message **to the test number** (shown on the API Setup page – Meta also provides a ready-made link/QR). Try these in order and watch **http://127.0.0.1:8000/dashboard/**:

    | You send | You should see |
    |---|---|
    | `What are your clinic timings on Sunday?` | A reply on your phone within a few seconds. Dashboard → *Auto-replied* → open it: "✓ Verified automatically", the source `clinic:timings`, and "WhatsApp: sent" / "delivered" / "read" under the reply. |
    | `I want to book an appointment for Saturday` | **No** reply. Dashboard → *Needs approval*. Press **Approve & send**: the reply arrives on your phone. |
    | `Do you have a wheelchair ramp?` | The honest "I don't have that information…" message on your phone; dashboard → *Escalated*, tagged *Not in knowledge base*. Write a reply and send it. |
    | A **voice note** | The notice "I can only read text messages…" and an *Escalated* item "[Sent a voice or audio message]". |

17. **Duplicate check:** in ngrok's web page (**http://127.0.0.1:4040**) find a `POST /whatsapp/webhook` request and press **Replay**. The response should say `"duplicates": 1` and **no second reply** is sent.

If all of 16–17 work, the integration is verified end to end. **Only then** is it fair to call it working.

---

## What the app does (so you can explain it)

| Your requirement | Where | How |
|---|---|---|
| 1 Webhook endpoint | `backend/meta_webhook.py` | `GET`/`POST` **`/whatsapp/webhook`** |
| 2 GET verification | `meta_webhook.verify`, `whatsapp_cloud.check_verification` | echoes `hub.challenge` only if `hub.verify_token` matches (constant-time compare); wrong/missing → 403 |
| 3 POST handling | `meta_webhook.receive` | checks the **signature first** (403 if wrong), answers **200 immediately**, processes in the background |
| 4 Extraction and sender | `whatsapp_cloud.parse_payload` | text, button/list replies, voice/photo/file/location; sender = `wa_id` (the phone number), name from the profile; reactions ignored |
| 5 Classifier + RAG | `webhook.handle_incoming_message` | the same pipeline as the demo: classify → retrieve → draft → verify |
| 6 Verified automatic replies | `outbound.send_reply` → `whatsapp_cloud.send_text` | only AI answers that passed every check; sent through the Graph API |
| 7 Uncertain → dashboard | existing verification + dashboard | held items show the draft, reasons, sources; nothing is sent |
| 8 Approved replies | `dashboard_api.send` → `outbound.send_reply` | goes to the original patient's number; failure keeps the item open |
| 9 Errors + duplicates | below | |

### Duplicate protection
Every WhatsApp message has a unique id (`wamid…`). It is stored as the **primary key** of the table `whatsapp_events` before anything else happens, so exactly one delivery can ever be processed, even if Meta's retries arrive at the same instant (tested with 48 simultaneous copies). A message that **failed** or whose processing was **interrupted by a crash** can be claimed again when Meta re-sends it, so nothing is lost.

### Errors – what the receptionist sees
| Problem | What happens |
|---|---|
| Wrong/missing signature | request refused (403); nothing processed |
| `WHATSAPP_APP_SECRET` not set | all POSTs refused (503) – the app will not trust unsigned data |
| WhatsApp rejects an automatic reply (expired token, outage…) | **nothing is claimed as sent**; the verified answer stays as a pending item with the reason ("WhatsApp rejected our access token…"); *Approve & send* retries |
| A receptionist's reply fails | the dashboard shows the reason; the item stays open |
| Reply after **24 hours** (WhatsApp's customer-service window) | the dashboard warns in advance; if sent anyway the error explains that a message template is needed |
| 5xx / rate limit | retried up to 3 times; connection errors are retried; a **timeout waiting for an answer is never retried** (the message may already have been sent) |
| WhatsApp later reports `failed` for a message it accepted | the message is marked ⚠ *Not delivered*; an automatic reply is handed back to a person |
| The app crashes while processing | marked *failed* at next start, visible at `/api/whatsapp/status`, re-processed if Meta re-sends it |

### Secrets and personal data
* Every secret is read **only** from environment variables (`.env`). `.env.example` contains the variable names and **no values**.
* Secrets never reach the browser: the web pages contain no token (a test scans every file); `/api/meta` and `/api/whatsapp/status` return only booleans and the **names** of missing settings.
* Secrets are never stored in the database (a test searches the database file for them).
* **Logs:** every log line is scrubbed of the configured secrets (and anything that looks like a Meta token); phone numbers appear only as `••••1234`; message text is never logged.
* The access token is sent only in the `Authorization` header, never in a URL.

## Troubleshooting

| Symptom | Likely cause → fix |
|---|---|
| Meta says **"The callback URL or verify token couldn't be validated"** | (a) the app isn't running; (b) `WHATSAPP_MODE` isn't `cloud` (the endpoint answers 409); (c) the token in Meta differs from `.env` (even a trailing space); (d) the tunnel is down/URL changed; (e) you forgot `/whatsapp/webhook` at the end. Run `python -m backend.whatsapp_check --probe <url>` to see which. Open ngrok's page (http://127.0.0.1:4040) to see what Meta actually sent. |
| Verified, but **no messages arrive** | You didn't subscribe to **`messages`** (step 14); or you are messaging a different number than the one whose *Phone number ID* is in `.env` (the app logs "different WhatsApp number" and ignores it); or your number isn't in `WHATSAPP_ALLOWED_SENDERS`. |
| Messages arrive, app answers **403 "Invalid signature"** (ngrok page) | `WHATSAPP_APP_SECRET` is wrong. It must be the **App secret of the same app** that owns the webhook. |
| Item appears in the dashboard but **the reply never reaches the phone** | Open the item → the reason is shown. Common: **expired token** (temporary tokens last ~24 h – generate a new one, update `.env`, restart); **131030** the number isn't on the test number's recipient list (step 4); **131047** more than 24 hours since the patient wrote. |
| Dashboard won't open on the ngrok address | By design (step 11). Use http://127.0.0.1:8000/dashboard/. |
| Everything worked yesterday, not today | Free ngrok URL changed → update the Callback URL in Meta. Temporary access token expired. |
| Want to go back to the demo | Set `WHATSAPP_MODE=simulated` in `.env`, restart. The simulated chat, sample conversations and reset button work again. |

While in `cloud` mode the **simulated chat, "Load sample conversations" and "Reset all demo data" are switched off**, so demo numbers can never be messaged and real patient conversations can never be wiped by accident. A demo conversation is never sent to a real phone, even in cloud mode.

## Before real patients use it

This setup uses Meta's free **test number**. For real patients you will additionally need (check Meta's current requirements – they change):

* a verified Meta business and your own WhatsApp Business phone number, with an approved display name;
* a **permanent** access token (Part B, step 8) and a payment method on the WhatsApp Business account;
* **message templates** approved by Meta, to contact a patient more than 24 hours after their last message;
* **proper hosting** (HTTPS on a real domain, restarts on crash) instead of a laptop tunnel;
* **a login for the dashboard** – it has none today, which is why it is blocked from the internet;
* legal advice on patient data and consent (India's DPDP Act), and a decision about how long messages are kept.

## What has and has not been tested

| Tested (automatically – `python -m pytest tests/test_whatsapp_cloud.py tests/test_meta_flow.py tests/test_graph_http.py`) | **Not** tested – needs your Meta account |
|---|---|
| signature check, including a published HMAC test vector; handshake; every message type; duplicates (including 48 at once); crash recovery; failed deliveries; 24-hour window; delivery statuses; the tunnel guard; no secrets in database/logs/pages; the request our code sends (over a real local socket) | that **Meta's servers accept our requests** and send payloads exactly like the samples; the exact wording of Meta's dashboard; real error responses; real delivery to a phone; the 24-hour behaviour; rate limits |
