"""Builds submission/Dental_Clinic_AI_Workbook.xlsx - the Knowledge & Testing Workbook.

    ./.venv/bin/python submission/build_workbook.py

Everything in the workbook comes from the project itself (the knowledge base in data/ and the saved audit runs in qa/results/).
The Performance Metrics and the counts on other tabs are real Excel FORMULAS over the test-result tabs, so they update if you
change a result; xlsxwriter also stores the value each formula should give, so viewers that do not recalculate still show numbers.
Requires: pip install xlsxwriter   (listed in requirements-dev.txt)
"""
from __future__ import annotations

import datetime
import re
import sys
from collections import Counter
from pathlib import Path

import xlsxwriter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import knowledge  # noqa: E402
from backend.textutils import HINGLISH_FILLER  # noqa: E402
from qa.cases import ESCALATED, PENDING, ROUND1, AUTO  # noqa: E402
from qa.cases_round2 import ROUND2  # noqa: E402
from qa.cases_round3 import ROUND3  # noqa: E402
from qa.cases_round4 import ROUND4  # noqa: E402
from qa.findings import FINDINGS  # noqa: E402
from qa.make_report import FIRST_RUN_FILE, TEST_ERRORS, failure_kind, load  # noqa: E402

OUT = ROOT / "submission" / "Dental_Clinic_AI_Workbook.xlsx"
TODAY = datetime.date(2026, 11, 23)
ROUNDS = [("Round 1", ROUND1), ("Round 2", ROUND2), ("Round 3", ROUND3), ("Round 4", ROUND4)]
ALL = [(rn, c) for rn, cs in ROUNDS for c in cs]
N = len(ALL)
FIRST = 5                                  # first data row (Excel numbering) on the test-result tabs
LAST = FIRST + N - 1

ROUTE = {"auto_replied": "Auto-replied", "pending_approval": "Held for approval", "escalated": "Escalated to receptionist"}
ROUTE_ORDER = list(ROUTE.values())
GATE = {"auto_send": "PASSED - safe to send", "needs_approval": "HELD - needs approval", "escalate": "BLOCKED - escalated"}
CAT_ORDER = ["Prices & treatments", "Doctors & timings", "Hindi / Hinglish", "Multiple requests", "Appointment availability",
             "No information", "Incorrect assumptions", "Medical / medicine", "Emergency / urgent", "Prompt injection", "Message styles"]
KIND_ORDER = ["sent automatically but should have been held", "wrong or incomplete answer sent automatically", "emergency not flagged urgent",
              "over-cautious: held something that could be answered", "wrong label or poor draft (held for a person)",
              "test or harness error (not the assistant's fault)"]

# ------------------------------------------------------------------------------------------------- the data
final = load("all_final.json")
first = {rn: load(f) for rn, f in FIRST_RUN_FILE.items()}
kb = knowledge.load()
finding_ids: dict = {}
for f in FINDINGS:
    for token in re.split(r"[\s,;()]+", f["found"]):
        finding_ids.setdefault(token, []).append(f["id"])


def clip(text: str, n: int = 700) -> str:
    text = text or ""
    return text if len(text) <= n else text[: n - 1].rstrip() + "… (full text: documentation/QA_CASES.md)"


def language_of(case, text: str) -> str:
    if re.search(r"[ऀ-ॿ]", text):
        return "Hindi (Devanagari script)"
    if not re.search(r"[A-Za-z]", text):
        return "Emoji / symbols"
    words = set(re.findall(r"[a-z]+", text.lower()))
    if case.category == "Hindi / Hinglish" or words & (set(HINGLISH_FILLER) | {"kitna", "kitne", "kab", "kahan", "kaun", "daant", "dard", "khoon", "paise", "kharcha", "dawai"}):
        return "Hinglish / Marathi (Roman letters)"
    return "English"


def expected_route(case) -> str:
    labels = {AUTO: "Auto-reply", PENDING: "Held for approval", ESCALATED: "Escalated"}
    return " or ".join(labels[r] for r in (AUTO, PENDING, ESCALATED) if r in case.routes)


# ------------------------------------------------------------------------------------------------- workbook + formats
wb = xlsxwriter.Workbook(str(OUT))
wb.set_properties({"title": "Dental Clinic AI - Knowledge & Testing Workbook", "subject": "Dental Clinic AI Assistant - Pune (student project)",
                   "comments": "Dummy sample clinic data. Generated from the project's knowledge base and quality-audit results."})
FONT = {"font_name": "Arial", "font_size": 10}
TEAL, TEAL_DARK, TEAL_LIGHT, GREY = "#0F766E", "#134E4A", "#E6F4F1", "#F3F4F6"


def fmt(**kw):
    return wb.add_format({**FONT, **kw})


f_title = fmt(bold=True, font_size=18, font_color=TEAL_DARK)
f_sub = fmt(italic=True, font_color="#555555", text_wrap=True, valign="top")
f_banner = fmt(bold=True, font_color="#92400E", bg_color="#FEF3C7", text_wrap=True, valign="vcenter", border=1, border_color="#F59E0B")
f_head = fmt(bold=True, font_color="#FFFFFF", bg_color=TEAL, text_wrap=True, valign="vcenter", border=1, border_color="#0B5A54")
f_section = fmt(bold=True, font_size=12, font_color=TEAL_DARK, bg_color=TEAL_LIGHT, valign="vcenter", bottom=2, bottom_color=TEAL)
f_cell = fmt(text_wrap=True, valign="top", border=1, border_color="#D1D5DB")
f_cell_c = fmt(text_wrap=True, valign="top", align="center", border=1, border_color="#D1D5DB")
f_cell_b = fmt(text_wrap=True, valign="top", border=1, border_color="#D1D5DB", bold=True)
f_label = fmt(bold=True, valign="top", text_wrap=True, bg_color=GREY, border=1, border_color="#D1D5DB")
f_int = fmt(valign="top", align="center", border=1, border_color="#D1D5DB", num_format="#,##0")
f_pct = fmt(valign="top", align="center", border=1, border_color="#D1D5DB", num_format="0.0%")
f_pct_b = fmt(valign="top", align="center", border=1, border_color="#D1D5DB", num_format="0.0%", bold=True, bg_color=TEAL_LIGHT)
f_int_b = fmt(valign="top", align="center", border=1, border_color="#D1D5DB", num_format="#,##0", bold=True, bg_color=TEAL_LIGHT)
f_money = fmt(valign="top", align="right", border=1, border_color="#D1D5DB", num_format='[>=100000]"₹"##\\,##\\,##0;"₹"##,##0')
f_conf = fmt(valign="top", align="center", border=1, border_color="#D1D5DB", num_format="0%")
f_input = fmt(valign="top", align="center", border=1, border_color="#D1D5DB", font_color="#0000FF", bg_color="#FFFF99", num_format="#,##0.0")
f_input_pct = fmt(valign="top", align="center", border=1, border_color="#D1D5DB", font_color="#0000FF", bg_color="#FFFF99", num_format="0%")
f_out = fmt(valign="top", align="center", border=1, border_color="#D1D5DB", num_format="#,##0.0", bold=True)
f_note = fmt(italic=True, font_color="#555555", text_wrap=True, valign="top")
f_good = fmt(bg_color="#D1FAE5", font_color="#065F46", bold=True)
f_bad = fmt(bg_color="#FEE2E2", font_color="#991B1B", bold=True)
f_warn = fmt(bg_color="#FEF3C7", font_color="#92400E", bold=True)

