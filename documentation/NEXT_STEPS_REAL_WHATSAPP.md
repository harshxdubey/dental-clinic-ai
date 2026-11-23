# Next steps: from prototype to a real clinic

## Where the WhatsApp integration stands

The **official Meta WhatsApp Cloud API** integration is **built**: webhook verification, signature checking, incoming messages, replies through the Graph API, approved-reply delivery, duplicate protection and error handling. How to configure it: **[WHATSAPP_CLOUD_SETUP.md](WHATSAPP_CLOUD_SETUP.md)**.

**It is NOT yet verified against Meta's real servers.** It was tested with signed sample payloads, a fake Graph API and a local HTTP server, because no Meta account was available while building it. Part E of the setup guide is the live test. Until it passes on a real phone, treat it as unproven. `WHATSAPP_MODE=simulated` (the default) keeps the demo working with no Meta account.

## Still to do before real patients use it

| Area | Why / what |
|---|---|
| **Run the live test** | Setup guide, Part E. Fix whatever Meta's real behaviour reveals (labels, payload details, error codes). |
| **Dashboard login** | The dashboard has **no authentication**. It is blocked from the internet by a guard, which means staff can only use it on the machine running the app. Real use needs per-receptionist login and proper hosting. |
| **Real clinic data** | Replace all dummy data (Knowledge Base page); have the owner approve prices and FAQ wording. |
| **Your own WhatsApp number** | Meta business verification, a registered number, an approved display name, a payment method. Requirements change – check Meta's current documentation. |
| **Permanent access token** | The temporary token expires in about 24 hours (setup guide, Part B step 8). |
| **Message templates** | WhatsApp only allows a free-form reply within 24 hours of the patient's last message. To contact someone later you need a Meta-approved template; the app currently shows a warning instead of sending one. |
| **Hosting** | HTTPS on a real domain, restart on crash, backups, monitoring – instead of a laptop and a tunnel. |
| **Privacy & consent** | Patient messages are personal (sometimes health) data. India's Digital Personal Data Protection Act applies – take legal advice on consent, retention and access. |
| **Medical safety** | Keep emergencies, complaints and medical questions escalated; consider an out-of-hours notice. |
| **Human review period** | Start with **auto-reply off** (or `APPROVE_MODEL_ANSWERS=true`), review accuracy for a few weeks, then enable auto-reply for the safest topics. |
| **Real database** | SQLite is fine for a demo. Production: PostgreSQL with backups. |
| **Appointments** | Connect the clinic's real calendar so availability can be checked (the verifier currently blocks all availability claims because there is no calendar). |
| **Media** | Voice notes, photos and files are passed to the receptionist as "[Sent a voice message]"; to view them the receptionist must open the WhatsApp Business app. Downloading them via the media API is a possible improvement. |

## Quality improvements worth considering
* Reply in Hindi/Marathi (Devanagari) – those messages currently go to a person.
* Longer conversation memory (collecting name, date and treatment over several messages).
* Embedding-based retrieval once the knowledge base grows to hundreds of items.
* An evaluation set of 100+ real, anonymised messages, run after every change.
* Staff feedback buttons ("good answer" / "wrong") to find gaps in the knowledge base.
* Dashboard analytics: busiest hours, most common topics (the data is already in the `inquiries` table).
