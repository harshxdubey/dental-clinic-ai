"""Builds submission/System_Design_Document.pdf (HTML -> Chrome PDF). Needs Playwright + Google Chrome."""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SUB = Path(__file__).resolve().parent
CSS = """
@page { size: A4; margin: 0; }
* { box-sizing: border-box; }
body { margin: 0; font-family: Arial, Helvetica, sans-serif; color: #1F2937; font-size: 10.4pt; line-height: 1.45; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.page { width: 210mm; height: 297mm; padding: 15mm 16mm 17mm; position: relative; overflow: hidden; page-break-after: always; }
.page:last-child { page-break-after: auto; }
.top { display: flex; justify-content: space-between; border-bottom: 2px solid #4F46E5; padding-bottom: 5px; margin-bottom: 14px; font-size: 8.5pt; color: #6B7280; letter-spacing: .04em; text-transform: uppercase; }
.top b { color: #4F46E5; }
.foot { position: absolute; left: 16mm; right: 16mm; bottom: 8mm; font-size: 8pt; color: #9CA3AF; display: flex; justify-content: space-between; }
h1 { font-size: 22pt; line-height: 1.15; margin: 0 0 8px; color: #312E81; } h2 { font-size: 12.5pt; margin: 13px 0 6px; color: #4F46E5; } h3 { font-size: 10.6pt; margin: 0 0 4px; color: #312E81; }
p { margin: 0 0 8px; } ul { margin: 0 0 8px; padding-left: 18px; } li { margin-bottom: 3px; }
.lead { font-size: 11.5pt; color: #374151; }
.cards { display: grid; gap: 9px; } .c2 { grid-template-columns: 1fr 1fr; } .c3 { grid-template-columns: 1fr 1fr 1fr; }
.card { border: 1px solid #D1D5DB; border-radius: 9px; padding: 9px 12px; } .card.ind { background: #EEF2FF; border-color: #C7D2FE; } .card.amber { background: #FFFBEB; border-color: #FCD34D; } .card.grey { background: #F3F4F6; }
table { border-collapse: collapse; width: 100%; font-size: 8.9pt; margin: 4px 0 10px; } th { background: #4F46E5; color: #fff; text-align: left; padding: 5px 7px; } td { border: 1px solid #D1D5DB; padding: 4px 7px; vertical-align: top; } tr:nth-child(even) td { background: #F9FAFB; }
code { background: #F3F4F6; padding: 0 4px; border-radius: 3px; font-size: 8.8pt; }
.cap { font-size: 8.6pt; color: #6B7280; font-style: italic; }
svg { width: 100%; height: auto; display: block; }
.step { display: grid; grid-template-columns: 26px 1fr; gap: 8px; margin: 5px 0; } .step i { background: #4F46E5; color: #fff; border-radius: 50%; width: 22px; height: 22px; display: grid; place-items: center; font-style: normal; font-size: 9pt; font-weight: 700; }
.dummy { background: #FEF3C7; border: 1px solid #F59E0B; color: #92400E; border-radius: 6px; padding: 3px 8px; font-size: 8.6pt; font-weight: 700; }
pre { background: #111827; color: #E5E7EB; border-radius: 8px; padding: 9px 11px; font-size: 8.2pt; line-height: 1.4; margin: 6px 0 8px; white-space: pre-wrap; }
"""