BANNER = ("DUMMY SAMPLE DATA: the clinic, doctors, prices and hours in this workbook are invented sample information (every entry is marked dummy: true). "
          "They are not a real clinic's verified facts and must be replaced and approved by the clinic owner before any real use.")


def sheet(name: str, tab: str, title: str, sub: str, widths: list[int], banner: bool = True):
    ws = wb.add_worksheet(name)
    ws.set_tab_color(tab)
    ws.hide_gridlines(2)
    for i, w in enumerate(widths):
        ws.set_column(i, i, w)
    ws.write(0, 0, title, f_title)
    ws.set_row(0, 28)
    last = max(len(widths) - 1, 1)
    ws.merge_range(1, 0, 1, last, sub, f_sub)
    ws.set_row(1, 30)
    if banner:
        ws.merge_range(2, 0, 2, last, BANNER, f_banner)
        ws.set_row(2, 32)
    return ws


def formula(ws, row, col, expr, value, fm):
    ws.write_formula(row, col, expr, fm, value)


def q(name: str) -> str:
    return "'" + name + "'"


TC, VRN, MET, HAND = "5. Test Cases", "6. Verification Results", "8. Performance Metrics", "7. Human Handoff"
VR = q(VRN)


def vr(col: str) -> str:
    return f"{VR}!${col}${FIRST}:${col}${LAST}"


# ================================================================================================ rows of data used everywhere
rows = []
for rn, case in ALL:
    r, fr = final[case.id], first[rn][case.id]
    kind = failure_kind(fr) if not fr.passed else ""
    note_bits = []
    if not r.passed:
        note_bits.append("FINAL FAIL: " + "; ".join(r.problems + r.invariant_problems))
    if not fr.passed:
        note_bits.append("First run: " + "; ".join(fr.problems + fr.invariant_problems)
                         + (f" [{TEST_ERRORS[case.id]}]" if case.id in TEST_ERRORS else "")
                         + (" - fixed by " + ", ".join(sorted(set(finding_ids.get(case.id, [])))) if finding_ids.get(case.id) else ""))
    rows.append(dict(rn=rn, case=case, r=r, fr=fr, kind=kind, note=" | ".join(note_bits),
                     retrieved="; ".join(f"{s['id']} ({s['score']:.2f})" for s in r.sources if s["score"] >= 0.5),
                     cited="; ".join(s["id"] for s in r.sources if s["used"]),
                     route=ROUTE[r.status], gate=GATE[r.decision], urgent="Yes" if r.urgent else "No",
                     result="PASS" if r.passed else "FAIL", first_result="PASS" if fr.passed else "FAIL",
                     invariants=1 if r.invariant_problems else 0))

# ================================================================================================ 8 first so its cell addresses are known
# (written last in tab order: xlsxwriter needs worksheets added in tab order, so we only PLAN the addresses here)
M = {}  # name -> Excel cell address on the metrics sheet
MET_ROWS = [  # (key, label, kind)
    ("total", "Total test cases", "int"), ("final_pass", "Final run: cases that pass", "int"), ("final_rate", "Final pass rate (after fixes)", "pct"),
    ("first_pass", "First run: cases that passed", "int"), ("first_rate", "FIRST-RUN pass rate (the honest figure)", "pct"),
    ("auto", "Automation rate: answered by the AI with no human", "pct"), ("held", "Held for receptionist approval", "pct"),
    ("esc", "Escalation rate: handed to a receptionist", "pct"), ("hand", "Human-handoff rate (held + escalated)", "pct"),
    ("prec", "Auto-replies that were correct (of those auto-replied)", "pct"), ("emer_n", "Emergency cases in the test set", "int"),
    ("emer_flag", "...of which flagged URGENT", "int"), ("invar", "Safety-rule violations found by the independent check", "int"),
]
for i, (key, _, _) in enumerate(MET_ROWS):
    M[key] = f"B{6 + i}"

# ================================================================================================ 1. Problem Statement
ws1 = sheet("1. Problem Statement", "#0F766E", "Dental Clinic AI Assistant – Pune: Problem Statement",
            "Knowledge & Testing Workbook · student project · prepared " + TODAY.strftime("%d %B %Y"), [30, 78, 36], banner=False)
r0 = 3
ws1.merge_range(r0, 0, r0, 2, "THE PROBLEM", f_section)
text_rows = [
    ("Problem statement", "A dental clinic in Pune receives about 150 WhatsApp enquiries every day (the figure given in the project brief). Most are repetitive: "
                          "treatment prices, doctors, clinic timings, location, payment options and appointment requests. Receptionists answer them by hand, "
                          "so patients wait, urgent messages can be buried among routine ones, and staff spend their day typing the same answers."),
    ("Who is affected", "Patients (waiting for simple answers, no reply after hours) · receptionists (overloaded, interrupted) · the clinic (lost enquiries, "
                        "slower response to real emergencies)."),
    ("Goal", "Answer the routine questions instantly and accurately, using only the clinic's own approved information, and make sure anything risky, "
             "uncertain or urgent reaches a human with all the context needed to reply quickly."),
    ("Proposed solution", "A WhatsApp assistant that: (1) classifies each message, (2) retrieves the relevant clinic entries (RAG), (3) drafts an answer from "
                          "those entries only, (4) VERIFIES the draft with code-based checks, then (5) either sends it automatically or places it in a receptionist "
                          "dashboard for approve / edit / reject. Emergencies, medical questions, complaints and appointment requests are never answered "
                          "automatically."),
    ("What 'accurate' means here", "Never invent a price, doctor, offer or appointment slot; never give medical advice; say 'I don't know' and pass the question "
                                  "to reception when the clinic's information does not cover it; flag emergencies urgent."),
]
for i, (a, b) in enumerate(text_rows):
    ws1.write(r0 + 1 + i, 0, a, f_label)
    ws1.merge_range(r0 + 1 + i, 1, r0 + 1 + i, 2, b, f_cell)
    ws1.set_row(r0 + 1 + i, 62 if len(b) > 330 else 48)
r = r0 + 1 + len(text_rows) + 1
ws1.merge_range(r, 0, r, 2, "SCOPE AND HONEST STATUS", f_section)
status_rows = [
    ("In scope", "Patient chat (simulated WhatsApp), receptionist dashboard, editable knowledge base, retrieval + drafting, verification and routing, "
                 "official Meta WhatsApp Cloud API integration (built), quality audit."),
    ("Not proven / out of scope", "• Meta Cloud API has NOT been tested against Meta's real servers (no Meta account was available).\n"
                                  "• The Claude (LLM) drafting path has NOT been run live; all results here are from the offline template mode.\n"
                                  "• No appointment calendar: bookings are always confirmed by a person.\n"
                                  "• The dashboard has no login. All clinic data is dummy sample data."),
    ("How it was tested", "265 test cases in four rounds, expectations written before each run. See tabs 5-8. Rounds 2-4 were blind (not run until written)."),
]
for i, (a, b) in enumerate(status_rows):
    ws1.write(r + 1 + i, 0, a, f_label)
    ws1.merge_range(r + 1 + i, 1, r + 1 + i, 2, b, f_cell)
    ws1.set_row(r + 1 + i, 78 if "\n" in b else 48)
