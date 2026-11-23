# Answer verification and routing

**Nothing the AI writes reaches a patient until code has checked it.** If it passes, it is sent and recorded. If it fails, it is *not* sent: it becomes a pending item for the receptionist, who can approve, edit or reject it.

```
 AI draft
    │
    ▼
 VERIFY (plain code – the AI never grades its own answer)
    │
    ├── all checks pass ────────► send via outbound.send_reply ──► saved in the conversation
    │                              (the send gate re-checks the verdict)   with its sources + "verified"
    │
    └── any check fails ────────► NOT sent
                                   └─► pending item in the dashboard
                                        original message · AI draft · why it was held ·
                                        retrieved sources · every check · activity timeline
                                        └─► receptionist: APPROVE  ·  EDIT  ·  REJECT
                                                          └─► only then is anything sent
```

Why code and not "ask the AI if it's right"? A model that invented a price will usually believe the price is fine. Every check below is a pattern, a lookup in the clinic's knowledge base, or arithmetic – deterministic and testable.

## The checks (`backend/validator.py`)

Each check has a **severity**: `block` (a hard failure → the message is *escalated*) or `warn` (a soft failure → *needs approval*).

### 1. Is there a relevant source?
| Check | Sev. | Passes when |
|---|---|---|
| `facts_supported` | block | at least one retrieved knowledge entry scores ≥ 0.5 (otherwise the patient is told "I don't have that information" and it is forwarded) |
| `sources_cited` | block | the answer names the entries it came from, every one was really retrieved, and none is a weak match |

### 2. Unsupported price or doctor name?
| Check | Sev. | Passes when |
|---|---|---|
| `prices_supported` | block | every amount of money (₹4,000 · Rs 4000 · "costs 5000" · "5,000 rupees") appears in the entries the answer cites. **A price repeated from the patient's own message does not count.** |
| `doctors_supported` | block | every "Dr. …" is a real doctor at the clinic, and is mentioned in the cited entries (naming Dr. Neha when only a root-canal entry was used fails) |
| `numbers_grounded` | block | every number (times, phone, years…) appears in a source or the patient's message |
| `links_grounded` | block | every link and email address appears in a source |
| `no_unsupported_claims` | block | no "discount", "free", "guaranteed", "painless"… unless the clinic's information says so |

### 3. Claims an appointment is available, without a calendar?
| Check | Sev. | Passes when |
|---|---|---|
| `no_appointment_claims` | block | the answer does not say a slot is available/open/free, that the appointment is confirmed/booked, "I've booked you", "we can see you today", "see you on Saturday"… |

There is **no calendar connected**, so the assistant can never know whether a slot is free. It may say the reception team *will* confirm ("Our reception team will confirm the exact slot with you") and may quote a doctor's general weekly schedule from the knowledge base ("Available: Tuesday, Thursday, 2:00 PM to 8:00 PM"). Appointment requests are additionally always held for a receptionist.

### 4. Medical diagnosis or medicine?
| Check | Sev. | Passes when |
|---|---|---|
| `no_medical_advice` | block | no medicine or dosage wording (ibuprofen, antibiotic, tablet, "dose", "prescribe"…) unless the clinic's own entry says it |
| `no_diagnosis` | block | nothing like "you probably have gingivitis", "it looks like an infection", "your gums are inflamed" |
| `no_treatment_advice` | block | nothing like "you need a root canal", "I recommend…", "you should rinse with salt water" |

Questions *from patients* about symptoms or medicine never reach the model at all: they are escalated by topic (`medical_advice`, `emergency`).

### 5. Is it valid and complete?
| Check | Sev. | Passes when |
|---|---|---|
| `has_draft` | block | there is a reply |
| `well_formed` | block | no `{placeholders}`, `[Insert…]`, `<tags>`, TODO, leaked `SOURCES:` / `treatment:root_canal` / "as an AI language model" |
| `not_truncated` | block | (model answers) the reply doesn't stop mid-sentence. A reply the API reports as cut off at its token limit is discarded outright |
| `covers_question` | warn | every topic asked about is actually answered: the price of **each treatment named**, the clinic hours, the address, the phone number, a doctor's name, how to pay |
| `length_ok` | warn | 20 – 900 characters for a reply written by the AI model; up to 1,600 for a reply assembled from the clinic's own entries (a message with several questions needs a long reply) |
| `language_ok` | warn | the patient wrote in English or Roman-script Hinglish (Devanagari goes to a person) |
| `plain_whatsapp_text` | warn | no markdown headings / **bold** / links |
| `intent_confident` | warn | the topic was understood with ≥ 70% confidence |
| `doctor_exists` | warn | a doctor the *patient* names ("Is Dr. Sharma available?") is in the clinic's list of doctors; otherwise a person replies |
| `no_prior_claim` | warn | the patient does not quote an earlier promise or price ("you told me yesterday…", "please honour that"): the assistant cannot know what staff said, so a person replies |

Also in routing: a *weak* sign of a health problem (the word "bleeding" or "fever" in a price question) never becomes the topic of the reply, but it holds the reply for a person (`caution`). And a reply is marked *partial* (held, with a note to the patient) when one of the patient's question sentences is not covered by anything the assistant found, so a second question is never silently dropped.