ARCH = """
<svg viewBox="0 0 720 470" font-family="Arial, Helvetica, sans-serif" font-size="11.5">
<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#475569"/></marker></defs>
<rect x="6" y="6" width="708" height="84" rx="10" fill="#F8FAFC" stroke="#CBD5E1"/><text x="18" y="24" font-weight="700" fill="#334155">CLIENTS (plain HTML / CSS / JavaScript – no build step)</text>
<rect x="30" y="34" width="190" height="46" rx="7" fill="#E6F4F1" stroke="#0F766E"/><text x="125" y="54" text-anchor="middle" font-weight="700" fill="#134E4A">Patient chat</text><text x="125" y="70" text-anchor="middle" font-size="10" fill="#334155">/chat – simulated WhatsApp</text>
<rect x="265" y="34" width="190" height="46" rx="7" fill="#E6F4F1" stroke="#0F766E"/><text x="360" y="54" text-anchor="middle" font-weight="700" fill="#134E4A">Reception dashboard</text><text x="360" y="70" text-anchor="middle" font-size="10" fill="#334155">/dashboard – approve / edit / reject</text>
<rect x="500" y="34" width="190" height="46" rx="7" fill="#E6F4F1" stroke="#0F766E"/><text x="595" y="54" text-anchor="middle" font-weight="700" fill="#134E4A">Knowledge Base editor</text><text x="595" y="70" text-anchor="middle" font-size="10" fill="#334155">/knowledge – edit data, test a question</text>
<rect x="6" y="110" width="520" height="350" rx="10" fill="#EEF2FF" stroke="#4F46E5"/><text x="18" y="128" font-weight="700" fill="#312E81">BACKEND – one FastAPI application (Python)</text>
<rect x="24" y="140" width="228" height="34" rx="6" fill="#fff" stroke="#6366F1"/><text x="138" y="161" text-anchor="middle" font-weight="700" fill="#312E81">webhook.py · meta_webhook.py</text>
<rect x="272" y="140" width="236" height="34" rx="6" fill="#fff" stroke="#6366F1"/><text x="390" y="161" text-anchor="middle" font-weight="700" fill="#312E81">dashboard_api.py · kb_api.py</text>
<rect x="24" y="186" width="484" height="150" rx="8" fill="#fff" stroke="#6366F1" stroke-dasharray="4 3"/><text x="36" y="203" font-weight="700" fill="#312E81" font-size="10.5">pipeline.py – runs the five stages in order</text>
<rect x="36" y="212" width="86" height="38" rx="6" fill="#EEF2FF" stroke="#4F46E5"/><text x="79" y="228" text-anchor="middle" font-size="10" font-weight="700">1 Classify</text><text x="79" y="242" text-anchor="middle" font-size="8.5" fill="#475569">classifier.py</text>
<rect x="134" y="212" width="86" height="38" rx="6" fill="#F5F3FF" stroke="#7C3AED"/><text x="177" y="228" text-anchor="middle" font-size="10" font-weight="700">2 Retrieve</text><text x="177" y="242" text-anchor="middle" font-size="8.5" fill="#475569">retriever.py</text>
<rect x="232" y="212" width="86" height="38" rx="6" fill="#FFF7ED" stroke="#EA580C"/><text x="275" y="228" text-anchor="middle" font-size="10" font-weight="700">3 Draft</text><text x="275" y="242" text-anchor="middle" font-size="8.5" fill="#475569">ai_response.py</text>
<rect x="330" y="212" width="86" height="38" rx="6" fill="#FEF2F2" stroke="#DC2626"/><text x="373" y="228" text-anchor="middle" font-size="10" font-weight="700">4 Verify</text><text x="373" y="242" text-anchor="middle" font-size="8.5" fill="#475569">validator.py</text>
<rect x="428" y="212" width="70" height="38" rx="6" fill="#ECFDF5" stroke="#059669"/><text x="463" y="228" text-anchor="middle" font-size="10" font-weight="700">5 Route</text><text x="463" y="242" text-anchor="middle" font-size="8.5" fill="#475569">validator.py</text>
<line x1="122" y1="231" x2="134" y2="231" stroke="#475569" marker-end="url(#a)"/><line x1="220" y1="231" x2="232" y2="231" stroke="#475569" marker-end="url(#a)"/><line x1="318" y1="231" x2="330" y2="231" stroke="#475569" marker-end="url(#a)"/><line x1="416" y1="231" x2="428" y2="231" stroke="#475569" marker-end="url(#a)"/>
<text x="36" y="274" font-size="10" fill="#334155">helpers: knowledge.py / kbstore.py (load &amp; save data) · textutils.py (stemming, Hinglish words)</text><text x="36" y="290" font-size="10" fill="#334155">medical_terms.py (drug &amp; condition words, shared by classifier and validator) · rag.py (model prompt)</text>
<text x="36" y="306" font-size="10" fill="#334155">explain.py (the “show your work” trace) · config.py (settings from environment variables)</text>
<text x="36" y="324" font-size="10" fill="#7F1D1D" font-weight="700">Only outbound.py can send – and only verified text (the single send gate)</text>
<rect x="24" y="350" width="484" height="40" rx="7" fill="#FEF2F2" stroke="#DC2626"/><text x="266" y="368" text-anchor="middle" font-weight="700" fill="#7F1D1D">outbound.py – the send gate</text><text x="266" y="383" text-anchor="middle" font-size="10" fill="#334155">AI text needs an AUTO_SEND verdict for that exact text · deliver first, record second</text>
<rect x="24" y="404" width="484" height="44" rx="7" fill="#fff" stroke="#6366F1"/><text x="266" y="422" text-anchor="middle" font-weight="700" fill="#312E81">whatsapp_cloud.py</text><text x="266" y="438" text-anchor="middle" font-size="10" fill="#334155">signature check · parsing · send with retries · error mapping · log redaction</text>
<rect x="548" y="110" width="166" height="100" rx="10" fill="#FFFBEB" stroke="#D97706"/><text x="631" y="132" text-anchor="middle" font-weight="700" fill="#92400E">SQLite database</text><text x="631" y="150" text-anchor="middle" font-size="10" fill="#334155">conversations</text><text x="631" y="164" text-anchor="middle" font-size="10" fill="#334155">messages · inquiries</text><text x="631" y="178" text-anchor="middle" font-size="10" fill="#334155">whatsapp_events · settings</text><text x="631" y="198" text-anchor="middle" font-size="9" fill="#64748B">audit trail of every decision</text>
<rect x="548" y="226" width="166" height="90" rx="10" fill="#F5F3FF" stroke="#7C3AED"/><text x="631" y="248" text-anchor="middle" font-weight="700" fill="#4C1D95">Knowledge base (files)</text><text x="631" y="266" text-anchor="middle" font-size="10" fill="#334155">clinic_facts · treatments</text><text x="631" y="280" text-anchor="middle" font-size="10" fill="#334155">doctors · faqs · synonyms</text><text x="631" y="298" text-anchor="middle" font-size="9" fill="#64748B">JSON or CSV, backups kept</text>
<rect x="548" y="332" width="166" height="56" rx="10" fill="#ECFEFF" stroke="#0891B2"/><text x="631" y="354" text-anchor="middle" font-weight="700" fill="#155E75">Meta WhatsApp Cloud API</text><text x="631" y="372" text-anchor="middle" font-size="10" fill="#334155">webhook in · Graph API out</text>
<rect x="548" y="404" width="166" height="56" rx="10" fill="#F8FAFC" stroke="#94A3B8" stroke-dasharray="4 3"/><text x="631" y="426" text-anchor="middle" font-weight="700" fill="#334155">Claude (optional)</text><text x="631" y="444" text-anchor="middle" font-size="10" fill="#334155">wording only · off by default</text>
<line x1="360" y1="80" x2="360" y2="108" stroke="#475569" marker-end="url(#a)"/><line x1="125" y1="80" x2="125" y2="108" stroke="#475569" marker-end="url(#a)"/>
<line x1="526" y1="160" x2="548" y2="160" stroke="#475569" marker-end="url(#a)"/><line x1="526" y1="270" x2="548" y2="270" stroke="#475569" marker-end="url(#a)"/><line x1="526" y1="360" x2="548" y2="360" stroke="#475569" marker-start="url(#a)" marker-end="url(#a)"/><line x1="526" y1="432" x2="548" y2="432" stroke="#475569" stroke-dasharray="3 3" marker-end="url(#a)"/>
</svg>
"""


