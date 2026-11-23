# Architecture

## The idea in one picture

```
┌────────────────────┐                                          ┌───────────────────────────┐
│  Patient chat      │   POST /api/webhook/whatsapp             │  Receptionist dashboard   │
│  (simulated        │ ───────────────┐                         │  polls every 3 seconds    │
│   WhatsApp)        │                ▼                         │  GET  /api/dashboard/...  │
│                    │   ┌────────────────────────────┐         │  POST .../send            │
│  polls every 2.5s  │   │ 1 WEBHOOK                  │         │       .../escalate        │
│  GET /api/chat/... │ ◄─┤   save message             │         │       .../dismiss         │
└────────────────────┘   │                            │ ───────►└───────────────────────────┘
                         │   pipeline.analyze():      │   shared SQLite database
                         │   2 CLASSIFIER  topic?     │   (conversations, messages, inquiries)
                         │   3 RETRIEVER   facts?     │
                         │   4 AI RESPONSE draft      │   data/*.json  = knowledge base (read-only)
                         │   5 VALIDATOR   verdict    │
                         │                            │
                         │   auto_send      → reply   │
                         │   needs_approval → queue   │
                         │   escalate       → queue   │
                         └────────────────────────────┘
```

**Technology (chosen for a beginner):** Python + FastAPI (web server), SQLite (one-file database), plain HTML/CSS/JS (no build tools). Pages refresh by *polling* (asking the server every few seconds) because it is far simpler than WebSockets and perfectly fine at clinic scale.

## A message, step by step

Patient types: *"How much is a root canal and what are your Sunday timings?"*

| # | Stage | What happens | Result |
|---|---|---|---|
| 1 | Webhook | Saves the message in `messages`, loads the previous clinic reply (for context) | message saved |
| 2 | Classifier | Normalises the text, scores keyword patterns | `clinic_timings` (1.6), `treatment_price` (1.2) → both topics, confidence 93% |
| 3 | Retriever | Matches "root canal" → treatment; intents → clinic hours | `treatment:root_canal` (1.0), `clinic:timings` (1.0) |
| 4 | AI response | Builds one section per topic from the sources, adds a booking prompt | The draft reply |
| 5 | Validator | Runs 9 checks (below). Every number (₹4,000, ₹9,000, 10:00, 8:00…) is found in a source | `auto_send` |
| 1 | Webhook | Saves an `inquiries` row (topic, confidence, draft, sources, checks, decision) and the reply as a message | patient sees the answer |

If the decision were `needs_approval` or `escalate`, nothing would be sent; the `inquiries` row appears in the dashboard queue instead.

## The five stages

### 1. Webhook – `backend/webhook.py`
A *webhook* is a URL that another system calls when something happens. With real WhatsApp, Meta calls it for each patient message. Here the chat page calls it directly. `normalize_incoming()` is the only place that needs to understand the incoming format, and `handle_incoming_message()` runs the whole flow. If the AI crashes, the message is still saved and escalated – **no patient message is ever lost**.

### 2. Classifier – `backend/classifier.py`
Keyword/regex rules with weights (no ML, so it is explainable). Output:

* `intent` – the main topic, and `intents` – every topic to answer (up to 5)
* `confidence` – 0 to 1
* `sensitive` / `urgent` – emergencies, complaints and medical questions are always sensitive
* `caution` – a *weak* sign of a health problem (just "bleeding"): it never becomes the topic of the reply, but a person must check the reply
* `entities` – e.g. `{"when": "saturday evening"}`, `script` (Roman or Devanagari)

Before scoring, one-letter typos in about 60 topic words are repaired ("prise" → "price"), and a leading "Hello doctor," is removed. Hindi/Hinglish grammar words live in `textutils.HINGLISH_FILLER`, medicine and health-condition words in `medical_terms.py` (shared with the validator). The quality audit ([QA_REPORT.md](QA_REPORT.md)) explains why each of these exists.

