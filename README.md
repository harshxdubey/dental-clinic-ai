# Dental Clinic AI Assistant – Pune

A working prototype of an AI assistant for a dental clinic that receives ~150 WhatsApp enquiries a day.
It reads each message, works out what the patient wants, finds the answer in the clinic's own information,
double-checks it, and then either **replies automatically** or **hands the message to the receptionist**.

> **Please read – what is real and what is not**
> * **WhatsApp is simulated by default.** The "patient chat" page imitates WhatsApp; nothing is sent over the real WhatsApp network.
> * **The official Meta WhatsApp Cloud API integration is built but NOT yet verified against Meta's real servers.** It is tested with signed sample webhooks, a fake Graph API and a local HTTP server (169 automated tests), but I had no Meta account to try it on. Follow [documentation/WHATSAPP_CLOUD_SETUP.md](documentation/WHATSAPP_CLOUD_SETUP.md); its Part E is the live test that decides whether it works. Switching back to the demo is one line in `.env`.
> * **All clinic information is dummy sample data** (clinic, doctors, prices, address, phone number). Every entry is labelled "Sample data" and a "Dummy data" badge is shown on every page until you replace it – see [documentation/KNOWLEDGE_BASE.md](documentation/KNOWLEDGE_BASE.md).
> * **The dashboard has no login.** It is for local demos only – do not put it on the public internet.
> * The AI runs in **template mode** by default (free, offline, no account needed). Optionally, Claude can write the wording – see [Using Claude](#using-claude-optional).

## What you get

| Page | URL | What it is |
|---|---|---|
| Patient chat | http://127.0.0.1:8000/chat/ | A WhatsApp-style window. Type as a patient and watch the assistant reply. |
| Receptionist dashboard | http://127.0.0.1:8000/dashboard/ | Every message, the AI's answer, the **knowledge entries it was built from**, the safety checks, **pending approvals** and **escalated** conversations. |
| Knowledge base | http://127.0.0.1:8000/knowledge/ | **Add, edit and delete** prices, doctors, FAQs and clinic details with forms (or via spreadsheet), and **test any question** to see what it retrieves. No code needed. |
| API docs | http://127.0.0.1:8000/docs | Auto-generated documentation of the backend. |

## Quick start (about 3 minutes)

You need **Python 3.10 or newer** (check with `python3 --version`). This build was developed and tested on Python 3.15.

```bash
cd Dental-Clinic-AI
python3 -m venv .venv
```

Activate the virtual environment (a private folder for this project's packages):

```bash
source .venv/bin/activate
```

On Windows use `.venv\Scripts\activate` instead.

```bash
pip install -r requirements.txt
```

```bash
python run.py
```

Now open **http://127.0.0.1:8000** in your browser. Press `Ctrl+C` in the terminal to stop.

Next time you only need `source .venv/bin/activate` and `python run.py`.

## Try it – a 2-minute demo

1. Open the **dashboard** and the **patient chat** in two browser tabs.
2. In the dashboard choose **Demo tools → Load sample conversations** (or just use the chat).
3. In the chat, tap the example questions on the left. Watch what happens:

| Patient types | What the assistant does | Why |
|---|---|---|
| "What are your timings on Sunday?" | Replies instantly | Safe, factual, found in the clinic info |
| "root canal ka kharcha kitna hoga?" | Replies instantly with the price range | Understands Hinglish; price comes from `treatments.json` |
| "I want to book an appointment for Saturday evening" | Waits in **Pending approval** | A person must confirm the slot |
| "Severe pain and swelling, I can't sleep" | **Escalated**, marked **Urgent** | Possible emergency – a human must act |
| "I was overcharged and want a refund" | **Escalated** | Complaints are never automated |
| "Do you have a wheelchair ramp?" | Tells the patient "I don't have that information" and **forwards it to reception** | Not in the knowledge base – the assistant never guesses |

4. In the dashboard click a message to see the AI's **topic, confidence, the knowledge entries it was built from (and why each matched) and safety checks**. Edit the suggested reply and press **Approve & send** – it appears in the patient chat, labelled "Reception team".
5. Try the **AI auto-reply** switch (top right). When it is off, *every* reply waits for approval.
   Held items show a **Reject draft** button next to approve/edit. To see verification catch a bad answer, run `python -m pytest tests/test_verification.py -v` – it feeds deliberately wrong answers (invented price, unknown doctor, "slot available tomorrow", diagnosis, cut-off text…) through the real pipeline.

6. Open the **Knowledge Base** page: add an FAQ for the wheelchair question, then use **Test a question** – it is now answered, with the new entry shown as the source.

More ideas to try are in [documentation/DEMO_SCRIPT.md](documentation/DEMO_SCRIPT.md).

## How it works

```
 Patient chat ──► WEBHOOK ──► CLASSIFIER ──► RETRIEVER ──► AI RESPONSE ──► VALIDATOR ──┬─► auto-reply
 (simulated        receives     what is the    find facts     draft an         check it    ├─► needs approval ─┐
  WhatsApp)        the message  question?      in data/*.json answer from      before it   └─► escalate ───────┤
                                                              those facts      is sent                         ▼
                                                                                              Receptionist dashboard
```

| Stage | File | Job |
|---|---|---|
| 1. Webhook | `backend/webhook.py` | Receives the message, saves it, runs the pipeline, saves the result |
| 2. Classifier | `backend/classifier.py` | Keyword rules decide the topic (price, timings, doctor, appointment, emergency…) and how sure it is |
| 3. Retriever | `backend/retriever.py` | Searches **every** knowledge entry (treatments, doctors, FAQs, clinic facts) and returns the best matches, each with a score and the reasons it matched |
| 4. AI response | `backend/ai_response.py`, `backend/rag.py` | Writes the answer using **only** those entries (templates, or Claude if enabled) and records which entries it used. If nothing relevant was found it says so instead of guessing |
| 5. Verifier | `backend/validator.py` | **Code-based** checks (the AI never grades itself): a relevant source exists and is cited · every price and doctor name is in the sources · no claim that an appointment is available or confirmed (there is no calendar) · no diagnosis or medicine advice · well formed, complete, covers the question — then decides |

The three possible outcomes:

* **Auto-reply** – every verification check passed and the topic is safe. Sent through the WhatsApp sending function and saved with the entries it came from.
* **Needs approval** – held; a person should confirm (appointments, a soft check failed, non-English text, or auto-reply switched off).
* **Escalate** – held; a person must handle it (emergency, complaint, medical question, **not in the knowledge base**, or a failed hard check such as an unsupported price or doctor name).

**A held answer is never sent.** It appears in the dashboard with the patient's message, the AI's draft, the reason it was held, the retrieved sources and every check; the receptionist can **approve, edit or reject** it, and only then is anything sent. Details: [documentation/VERIFICATION.md](documentation/VERIFICATION.md).

How retrieval and answering work, and how well they perform on test questions: [documentation/RAG.md](documentation/RAG.md). Full architecture: [documentation/ARCHITECTURE.md](documentation/ARCHITECTURE.md).

## Project structure

```
Dental-Clinic-AI/
├── data/                       The clinic knowledge base (DUMMY data) – JSON or CSV, edit by hand or via the web page
│   ├── clinic_facts.json         name, address, timings, payments, policies
│   ├── treatments.json           treatments, prices, durations
│   ├── doctors.json              doctors, specialities, availability
│   ├── faqs.json                 common questions and answers
│   ├── synonyms.json             words that mean the same ("cost" = "price")
│   └── backups/                  previous versions, saved automatically before every change
├── backend/                    Python (FastAPI)
│   ├── webhook.py                1. receives patient messages
│   ├── classifier.py             2. what is the patient asking?
│   ├── retriever.py              3. finds the relevant knowledge entries
│   ├── ai_response.py            4. drafts the answer from those entries (+ rag.py: the model prompt & citations)
│   ├── validator.py              5. safety checks + routing decision
│   ├── pipeline.py               runs stages 2–5 in order
│   ├── knowledge.py, kbstore.py  load / validate / save the knowledge base (JSON + CSV)
│   ├── kb_api.py, explain.py     API for the Knowledge Base page; "show your work" trace
│   ├── outbound.py               the send gate: delivers replies (simulated, or via the Cloud API)
│   ├── meta_webhook.py           the URL Meta calls: GET verification + signed POST (WhatsApp Cloud API)
│   ├── whatsapp_cloud.py         Cloud API client: signature, parsing, sending, errors, log redaction
│   ├── whatsapp_check.py         python -m backend.whatsapp_check  (your live connection test)
│   ├── dashboard_api.py          API used by the dashboard
│   ├── database.py               SQLite storage
│   ├── config.py, textutils.py   settings and small helpers
│   └── main.py                   the web app
├── frontend/                   Plain HTML/CSS/JavaScript (no build step)
│   ├── index.html                home page
│   ├── patient_chat/             the WhatsApp-style chat
│   ├── reception_dashboard/      the receptionist dashboard
│   ├── knowledge_base/           add/edit information, import/export CSV, test a question
│   └── shared/                   colours, fonts and small helpers shared by all pages
├── tests/                      automated tests (run with pytest); retrieval_cases.py = the question test set; test_qa_*.py = the quality audit
├── qa/                         the quality audit: 265 test cases with expected results, the runner, the report generator
├── documentation/              verification, RAG, architecture, knowledge-base guide, demo script, next steps
├── .env.example                optional settings
├── requirements.txt            Python packages
└── run.py                      start here: python run.py
```

## Add or update clinic information (no code)

Open **http://127.0.0.1:8000/knowledge/**.

* **Forms:** add, edit or delete treatments, doctors, FAQs and the clinic details. A mistake (e.g. lowest price higher than highest) is refused with a clear message; the previous version of the file is saved to `data/backups/`.
* **Spreadsheet:** **Export CSV** → edit in Excel or Google Sheets → **Import CSV** (with a preview of what will change).
* **Files:** the JSON/CSV files in `data/` can also be edited by hand. The app reads `.json`, or `.csv` if there is no `.json`.
* **Test a question:** the second tab shows exactly what the assistant retrieves and how it answers. Also available in the terminal: `python -m backend.explain "How much is a root canal?"`.
* **Questions it couldn't answer** are listed on the same page, with an **Add as FAQ** button.

Changes take effect immediately – no restart. Full guide: [documentation/KNOWLEDGE_BASE.md](documentation/KNOWLEDGE_BASE.md).

Other things you can change without much code: colours in `frontend/shared/theme.css`; words the assistant treats as the same in `data/synonyms.json`; keyword patterns in `backend/classifier.py`. Backend code changes need a restart (`Ctrl+C`, then `python run.py`).

Optional settings go in a `.env` file (copy `.env.example` to `.env`). The app runs fine without one.

## Real WhatsApp (optional – Meta Cloud API)

Two modes, chosen by `WHATSAPP_MODE` in `.env`:

| Mode | What it is | Needs |
|---|---|---|
| `simulated` (default) | the demo chat page imitates WhatsApp | nothing |
| `cloud` | the **official** Meta WhatsApp Cloud API: real patients write to your WhatsApp number, replies go to their phones | a Meta developer account, a test number, a tunnel (ngrok) – see the guide |

What the Cloud mode adds: a webhook at `/whatsapp/webhook` (GET handshake with your verify token; POST checked against Meta's `X-Hub-Signature-256` signature), message extraction, the same classify → RAG → verify pipeline, **verified answers sent automatically through the Graph API**, uncertain ones held in the dashboard until a receptionist approves them, **duplicate protection** (Meta re-sends failed deliveries for up to 36 hours), and clear handling of every failure (expired token, 24-hour window, outages).

* **Secrets** live only in `.env` (see `.env.example`, which contains names but no values). They are never in the web pages, the database, or the logs.
* **The dashboard still has no login**, so in Cloud mode any request that arrives through a tunnel is refused unless it is for the webhook. Use the dashboard on the laptop at `http://127.0.0.1:8000/dashboard/`.
* In Cloud mode the simulated chat and the demo tools (sample conversations, reset) are switched off, so demo numbers are never messaged and real conversations can never be wiped.
* Check your setup: `python -m backend.whatsapp_check` (token) and `python -m backend.whatsapp_check --probe https://your-tunnel` (webhook, secrets).

Full step-by-step, including exactly what to click in Meta's dashboard: **[documentation/WHATSAPP_CLOUD_SETUP.md](documentation/WHATSAPP_CLOUD_SETUP.md)**.

## Using Claude (optional)

Out of the box the assistant builds answers from templates. To let Claude write the wording of ordinary answers
(prices, timings, doctors, FAQs) instead:

1. Get an API key from https://console.anthropic.com.
2. `cp .env.example .env`, then put the key after `ANTHROPIC_API_KEY=`.
3. Restart. The pages show **AI: Claude** instead of **AI: template mode**.

Claude is given **only the retrieved entries** as context, told to use nothing else, and must name the entries it used
(or reply `NO_ANSWER`, which forwards the question to reception). An answer that cites an entry it wasn't given, ignores
the required format, or fails for any reason falls back to the template answer; the validator still checks every number.
Emergencies, complaints, medical questions, greetings and appointment requests never use the model. `CLAUDE_MODEL` in
`.env` chooses the model (`claude-haiku-5-5` is the cheapest). Details: [documentation/RAG.md](documentation/RAG.md).

> **Not yet verified live.** This path is covered by automated tests that use a stand-in model (prompt contents, citation
> checking, every fallback), but it has **not been run against the real API** – no key was available while building it.
> Try it with your own key on a few questions and tell me if anything needs adjusting. Everything else was run for real.

## Run the tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

The tests use a temporary database and a temporary copy of `data/`, never call the network and never need an API key. They include a retrieval accuracy test: add a line to `tests/retrieval_cases.py` whenever the assistant retrieves the wrong thing for a real question.

## Quality audit

`python -m qa.run_qa --round all` sends 265 test messages (prices, timings, Hindi/Hinglish, several questions at once, appointment availability, unknown topics, wrong assumptions, medical questions, emergencies, prompt-injection attempts, odd message styles) through the real pipeline and compares each outcome with an expectation written *before* running it.

* **Results and every defect found/fixed: [documentation/QA_REPORT.md](documentation/QA_REPORT.md)** – about **82%** correct on the first run of messages the assistant had not been tuned on; 99.6% after the fixes, but that figure is on the cases used to drive the fixes, so it is *not* a prediction. 1 known failure remains.
* Every case's input, intent, retrieved sources, answer, verification result, routing, expected vs actual and pass/fail: [documentation/QA_CASES.md](documentation/QA_CASES.md).
* Add real reception messages as new `Case(...)` lines in `qa/` and re-run; `python -m qa.make_report` rebuilds both documents.

## Troubleshooting

| Problem | Fix |
|---|---|
| `command not found: python3` | Install Python 3.10+ from https://www.python.org/downloads/ |
| `ModuleNotFoundError: No module named 'fastapi'` | Activate the virtual environment (`source .venv/bin/activate`) and run `pip install -r requirements.txt` |
| `address already in use` | Something else uses port 8000. Add `PORT=8010` to `.env` and restart |
| Chat says "Can't reach the server" | `python run.py` is not running (or crashed – read the terminal) |
| "Knowledge base problem: data/… is not valid JSON" | A typo in a data file (often a missing comma). The message gives the line number. Restore a backup from `data/backups/` if needed |
| Meta says the callback URL/verify token "couldn't be validated" | See the troubleshooting table in [documentation/WHATSAPP_CLOUD_SETUP.md](documentation/WHATSAPP_CLOUD_SETUP.md); `python -m backend.whatsapp_check --probe <url>` finds the cause |
| An answer I expected was held back | Open it in the dashboard → **Verification checks** shows exactly which check failed and why |
| Dashboard shows nothing | Send a message in the chat, or use **Demo tools → Load sample conversations** |
| Start again from scratch | Dashboard → **Demo tools → Reset all demo data**, or delete `clinic_ai.db` |

## Limitations (honest list)

* WhatsApp is simulated unless you switch to Cloud mode, and the Cloud integration is **unverified against real Meta** until you run the live test in [documentation/WHATSAPP_CLOUD_SETUP.md](documentation/WHATSAPP_CLOUD_SETUP.md). What is still needed for real patients is in [documentation/NEXT_STEPS_REAL_WHATSAPP.md](documentation/NEXT_STEPS_REAL_WHATSAPP.md).
* No login or user accounts on the dashboard.
* Retrieval is word-based (with word roots and synonyms), not meaning-based. It scored 100% on the project's test questions, but real WhatsApp messages will find gaps – a missed question is forwarded to a person, which is the safe failure. See [documentation/RAG.md](documentation/RAG.md).
* The classifier is keyword-based. It handles English and Hinglish, but **the quality audit measured about 82% fully-correct handling on fresh messages**: unusual phrasing, new Hinglish/Marathi words and typos are the usual gaps, and they are mostly sent to a person (the safe direction). It does not reply in Hindi/Marathi script – those messages go to the receptionist. Details and the open safety decision (emergency patients get no automatic acknowledgement) are in [documentation/QA_REPORT.md](documentation/QA_REPORT.md).
* Conversation memory is minimal: it only remembers the previous reply, so a "yes please" after "Would you like to book…?" works, but longer back-and-forth does not.
* There is no real appointment calendar – bookings are always confirmed by a person.
* Prices and doctors are dummy data. The AI is only as correct as the files in `data/`.
