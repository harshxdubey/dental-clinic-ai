"""STAGE 5 - VERIFIER: nothing reaches a patient until this has checked it.

Every check is plain code (patterns, lookups in the clinic's knowledge base, arithmetic). No AI
model is ever asked "is this answer correct?" - a model that wrote a wrong answer can easily
believe it is right, so it is never allowed to grade itself.

The checks are grouped under five questions:

  1. SOURCE          Is there a relevant entry in the knowledge base, and does the answer cite it?
  2. PRICE / DOCTOR  Does the answer contain a price or a doctor name that is not in its sources?
  3. CALENDAR        Does it say an appointment is available or confirmed? (No calendar is
                     connected, so the assistant can never know - it must not claim it.)
  4. MEDICAL         Does it diagnose, or recommend medicine or treatment?
  5. VALID           Is it well formed (no placeholders, not cut off, no leaked instructions) and
                     does it actually answer what was asked?

Then the routing decision:

  AUTO_SEND       every check passed and the topic is safe -> sent to the patient automatically
  NEEDS_APPROVAL  a soft check failed (low confidence, appointment request...) -> held for a receptionist
  ESCALATE        a hard check failed, or the topic is sensitive -> held; a person must handle it

Failed answers are never sent. The same text-level checks are also run on a receptionist's edited
reply (see check_text) so a typo in a price is flagged before it reaches a patient.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field

from . import config, knowledge
from .ai_response import Draft
from .classifier import Classification
from .medical_terms import MEDICINE_TERMS
from .retriever import Source
from .textutils import extract_numbers, extract_prices, normalize

AUTO_SEND = "auto_send"
NEEDS_APPROVAL = "needs_approval"
ESCALATE = "escalate"

# Replies about appointments always need a receptionist to confirm the slot.
APPROVAL_INTENTS = {"appointment_booking", "appointment_change"}

GROUPS = [
    ("source", "1. Relevant source in the knowledge base"),
    ("price_doctor", "2. Prices and doctor names"),
    ("calendar", "3. Appointment availability"),
    ("medical", "4. Diagnosis and medicine"),
    ("validity", "5. Valid and complete"),
    ("routing", "Routing"),
]
_GROUP_ORDER = {key: i for i, (key, _) in enumerate(GROUPS)}

SENSITIVE_LABELS = {
    "emergency": "a possible dental emergency",
    "complaint": "a complaint",
    "medical_advice": "a medical question",
}
MAX_REPLY_CHARS = 900          # a reply written by the AI model: short and to the point
MAX_TEMPLATE_CHARS = 1600      # a reply assembled from the clinic's own entries: as long as the topics asked about need
MIN_REPLY_CHARS = 20

# ---- 2. claims the clinic never made ----------------------------------------------------------
UNSUPPORTED_CLAIM_TERMS = [
    "discount", "offer", "free", "guarantee", "guaranteed", "cure", "painless", "100%",
    "lifetime", "permanent", "cheapest", "best in", "cashless",
]
_DOCTOR_MENTION = re.compile(r"\bDr\.?\s+([A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+)?)")

# A patient quoting what the clinic supposedly promised ("you told me yesterday it costs 10,000, please honour that").
# The assistant cannot know what staff said, and neither agreeing nor disagreeing is its call: a person replies.
_PRIOR_CLAIM = re.compile("|".join([
    r"\b(?:you|your\s+(?:staff|team|receptionist|reception|doctor|clinic)|the\s+(?:receptionist|reception|doctor|staff)|someone\s+(?:at|from)\s+(?:your|the)\s+clinic)\s+"
    r"(?:had\s+|have\s+)?(?:told|said|promised|quoted|assured|confirmed|agreed|offered|guaranteed)\b",
    r"\b(?:honou?r|stick\s+to)\s+(?:that|this|the|your)\b",
    r"\bas\s+(?:agreed|promised|discussed|quoted|per\s+(?:our|the)\s+(?:call|discussion|conversation))\b",
    r"\baapne\s+(?:kaha|bola|bataya|promise)\b",
]), re.IGNORECASE)

# ---- 3. appointment claims (we have no calendar, so none of these may be said) -----------------
_CONFIRMED = re.compile("|".join([
    r"\b(?:your|the)\s+(?:appointment|slot|booking|visit|consultation|session)\s+(?:is|has\s+been|have\s+been|'s|’s)\s+(?:now\s+|successfully\s+)?(?:confirmed|booked|scheduled|reserved|fixed|set|done|ready)\b",
    r"\bI(?:'ve|’ve|\s+have)?\s+(?:just\s+|already\s+)?(?:booked|scheduled|reserved|confirmed|fixed|arranged|blocked)\b",
    r"\bI(?:'ll|’ll|\s+will)\s+(?:book|schedule|reserve|fix|confirm)\b",
    r"\b(?:you(?:'re|’re|\s+are)|you(?:'ve|’ve|\s+have))\s+(?:all\s+set|booked|confirmed|scheduled|registered)\b",
    r"\bsee\s+you\s+(?:on|at|tomorrow|today|tonight|then|this|next)\b",
    r"\b(?:booking|appointment)\s+(?:is\s+)?(?:confirmed|complete|completed|successful|done)\b",
    r"\bslot\s+(?:is\s+|has\s+been\s+)?(?:booked|reserved|yours|secured)\b",
]), re.IGNORECASE)
_AVAILABLE = re.compile("|".join([
    r"\b(?:slots?|openings?|appointments?|timings?)\s+(?:is\s+|are\s+)?(?:available|open|free|vacant)\b",
    r"\b(?:we|I)\s+(?:do\s+)?have\s+(?:a\s+|an\s+|some\s+|several\s+)?(?:free\s+|open\s+|available\s+)?(?:slots?|openings?|appointments?)\b",
    r"\b(?:is|are|we're|we\s+are)\s+(?:currently\s+)?(?:available|free|in)\s+(?:today|tomorrow|tonight|this|next|at\s+\d)",
    r"\b(?:we|doctors?|dr\.?\s+[a-z]+(?:\s+[a-z]+)?)\s+can\s+(?:see|fit|take|accommodate|squeeze)\s+you\b",
    r"\byou\s+can\s+(?:come|visit|drop\s+in|walk\s+in)(?:\s+(?:in|over|by))?\s+(?:at\s+\d|today|tomorrow|tonight|this\s)",
]), re.IGNORECASE)

# ---- 4. medical ------------------------------------------------------------------------------
# MEDICINE_TERMS (the drug and brand names a reply may not use) lives in medical_terms.py, shared with the classifier.
_CONDITIONS = (r"(?:infection|infected|cavity|cavities|abscess|gum\s+disease|gingivitis|periodontitis|decay|"
               r"cracked\s+tooth|pulpitis|nerve\s+damage|sinus|ulcer|cancer)")
_DIAGNOSIS = re.compile("|".join([
    rf"\byou\s+(?:probably\s+|likely\s+|may\s+|might\s+|could\s+|definitely\s+)?(?:have|has|are\s+suffering\s+from|suffer\s+from|got)\s+(?:an?\s+)?{_CONDITIONS}",
    rf"\b(?:it|this|that)\s+(?:is|looks\s+like|sounds\s+like|seems\s+like|could\s+be|might\s+be|may\s+be|is\s+probably|is\s+likely)\s+(?:an?\s+)?{_CONDITIONS}",
    r"\b(?:your|the)\s+(?:tooth|teeth|gums?)\s+(?:is|are)\s+(?:infected|decayed|damaged|inflamed|abscessed)",
    r"\bsymptoms?\s+of\b",
]), re.IGNORECASE)
_RECOMMEND = re.compile("|".join([
    r"\byou\s+(?:need|require)\s+(?:an?\s|the\s|some\s|to\s+(?:have|get|take|undergo|use)\b)",
    r"\byou\s+(?:must\s+have|should\s+(?:have|get|take|use|apply|rinse|avoid|stop|start))\b",
    r"\bI\s+(?:would\s+)?(?:recommend|advise|suggest)\b",
    r"\b(?:try|use|apply|take|rinse\s+with|gargle|chew)\s+(?:some\s+)?(?:clove|salt\s+water|warm\s+water|ice|a\s+cold\s+compress|an?\s+(?:painkiller|antibiotic)|antiseptic|mouthwash|numbing)",
]), re.IGNORECASE)

# ---- 5. validity ------------------------------------------------------------------------------
_PLACEHOLDER = re.compile(
    r"\{[^{}\n]{1,40}\}|\[(?!treatment:|doctor:|faq:|clinic:)[A-Za-z][^\[\]\n]{0,40}\]|<[A-Za-z_ /]{1,30}>|"
    r"\bTODO\b|lorem\s+ipsum|\bXXX+\b|\[insert|\(insert", re.IGNORECASE)
_LEAK = re.compile(
    r"\b(?:SOURCES|ANSWER|NO_ANSWER)\s*:|\b(?:treatment|doctor|faq|clinic):[a-z_]+\b|system\s+prompt|<sources>|"
    r"<patient_message>|\bas\s+an\s+ai\b|language\s+model|\bI\s+(?:cannot|can't|am\s+unable\s+to)\s+(?:assist|help)\s+with|"
    r"\bI'm\s+sorry,\s+but\s+I\s+(?:can't|cannot)\b", re.IGNORECASE)
_MARKDOWN = re.compile(r"\*\*[^*\n]+\*\*|^\s*#{1,6}\s|```|\[[^\]\n]+\]\(https?://", re.MULTILINE)
_PROPER_END = re.compile(
    r"([.!?…)\]\"'”’:;]|[\U0001F300-\U0001FAFF☀-➿️]|https?://\S+|\S+@\S+\.\S+|\d)\s*$")


@dataclass
class Check:
    name: str
    label: str
    passed: bool
    severity: str    # "block" -> escalate, "warn" -> needs approval, "info" -> informational
    detail: str
    group: str = "validity"


@dataclass
class Verdict:
    decision: str
    reasons: list = field(default_factory=list)
    checks: list = field(default_factory=list)
    text_hash: str = ""    # fingerprint of the exact text that was verified (see outbound.send_reply)

    def to_dict(self) -> dict:
        return {"decision": self.decision, "reasons": self.reasons, "checks": [asdict(c) for c in self.checks],
                "text_hash": self.text_hash}


def hash_text(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def _word_in(term: str, text: str) -> bool:
    return bool(re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", text))


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [re.sub(r"^[•\-\*\s]+", "", p).strip() for p in parts if p.strip()]


def _claims(pattern: re.Pattern, text: str, source_norm: str = "", exempt_if_in_sources: bool = False) -> list[str]:
    """Sentences that match a pattern.

    With exempt_if_in_sources, a match is ignored when the clause it is in (the part between colons or
    semicolons) is word-for-word in the clinic's own entries - the clinic is allowed to say its own things.
    """
    found = []
    for sentence in _sentences(text):
        for match in pattern.finditer(sentence):
            clause = next((c for c in re.split(r"[:;]", sentence) if match.group() in c), sentence)
            if exempt_if_in_sources and source_norm and normalize(clause) in source_norm:
                continue
            found.append(sentence)
            break
    return found


def _quote(items: list[str], limit: int = 2) -> str:
    return "; ".join(f"“{i[:90]}”" for i in items[:limit])


def _doctor_problems(text: str, source_low: str, patient_low: str) -> list[str]:
    """Doctor names that are not real, or are real but not mentioned in the answer's sources."""
    doctors = knowledge.load()["doctors"]
    lowered = text.lower()
    problems, referenced = [], {}

    def tokens(d: dict) -> set:
        return {t for t in normalize(d["name"]).split() if t != "dr"}

    for match in _DOCTOR_MENTION.finditer(text):
        mention = {t for t in normalize(match.group(1)).split()}
        doctor = next((d for d in doctors if mention and mention <= tokens(d)), None)
        if doctor is None:
            problems.append(f"“{match.group(0).strip()}” is not a doctor at this clinic")
        else:
            referenced[doctor["id"]] = doctor
    for d in doctors:  # a doctor named without the "Dr." prefix
        if any(len(t) >= 4 and re.search(rf"\b{re.escape(t)}\b", lowered) and not re.search(rf"\b{re.escape(t)}\b", patient_low)
               for t in tokens(d)):
            referenced[d["id"]] = d
    for d in referenced.values():
        if not any(len(t) >= 4 and re.search(rf"\b{re.escape(t)}\b", source_low) for t in tokens(d)):
            problems.append(f"{d['name']} is not mentioned in the entries this answer is based on")
    return problems