def page(n: int, title: str, body: str) -> str:
    return (f'<section class="page"><div class="top"><span><b>Dental Clinic AI Assistant</b> · System Design</span><span>{title}</span></div>{body}'
            f'<div class="foot"><span>System Design Document · dummy sample clinic data</span><span>Page {n} of 8</span></div></section>')


P = []
P.append(page(1, "Overview", """
<h1>System Design: Dental Clinic AI Assistant – Pune</h1>
<p class="lead">A WhatsApp assistant for a dental clinic that answers routine questions from the clinic’s own approved information, verifies every answer with code before sending, and routes anything risky or uncertain to a receptionist.</p>
<div class="cards c3"><div class="card ind"><h3>Problem</h3>~150 WhatsApp enquiries a day, mostly repetitive; urgent ones get buried; staff time is spent retyping the same answers.</div>
<div class="card ind"><h3>Approach</h3>Classify → retrieve (RAG) → draft → <b>verify in code</b> → auto-send or hand to a human. The model, if used, only phrases text.</div>
<div class="card ind"><h3>Outcome</h3>A working app (patient chat, dashboard, knowledge-base editor), official Meta Cloud API integration (built), and a 265-case audit (82% correct on fresh messages).</div></div>
<h2>Goals and non-goals</h2>
<div class="cards c2"><div class="card"><h3>Goals</h3><ul style="margin:0"><li><b>Never invent</b> a price, doctor, offer or appointment slot</li><li><b>Fail safe</b>: when unsure, a person decides</li><li><b>Traceable</b>: every reply records its sources and the checks it passed</li><li><b>Maintainable</b> by a beginner: few moving parts, readable rules, no build step</li><li>Editable clinic data <b>without code</b></li></ul></div>
<div class="card grey"><h3>Non-goals (deliberately out of scope)</h3><ul style="margin:0"><li>Medical advice or diagnosis</li><li>Checking or confirming appointment availability (no calendar)</li><li>Replies in Devanagari script</li><li>Login / multi-user roles (listed as future work)</li><li>High-volume scaling beyond one server</li></ul></div></div>
<h2>Design principles</h2>
<table><tr><th style="width:30%">Principle</th><th>How it shows up in the system</th></tr>
<tr><td>Retrieval before generation</td><td>The drafter receives only the retrieved entries; the answer must cite their IDs</td></tr>
<tr><td>Code verifies, models don’t grade themselves</td><td><code>validator.py</code> is regexes and lookups; no model call is ever used to judge an answer</td></tr>
<tr><td>One way out</td><td>All sending goes through <code>outbound.send_reply</code>, which refuses unverified AI text</td></tr>
<tr><td>Safe by default</td><td>Template mode, simulated WhatsApp, dashboard blocked from the internet, secrets only in environment variables</td></tr>
<tr><td>Explain everything</td><td>Dashboard shows the draft, sources, reason for a hold and an audit timeline; a “Test a question” tool shows the pipeline step by step</td></tr></table>
<p class="cap">Data in this project is <span class="dummy">dummy sample data</span>.</p>
"""))