Topics: greeting, thanks, clinic_timings, location, treatment_price, treatment_info, doctor_info, appointment_booking, appointment_change, payment_insurance, general_faq, emergency, complaint, medical_advice, unknown.

### 3. Retriever – `backend/retriever.py`
Searches **every knowledge entry** (treatments, doctors, FAQs, clinic facts) and returns `Source` objects `{id, kind, title, text, score, file, reasons, method}`. Three simple methods are combined: precise name/keyword matches (with word roots and typo tolerance), topic matches (the clinic-hours entry for a timings question) and word overlap across all entries (with an editable synonym list). Nothing relevant → nothing returned → the assistant says it does not know. See [RAG.md](RAG.md) for details and accuracy figures.

### 4. AI response – `backend/ai_response.py` and `backend/rag.py`
* **Template mode** (default): one section per topic, built from the retrieved entries. Each section records the entry ids it used.
* **Claude mode** (when `ANTHROPIC_API_KEY` is set): the retrieved entries are the model's only context. It replies `SOURCES: <ids>` + `ANSWER: <text>`, or `NO_ANSWER`. A reply citing an entry that was not provided, or in the wrong format, is rejected. The patient's message is wrapped in `<patient_message>` tags and labelled as data to resist prompt injection. Sensitive and appointment topics never use the model.
* If nothing relevant is found, the draft is a short "I don't know, I've asked reception" message (`kind = "no_answer"`).
* The question is judged on the sentences that actually *ask* something (`textutils.question_part`), so a chatty lead-in does not matter; a question sentence that nothing found speaks to marks the draft *partial* instead of being silently dropped.
* Any model failure falls back to the template.

### 5. Verifier – `backend/validator.py`
Never trusts the draft. Every check is plain code, grouped under five questions (relevant source · prices and doctor names · appointment availability · diagnosis and medicine · valid and complete) plus routing. Full list, severities and examples: **[VERIFICATION.md](VERIFICATION.md)**.

**Decision:** any *block* failure, sensitive topic, or unknown → `escalate`. Otherwise any *warn*, appointment topic, partial answer, or auto-reply switched off → `needs_approval`. Otherwise → `auto_send`. Held answers are never sent.

**The send gate:** `outbound.send_reply` only sends an assistant message that carries an `AUTO_SEND` verdict for that exact text (fingerprint compared); anything else raises `UnverifiedMessageError`. Receptionist replies are the only other path, and they are human-approved.

## WhatsApp: simulated or the real Cloud API

`WHATSAPP_MODE` picks how messages arrive and leave; **everything in between (classify → retrieve → draft → verify → route) is identical**.

```
 simulated:  chat page ─POST /api/webhook/whatsapp─►  webhook.handle_incoming_message ─► outbound.send_reply ─► saved; chat page polls
 cloud:      Meta ─POST /whatsapp/webhook (signed)─►  meta_webhook: verify signature · claim message id · answer 200
                         └─ background ─► webhook.handle_incoming_message ─► outbound.send_reply ─► Graph API ─► patient's phone
                                                                                      └ held items → dashboard → receptionist → outbound.send_reply
```

| File | Job |
|---|---|
| `backend/meta_webhook.py` | the URLs Meta calls: GET handshake, POST events (signature → 200 → background), delivery statuses, `/api/whatsapp/status`, `/healthz` |
| `backend/whatsapp_cloud.py` | signature check, handshake check, payload parsing (text, buttons, media, statuses), `send_text` with retries and plain-English errors, secret redaction |
| `backend/outbound.py` | **the one send gate**: AI messages need a verdict for that exact text; **delivers first, records second** (a reply is saved as sent only if WhatsApp accepted it); a demo conversation never reaches a real phone |
| `backend/database.py` | `whatsapp_events` (one row per incoming message id = duplicate protection), `messages.wa_id/delivery`, `conversations.channel` (`simulated` / `whatsapp`) |
| `backend/main.py` | the tunnel guard: requests carrying proxy headers may reach only the webhook and `/healthz` |
| `backend/whatsapp_check.py` | the live connection test you run yourself |