def text_checks(text: str, ground: list[Source], patient_text: str = "", mode: str = "template") -> list[Check]:
    """The checks that look only at the text of a reply (no topic needed). `ground` = the entries it may rely on."""
    lowered = text.lower()
    source_text = " ".join(f"{s.title} {s.text}" for s in ground)
    source_low, source_norm = source_text.lower(), normalize(source_text)
    patient_low = patient_text.lower()
    checks: list[Check] = []

    def add(group: str, name: str, label: str, ok: bool, severity: str, good: str, bad: str) -> None:
        checks.append(Check(name, label, ok, severity, good if ok else bad, group))

    # ---- 2. prices and doctor names ----
    unknown_prices = sorted(extract_prices(text) - extract_numbers(source_text), key=lambda n: (len(n), n))
    add("price_doctor", "prices_supported", "Every price comes from the knowledge base", not unknown_prices, "block",
        "Every price appears in the entries this answer is based on.",
        "Price not found in the sources: " + ", ".join("₹" + p for p in unknown_prices)
        + " (a price in the patient's own message does not count)")
    doctor_issues = _doctor_problems(text, source_low, patient_low)
    add("price_doctor", "doctors_supported", "Every doctor name is a real doctor found in the sources", not doctor_issues,
        "block", "No unsupported doctor names.", "; ".join(doctor_issues))
    unknown = sorted(extract_numbers(text) - extract_numbers(source_text) - extract_numbers(patient_text),
                     key=lambda n: (len(n), n))
    add("price_doctor", "numbers_grounded", "Prices, times and numbers match the knowledge base", not unknown, "block",
        "Every number appears in a source.", "Numbers not found in any source: " + ", ".join(unknown))
    links = [u.rstrip(".,)") for u in re.findall(r"https?://\S+|\b[\w.+-]+@[\w-]+\.[\w.-]+", lowered)]
    bad_links = [u for u in links if u not in source_low]
    add("price_doctor", "links_grounded", "Links and email addresses come from the knowledge base", not bad_links, "block",
        "No unknown links or emails.", "Unknown link or email: " + ", ".join(bad_links))
    claims = [t for t in UNSUPPORTED_CLAIM_TERMS if _word_in(t, lowered) and not _word_in(t, source_low)]
    add("price_doctor", "no_unsupported_claims", "No invented offers or guarantees", not claims, "block",
        "No unsupported claims.", "Unsupported claim: " + ", ".join(claims))

    # ---- 3. appointment availability / confirmation ----
    confirmed = _claims(_CONFIRMED, text)
    available = _claims(_AVAILABLE, text)
    add("calendar", "no_appointment_claims", "Does not say an appointment is available or confirmed", not (confirmed or available),
        "block", "No claim about availability or a confirmed booking.",
        "No calendar is connected, so the assistant cannot know this. " + _quote(confirmed + available))

    # ---- 4. diagnosis and medicine ----
    medicine = [t for t in MEDICINE_TERMS if _word_in(t, lowered) and not _word_in(t, source_low)]
    add("medical", "no_medical_advice", "No medicine or drug advice", not medicine, "block",
        "No medicine or dosage wording.", "Medicine wording found: " + ", ".join(medicine))
    diagnosis = _claims(_DIAGNOSIS, text, source_norm, exempt_if_in_sources=True)
    add("medical", "no_diagnosis", "No diagnosis", not diagnosis, "block", "No diagnosis found.",
        "Sounds like a diagnosis: " + _quote(diagnosis))
    advice = _claims(_RECOMMEND, text, source_norm, exempt_if_in_sources=True)
    add("medical", "no_treatment_advice", "No personal treatment recommendation", not advice, "block",
        "No personal treatment recommendation.", "Sounds like a recommendation only a dentist should make: " + _quote(advice))

    # ---- 5. well formed ----
    broken = _PLACEHOLDER.findall(text) + _LEAK.findall(text)
    add("validity", "well_formed", "No placeholders, internal markers or AI boilerplate", not broken, "block",
        "Clean text.", "Contains text that should never reach a patient: " + ", ".join(f"“{b.strip()}”" for b in broken[:3]))
    if mode == "claude":
        last_line = text.strip().splitlines()[-1].strip() if text.strip() else ""
        complete = bool(_PROPER_END.search(text.strip())) or last_line.startswith(("•", "-", "*"))
        add("validity", "not_truncated", "The reply is not cut off", complete, "block", "The reply ends properly.",
            f"The reply seems to stop mid-sentence: “…{text.strip()[-50:]}”")
    add("validity", "plain_whatsapp_text", "Plain text suitable for WhatsApp", not _MARKDOWN.search(text), "warn",
        "Plain text.", "Contains markdown (headings, **bold**, links) that WhatsApp will not format.")
    return checks