P.append(page(2, "Architecture", f"""
<h1>System architecture</h1>
<p>One Python process serves the API and the three web pages. Persistent state is a SQLite file and the clinic’s data files; the only outside services are Meta’s WhatsApp Cloud API (optional) and Claude (optional).</p>
{ARCH}
<p class="cap">Solid arrows: always used. Dashed: optional. The dashboard polls the API every 3 seconds (simple and robust; see trade-offs, page 8).</p>
"""))

P.append(page(3, "Request lifecycle", """
<h1>What happens to one message</h1>
<div class="step"><i>1</i><div><b>Receive.</b> Simulated mode: the chat page posts to <code>POST /api/webhook/whatsapp</code>. Real mode: Meta posts to <code>POST /whatsapp/webhook</code>; the HMAC-SHA256 signature is checked on the <i>raw</i> body, the request is answered <b>200 immediately</b>, and processing continues in the background. Each WhatsApp message id is claimed once in <code>whatsapp_events</code> (duplicate protection).</div></div>
<div class="step"><i>2</i><div><b>Save first.</b> The patient message is stored before any AI runs, so a crash can never lose it (the inquiry is then escalated with an error note).</div></div>
<div class="step"><i>3</i><div><b>Classify.</b> Weighted keyword/regex rules give topic(s), confidence, whether it is sensitive (emergency / medical / complaint), whether it is urgent, language script and entities such as “tomorrow 5 pm”. One-letter typos in topic words are repaired first.</div></div>
<div class="step"><i>4</i><div><b>Retrieve.</b> Three methods (precise name/keyword, topic, word-overlap with synonyms) score every knowledge entry. Result: ranked <code>Source</code> objects with IDs, scores and reasons.</div></div>
<div class="step"><i>5</i><div><b>Draft.</b> Template mode builds one section per topic from the entries. Optional Claude mode phrases informational answers from the entries only and must return <code>SOURCES: &lt;ids&gt;</code>; any failure falls back to the template. No entry found → a fixed “I don’t have that information” notice.</div></div>
<div class="step"><i>6</i><div><b>Verify and route.</b> Code checks (page 7) produce a <code>Verdict</code>: <code>auto_send</code>, <code>needs_approval</code> or <code>escalate</code>, with reasons. The verdict carries a SHA-256 of the exact text it verified.</div></div>
<div class="step"><i>7</i><div><b>Act.</b> <i>auto_send</i>: <code>outbound.send_reply</code> delivers, then records message + sources. <i>needs_approval / escalate</i>: nothing is sent (except the fixed notice for unknown questions); an inquiry appears on the dashboard, urgent first.</div></div>
<div class="step"><i>8</i><div><b>Human step.</b> The receptionist approves, edits (the same price / doctor / medicine checks re-run), rejects or escalates. Only then is the reply delivered. Every action is appended to the inquiry’s audit timeline.</div></div>
<h2>Sequence (simplified)</h2>
<pre>Patient ─► Webhook ─► save msg ─► Classifier ─► Retriever ─► Drafter ─► Validator ─┐
                                                                                    ├─ auto_send ───────► send gate ─► WhatsApp ─► Patient
                                                                                    └─ hold / escalate ─► Dashboard ─► Receptionist ─► send gate ─► Patient</pre>
<h2>Failure handling</h2>
<table><tr><th style="width:34%">Failure</th><th>Behaviour</th></tr>
<tr><td>AI pipeline raises an exception</td><td>Message already saved; inquiry created as <i>escalated</i> with the error; a person replies</td></tr>
<tr><td>Claude unavailable / malformed / cut off</td><td>Falls back to the template answer (which is still verified)</td></tr>
<tr><td>WhatsApp rejects a send</td><td>Nothing is recorded as sent; the item stays open (“approve to try again”); error codes mapped to plain advice</td></tr>
<tr><td>Meta retries a webhook</td><td>Duplicate wamid is ignored; interrupted messages are marked failed on restart</td></tr></table>
"""))

