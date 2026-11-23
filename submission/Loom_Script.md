# Loom script (about 3 minutes)

Assignment asks for: *what* you built, *why*, and *how* (2–3 min). Plan: intro → mind map (structure, architecture, how it works) → live demo → close.
Speak at a relaxed pace (~140 words/minute). The bold text is what to SAY; the arrows are what to SHOW.

## Before you press record (3 minutes)
1. Open tab 1: NotebookLM mind map (all branches collapsed except the centre). Tab 2: https://dental-clinic-ai-steel.vercel.app/chat/ Tab 3: https://dental-clinic-ai-steel.vercel.app/dashboard/ Tab 4: .../knowledge/
2. Load tab 2 and 3 once so the site is awake. Do NOT click "Reset all demo data".
3. Record the screen + camera in Loom. Close notifications.

## 0:00 – Intro (≈20 s) → show the centre of the mind map
**"Hi, I'm [your name]. This is my Dental Clinic AI Assistant for a clinic in Pune. The clinic gets around 150 WhatsApp messages a day, mostly the same questions about prices, timings and doctors, and urgent messages get buried. My assistant answers the routine ones instantly and safely, and hands anything risky to a receptionist. Let me show you how I built it, then a live demo."**

## 0:20 – Structure and architecture (≈70 s) → click the mind map branches in this order
→ Branch "How a Message Flows":
**"Every message goes through five stages. One: classify, simple keyword rules work out the topic and whether it's urgent, in English and Hinglish. Two: retrieve, this is the RAG part, it searches the clinic's own data, prices, doctors, FAQs. Three: draft, the answer is built only from those entries. Four: verify, and this is the key design choice, plain code checks every price, doctor name, and blocks any claim that a slot is booked or any medical advice. The AI never grades itself. Five: route."**

→ Branch "Route" / "Safety Design":
**"Route means: if every check passes it's sent automatically. Appointments always wait for a receptionist. Emergencies, medical questions and anything not in the clinic's data are escalated, and the patient is told 'I don't know, I've asked reception' rather than getting a guess."**

→ Branch "System Architecture":
**"Technically it's one FastAPI app in Python, a SQLite database for the audit trail, the clinic data in editable JSON files, and plain HTML pages with no build step. There's one send gate, so no unverified AI answer can ever reach a patient. It's built for the official WhatsApp Cloud API, but today's demo uses simulated WhatsApp."**

## 1:30 – Live demo (≈90 s) → switch to the live site
1. → Tab 2 (chat). Click/type **"root canal ka kharcha kitna hoga?"**
   **"A patient asks in Hinglish. It answers instantly with the price range from the clinic's data."**
2. Type **"I want to book an appointment for braces this Saturday evening"**
   **"Now a booking. Notice the patient gets nothing yet, because there's no calendar, so the AI is not allowed to confirm a slot."**
3. → Tab 3 (dashboard). Click that item (Needs approval).
   **"Here's the receptionist's view: what the patient said, what the AI understood, why it was held, and the draft. She can approve, edit or reject."** Click **Approve & send**, then flip to the chat: **"and now the patient sees the reply."**
4. Back in dashboard, click the red urgent item ("Severe pain and swelling…").
   **"An emergency is never answered automatically. It's flagged urgent and shown first for a person."**
5. → Tab 4 (Knowledge Base → Test a question). Ask **"How much is a root canal and are you open on Sunday?"**
   **"This shows exactly which clinic entries were retrieved and how the answer was built, so nothing is a black box."**

## 2:40 – Close (≈20 s) → back to the mind map "Testing and Results"
**"I tested it with 265 test cases. The honest number is about 82% correct the first time on messages it hadn't been tuned on; after fixing 32 bugs it passes 99.6% of them, but that's on the same cases, so I don't call it 100%. What's left: a live test with real WhatsApp and real clinic data, and a trial where a receptionist approves every reply. Thanks for watching."**

---
## If you run short of time
Cut demo step 5 (knowledge base) and shorten the architecture paragraph. If you run long, speak faster in the architecture part, not the demo.

## Questions you might be asked (short answers)
- **Why not just use ChatGPT/Claude directly?** It can invent prices or promise slots. Here facts come only from the clinic's data and code verifies them.
- **Why code-based verification?** A model that writes an answer can repeat its own mistake confidently.
- **Why no vector database?** The clinic has about 40 entries; simple retrieval passed the tests. I'd add embeddings when the data grows.
- **Is it connected to real WhatsApp?** The integration is built with the official API but not yet tested against Meta; the demo is simulated.
- **What's the accuracy?** ~82% on fresh test messages; 99.6% after fixes on tuned-on messages; one known failure.
- **What did you learn?** Testing finds problems a demo hides; safety rules belong in code, not just prompts.