def _coverage_check(draft: Draft, cls: Classification, sources: list[Source]) -> Check:
    """Does the answer actually contain what each topic in the question asks for? (code, not opinion)"""
    label = "Answers every part of the question"
    if draft.kind != "answer" or not draft.needs_sources:
        return Check("covers_question", label, True, "info", "No clinic facts were requested.", "validity")
    kb = knowledge.load()
    clinic, lowered, numbers = kb["clinic"], draft.text.lower(), extract_numbers(draft.text)
    missing: list[str] = []
    for intent in cls.intents:
        if intent == "treatment_price":
            for s in sources:
                if s.kind == "treatment" and s.method == "precise" and s.score >= 0.9:
                    low = extract_numbers(str(s.data.get("price_min", "")))
                    if low and not low <= numbers:
                        missing.append(f"the price of {s.title}")
        elif intent == "clinic_timings":
            hours = set().union(*(extract_numbers(row["hours"]) for row in clinic["timings"]))
            if hours and not hours & numbers:
                missing.append("the clinic hours")
        elif intent == "location":
            street = clinic["address"].split(",")[0].lower()
            if street not in lowered and clinic.get("maps_link", "\0") not in draft.text:
                missing.append("the clinic address")
        elif intent == "contact_info":
            if not extract_numbers(clinic["phone"]) <= numbers:
                missing.append("the phone number")
        elif intent == "doctor_info":
            if not any(d["name"].lower() in lowered or d["name"].split()[-1].lower() in lowered for d in kb["doctors"]):
                missing.append("a doctor's name")
        elif intent == "payment_insurance":
            words = [m.split()[0].lower() for m in clinic.get("payment_methods", [])] + ["insurance"]
            if not any(w in lowered for w in words):
                missing.append("how patients can pay")
    return Check("covers_question", label, not missing, "warn", "Every topic asked about is answered."
                 if not missing else "The reply does not include " + ", ".join(missing) + ".", "validity")