P.append(page(4, "Components", """
<h1>Components in detail</h1>
<table><tr><th style="width:15%">Stage</th><th style="width:20%">Input → output</th><th>Design and why</th></tr>
<tr><td><b>Classifier</b><br><code>classifier.py</code></td><td>text → intents, confidence, urgent, caution</td><td>Weighted regex rules (English + Hinglish). Explainable and editable; chosen over ML because there is no training data and every label must be justifiable. Weak health words set a <i>caution</i> (reply is held) instead of becoming the topic.</td></tr>
<tr><td><b>Retriever</b><br><code>retriever.py</code></td><td>text + intents → scored entries</td><td>Precise + topic + lexical (idf-weighted) matching, stemming, synonyms, typo tolerance. No vector DB: the knowledge base is ~40 entries and simple retrieval met the test set. Guards: words must be close together; a stray unexplained noun vetoes a one-word match.</td></tr>
<tr><td><b>Drafter</b><br><code>ai_response.py</code>, <code>rag.py</code></td><td>entries → text + cited IDs</td><td>Template per topic (default) or Claude. Judges only the sentences that actually ask something; marks a reply <i>partial</i> if a question is not covered.</td></tr>
<tr><td><b>Verifier</b><br><code>validator.py</code></td><td>draft + sources → Verdict</td><td>Pure code: source exists, prices/doctors/numbers/links grounded in cited entries, no “slot is free/booked”, no diagnosis/medicine, well-formed, covers every topic, length, language, confidence, doctor named by patient exists, no quoted promise.</td></tr>
<tr><td><b>Send gate</b><br><code>outbound.py</code></td><td>text + verdict → delivery</td><td>AI text needs an AUTO_SEND verdict whose hash matches. Human text bypasses only that rule. Deliver first, record second; demo chats never reach real phones.</td></tr>
<tr><td><b>Knowledge store</b><br><code>kbstore.py</code>, <code>knowledge.py</code></td><td>JSON/CSV ↔ entries</td><td>Validates on every save (clear line-level errors), writes a backup first, supports CSV import/export, marks dummy entries.</td></tr>
<tr><td><b>WhatsApp client</b><br><code>whatsapp_cloud.py</code></td><td>payloads ↔ Graph API</td><td>Signature verification, payload parsing, retrying sender, error-code mapping, log redaction of every configured secret.</td></tr></table>
<h2>Routing decision table</h2>
<table><tr><th>Condition</th><th style="width:20%">Decision</th><th style="width:34%">Patient sees</th></tr>
<tr><td>Every check passed, topic is safe, auto-reply on</td><td>AUTO_SEND</td><td>The verified answer</td></tr>
<tr><td>A soft check failed · appointment request · partial answer · low confidence · weak health sign · auto-reply off</td><td>NEEDS_APPROVAL</td><td>Nothing until a person approves</td></tr>
<tr><td>A hard check failed · emergency / medical / complaint · not understood</td><td>ESCALATE (urgent flagged)</td><td>Nothing, or the fixed “I don’t have that information” notice</td></tr></table>
"""))