### Routing
| Result | Condition | What happens |
|---|---|---|
| **AUTO_SEND** | every check passed, the topic is safe, auto-reply is on | sent automatically |
| **NEEDS_APPROVAL** | a `warn` check failed · appointment request · part of the question isn't in the knowledge base · auto-reply switched off · `APPROVE_MODEL_ANSWERS=true` | held; status *Needs approval* |
| **ESCALATE** | a `block` check failed · emergency, complaint or medical topic · not understood · nothing relevant in the knowledge base | held; status *Escalated* (list shows a red **Failed verification** tag when a check failed) |

In both held cases **nothing is sent to the patient**. (The one exception is the fixed notice "I'm sorry, I don't have that information… I've passed your question to our reception team", which is written by a human, not the AI.)

## When it passes

1. `outbound.send_reply` is called – the single WhatsApp sending function.
2. The message is saved in the conversation **together with the entries it was built from** (`messages.sources`) and a verification record (`messages.meta`: verified, N of N checks passed).
3. The audit trail (`inquiries.audit`) gets *verified* and *sent* events.

### The send gate
`send_reply` refuses to send an assistant message unless it is given a verdict of `AUTO_SEND` **for that exact text** (a SHA-256 fingerprint is compared). So even a future bug that edits a draft after verification, or calls the sender directly, raises `UnverifiedMessageError` instead of messaging a patient. Only a receptionist's message – a human approved or wrote it – bypasses the verdict.

## When it fails: the pending item

The receptionist sees, in the dashboard:

| They see | Where |
|---|---|
| the **original patient message** | Conversation (highlighted) |
| the **AI's draft** | Reply box (editable) – with a red "This draft failed verification" box listing the failed checks |
| the **reason it was held** | AI analysis → decision box |
| the **retrieved sources** | Sources retrieved (which were used, why each matched) |
| **every check**, grouped under the five questions above | Verification checks |
| **what has happened so far** | Activity timeline |

Actions – **nothing is sent until one of these is chosen**:

| Action | Result |
|---|---|
| **Approve & send** | sends the draft exactly as written → status *Approved & sent* |
| edit the text, then **Send edited reply** | sends the edited text → status *Replied by staff* |
| **Reject draft** (optional reason) | the draft is never sent and is kept for the record; the message stays open for the receptionist to write their own reply |
| Escalate · Close without reply | route it to a doctor/manager · close it with no reply |

**A safety net for people too.** Approving a draft that *failed* a hard check, or sending an edit that introduces a wrong price, an unknown doctor name, medicine advice or a leftover placeholder, asks the receptionist to confirm ("This reply did not pass verification: … Send it anyway?"). The override is recorded (`messages.meta.overrode_checks` and the timeline). A receptionist may freely confirm times and appointments in their own words – that is their job – so those are not flagged on human replies.

## What is recorded

| Where | What |
|---|---|
| `messages.sources` / `messages.meta` | for each AI or receptionist reply: the entries it was built from, whether it was verified automatically, who approved it, whether it was edited, which checks were overridden |
| `inquiries.checks` | every check with its group, severity, pass/fail and explanation |
| `inquiries.audit` | timeline: *verified → sent / held → approved / edited / rejected / escalated / dismissed*, who, when, and detail |
| `inquiries.rag` | the entries used, which part of the answer came from which entry, whether the draft was rejected |

## Honest limits

* **Code can't prove every sentence true.** It reliably checks prices, numbers, doctor names, links, listed claim words, availability/confirmation wording, medical wording and formatting. A model could still write an unusual false statement that matches none of those patterns (for example inventing a service the clinic doesn't offer). The defences are: the model sees only the retrieved entries, every answer must cite them, template mode is the default, and the receptionist can review every auto-sent reply in the dashboard (**Auto-replied** tab). For a cautious start, set `APPROVE_MODEL_ANSWERS=true` in `.env` so *every* model-written answer waits for a person.
* **Pattern checks are heuristics.** They err on the side of holding a message back: a harmless sentence may occasionally be flagged (a person then approves it), and a cleverly phrased claim could slip through. Each pattern has positive and negative examples in `tests/test_verification.py` – add a line when you find a miss.
* **Appointment availability is never verified**, because there is no calendar. If one is connected later, the `no_appointment_claims` check is where a calendar lookup would plug in.
* **The model path hasn't been run against the live API** (no key was available). The verification of its answers is tested with a stand-in model that writes deliberately bad answers.

## Adding a check (developers)
Add it to `text_checks` (for the text of a reply) or `run_checks` (needs the topic) in `backend/validator.py`, give it a `group` and `severity`, then add a good and a bad example in `tests/test_verification.py`. It will automatically appear, grouped, in the dashboard.


## How well does it work?

See **[QA_REPORT.md](QA_REPORT.md)**: 265 test cases, about 82% correct on the first run of messages it had not been tuned on, 32 defects found and fixed, one failure remaining, and the limits of the audit.