r = r + 1 + len(status_rows) + 1
ws1.merge_range(r, 0, r, 2, "SUCCESS MEASURES (live links to tab 8 – they update with the test results)", f_section)
ws1.write(r + 1, 0, "Measure", f_head); ws1.write(r + 1, 1, "How it is measured", f_head); ws1.write(r + 1, 2, "Result", f_head)
n_auto = sum(x["route"] == "Auto-replied" for x in rows)
n_pass_first = sum(x["first_result"] == "PASS" for x in rows)
n_pass_final = sum(x["result"] == "PASS" for x in rows)
n_held = sum(x["route"] == "Held for approval" for x in rows)
n_esc = sum(x["route"] == "Escalated to receptionist" for x in rows)
n_auto_ok = sum(x["route"] == "Auto-replied" and x["result"] == "PASS" for x in rows)
measures = [
    ("Accuracy on messages the AI had not been tuned on", "First-run pass rate over all test cases (tab 8)", f"='{MET}'!{M['first_rate']}", n_pass_first / N, f_pct_b),
    ("Accuracy after fixes", "Final pass rate - measured on cases used to drive the fixes, so NOT a prediction", f"='{MET}'!{M['final_rate']}", n_pass_final / N, f_pct_b),
    ("Automation rate on the test set", "Share of test messages answered with no human", f"='{MET}'!{M['auto']}", n_auto / N, f_pct_b),
    ("Escalation rate on the test set", "Share handed to a receptionist for a decision", f"='{MET}'!{M['esc']}", n_esc / N, f_pct_b),
    ("Correctness of automatic replies", "Of the messages auto-replied, the share whose test passed", f"='{MET}'!{M['prec']}", n_auto_ok / max(1, n_auto), f_pct_b),
    ("Unsafe outputs", "Independent check: unverified send, unknown price/doctor, internal text, claimed booking", f"='{MET}'!{M['invar']}", 0, f_int_b),
]
for i, (a, b, expr, val, fm) in enumerate(measures):
    ws1.write(r + 2 + i, 0, a, f_cell_b); ws1.write(r + 2 + i, 1, b, f_cell)
    formula(ws1, r + 2 + i, 2, expr, val, fm)
    ws1.set_row(r + 2 + i, 30)
ws1.merge_range(r + 2 + len(measures), 0, r + 2 + len(measures), 2,
                "The test set deliberately contains many hard, adversarial and emergency messages, so its automation and escalation rates are NOT the rates real "
                "patient traffic would produce. Use a trial period with real messages to measure those.", f_note)
ws1.set_row(r + 2 + len(measures), 42)
ws1.set_landscape(); ws1.fit_to_pages(1, 0)

# ================================================================================================ 2. Clinic Knowledge Base
ws2 = sheet("2. Clinic Knowledge Base", "#2563EB", "Clinic Knowledge Base",
            "The clinic information the assistant is allowed to use (source files: data/clinic_facts.json, treatments.json, doctors.json, faqs.json). "
            "Edit it in the app's Knowledge Base page or in these files - no code changes needed.", [26, 34, 36, 15, 15, 20, 36, 30, 26, 16])
c = kb["clinic"]
row = 4
ws2.merge_range(row, 0, row, 9, "A. CLINIC FACTS", f_section); row += 1
for i, h in enumerate(["Field", "Value", "Status"]):
    ws2.write(row, i, h, f_head)
row += 1
facts = [("Clinic name", c["clinic_name"]), ("Tagline", c.get("tagline", "")), ("Address", c["address"]), ("Landmark", c.get("landmark", "")),
         ("Google Maps link", c.get("maps_link", "")), ("Parking", c.get("parking", "")), ("Phone", c["phone"]), ("Email", c.get("email", ""))]
facts += [(f"Opening hours – {t['days']}", t["hours"]) for t in c["timings"]]
facts += [("Closed days note", c.get("closed_note", "")), ("Emergency guidance", c.get("emergency_note", "")),
          ("Payment methods", ", ".join(c.get("payment_methods", []))), ("Insurance", c.get("insurance_note", "")),
          ("Languages spoken", ", ".join(c.get("languages", []))), ("Appointment policy", c.get("appointment_policy", ""))]