P.append(page(5, "Data design", """
<h1>Data design</h1>
<h2>1 · Knowledge base (files, edited without code)</h2>
<p>Four datasets (<code>clinic_facts</code>, <code>treatments</code>, <code>doctors</code>, <code>faqs</code>) plus an optional <code>synonyms</code> list. Each record becomes an <b>entry</b> with a stable ID: <code>treatment:root_canal</code>, <code>doctor:dr_neha_joshi</code>, <code>faq:walk_in</code>, <code>clinic:timings</code>. IDs are the internal <i>source references</i> stored with every reply. Records carry <code>"dummy": true</code> until the owner confirms them.</p>
<h2>2 · SQLite (conversation history and audit trail)</h2>
<table><tr><th style="width:21%">Table</th><th>Purpose and key columns</th></tr>
<tr><td><code>conversations</code></td><td>One row per patient phone: <code>phone</code> (unique), <code>name</code>, <code>channel</code> (<i>simulated</i> | <i>whatsapp</i>)</td></tr>
<tr><td><code>messages</code></td><td>Every bubble: <code>role</code> (patient | assistant | receptionist), <code>text</code>, <code>sources</code> (entries used), <code>meta</code> (verified automatically / approved by whom / edited?), <code>wa_id</code>, <code>delivery</code></td></tr>
<tr><td><code>inquiries</code></td><td>One row per patient message: <code>intent(s)</code>, <code>confidence</code>, <code>urgent</code>, <code>draft</code>, <code>sources</code>, <code>checks</code>, <code>reasons</code>, <code>decision</code>, <code>status</code>, <code>final_reply</code>, <code>audit</code> (timeline), <code>rag</code> (how the answer was built)</td></tr>
<tr><td><code>whatsapp_events</code></td><td>Primary key = WhatsApp message id → each incoming message processed once; state <i>processing | done | failed | ignored</i></td></tr>
<tr><td><code>settings</code></td><td>Key/value (e.g. auto-reply on/off)</td></tr></table>
<pre>conversations 1 ──── * messages            conversations 1 ──── * inquiries 1 ──── 1 patient message
whatsapp_events.inquiry_id ─► inquiries.id    status: auto_replied | pending_approval | escalated | approved | replied | dismissed</pre>
<h2>3 · Design choices</h2>
<ul><li><b>Why store checks, reasons and sources as JSON on the inquiry?</b> The dashboard needs the complete explanation of one decision at once; it is read far more than it is queried.</li>
<li><b>Why SQLite?</b> Zero setup, a single file, enough for a demo. The access code is isolated in <code>database.py</code>, so moving to PostgreSQL later is a contained change.</li>
<li><b>Status is separate from decision.</b> <code>decision</code> is what the AI/verifier chose; <code>status</code> is what happened (including what the human did).</li>
<li><b>Secrets are never stored</b> in the database, logs or pages.</li></ul>
"""))

P.append(page(6, "API surface", """
<h1>API surface</h1>
<p>All JSON over HTTP; interactive documentation is generated at <code>/docs</code> (FastAPI/OpenAPI).</p>
<table><tr><th style="width:11%">Method</th><th style="width:36%">Path</th><th>Purpose</th></tr>
<tr><td>POST</td><td><code>/api/webhook/whatsapp</code></td><td>Simulated chat: receive a patient message (disabled when <code>WHATSAPP_MODE=cloud</code>)</td></tr>
<tr><td>GET</td><td><code>/api/chat/{phone}/messages</code></td><td>Chat page polls for new replies</td></tr>
<tr><td>GET · POST</td><td><code>/whatsapp/webhook</code></td><td>Meta: verification handshake (GET) · signed incoming events (POST, answers 200 at once)</td></tr>
<tr><td>GET</td><td><code>/api/whatsapp/status</code></td><td>Is WhatsApp connected? Never shows secrets</td></tr>
<tr><td>GET</td><td><code>/api/dashboard/stats</code> · <code>/inquiries</code> · <code>/inquiries/{id}</code></td><td>Dashboard numbers, the inbox (filterable), one inquiry with its full explanation</td></tr>
<tr><td>POST</td><td><code>/api/dashboard/inquiries/{id}/send</code></td><td>Approve or edit-and-send (checks re-run; override needs explicit acknowledgement)</td></tr>
<tr><td>POST</td><td><code>…/{id}/reject · escalate · dismiss</code></td><td>Reject a draft, push to a person, or close without reply</td></tr>
<tr><td>GET · POST</td><td><code>/api/dashboard/settings</code></td><td>Auto-reply switch</td></tr>
<tr><td>POST</td><td><code>/api/dashboard/seed-demo</code> · <code>/reset</code></td><td>Demo tools (disabled in cloud mode)</td></tr>
<tr><td>GET · POST · PUT · DELETE</td><td><code>/api/kb/{dataset}[/{id}]</code>, <code>/api/kb/clinic</code></td><td>Create / read / update / delete knowledge records</td></tr>
<tr><td>GET · POST</td><td><code>/api/kb/{dataset}/export.csv</code> · <code>/import</code></td><td>CSV round trip for spreadsheets</td></tr>
<tr><td>POST</td><td><code>/api/kb/ask</code></td><td>“Test a question”: runs the pipeline, saves and sends nothing, returns the whole trace</td></tr>
<tr><td>GET</td><td><code>/api/kb/summary</code> · <code>/gaps</code></td><td>Counts; questions patients asked that the knowledge base could not answer</td></tr>
<tr><td>GET</td><td><code>/healthz</code></td><td>Liveness (also reachable through a tunnel)</td></tr></table>
<h2>Example: the “Test a question” response (shape)</h2>
<pre>{ "question": "...", "understood": {"intent": "treatment_price", "intents": [...], "confidence": 0.97, "sensitive": false, "urgent": false, "entities": {}},
  "retrieved": [{"id": "treatment:root_canal", "score": 1.0, "method": "precise", "why": [...], ...}],
  "context": "...", "prompt": {"system": "...", "user": "..."}, "generation": {"mode": "template", "kind": "answer", ...},
  "answer": "...", "parts": [...], "used_sources": [...], "answerable": true,
  "decision": "auto_send", "reasons": [...], "checks": [{"name": "prices_supported", "passed": true, "severity": "block", ...}] }</pre>
<p class="cap">Dashboard and knowledge-base routes have no login. A middleware refuses them for requests that arrive through a tunnel or proxy (detected by proxy headers) unless <code>ALLOW_PUBLIC_DASHBOARD=true</code> is set for a dummy-data public demo; that setting cannot be combined with real WhatsApp.</p>
"""))

