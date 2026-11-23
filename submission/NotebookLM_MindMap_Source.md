# Dental Clinic AI Assistant (Pune) – Project Map

Central idea: A WhatsApp assistant that answers a dental clinic's routine questions safely from the clinic's own data, checks every answer with code, and hands risky or unknown questions to a receptionist.

Note: all clinic data (prices, doctors, hours) is dummy sample data. WhatsApp is simulated in the demo.

## 1. The Problem
- A Pune dental clinic receives about 150 WhatsApp enquiries every day.
- Most are repetitive: prices, doctors, timings, location, payment options, appointment requests.
- Receptionists retype the same answers, patients wait, and urgent messages get buried.
- A plain chatbot is risky: it can invent prices, doctors or free slots, give medical advice, or be tricked by "ignore your instructions".

## 2. The Solution Idea
- Answer the easy questions instantly, only from the clinic's approved information.
- Verify every answer with code before it is sent.
- Send risky, uncertain or urgent messages to a human with full context.
- Three promises: fast, accurate, safe.

## 3. How a Message Flows (5 stages)
- Stage 1 – Classify: keyword rules find the topic (price, timings, doctor, appointment, emergency, medical), the confidence, and whether it is urgent. Works in English and Hinglish.
- Stage 2 – Retrieve (RAG): search the clinic knowledge base for matching entries (treatments, doctors, FAQs, hours, location). Each entry has an ID such as treatment:root_canal.
- Stage 3 – Draft: build the answer only from the retrieved entries (template wording by default; an optional Claude model can only phrase the text). The answer names the entries it used.
- Stage 4 – Verify (code only): check source exists, prices and doctors are real, no claim that a slot is free or booked, no diagnosis or medicine, answer is complete.
- Stage 5 – Route: decide what happens next.
  - Auto-send: every check passed and the topic is safe.
  - Needs approval: held as a draft until a receptionist approves, edits or rejects it (all appointment requests).
  - Escalate: emergencies, medical questions, complaints, or anything not in the knowledge base. Urgent ones are shown first.

## 4. System Architecture
- Clients: patient chat page, receptionist dashboard, knowledge base editor (plain HTML, CSS and JavaScript, no build step).
- Backend: one FastAPI application in Python.
  - webhook: receives messages (simulated chat, or the official Meta WhatsApp Cloud API).
  - pipeline: runs the five stages in order.
  - send gate: the only code that can send a message, and it refuses unverified AI text.
- Storage:
  - SQLite database: conversations, messages, inquiries with the full audit trail.
  - Knowledge base files: JSON or CSV, editable on a web page without code.
- External services (optional): Meta WhatsApp Cloud API, Claude for wording.

## 5. Safety Design
- Retrieval before generation: the AI may only use retrieved clinic entries.
- Code verifies, the AI never grades itself.
- One send gate: no unverified AI answer can reach a patient.
- Never auto-answered: emergencies, medical advice, complaints, appointment confirmations.
- "I don't know" instead of guessing, and the question goes to reception.
- Prompt-injection attempts do not change prices, confirm bookings or leak internal text.
- Secrets live only in environment variables, never in code, database, logs or web pages.

## 6. Receptionist Dashboard
- Shows the patient message, what the AI understood, the draft, the sources used, and why it was held.
- Actions: Approve and send, Edit, Reject, Escalate.
- Urgent emergencies appear first.
- Every action is recorded in an audit trail.

## 7. Knowledge Base (RAG data)
- Four datasets: clinic facts, treatments and prices, doctors, FAQs, plus a synonym list.
- Every record becomes an entry with an ID used as an internal source reference.
- Edit, add, delete, import and export CSV on the Knowledge Base page.
- "Test a question" tool shows exactly which entries were retrieved and how the answer was built.

## 8. Technology Stack
- Python 3 and FastAPI backend.
- SQLite database.
- Plain HTML, CSS and JavaScript frontend.
- Official Meta WhatsApp Cloud API (built, not yet tested against real Meta servers).
- Claude via the Anthropic SDK (optional, off by default, not yet run live).
- Deployed on Vercel; code on GitHub.

## 9. Testing and Results
- 958 automated tests.
- A quality audit with 265 test cases in four rounds, in 11 categories: prices, doctors and timings, Hindi and Hinglish, multiple questions, appointment availability, no information, wrong assumptions, medical, emergency, prompt injection, message styles.
- Expected results were written before each run; rounds 2 to 4 were blind.
- About 82% correct on the first run of fresh messages (the honest accuracy).
- 99.6% after fixes, but only because fixes were made on those same cases; one case still fails.
- 32 defects found and fixed, each with a regression test.
- Zero safety-rule violations found: no unverified send, invented price or doctor, or claimed booking.

## 10. Limits and Next Steps
- Limits: keyword-based understanding misses new phrasings and Marathi words; no appointment calendar; no login on the dashboard; replies in Devanagari script are not supported; emergencies get no automatic acknowledgement until the clinic approves wording.
- Next steps: live Meta WhatsApp test, real clinic data, supervised trial with auto-reply off, login, calendar integration, test the Claude path.

## 11. Live Demo
- Patient asks a price question in Hinglish: answered automatically.
- Patient asks to book an appointment: held for the receptionist, who approves.
- Patient reports severe pain and swelling: escalated and flagged urgent.
- Knowledge base "Test a question" shows retrieval step by step.