def run_checks(draft: Draft, cls: Classification, sources: list[Source], patient_text: str) -> list[Check]:
    text = draft.text.strip()
    checks: list[Check] = []

    # ---- 1. relevant source ----
    checks.append(Check("has_draft", "A reply was drafted", bool(text), "block",
                        "Draft written." if text else "No draft could be written for this message.", "validity"))
    if draft.needs_sources:
        best = max(sources, key=lambda s: s.score, default=None)
        ok = best is not None and best.score >= config.MIN_SOURCE_SCORE
        detail = f"Best source: {best.title} (match {best.score:.2f})." if best else "No source found."
        if best and not ok:
            detail = f"Best source only matched {best.score:.2f} (needs {config.MIN_SOURCE_SCORE:.2f}): {best.title}."
        checks.append(Check("facts_supported", "A relevant entry exists in the knowledge base", ok, "block", detail, "source"))
    else:
        checks.append(Check("facts_supported", "A relevant entry exists in the knowledge base", True, "info",
                            "No clinic facts are quoted in this reply.", "source"))

    cited_sources = sources
    if draft.needs_sources and draft.kind == "answer":
        by_id = {s.id: s for s in sources}
        cited = list(dict.fromkeys(draft.used_source_ids))
        ok = bool(cited) and all(c in by_id and by_id[c].score >= config.MIN_SOURCE_SCORE for c in cited)
        checks.append(Check("sources_cited", "The answer names the entries it came from", ok, "block",
                            "Built from: " + ", ".join(cited) if ok
                            else "The answer does not cite sources, or cites entries that were not retrieved or are too weak a match.",
                            "source"))
        cited_sources = [by_id[c] for c in cited if c in by_id] or sources   # facts must come from what was cited

    checks += text_checks(text, cited_sources, patient_text, mode=draft.mode)
    checks.append(_coverage_check(draft, cls, sources))

    # ---- 5. valid: length and language; routing: topic confidence ----
    limit = MAX_REPLY_CHARS if draft.mode == "claude" else MAX_TEMPLATE_CHARS
    length_ok = len(text) <= limit and (len(text) >= MIN_REPLY_CHARS or not draft.needs_sources)
    checks.append(Check("length_ok", "Reply length is reasonable", length_ok, "warn",
                        f"{len(text)} characters (between {MIN_REPLY_CHARS} and {limit}).", "validity"))
    checks.append(Check("language_ok", "Message is in English or Roman-script Hinglish", cls.script != "devanagari", "warn",
                        "Roman script." if cls.script != "devanagari"
                        else "The message uses Devanagari script; a person should reply in the patient's language.", "validity"))
    named = knowledge.unknown_doctor_mentions(patient_text, knowledge.load())
    checks.append(Check("doctor_exists", "A doctor the patient names works at this clinic", not named, "warn",
                        "No unknown doctor was named." if not named else
                        f"The patient asks about {', '.join(named)}, who is not in the clinic's list of doctors - a person should reply.",
                        "routing"))
    prior = _PRIOR_CLAIM.search(patient_text)
    checks.append(Check("no_prior_claim", "The patient does not quote an earlier promise or price", not prior, "warn",
                        "No earlier promise is quoted." if not prior else
                        f"The patient refers to something the clinic said earlier (“{prior.group(0)}”). The assistant cannot check "
                        "what was said, so a person should reply.", "routing"))
    checks.append(Check("intent_confident", "Topic was understood clearly",
                        cls.confidence >= config.MIN_CLASSIFIER_CONFIDENCE, "warn",
                        f"Intent '{cls.intent}' at {cls.confidence:.0%} confidence (needs {config.MIN_CLASSIFIER_CONFIDENCE:.0%}).",
                        "routing"))
    return sorted(checks, key=lambda c: _GROUP_ORDER.get(c.group, 99))