P.append(page(7, "Verification, security and privacy", """
<h1>Verification, security and privacy</h1>
<h2>Verification (all code)</h2>
<table><tr><th style="width:27%">Group</th><th>Checks (severity)</th></tr>
<tr><td>1 · Source</td><td>A relevant entry exists, score ≥ threshold (block) · the answer cites retrieved, strong-enough entries (block)</td></tr>
<tr><td>2 · Prices and doctors</td><td>Every price, number, link/email and doctor name appears in the cited entries (block) · no invented “discount / free / guarantee / cashless” (block)</td></tr>
<tr><td>3 · Calendar</td><td>No “slot is available”, “your appointment is confirmed”, “see you at…” (block); appointment topics always need a person</td></tr>
<tr><td>4 · Medical</td><td>No drug names or dosage, no “you probably have…”, no personal treatment recommendation (block)</td></tr>
<tr><td>5 · Valid and complete</td><td>No placeholders/leaks (block) · covers each topic asked (warn) · length · language · confidence (warn)</td></tr>
<tr><td>Routing</td><td>Doctor named by the patient exists · patient does not quote an earlier promise · weak health sign (warn → approval)</td></tr></table>
<h2>Threats and mitigations</h2>
<table><tr><th style="width:27%">Threat</th><th>Mitigation</th></tr>
<tr><td>Invented facts (hallucination)</td><td>Answers only from retrieved entries; every number/doctor/link verified against them; unknown → “I don’t know”</td></tr>
<tr><td>Prompt injection (“ignore your rules”)</td><td>Patient text is wrapped as data in the model prompt; sensitive topics never reach the model; verifier and send gate are code the model cannot talk its way past; 23 injection cases tested</td></tr>
<tr><td>Medical harm</td><td>Medical/emergency/complaint topics are escalated by topic; medicine and condition words detected in both the patient’s message and the reply</td></tr>
<tr><td>Forged webhook</td><td>HMAC-SHA256 of the raw body must match <code>X-Hub-Signature-256</code></td></tr>
<tr><td>Replays / duplicates</td><td>Message id is a primary key in <code>whatsapp_events</code></td></tr>
<tr><td>Secret leakage</td><td>Only environment variables; log-record filter redacts configured secrets; never in DB, API or pages (tested)</td></tr>
<tr><td>Exposed dashboard (no login)</td><td>Proxy-header guard; refuses to run public + real WhatsApp together</td></tr>
<tr><td>Messaging real people by mistake</td><td>Demo conversations are flagged <i>simulated</i> and never delivered to a real phone</td></tr></table>
<h2>Privacy</h2>
<p>Patient messages and phone numbers are personal data and sometimes health data. Phone numbers are masked in logs. A real deployment needs login, retention rules, consent and a review under India’s Digital Personal Data Protection Act – <b>take legal advice</b>. The project uses dummy clinic data only.</p>
"""))