for k, v in facts:
    ws2.write(row, 0, k, f_label); ws2.merge_range(row, 1, row, 1, v, f_cell) if False else ws2.write(row, 1, v, f_cell)
    ws2.write(row, 2, "DUMMY sample – owner must verify", f_cell)
    ws2.set_row(row, 15 * max(1, -(-len(v) // 38)))
    row += 1
row += 1
ws2.merge_range(row, 0, row, 9, "B. TREATMENTS AND PRICES", f_section); row += 1
heads = ["ID", "Treatment", "Words patients use (aliases)", "Price from", "Price to", "Charged", "Price variants / notes", "Duration", "Handled by", "Status"]
for i, h in enumerate(heads):
    ws2.write(row, i, h, f_head)
treat_header_row = row
row += 1
doc_name = {d["id"]: d["name"] for d in kb["doctors"]}
for t in kb["treatments"]:
    variants = "; ".join(f"{v['name']}: {knowledge.format_price_range(v['price_min'], v['price_max'])}" for v in t.get("variants", []))
    notes = (variants + (" · " if variants and t.get("price_notes") else "") + t.get("price_notes", "")).strip()
    vals = [t["id"], t["name"], ", ".join(t["aliases"]), t["price_min"], t["price_max"], t["price_unit"], notes, t["duration"],
            ", ".join(doc_name.get(d, d) for d in t.get("handled_by", [])), "DUMMY sample"]
    for i, v in enumerate(vals):
        ws2.write(row, i, v, f_money if i in (3, 4) else f_cell)
    ws2.set_row(row, 15 * max(2, -(-len(notes) // 34), -(-len(vals[2]) // 34)))
    row += 1
row += 1
ws2.merge_range(row, 0, row, 9, "C. DOCTORS", f_section); row += 1
for i, h in enumerate(["ID", "Name", "Title / role", "Experience (years)", "", "Languages", "Qualification and specialties", "Available days and hours", "", "Status"]):
    ws2.write(row, i, h, f_head)
row += 1
for d in kb["doctors"]:
    vals = [d["id"], d["name"], d["title"], d["experience_years"], "", ", ".join(d.get("languages", [])),
            d["qualification"] + " · " + ", ".join(d.get("specialties", [])), knowledge.doctor_availability(d), "", "DUMMY sample"]
    for i, v in enumerate(vals):
        ws2.write(row, i, v, f_int if i == 3 else f_cell)
    ws2.set_row(row, 45)
    row += 1
row += 1
ws2.merge_range(row, 0, row, 9, "D. FREQUENTLY ASKED QUESTIONS", f_section); row += 1
for i, h in enumerate(["ID", "Question", "Words that trigger it (keywords)", "", "", "", "Approved answer", "", "", "Status"]):
    ws2.write(row, i, h, f_head)
row += 1
for fq in kb["faqs"]:
    ws2.write(row, 0, fq["id"], f_cell); ws2.write(row, 1, fq["question"], f_cell)
    ws2.merge_range(row, 2, row, 5, ", ".join(fq.get("keywords", [])), f_cell)
    ws2.merge_range(row, 6, row, 8, fq["answer"], f_cell)
    ws2.write(row, 9, "DUMMY sample", f_cell)
    ws2.set_row(row, 15 * max(2, -(-len(fq["answer"]) // 90)))
    row += 1
ws2.freeze_panes(4, 0)
ws2.set_landscape(); ws2.fit_to_pages(1, 0)
kb_counts = (len(facts), len(kb["treatments"]), len(kb["doctors"]), len(kb["faqs"]))

# ================================================================================================ 3. RAG Database
ws3 = sheet("3. RAG Database", "#7C3AED", "RAG Database – what the AI retrieves",
            f"The {len(kb['entries'])} 'entries' the retriever searches. Every treatment, doctor, FAQ and clinic fact becomes one entry with a stable ID. "
            "The AI may quote ONLY the text in column D, and every reply names the entry IDs it used (the internal source references). "
            "Columns H-I count how often each entry was retrieved / used across the test cases (live formulas over tab 6).",
            [26, 12, 32, 78, 40, 18, 9, 14, 14])
for i, h in enumerate(["Entry ID", "Type", "Title", "Text the AI is allowed to use", "Search keywords / aliases", "Source file", "Dummy?",
                       "Times retrieved in tests", "Times used in an answer"]):
    ws3.write(3, i, h, f_head)
ws3.set_row(3, 34)
r3 = 4
for e in kb["entries"]:
    n_ret = sum(e.id in x["retrieved"] for x in rows)
    n_used = sum(e.id in x["cited"] for x in rows)
    ws3.write(r3, 0, e.id, f_cell_b); ws3.write(r3, 1, e.kind, f_cell_c); ws3.write(r3, 2, e.title, f_cell)
    ws3.write(r3, 3, clip(e.text, 900), f_cell); ws3.write(r3, 4, ", ".join(e.keywords), f_cell); ws3.write(r3, 5, e.file, f_cell)
    ws3.write(r3, 6, "Yes" if e.dummy else "No", f_cell_c)
    formula(ws3, r3, 7, f'=COUNTIF({vr("E")},"*"&A{r3 + 1}&"*")', n_ret, f_int)
    formula(ws3, r3, 8, f'=COUNTIF({vr("F")},"*"&A{r3 + 1}&"*")', n_used, f_int)
    ws3.set_row(r3, 15 * max(2, -(-len(e.text) // 80)))
    r3 += 1
ws3.write(r3 + 1, 0, "Totals", f_label)
ws3.write_formula(r3 + 1, 7, f"=SUM(H5:H{r3})", f_int_b, sum(sum(e.id in x["retrieved"] for x in rows) for e in kb["entries"]))
ws3.write_formula(r3 + 1, 8, f"=SUM(I5:I{r3})", f_int_b, sum(sum(e.id in x["cited"] for x in rows) for e in kb["entries"]))
ws3.autofilter(3, 0, r3 - 1, 8)
ws3.freeze_panes(4, 1)
ws3.set_landscape(); ws3.fit_to_pages(1, 0)

# ================================================================================================ 4. Query Classification
INTENTS = [
    ("greeting", "Says hello", "hi, hello, namaste", "Replies with a welcome message", "Auto if checks pass"),
    ("thanks", "Thanks / acknowledgement", "thanks, ok, 👍", "Replies 'happy to help'", "Auto"),
    ("clinic_timings", "Asks opening hours", "timings, open, close, kab khulti hai", "Quotes the clinic hours", "Auto"),
    ("location", "Asks where the clinic is / parking", "where, address, map, kahan, parking", "Quotes address, landmark, map link", "Auto"),
    ("contact_info", "Asks phone / email", "phone number, email, WhatsApp number", "Quotes the clinic phone and email", "Auto"),
    ("treatment_price", "Asks what a treatment costs", "price, cost, fee, kitna, kharcha, free", "Quotes the price range of the named treatment", "Auto (price must exist in the knowledge base)"),
    ("treatment_info", "Asks about a treatment / how long / is it safe", "how long, procedure, painful, safe", "Quotes description, duration or matching FAQ", "Auto"),
    ("doctor_info", "Asks about doctors", "doctor, specialist, who does implants", "Quotes the doctor's title, experience, days", "Auto (doctor must exist)"),
    ("payment_insurance", "Asks about payment / insurance / EMI", "UPI, card, insurance, EMI", "Quotes payment methods and insurance note", "Auto"),
    ("general_faq", "Matches a stored FAQ", "walk-in, first visit, reports", "Quotes the approved FAQ answer", "Auto"),
    ("appointment_booking", "Wants to book / check availability", "book, slot, appointment, available tomorrow", "Collects name/time/reason; NEVER confirms a slot", "ALWAYS held for a receptionist"),
    ("appointment_change", "Wants to cancel / reschedule", "cancel, reschedule, move my appointment", "Asks for details; NEVER confirms a change", "ALWAYS held for a receptionist"),
    ("emergency", "Possible dental emergency", "severe, knocked out, bleeding won't stop, can't swallow", "Drafts call-now / hospital advice; flags URGENT", "ESCALATED – a person must act"),
    ("complaint", "Complaint / refund / unhappy", "refund, rude, overcharged, bad experience", "Drafts an apology for the manager", "ESCALATED – a person must act"),
    ("medical_advice", "Asks for diagnosis, medicine or treatment choice", "which painkiller, is it normal, should I get a filling", "Says it cannot give medical advice", "ESCALATED – a person must act"),
    ("unknown", "Not understood / not in the knowledge base", "(anything else)", "Fixed notice: 'I don't have that information, I've asked reception'", "ESCALATED with notice"),
]
ws4 = sheet("4. Query Classification", "#D97706", "Query Classification – what patients ask and how the AI labels it",
            "Top: the question categories (intents) the classifier knows and how each is handled. Below: every test query with the category the AI "
            "identified, its confidence, language style and whether it was flagged urgent. The classifier is plain keyword/regex rules (no ML), so every label can be explained.",
            [24, 56, 34, 30, 30, 11, 11, 11, 30, 14])
INT_HEAD, INT_FIRST = 3, 4
for i, h in enumerate(["Intent (category)", "What the patient wants", "Typical words (English / Hinglish)", "What the AI does", "Routing policy", "Test queries with this label"]):
    ws4.write(INT_HEAD, i, h, f_head)
ws4.set_row(INT_HEAD, 34)
LIST_HEAD = INT_FIRST + len(INTENTS) + 3        # zero-based row of the list header
LIST_FIRST = LIST_HEAD + 1                       # zero-based first data row
LIST_LAST = LIST_FIRST + N - 1
intent_counts = Counter(x["r"].intent for x in rows)
for k, (intent, want, words, does, policy) in enumerate(INTENTS):
    rr = INT_FIRST + k
    for i, v in enumerate([intent, want, words, does, policy]):
        ws4.write(rr, i, v, f_cell_b if i == 0 else f_cell)
    formula(ws4, rr, 5, f"=COUNTIF($D${LIST_FIRST + 1}:$D${LIST_LAST + 1},A{rr + 1})", intent_counts.get(intent, 0), f_int)
    ws4.set_row(rr, 30)
tot_row = INT_FIRST + len(INTENTS)
ws4.write(tot_row, 4, "Total queries", f_label)
formula(ws4, tot_row, 5, f"=SUM(F{INT_FIRST + 1}:F{tot_row})", sum(intent_counts.get(i[0], 0) for i in INTENTS), f_int_b)
ws4.merge_range(LIST_HEAD - 1, 0, LIST_HEAD - 1, 9, "CLASSIFIED TEST QUERIES (final run)", f_section)
for i, h in enumerate(["Case ID", "Patient message", "Language style", "Primary intent", "All topics detected", "Confidence", "Sensitive topic?",
                       "Urgent?", "Expected topic(s)", "Primary topic is expected?"]):
    ws4.write(LIST_HEAD, i, h, f_head)
ws4.set_row(LIST_HEAD, 34)
SENS = {"emergency", "complaint", "medical_advice"}
for k, x in enumerate(rows):
    rr = LIST_FIRST + k
    case, res = x["case"], x["r"]
    expected = ", ".join(case.intent_any or case.intents_include)
    ws4.write(rr, 0, case.id, f_cell_b); ws4.write(rr, 1, clip(case.message, 400), f_cell)
    ws4.write(rr, 2, language_of(case, case.message), f_cell); ws4.write(rr, 3, res.intent, f_cell_b)
    ws4.write(rr, 4, ", ".join(res.intents), f_cell); ws4.write(rr, 5, res.confidence, f_conf)
    ws4.write(rr, 6, "Yes" if res.intent in SENS else "No", f_cell_c); ws4.write(rr, 7, x["urgent"], f_cell_c)
    ws4.write(rr, 8, expected, f_cell)
    match = "n/a" if not expected else ("Yes" if res.intent in (case.intent_any or case.intents_include) else "No")
    formula(ws4, rr, 9, f'=IF(I{rr + 1}="","n/a",IF(ISNUMBER(SEARCH(D{rr + 1},I{rr + 1})),"Yes","No"))', match, f_cell_c)
ws4.autofilter(LIST_HEAD, 0, LIST_LAST, 9)
ws4.freeze_panes(LIST_HEAD + 1, 0) if False else ws4.freeze_panes(4, 0)
ws4.conditional_format(LIST_FIRST, 7, LIST_LAST, 7, {"type": "cell", "criteria": "==", "value": '"Yes"', "format": f_bad})
ws4.conditional_format(LIST_FIRST, 9, LIST_LAST, 9, {"type": "cell", "criteria": "==", "value": '"No"', "format": f_bad})
ws4.set_landscape(); ws4.fit_to_pages(1, 0)

# ================================================================================================ 5. Test Cases
ws5 = sheet(TC, "#059669", "Test Cases",
            f"{N} test cases in four rounds (the brief asked for at least 30). Each states what SHOULD happen, written BEFORE the case was run. "
            "Categories: prices & treatments · doctors & timings · Hindi/Hinglish · multiple requests · appointment availability · no information · "
            "incorrect assumptions · medical/medicine · emergency/urgent · prompt injection · message styles.",
            [9, 9, 22, 54, 28, 24, 24, 34, 34, 10, 46])
for i, h in enumerate(["Case ID", "Round", "Category", "Patient message (input)", "Earlier message in the same chat", "Expected result", "Expected topic(s)",
                       "Facts the reply must contain", "Must never say / claim", "Must be flagged urgent?", "Why this case exists"]):
    ws5.write(3, i, h, f_head)
ws5.set_row(3, 40)
for k, x in enumerate(rows):
    case, rr = x["case"], FIRST - 1 + k
    must_not = list(case.must_not_contain) + [f"(pattern) {p[:40]}…" if len(p) > 40 else f"(pattern) {p}" for p in case.must_not_match]
    vals = [case.id, x["rn"], case.category, case.message, "; ".join(case.prior), expected_route(case), ", ".join(case.intent_any or case.intents_include),
            "; ".join(case.must_contain), "; ".join(must_not), "" if case.urgent is None else ("Yes" if case.urgent else "No"), case.note]
    for i, v in enumerate(vals):
        ws5.write(rr, i, v, f_cell_b if i == 0 else f_cell_c if i in (1, 9) else f_cell)
ws5.autofilter(3, 0, LAST - 1, 10)
ws5.freeze_panes(4, 1)
ws5.set_landscape(); ws5.fit_to_pages(1, 0)

# ================================================================================================ 6. Verification Results
ws6 = sheet(VRN, "#DC2626", "Verification Results – what the AI answered and whether it passed",
            "For every test case: the knowledge entries retrieved, the answer, the verification gate's decision, how the message was routed, and whether the case passed. "
            "'Final' = the system after all fixes; 'First run' = how it behaved the first time the case was run (before it was fixed). "
            "A failed-then-fixed case is a bug the testing found; the cause of each is in documentation/QA_REPORT.md.",
            [9, 9, 22, 40, 34, 26, 62, 22, 30, 22, 9, 34, 34, 10, 10, 30, 11, 50])
for i, h in enumerate(["Case ID", "Round", "Category", "Patient message", "Knowledge entries retrieved (match score)", "Entries cited in the answer",
                       "AI-generated answer (what the patient reads, or the held draft)", "Verification gate", "Failed checks", "Routing outcome",
                       "Flagged urgent", "Expected", "Actual", "Test result (final)", "Test result (first run)", "First-run failure kind",
                       "Safety-rule violations", "Notes (problems; what fixed it)"]):
    ws6.write(3, i, h, f_head)
ws6.set_row(3, 52)
for k, x in enumerate(rows):
    rr, res, case = FIRST - 1 + k, x["r"], x["case"]
    vals = [case.id, x["rn"], case.category, clip(case.message, 400), x["retrieved"], x["cited"], clip(res.answer), x["gate"],
            ", ".join(c["name"] for c in res.failed_checks), x["route"], x["urgent"], clip(res.expected_summary, 300), clip(res.actual_summary, 300),
            x["result"], x["first_result"], x["kind"]]
    for i, v in enumerate(vals):
        ws6.write(rr, i, v, f_cell_b if i == 0 else f_cell_c if i in (1, 10, 13, 14) else f_cell)
    ws6.write_number(rr, 16, x["invariants"], f_int)
    ws6.write(rr, 17, clip(x["note"], 500), f_cell)
ws6.autofilter(3, 0, LAST - 1, 17)
ws6.freeze_panes(4, 1)
for col in (13, 14):
    ws6.conditional_format(FIRST - 1, col, LAST - 1, col, {"type": "cell", "criteria": "==", "value": '"PASS"', "format": f_good})
    ws6.conditional_format(FIRST - 1, col, LAST - 1, col, {"type": "cell", "criteria": "==", "value": '"FAIL"', "format": f_bad})
ws6.conditional_format(FIRST - 1, 7, LAST - 1, 7, {"type": "text", "criteria": "begins with", "value": "PASSED", "format": f_good})
ws6.conditional_format(FIRST - 1, 7, LAST - 1, 7, {"type": "text", "criteria": "begins with", "value": "HELD", "format": f_warn})
ws6.conditional_format(FIRST - 1, 7, LAST - 1, 7, {"type": "text", "criteria": "begins with", "value": "BLOCKED", "format": f_bad})
ws6.set_landscape(); ws6.fit_to_pages(1, 0)

# ================================================================================================ 7. Human Handoff
ACTION = {
    "emergency": "Phone the patient now (or reply immediately); advise hospital emergency care if bleeding/breathing/jaw injury.",
    "complaint": "Clinic manager contacts the patient personally; do not argue by chat.",
    "medical_advice": "Dentist or receptionist replies; arrange a visit. The AI gives no medical advice.",
    "appointment_booking": "Check the real calendar, then confirm a slot (edit the draft with the time) and Approve.",
    "appointment_change": "Find the booking, apply the change, confirm to the patient and Approve.",
    "unknown": "Answer the question; if patients keep asking it, add it to the Knowledge Base.",
}
hand = [x for x in rows if x["r"].status != "auto_replied"]
hand.sort(key=lambda x: (0 if x["r"].urgent else 1, 0 if x["r"].status == "escalated" else 1, x["case"].id))
ws7 = sheet(HAND, "#9333EA", "Human Handoff – queries that need a receptionist",
            "Every test message the AI did NOT answer by itself (final run). 'Escalated' = a person must handle it; 'Held for approval' = the AI wrote a draft but nothing is sent "
            "until a receptionist approves, edits or rejects it. Urgent items go first. These rows are what the dashboard shows the receptionist.",
            [9, 44, 24, 11, 56, 30, 60, 52])
for i, h in enumerate(["Case ID", "Patient message", "Handoff type", "Priority", "Why it was handed off", "What the patient received", "AI draft shown to the receptionist",
                       "Suggested receptionist action"]):
    ws7.write(8, i, h, f_head)
ws7.set_row(8, 34)
H1, HL = 10, 10 + len(hand) - 1      # Excel rows of the data
ws7.write(4, 0, "Summary (live formulas)", f_label); ws7.write(4, 1, "", f_label)
sumrows = [("Messages handed to a person", f"=COUNTA(A{H1}:A{HL})", len(hand)),
           ("...Escalated (a person must handle it)", f'=COUNTIF(C{H1}:C{HL},"Escalated")', sum(x["r"].status == "escalated" for x in hand)),
           ("...Held for approval (draft waiting)", f'=COUNTIF(C{H1}:C{HL},"Held for approval")', sum(x["r"].status == "pending_approval" for x in hand)),
           ("...URGENT (emergencies)", f'=COUNTIF(D{H1}:D{HL},"URGENT")', sum(x["r"].urgent for x in hand))]
for i, (lab, expr, val) in enumerate(sumrows):
    ws7.write(4 + i, 1, lab, f_label)
    formula(ws7, 4 + i, 2, expr, val, f_int_b)
ws7.write(4, 3, "", f_label)
for i, x in enumerate(hand):
    rr, res = 9 + i, x["r"]
    reason = res.reasons[0] if res.reasons else ""
    received = "Fixed notice only: 'I don't have that information, I've passed it to reception'" if res.sent_text else "Nothing (held)"
    draft = res.draft if res.draft else "(none - the AI had no answer; the fixed notice was sent)"
    action = ACTION.get(res.intent, ACTION["unknown"] if res.status == "escalated" else "Review the draft, edit if needed, then Approve or Reject.")
    vals = [x["case"].id, clip(x["case"].message, 300), "Escalated" if res.status == "escalated" else "Held for approval",
            "URGENT" if res.urgent else "Normal", reason, received, clip(draft, 600), action]
    for j, v in enumerate(vals):
        ws7.write(rr, j, v, f_cell_b if j == 0 else f_cell_c if j in (2, 3) else f_cell)
ws7.autofilter(8, 0, 9 + len(hand) - 1, 7)
ws7.freeze_panes(9, 1)
ws7.conditional_format(9, 3, 9 + len(hand) - 1, 3, {"type": "cell", "criteria": "==", "value": '"URGENT"', "format": f_bad})
ws7.conditional_format(9, 2, 9 + len(hand) - 1, 2, {"type": "cell", "criteria": "==", "value": '"Held for approval"', "format": f_warn})
ws7.set_landscape(); ws7.fit_to_pages(1, 0)

# ================================================================================================ 8. Performance Metrics
ws8 = sheet(MET, "#0891B2", "Performance Metrics",
            "Accuracy, escalation rate and automation rate - all live formulas over tab 6 (change a result there and these update). "
            "READ THE NOTES AT THE BOTTOM: the first-run figure is the honest accuracy; the final figure is on cases the fixes were made against.",
            [58, 20, 20, 20, 20, 20, 20], banner=False)
ws8.merge_range(3, 0, 3, 6, "A. HEADLINE METRICS", f_section)
for i, h in enumerate(["Metric", "Value", "How it is calculated"]):
    ws8.write(4, i, h, f_head)
ws8.merge_range(4, 2, 4, 6, "How it is calculated", f_head)
cat_total = {k: sum(x["case"].category == k for x in rows) for k in CAT_ORDER}
vals_ = {
    "total": (f"=COUNTA({vr('A')})", N, "Number of rows on tab 6"),
    "final_pass": (f'=COUNTIF({vr("N")},"PASS")', n_pass_final, "Cases whose final result is PASS"),
    "final_rate": (f"=B7/B6", n_pass_final / N, "Final passes ÷ total (after fixes; tuned-on data)"),
    "first_pass": (f'=COUNTIF({vr("O")},"PASS")', n_pass_first, "Cases that passed the first time they were run"),
    "first_rate": (f"=B9/B6", n_pass_first / N, "First-run passes ÷ total - use this as the accuracy figure"),
    "auto": (f'=COUNTIF({vr("J")},"Auto-replied")/B6', n_auto / N, "Auto-replied ÷ total (test set, not real traffic)"),
    "held": (f'=COUNTIF({vr("J")},"Held for approval")/B6', n_held / N, "Held for approval ÷ total"),
    "esc": (f'=COUNTIF({vr("J")},"Escalated to receptionist")/B6', n_esc / N, "Escalated ÷ total"),
    "hand": ("=B12+B13", (n_held + n_esc) / N, "Held + escalated"),
    "prec": (f'=COUNTIFS({vr("J")},"Auto-replied",{vr("N")},"PASS")/COUNTIF({vr("J")},"Auto-replied")', n_auto_ok / max(1, n_auto),
             "Of the auto-replied messages, those whose test passed"),
    "emer_n": (f'=COUNTIF({vr("C")},"Emergency / urgent")', cat_total["Emergency / urgent"], "Cases in the Emergency / urgent category"),
    "emer_flag": (f'=COUNTIFS({vr("C")},"Emergency / urgent",{vr("K")},"Yes")', sum(x["case"].category == "Emergency / urgent" and x["urgent"] == "Yes" for x in rows),
                  "Emergency cases flagged URGENT. The other 2 ('still bleeding' after an extraction; 'my crown fell out') were escalated to a person but are not flagged urgent"),
    "invar": (f"=SUM({vr('Q')})", sum(x["invariants"] for x in rows), "Independent check: unverified send, unknown price/doctor, internal text, booking claimed"),
}
for i, (key, label, kind) in enumerate(MET_ROWS):
    rr = 5 + i
    expr, val, how = vals_[key]
    key_rows = key in ("first_rate", "final_rate")
    ws8.write(rr, 0, label, f_cell_b if key_rows else f_cell)
    formula(ws8, rr, 1, expr, val, (f_pct_b if key_rows else f_pct) if kind == "pct" else f_int_b if key_rows else f_int)
    ws8.merge_range(rr, 2, rr, 6, how, f_cell)
row = 5 + len(MET_ROWS) + 1

# ---- B by round
ws8.merge_range(row, 0, row, 6, "B. ACCURACY BY ROUND", f_section); row += 1
for i, h in enumerate(["Round", "Cases", "First run: passed", "First-run accuracy", "Final: passed", "Final accuracy", "Written"]):
    ws8.write(row, i, h, f_head)
ws8.set_row(row, 30); row += 1
ROUND_NOTE = {"Round 1": "Before any run; drove the first fixes", "Round 2": "Blind, after round-1 fixes", "Round 3": "Blind, after round-2 fixes", "Round 4": "Blind, after round-3 fixes"}
round_first = row
for rn, cases in ROUNDS:
    nn = len(cases)
    p1 = sum(x["first_result"] == "PASS" for x in rows if x["rn"] == rn)
    pf = sum(x["result"] == "PASS" for x in rows if x["rn"] == rn)
    ws8.write(row, 0, rn, f_cell_b)
    formula(ws8, row, 1, f'=COUNTIF({vr("B")},A{row + 1})', nn, f_int)
    formula(ws8, row, 2, f'=COUNTIFS({vr("B")},A{row + 1},{vr("O")},"PASS")', p1, f_int)
    formula(ws8, row, 3, f"=C{row + 1}/B{row + 1}", p1 / nn, f_pct)
    formula(ws8, row, 4, f'=COUNTIFS({vr("B")},A{row + 1},{vr("N")},"PASS")', pf, f_int)
    formula(ws8, row, 5, f"=E{row + 1}/B{row + 1}", pf / nn, f_pct)
    ws8.write(row, 6, ROUND_NOTE[rn], f_cell)
    row += 1
round_last = row - 1
ws8.write(row, 0, "All rounds", f_label)
formula(ws8, row, 1, f"=SUM(B{round_first + 1}:B{round_last + 1})", N, f_int_b)
formula(ws8, row, 2, f"=SUM(C{round_first + 1}:C{round_last + 1})", n_pass_first, f_int_b)
formula(ws8, row, 3, f"=C{row + 1}/B{row + 1}", n_pass_first / N, f_pct_b)
formula(ws8, row, 4, f"=SUM(E{round_first + 1}:E{round_last + 1})", n_pass_final, f_int_b)
formula(ws8, row, 5, f"=E{row + 1}/B{row + 1}", n_pass_final / N, f_pct_b)
ws8.write(row, 6, "", f_label)
row += 2

# ---- C by category
ws8.merge_range(row, 0, row, 6, "C. ACCURACY BY CATEGORY", f_section); row += 1
for i, h in enumerate(["Category", "Cases", "First run: passed", "First-run accuracy", "Final: passed", "Final accuracy", "Auto-replied"]):
    ws8.write(row, i, h, f_head)
ws8.set_row(row, 30); row += 1
cat_first = row
for cat in CAT_ORDER:
    sub = [x for x in rows if x["case"].category == cat]
    nn = len(sub)
    p1 = sum(x["first_result"] == "PASS" for x in sub); pf = sum(x["result"] == "PASS" for x in sub)
    ws8.write(row, 0, cat, f_cell_b)
    formula(ws8, row, 1, f'=COUNTIF({vr("C")},A{row + 1})', nn, f_int)
    formula(ws8, row, 2, f'=COUNTIFS({vr("C")},A{row + 1},{vr("O")},"PASS")', p1, f_int)
    formula(ws8, row, 3, f"=C{row + 1}/B{row + 1}", p1 / nn, f_pct)
    formula(ws8, row, 4, f'=COUNTIFS({vr("C")},A{row + 1},{vr("N")},"PASS")', pf, f_int)
    formula(ws8, row, 5, f"=E{row + 1}/B{row + 1}", pf / nn, f_pct)
    formula(ws8, row, 6, f'=COUNTIFS({vr("C")},A{row + 1},{vr("J")},"Auto-replied")', sum(x["route"] == "Auto-replied" for x in sub), f_int)
    row += 1
cat_last = row - 1
row += 1

# ---- D routing mix
ws8.merge_range(row, 0, row, 6, "D. HOW MESSAGES WERE ROUTED (final run)", f_section); row += 1
for i, h in enumerate(["Outcome", "Messages", "Share"]):
    ws8.write(row, i, h, f_head)
row += 1
route_first = row
for lab in ROUTE_ORDER:
    cnt = sum(x["route"] == lab for x in rows)
    ws8.write(row, 0, lab, f_cell_b)
    formula(ws8, row, 1, f'=COUNTIF({vr("J")},A{row + 1})', cnt, f_int)
    formula(ws8, row, 2, f"=B{row + 1}/$B$6", cnt / N, f_pct)
    row += 1
route_last = row - 1
row += 1

# ---- E first-run failures
ws8.merge_range(row, 0, row, 6, "E. WHAT WENT WRONG THE FIRST TIME A CASE WAS RUN", f_section); row += 1
for i, h in enumerate(["Kind of first-run failure", "Cases", "Why it matters"]):
    ws8.write(row, i, h, f_head)
ws8.merge_range(row, 2, row, 6, "Why it matters", f_head)
row += 1
WHY = {KIND_ORDER[0]: "Reached a patient and should have waited for a person - most serious", KIND_ORDER[1]: "Reached a patient and was wrong or incomplete - most serious",
       KIND_ORDER[2]: "A person would not have been alerted first", KIND_ORDER[3]: "Safe, but costs reception time", KIND_ORDER[4]: "Safe; wrong label or draft text",
       KIND_ORDER[5]: "My own mistake in the test, not a fault of the AI"}
kind_counts = Counter(x["kind"] for x in rows if x["kind"])
kind_first = row
for kind in KIND_ORDER:
    ws8.write(row, 0, kind, f_cell)
    formula(ws8, row, 1, f'=COUNTIF({vr("P")},A{row + 1})', kind_counts.get(kind, 0), f_int)
    ws8.merge_range(row, 2, row, 6, WHY[kind], f_cell)
    row += 1
ws8.write(row, 0, "Total first-run failures", f_label)
formula(ws8, row, 1, f"=SUM(B{kind_first + 1}:B{row})", sum(kind_counts.values()), f_int_b)
ws8.merge_range(row, 2, row, 6, "Total cases minus first-run passes", f_cell)
row += 2

# ---- F what-if
ws8.merge_range(row, 0, row, 6, "F. ILLUSTRATIVE EXAMPLE: reception time saved (change the yellow cells)", f_section); row += 1
wi = row
ws8.write(row, 0, "Enquiries per day", f_cell); ws8.write_number(row, 1, 150, f_input)
ws8.merge_range(row, 2, row, 6, "Input (blue): 150 is the figure in the project brief", f_cell); row += 1
ws8.write(row, 0, "Share answered automatically", f_cell)
formula(ws8, row, 1, f"=B{6 + [k for k, *_ in MET_ROWS].index('auto')}", n_auto / N, fmt(valign="top", align="center", border=1, border_color="#D1D5DB",
                                                                                              num_format="0%", font_color="#0000FF", bg_color="#FFFF99"))
ws8.merge_range(row, 2, row, 6, "Starts as this test set's automation rate (assumption). REPLACE it with the rate from a real trial: the test set is not real traffic.", f_cell); row += 1
ws8.write(row, 0, "Minutes a receptionist spends on one routine reply", f_cell); ws8.write_number(row, 1, 2, f_input)
ws8.merge_range(row, 2, row, 6, "Input (blue): assumption; 2 is the default used by the dashboard's 'time saved' estimate", f_cell); row += 1
ws8.write(row, 0, "Reception hours saved per day (illustrative)", f_cell_b)
formula(ws8, row, 1, f"=B{wi + 1}*B{wi + 2}*B{wi + 3}/60", 150 * (n_auto / N) * 2 / 60, f_out)
ws8.merge_range(row, 2, row, 6, "Calculated as enquiries × automation share × minutes ÷ 60. An example calculation, not a measured result.", f_cell); row += 2

# ---- notes
ws8.merge_range(row, 0, row, 6, "HOW TO READ THESE NUMBERS", f_section); row += 1
notes = [
    "1. The FIRST-RUN pass rate is the honest accuracy: the cases in rounds 2-4 were written after earlier fixes and not run until finished, so the AI had not been tuned on them.",
    "2. The FINAL pass rate is high because the AI was repaired against these same cases. It is not a prediction for real patients and it is not 100%: one case still fails (R-G2). "
    "'Auto-replies that were correct' is likewise a final-run figure; on first runs some auto-replies were wrong (see section E).",
    "3. The first-run rate did not rise from round to round: each new set of messages exposed new gaps (mostly vocabulary and phrasing). Expect that to continue with real patients.",
    "4. Automation and escalation rates describe THIS test set, which deliberately over-represents emergencies, medical questions, injection attempts and unusual wording.",
    "5. Eight of the first-run failures were mistakes in the tests themselves (not the AI); they are counted as failures and labelled on tab 6.",
    "6. All results are from the offline template mode. The Claude (LLM) answer path and the live Meta WhatsApp connection have not been tested.",
]
for n_ in notes:
    ws8.merge_range(row, 0, row, 6, n_, f_note); ws8.set_row(row, 30); row += 1

# charts
ch1 = wb.add_chart({"type": "column"})
for col, name, color in ((3, "First-run accuracy", "#F59E0B"), (5, "Final accuracy (after fixes)", "#0F766E")):
    ch1.add_series({"name": name, "categories": [MET, round_first, 0, round_last, 0], "values": [MET, round_first, col, round_last, col],
                    "fill": {"color": color}, "data_labels": {"value": True, "num_format": "0%", "font": {"name": "Arial", "size": 9}}})
ch1.set_title({"name": "Accuracy by round", "name_font": {"name": "Arial", "size": 11}, "overlay": False})
ch1.set_y_axis({"min": 0, "max": 1, "num_format": "0%", "major_gridlines": {"visible": True, "line": {"color": "#E5E7EB"}}, "name": "Cases passed", "name_font": {"name": "Arial", "size": 9}})
ch1.set_x_axis({"num_font": {"name": "Arial", "size": 9}})
ch1.set_legend({"position": "bottom", "overlay": False, "font": {"name": "Arial", "size": 9}})
ch1.set_size({"width": 560, "height": 300}); ch1.set_chartarea({"border": {"none": True}})
ws8.insert_chart(3, 8, ch1)

ch2 = wb.add_chart({"type": "pie"})
ch2.add_series({"name": "Routing", "categories": [MET, route_first, 0, route_last, 0], "values": [MET, route_first, 1, route_last, 1],
                "points": [{"fill": {"color": "#0F766E"}}, {"fill": {"color": "#F59E0B"}}, {"fill": {"color": "#DC2626"}}],
                "data_labels": {"percentage": True, "font": {"name": "Arial", "size": 9}}})
ch2.set_title({"name": "How messages were routed (test set)", "name_font": {"name": "Arial", "size": 11}, "overlay": False})
ch2.set_legend({"position": "bottom", "overlay": False, "font": {"name": "Arial", "size": 9}})
ch2.set_size({"width": 560, "height": 300}); ch2.set_chartarea({"border": {"none": True}})
ws8.insert_chart(19, 8, ch2)

ch3 = wb.add_chart({"type": "bar"})
for col, name, color in ((3, "First run", "#F59E0B"), (5, "After fixes", "#0F766E")):
    ch3.add_series({"name": name, "categories": [MET, cat_first, 0, cat_last, 0], "values": [MET, cat_first, col, cat_last, col], "fill": {"color": color}})
ch3.set_title({"name": "Accuracy by category", "name_font": {"name": "Arial", "size": 11}, "overlay": False})
ch3.set_x_axis({"min": 0, "max": 1, "num_format": "0%", "num_font": {"name": "Arial", "size": 9}})
ch3.set_y_axis({"reverse": True, "num_font": {"name": "Arial", "size": 9}})
ch3.set_legend({"position": "bottom", "overlay": False, "font": {"name": "Arial", "size": 9}})
ch3.set_size({"width": 560, "height": 380}); ch3.set_chartarea({"border": {"none": True}})
ws8.insert_chart(35, 8, ch3)
ws8.set_landscape(); ws8.fit_to_pages(1, 0)

wb.close()
print(f"wrote {OUT.relative_to(ROOT)}: {N} test cases, {len(hand)} human-handoff rows, {len(kb['entries'])} RAG entries, "
      f"KB (facts/treatments/doctors/faqs) = {kb_counts}")
