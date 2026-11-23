# Assignment 1 – Advance track: what to submit on Nexus

**Deadline: Nexus closes 11:59 PM on 23 November.** Submit by the end of class.

| # | Submission | Format | Status | File / what to do |
|---|---|---|---|---|
| 1 | Live URL of the web app | Link | **You: deploy (10 min)** | App is ready to deploy – steps below |
| 2 | Loom walkthrough (2–3 min) | Loom link | **You: record** | Outline below |
| 3 | Document showing the system design | PDF | **Ready** | `System_Design_Document.pdf` |
| 4 | Reflections document | PDF | **Needs your 5 edits** | `Reflections_EDIT_ME.docx` → fill yellow parts → Download as PDF |
| – | The "links document" (the NOTE) | Google Doc, view access for all | **You: create (5 min)** | Template below |

Extra material (optional but strong): `Dental_Clinic_AI_Project_Report.pdf` (12-page report), `Dental_Clinic_AI_Workbook.xlsx` (testing workbook), `Dental_Clinic_AI_Source.zip`, `screenshots/`.

---
## 1 · Deploy the live URL (free, about 10 minutes)

The app is ready: it includes a `Dockerfile` and `render.yaml`, and a public-demo mode (dummy data only, no real WhatsApp).

1. Make a GitHub account/repo (public or private), e.g. `dental-clinic-ai`. Upload the project folder **without** `.venv`, `clinic_ai.db`, `.env` (the included `.gitignore` already excludes them). Easiest: GitHub Desktop → "Add existing repository" → Publish. Or on github.com: *New repository* → *uploading an existing file* and drag the files.
2. Go to https://render.com → sign up with GitHub → **New +** → **Blueprint** → choose the repo → **Apply**. (It reads `render.yaml`.)
3. Wait for the build (3–5 min). Open the URL Render shows, e.g. `https://dental-clinic-ai.onrender.com`.
4. Check: `…/chat/` (patient chat), `…/dashboard/` (should already show 8 sample conversations), `…/knowledge/`, `…/healthz` shows `{"ok":true}`.
5. Submit the **base URL** (or the `/chat/` page). In the links document also list `/dashboard/`.

Notes: the free plan sleeps after ~15 min idle (first load takes ~50 s: open it once before your Loom and before submitting). Data resets on restart (it re-loads the sample conversations). The dashboard has no login, so only dummy data should be on this deployment.
Other hosts that also work with the `Dockerfile`: Railway, Fly.io, Hugging Face Spaces (Docker).

---
## 2 · Loom video (2–3 minutes) – suggested script

Open the live URL first. Follow `documentation/DEMO_SCRIPT.md` for exact messages.

| Time | Show | Say (the *what*, *why*, *how*) |
|---|---|---|
| 0:00 | Title + problem | A Pune dental clinic gets ~150 WhatsApp enquiries a day, mostly repetitive; urgent ones get buried. I built an assistant that answers the easy ones safely and hands the rest to a receptionist. |
| 0:25 | Patient chat: "root canal ka kharcha kitna hoga?" | Works in English and Hinglish. The answer comes only from the clinic's own data (dummy data here). |
| 0:50 | Chat: "Can I book Dr. Neha tomorrow 5 PM?" → Dashboard | Appointments are never auto-confirmed (no calendar). It appears as *Needs approval*: show the draft, the reason, Approve / Edit / Reject. |
| 1:20 | Dashboard: the urgent emergency item | Emergencies and medical questions are never answered automatically; urgent shown first. |
| 1:40 | Knowledge Base → "Test a question" | How it works: classify → retrieve from clinic data (RAG) → draft → **verify with code** → send or hand over. Show the entries it retrieved. |
| 2:10 | One slide/page of the System Design PDF (workflow) | The AI never grades itself: code checks prices, doctors, booking claims and medicine; one send gate. |
| 2:35 | Testing | 265 test cases, 82% correct on fresh messages first time, 32 bugs found and fixed. Honest limits: Meta live connection and Claude not yet tested. |

Tips: use the chat page's "Try asking" buttons; keep the dashboard open in a second tab; don't read the screen, explain choices.

---
## 4 · Reflections
Open `Reflections_EDIT_ME.docx` in Google Docs (Drive → New → File upload → open with Google Docs). Replace every **yellow** part (your name, what you did in Hackathon 1, and 1–2 sentences about how your prompting changed). Delete the yellow instruction line. File → Download → PDF.

---
## The links document (Google Doc, "Anyone with the link – Viewer")

Create a Google Doc titled **"Dental Clinic AI – Submission links"** and paste:

```
Dental Clinic AI Assistant – Pune  (Assignment 1, Advance track)
Name: ________   Batch/Roll no.: ________

1. Live URL:            <your Render URL>        (dashboard: <URL>/dashboard/ · knowledge base: <URL>/knowledge/)
2. Loom walkthrough:    <Loom link>
3. System design PDF:   <Google Drive link, anyone with the link can view>
4. Reflections PDF:     <Google Drive link, anyone with the link can view>

Extras:
 - Project report (12 pages):  <Drive link>
 - Testing workbook (.xlsx):   <Drive link>
 - Source code (ZIP / GitHub): <link>
```
Upload each PDF to Google Drive → right-click → Share → General access: **Anyone with the link → Viewer** → copy link. Then Share the Google Doc the same way and paste **that one link** into Nexus (the NOTE says: attach the link of your work with view-for-all access).

Final check: open every link in a private/incognito window.