P.append(page(8, "Decisions, testing and deployment", """
<h1>Trade-offs, testing and deployment</h1>
<h2>Key decisions and trade-offs</h2>
<table><tr><th style="width:24%">Decision</th><th style="width:38%">Why</th><th>Cost / when to revisit</th></tr>
<tr><td>Keyword rules, not an ML classifier</td><td>No data; explainable; editable by a beginner</td><td>New phrasings and Marathi words find gaps (82% first-run accuracy) – grow vocabulary from real messages</td></tr>
<tr><td>Simple retrieval, no vector DB</td><td>~40 entries; simple methods met the tests</td><td>Embeddings once the knowledge base reaches hundreds of entries</td></tr>
<tr><td>Code verifier, model never judges</td><td>A model can repeat its own mistake with confidence</td><td>Heuristic regexes miss unusual wording – held-for-approval is the net</td></tr>
<tr><td>Template mode by default</td><td>Free, offline, deterministic, testable</td><td>Replies are stiff; Claude path exists but was not run live</td></tr>
<tr><td>SQLite</td><td>Zero setup</td><td>PostgreSQL + backups for production</td></tr>
<tr><td>Polling (3 s), not WebSockets</td><td>Simple and robust</td><td>Server-sent events if latency matters</td></tr>
<tr><td>Answer 200 first, process after</td><td>Meta retries slow webhooks for up to 36 hours</td><td>Use a real job queue at higher volume</td></tr></table>
<h2>Testing strategy</h2>
<ul><li><b>958 automated tests</b> (pytest), run on a temp copy of the data: units for each stage, API, WhatsApp flow (fake Graph API, local HTTP server), retrieval accuracy set.</li>
<li><b>265-case quality audit</b> in four rounds with expectations written first; rounds 2–4 blind. First-run <b>82.3%</b>, after fixes 99.6% on tuned-on cases, 1 known failure. 32 defects fixed, each with a regression test; fixes mutation-checked.</li>
<li><b>Independent safety invariants</b> on every case (unverified send, unknown price/doctor, internal text, claimed booking): 0 violations.</li></ul>
<h2>Deployment</h2>
<table><tr><th style="width:24%">Mode</th><th>How</th></tr>
<tr><td>Local demo</td><td><code>python run.py</code> → <code>/chat</code>, <code>/dashboard</code>, <code>/knowledge</code></td></tr>
<tr><td>Public demo (dummy data)</td><td>Docker image / Render blueprint: <code>HOST=0.0.0.0 ALLOW_PUBLIC_DASHBOARD=true SEED_DEMO_ON_START=true WHATSAPP_MODE=simulated</code>; free-tier disks are ephemeral, so demo data resets on restart</td></tr>
<tr><td>Real WhatsApp</td><td><code>WHATSAPP_MODE=cloud</code> + four secrets in the environment; HTTPS webhook URL; <b>not yet tested against Meta</b></td></tr></table>
<h2>Known limitations and next steps</h2>
<p>No calendar, no login, no Devanagari replies, Claude and Meta paths untested live; emergencies get no automatic acknowledgement until the clinic approves wording. Next: live Meta test, real clinic data, supervised trial with auto-reply off, login and hosting, calendar integration.</p>
"""))

html = f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>System Design - Dental Clinic AI Assistant</title><style>{CSS}</style></head><body>{"".join(P)}</body></html>'
(SUB / "system_design.html").write_text(html, encoding="utf-8")
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page()
    pg.goto((SUB / "system_design.html").as_uri()); pg.wait_for_timeout(800)
    for n, bottom, h in pg.evaluate("""() => [...document.querySelectorAll('.page')].map((el, i) => {
        const kids = [...el.children].filter(c => !c.classList.contains('foot'));
        return [i + 1, Math.round(Math.max(...kids.map(c => c.getBoundingClientRect().bottom)) - el.getBoundingClientRect().top), el.clientHeight]; })"""):
        print(f"page {n}: ends at {bottom}px of {h}px", "OVERFLOW" if bottom > h - 40 else "ok")
    pg.pdf(path=str(SUB / "System_Design_Document.pdf"), prefer_css_page_size=True, print_background=True)
    b.close()
print("wrote System_Design_Document.pdf")