# What is worth double-checking in a reply a PERSON wrote or edited. A receptionist is allowed to confirm
# times and appointments (that is their job), so only slips they could make by accident are checked.
_HUMAN_CHECKS = {"prices_supported", "doctors_supported", "no_medical_advice", "no_diagnosis",
                 "no_treatment_advice", "well_formed"}


def check_text(text: str, sources: list[Source], patient_text: str = "") -> list[Check]:
    """Re-check a reply a person wrote or edited, against the entries that were retrieved for the question."""
    return [c for c in text_checks(text, sources, patient_text, mode="human") if c.name in _HUMAN_CHECKS]


def failed_blocks(checks: list[Check]) -> list[Check]:
    return [c for c in checks if not c.passed and c.severity == "block"]


def validate(draft: Draft, cls: Classification, sources: list[Source], patient_text: str,
             auto_reply_enabled: bool = True) -> Verdict:
    fingerprint = hash_text(draft.text)
    if draft.kind == "no_answer":
        # The knowledge base cannot answer this. Never guess: forward it to a person.
        check = Check("answer_found", "A relevant entry exists in the knowledge base", False, "block",
                      draft.note or "Nothing in the knowledge base matched this question well enough.", "source")
        return Verdict(ESCALATE, ["The clinic's information does not cover this question, so the assistant did not "
                                  "guess. A person must answer it."], [check], fingerprint)

    checks = run_checks(draft, cls, sources, patient_text)
    escalate: list[str] = []
    approval: list[str] = []

    if cls.sensitive:
        escalate.append(f"This looks like {SENSITIVE_LABELS.get(cls.intent, 'a sensitive topic')} - "
                        "a person must handle it.")
    if cls.intent == "unknown":
        escalate.append("The assistant could not tell what the patient is asking.")

    for check in checks:
        if check.passed or check.severity == "info":
            continue
        if cls.intent == "unknown" and check.name in ("has_draft", "facts_supported", "intent_confident"):
            continue  # already explained above
        (escalate if check.severity == "block" else approval).append(f"{check.label}: {check.detail}")

    if cls.caution:
        approval.append("The message may mention a health concern (" + ", ".join(SENSITIVE_LABELS.get(c, c) for c in cls.caution)
                        + ") that is too weak to be sure about - check the reply before it is sent.")
    if draft.partial:
        approval.append("Part of the question is not in the knowledge base - check the reply before it is sent.")
    if APPROVAL_INTENTS & set(cls.intents):
        approval.append("Appointment requests need a receptionist to confirm the slot (no calendar is connected).")
    if draft.mode == "claude" and config.APPROVE_MODEL_ANSWERS:
        approval.append("Settings require a receptionist to approve every answer written by the AI model.")
    if not auto_reply_enabled:
        approval.append("Auto-reply is switched off, so every reply needs approval.")

    if escalate:
        return Verdict(ESCALATE, escalate, checks, fingerprint)
    if approval:
        return Verdict(NEEDS_APPROVAL, approval, checks, fingerprint)
    return Verdict(AUTO_SEND, ["All verification checks passed - safe to reply automatically."], checks, fingerprint)