Setup and troubleshooting: [WHATSAPP_CLOUD_SETUP.md](WHATSAPP_CLOUD_SETUP.md).

## Data model (SQLite – `clinic_ai.db`)

| Table | Holds |
|---|---|
| `conversations` | one per phone number |
| `messages` | every chat bubble: `patient`, `assistant` (automatic) or `receptionist`; replies also keep the **entries they came from** (`sources`) and how they were approved (`meta`) |
| `inquiries` | one per patient message: topic(s), confidence, urgent, draft, mode, sources (each with score, match reasons and whether it was **used**), checks, reasons, decision, **status**, final reply, who resolved it, `audit` (timeline of who did what), and `rag` (the entries the answer was built from, which part came from where, whether it was answerable) |
| `settings` | the auto-reply switch |

`status` values: `auto_replied` · `pending_approval` · `escalated` · `approved` (AI draft sent unchanged) · `replied` (staff edited/wrote it) · `dismissed`.

## API summary (full interactive docs at `/docs`)

| Method & path | Used by | Purpose |
|---|---|---|
| `POST /api/webhook/whatsapp` | patient chat | submit a patient message |
| `GET /api/chat/{phone}/messages?after_id=` | patient chat | new messages + "waiting for reception" notice |
| `GET /api/dashboard/stats` | dashboard | counts, auto-reply rate, time saved |
| `GET /api/dashboard/inquiries?status=` | dashboard | list (`open`, `pending`, `escalated`, `auto`, `resolved`, `all`) |
| `GET /api/dashboard/inquiries/{id}` | dashboard | full detail incl. thread, sources, checks |
| `POST /api/dashboard/inquiries/{id}/send` | dashboard | **approve** the draft or send an **edited** reply (needs `acknowledge` if it fails the checks) |
| `POST /api/dashboard/inquiries/{id}/reject` | dashboard | **reject** the AI draft – it is never sent |
| `POST /api/dashboard/inquiries/{id}/escalate` · `/dismiss` | dashboard | route or close |
| `GET/POST /api/dashboard/settings` | dashboard | auto-reply on/off |
| `POST /api/dashboard/seed-demo` · `/reset` | dashboard | demo tools |
| `GET /api/meta` | all pages | clinic name, dummy-data count, AI mode, WhatsApp mode (booleans only, never secrets) |
| `GET/POST /whatsapp/webhook` | **Meta** | verification handshake; signed incoming events (Cloud mode only) |
| `GET /api/whatsapp/status` | dashboard | is WhatsApp configured? names of missing settings, event counts |
| `GET /api/kb/summary` · `GET /api/kb/{dataset}` | knowledge base page | datasets (clinic, treatments, doctors, faqs), counts, warnings |
| `POST /api/kb/{dataset}` · `PUT /api/kb/{dataset}/{id}` · `DELETE …` · `PUT /api/kb/clinic` | knowledge base page | add / change / remove entries (validated, backed up) |
| `GET /api/kb/{dataset}/export.csv` · `POST /api/kb/{dataset}/import` | knowledge base page | spreadsheet export / import (preview with `dry_run`) |
| `POST /api/kb/ask` | knowledge base page | trace one question: retrieved entries, model context, answer, decision (saves nothing) |
| `GET /api/kb/gaps` | knowledge base page | recent questions the knowledge base could not answer |

## Design decisions

* **Safe failure everywhere.** When unsure, the assistant hands over to a person rather than guessing.
* **Explainable.** The dashboard shows topic, confidence, sources and each check, so staff can trust (or correct) the AI.
* **The AI pipeline is pure.** `pipeline.analyze()` does no I/O, so it is easy to test (`tests/`).
* **One place for outbound messages.** `outbound.send_reply()` is the only code that "sends" – swapping in real WhatsApp touches one function.
* **No secrets in code.** Settings come from environment variables / `.env`.
