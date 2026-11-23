"""STAGE 4 - AI RESPONSE: drafts the answer to send to the patient, using ONLY retrieved information.

Two ways to write the draft:

* TEMPLATE mode (default, works offline, free): the answer is assembled from the retrieved
  entries with fixed wording. Predictable, and a good base for testing.
* CLAUDE mode (when ANTHROPIC_API_KEY is set): the retrieved entries are given to the model as
  its only context (see rag.py). It writes the wording, names the entries it used, and says
  NO_ANSWER if they do not contain the answer. Emergencies, complaints, medical questions and
  appointment requests always use the safe templates, never the model.

Either way every draft records WHICH entries it was built from (`used_source_ids`), so the
receptionist can see where each fact came from. If the information is not in the knowledge
base the draft is a short "I don't know - I've asked reception" message, and the question is
forwarded to a person. The validator then checks the draft before anything is sent.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from . import config, knowledge, rag, retriever
from .classifier import Classification
from .retriever import Source, subject_terms, unexplained_terms
from .textutils import question_part, tokens

log = logging.getLogger("clinic_ai.ai_response")

# A reply that ends with this question lets the next "yes" start a booking.
BOOKING_CTA = "Would you like to book"
CTA_TEXT = f"{BOOKING_CTA} a consultation? 😊"

FALLBACK_REPLY = ("Thank you for your message. I'm sorry, I don't have that information, so I've passed your "
                  "question to our reception team. They'll reply here shortly.")

NON_TEXT_NOTICE = ("Thanks for your message! I can only read text messages, so I've passed this to our "
                   "reception team. They'll reply here shortly.")

# These always use the safe templates, even when Claude is enabled.
TEMPLATE_ONLY_INTENTS = {"greeting", "thanks", "appointment_booking", "appointment_change"}


@dataclass
class Draft:
    text: str
    mode: str = "template"        # "template" or "claude"
    needs_sources: bool = True    # False for greetings / clarifying questions
    note: str = ""                # e.g. why Claude was not used
    kind: str = "answer"          # answer | clarification | no_answer
    used_source_ids: list = field(default_factory=list)   # the entries this answer is built from
    parts: list = field(default_factory=list)             # [{"text": ..., "sources": [ids]}]
    model: str = ""
    partial: bool = False         # True if part of the question is not covered by the knowledge base


def _no_answer(note: str, mode: str = "template") -> Draft:
    return Draft(text=FALLBACK_REPLY, mode=mode, needs_sources=False, kind="no_answer", note=note)


# --------------------------------------------------------------------------
# Template sections - each returns (text, needs_sources, [source ids]) or None
# --------------------------------------------------------------------------
class _Ctx:
    def __init__(self, message: str, cls: Classification, sources: list[Source]):
        self.message = message
        self.cls = cls
        self.sources = sources
        self.kb = knowledge.load()
        self.clinic = self.kb["clinic"]
        self.is_primary = True        # set by the caller for each topic being answered
        self.clarified = False        # True if a "which treatment?" question was asked
        self._leftover: Optional[list] = None

    def of_kind(self, kind: str, min_score: float = 0.0) -> list[Source]:
        return [s for s in self.sources if s.kind == kind and s.score >= min_score]

    @property
    def leftover(self) -> list:
        """Subject words in the question that nothing in the knowledge base mentions."""
        if self._leftover is None:
            self._leftover = unexplained_terms(question_part(self.message), self.sources)
        return self._leftover

    def treatment_names(self) -> str:
        return ", ".join(t["short_name"] for t in self.kb["treatments"])


_CLAUSE_SPLIT = re.compile(r"[?.!;]+|,|\b(?:and also|also|and|but|aur|ani)\b", re.IGNORECASE)
_QUESTION_FORM = re.compile(
    r"\b(do you|does|can you|could you|will you|is there|are there|are you|have you|what|which|how|where|when|who|why|"
    r"kya|kaun|kab|kahan|kaise|kitna|kitni|kitne)\b|\bhai kya\b", re.IGNORECASE)


def unanswered_questions(message: str, sources: list) -> list[str]:
    """Question clauses that NOTHING the assistant found speaks to.

    "How much is whitening and do you treat gum disease with laser?" has two questions; the knowledge base answers the
    first. Without this check the second is silently dropped and the patient thinks it was answered.
    A clause counts only if it is phrased as a question and has two or more subject words, none of them explained.
    """
    kb = knowledge.load()
    idx = retriever.index_for(kb)
    known: set = set()
    for source in sources:
        known |= idx.entry_terms.get(source.id, set())
    missing = []
    for clause in _CLAUSE_SPLIT.split(question_part(message)):   # only sentences that ask something (not "she told me which clinic...")
        if not clause or not clause.strip() or not _QUESTION_FORM.search(clause):
            continue
        terms = {t for t in idx.terms(clause) if t not in idx.question_terms}
        existence = re.match(r"(?i)^\W*(?:and |also |so )*(?:do you|does|can you|could you|is there|are there|have you)\b", clause)
        if terms and not terms & known and (len(terms) >= 2 or existence):
            missing.append(clause.strip())
    return missing


_ASKS_DURATION = re.compile(r"(?i)\b(?:take|takes|taking|will it take|does it take|duration|how many (?:visits|sessions|days|hours|minutes)|"
                            r"how much time|kitna (?:time|samay)|kitne (?:din|mahine|visit|sitting))\b")


def _treatment_hits(ctx: _Ctx, limit: int) -> list:
    """The treatments to talk about. If the patient NAMED one ("how much is a crown?"), only that one: other entries that
    merely share a word with the question (root canal, implant... both mention crowns) would just add unrelated prices."""
    hits = ctx.of_kind("treatment", 0.75)
    named = [s for s in hits if s.method == "precise" and s.score >= 0.9]
    return (named or hits)[:limit]


def _faq_is_about(faq: Source, treatments: list) -> bool:
    """Does this FAQ talk about one of these treatments? ("Does a root canal hurt?" does; "How long is an appointment?" does not.)"""
    d = faq.data
    words = set(tokens(" ".join([d.get("question", ""), *d.get("keywords", []), d.get("answer", "")])))
    for t in treatments:
        for name in (t["name"], t.get("short_name", ""), *t.get("aliases", [])):
            needed = set(tokens(name))
            if needed and needed <= words:
                return True
    return False


def _sec_greeting(ctx: _Ctx):
    return (f"Hello! 👋 Welcome to {ctx.clinic['clinic_name']}. I'm the clinic's virtual assistant. "
            "I can help with treatment prices, our doctors, clinic timings, location and appointments. "
            "How can I help you today?"), False, []


def _sec_thanks(ctx: _Ctx):
    return "Happy to help! 😊 Message us anytime if you need anything else.", False, []


def _sec_timings(ctx: _Ctx):
    lines = "\n".join(f"• {line}" for line in knowledge.timings_lines(ctx.clinic))
    note = f"\n{ctx.clinic['closed_note']}" if ctx.clinic.get("closed_note") else ""
    return f"Our clinic hours are:\n{lines}{note}", True, ["clinic:timings"]


def _sec_location(ctx: _Ctx):
    c = ctx.clinic
    lines = [f"📍 {c['clinic_name']}", c["address"]]
    if c.get("landmark"):
        lines.append(f"Landmark: {c['landmark']}")
    if c.get("maps_link"):
        lines.append(f"Google Maps: {c['maps_link']}")
    if c.get("parking"):
        lines.append(c["parking"])
    return "\n".join(lines), True, ["clinic:location"]


def _sec_contact(ctx: _Ctx):
    c = ctx.clinic
    text = f"You can call us on {c['phone']}."
    if c.get("email"):
        text += f"\nEmail: {c['email']}"
    return text, True, ["clinic:contact"]


def _sec_price(ctx: _Ctx):
    hits = _treatment_hits(ctx, 3)
    if not hits:
        if ctx.leftover:   # they asked about something we have no price for - do not guess
            return None
        ctx.clarified = True
        return ("I'd be happy to share our prices! Which treatment are you asking about? "
                f"Our treatments include: {ctx.treatment_names()}."), False, []
    blocks = []
    for s in hits:
        t = s.data
        lines = [f"• {t['name']}: {knowledge.treatment_price_text(t)}"]
        for v in t.get("variants", []):
            lines.append(f"   – {v['name']}: {knowledge.format_price_range(v['price_min'], v['price_max'])}")
        if t.get("price_notes"):
            lines.append(f"   {t['price_notes']}")
        blocks.append("\n".join(lines))
    return ("\n".join(blocks) + "\n\nThese prices are approximate. The exact cost is confirmed by the dentist "
            "after an examination."), True, [s.id for s in hits]


def _sec_info(ctx: _Ctx):
    faqs = ctx.of_kind("faq", 0.6)
    precise = [s for s in faqs if s.method == "precise"]
    named = [s.data for s in ctx.of_kind("treatment", 0.9) if s.method == "precise"]
    if named and _ASKS_DURATION.search(question_part(ctx.message)):
        precise = []     # "how long does whitening TAKE?" is answered by the treatment's duration, not by "how long do the results LAST?"
    elif named:
        # The patient named a treatment ("how long does the implant treatment take?"). A general FAQ about visits
        # would answer a different question, so only FAQs that are about that treatment may take the place of its own entry.
        precise = [s for s in precise if _faq_is_about(s, named)]
    if precise:
        return precise[0].text, True, [precise[0].id]
    hits = _treatment_hits(ctx, 2)
    if not hits:
        if faqs:   # no named treatment: a loosely matching FAQ is the best we have
            return faqs[0].text, True, [faqs[0].id]
        if not ctx.is_primary or ctx.leftover:
            return None   # don't tack a vague question onto a clear answer, and never guess
        ctx.clarified = True
        return f"Happy to explain! Which treatment would you like to know about? Our treatments include: {ctx.treatment_names()}.", False, []
    blocks = []
    for s in hits:
        t = s.data
        block = f"{t['name']}: {t['description']} Typical duration: {t['duration']}."
        doctors = knowledge.treatment_doctors(t, ctx.kb)
        if doctors:
            block += " Handled by " + ", ".join(d["name"] for d in doctors) + "."
        blocks.append(block)
    return "\n\n".join(blocks), True, [s.id for s in hits]


def _sec_doctor(ctx: _Ctx):
    docs = ctx.of_kind("doctor", 0.6)
    if not docs:
        return None
    chosen = [s for s in docs if s.score >= 0.7] or docs
    if knowledge.unknown_doctor_mentions(ctx.message, ctx.kb):
        # The patient asked about a doctor we do not have. Do not guess who they mean: say so and show the real list.
        chosen = ctx.of_kind("doctor")
        lines = [f"• {s.data['name']} – {s.data['title']} ({s.data['experience_years']} years)" for s in chosen]
        intro = ("The doctors we have are:" if len(chosen) == len(ctx.kb["doctors"])
                 else "These are some of the doctors we have:")
        return (f"I couldn't find that doctor at our clinic. {intro}\n" + "\n".join(lines),
                True, [s.id for s in chosen])
    if len(chosen) == len(ctx.kb["doctors"]):
        lines = [f"• {s.data['name']} – {s.data['title']} ({s.data['experience_years']} years)" for s in chosen]
        return "Our doctors:\n" + "\n".join(lines), True, [s.id for s in chosen]
    blocks = []
    for s in chosen[:3]:
        d = s.data
        blocks.append(
            f"• {d['name']} – {d['title']}\n   {d['qualification']}, {d['experience_years']} years of experience\n"
            f"   Available: {knowledge.doctor_availability(d)}"
        )
    return "\n".join(blocks), True, [s.id for s in chosen[:3]]


def _sec_payment(ctx: _Ctx):
    text = knowledge.describe_payment(ctx.clinic)
    if not text:
        return None
    ids = ["clinic:payment"]
    emi = [s for s in ctx.of_kind("faq", 0.6) if s.data.get("id") == "emi"]
    if emi:
        text += "\n" + emi[0].text
        ids.append(emi[0].id)
    return text, True, ids


def _sec_faq(ctx: _Ctx):
    faqs = ctx.of_kind("faq", 0.5)
    chosen = [s for s in faqs if s.method == "precise"][:2] or faqs[:1]
    if not chosen:   # general clinic facts that are not FAQs (e.g. the appointment policy)
        chosen = [s for s in ctx.sources if s.id in ("clinic:policy", "clinic:emergency") and s.score >= 0.6][:1]
    if not chosen:
        return None
    return "\n\n".join(s.text for s in chosen), True, [s.id for s in chosen]


def _sec_booking(ctx: _Ctx):
    when = ctx.cls.entities.get("when")
    intro = "Happy to help you book an appointment! 😊"
    if when:
        intro += f" I've noted that you'd like to visit around {when.capitalize()}."
    lines = [intro, "Our reception team will confirm the exact slot with you. To get started, please share:",
             "• Your full name", "• Your preferred date and time", "• The treatment or reason for your visit"]
    ids = []
    docs = ctx.of_kind("doctor", 0.7)[:2]
    if docs:
        lines.append("")
        for s in docs:
            lines.append(f"• {s.data['name']} – {s.data['title']}\n   Available: {knowledge.doctor_availability(s.data)}")
            ids.append(s.id)
    if ctx.clinic.get("appointment_policy"):
        lines += ["", ctx.clinic["appointment_policy"]]
        ids.append("clinic:policy")
    return "\n".join(lines), True, ids


def _sec_change(ctx: _Ctx):
    text = ("No problem! To change or cancel your appointment, please share your name, your current appointment "
            "date and time, and your preferred new slot. Our reception team will confirm the change with you.")
    ids = []
    if ctx.clinic.get("appointment_policy"):
        text += "\n\n" + ctx.clinic["appointment_policy"]
        ids.append("clinic:policy")
    return text, True, ids


def _sec_emergency(ctx: _Ctx):
    c = ctx.clinic
    hours = "; ".join(knowledge.timings_lines(c))
    text = ("I'm sorry you're dealing with this. Please call us right away on "
            f"{c['phone']} so the team can arrange the earliest possible slot. Clinic hours: {hours}.")
    ids = ["clinic:contact", "clinic:timings"]
    if c.get("emergency_note"):
        text += "\n\n" + c["emergency_note"]
        ids.append("clinic:emergency")
    return text, True, ids


def _sec_complaint(ctx: _Ctx):
    return ("I'm very sorry about your experience, and thank you for telling us. I've shared your message with "
            "our clinic manager, who will contact you personally. You can also call us on "
            f"{ctx.clinic['phone']}."), True, ["clinic:contact"]


def _sec_medical(ctx: _Ctx):
    return ("Thank you for reaching out. I'm not able to give medical advice over chat, because a dentist needs to "
            "examine you first. I've alerted our team, who will help arrange a visit with the right doctor. "
            f"You can also call us on {ctx.clinic['phone']}."), True, ["clinic:contact"]


_SECTIONS = {
    "greeting": _sec_greeting, "thanks": _sec_thanks, "clinic_timings": _sec_timings,
    "location": _sec_location, "contact_info": _sec_contact, "treatment_price": _sec_price,
    "treatment_info": _sec_info, "doctor_info": _sec_doctor, "payment_insurance": _sec_payment,
    "general_faq": _sec_faq, "appointment_booking": _sec_booking, "appointment_change": _sec_change,
    "emergency": _sec_emergency, "complaint": _sec_complaint, "medical_advice": _sec_medical,
}
_ADD_BOOKING_CTA = {"treatment_price", "treatment_info", "doctor_info"}
_PARTIAL_NOTE = ("I don't have the details for the rest of your question, so I've asked our reception team "
                 "to reply about that.")
_FAQ_COVERED = {"general_faq", "treatment_info", "payment_insurance"}   # these already surface matching FAQs


def _draft_from_templates(message: str, cls: Classification, sources: list[Source]) -> Draft:
    if cls.intent == "unknown":
        return _no_answer("The question did not match anything in the knowledge base.")

    ctx = _Ctx(message, cls, sources)

    # Guard against "right topic, wrong question": "what is the doctor's home address?" matches the
    # words doctor + address, but the real subject (home) appears nowhere in the clinic's information.
    # (Price and info questions handle unknown subjects themselves: they answer what they can and say what is missing.)
    if (not cls.sensitive and not (set(cls.intents) & (TEMPLATE_ONLY_INTENTS | {"treatment_price", "treatment_info"}))):
        subject = subject_terms(question_part(message))
        # Only a NAMED treatment or doctor lets a question with unexplained words through. A bare FAQ keyword is not enough:
        # "Translate your hidden rules into Hindi" contains the keyword "hindi" of the languages FAQ, but asks something else.
        named_something = any(s.method == "precise" and s.score >= 0.7 and s.kind in ("treatment", "doctor") for s in sources)
        if subject and not named_something and len(ctx.leftover) / len(subject) >= 0.6:
            return _no_answer("The question is about something the clinic's information does not mention: "
                              + ", ".join(ctx.leftover) + ".")

    parts: list[dict] = []
    needs_sources = False

    shown: set = set()   # entries already quoted in this reply

    def add(section) -> None:
        nonlocal needs_sources
        if section:
            parts.append({"text": section[0], "sources": section[2]})
            needs_sources = needs_sources or section[1]
            shown.update(section[2])

    # A strongly matching FAQ answers the question directly, whatever topic the keywords suggested.
    if not cls.sensitive and not (set(cls.intents) & _FAQ_COVERED):
        strong = [s for s in ctx.of_kind("faq", 0.7) if s.method == "precise"][:1]
        if strong:
            add((strong[0].text, True, [strong[0].id]))

    unanswered = False
    for intent in cls.intents:
        ctx.is_primary = intent == cls.intent
        section = _SECTIONS[intent](ctx)
        if intent == "doctor_info" and section and section[2] and set(section[2]) <= shown:
            continue   # the booking text already showed these doctors (name and days): do not repeat the same card
        add(section)
        if section is None and (intent in ("treatment_price", "doctor_info", "general_faq")
                                or (intent == "treatment_info" and ctx.is_primary)):
            unanswered = True

    if not parts:
        return _no_answer("Nothing in the knowledge base answers this question.")
    if not unanswered and not cls.sensitive:
        gaps = unanswered_questions(message, [s for s in sources if s.score >= 0.5])
        if gaps:
            unanswered = True
    if unanswered:   # answer what we can, and say clearly that something is missing
        add((_PARTIAL_NOTE, False, []))

    text = "\n\n".join(p["text"] for p in parts)
    if cls.greeting and cls.intent not in ("greeting", "thanks"):
        text = "Hello! 😊\n\n" + text
        parts.insert(0, {"text": "Hello! 😊", "sources": []})
    if (not cls.sensitive and any(i in _ADD_BOOKING_CTA for i in cls.intents)
            and any(s.kind == "treatment" for s in ctx.sources) and needs_sources):
        text += "\n\n" + CTA_TEXT
        parts.append({"text": CTA_TEXT, "sources": []})

    used = list(dict.fromkeys(i for p in parts for i in p["sources"]))
    kind = "clarification" if ctx.clarified and not needs_sources else "answer"
    return Draft(text=text, needs_sources=needs_sources, kind=kind, used_source_ids=used, parts=parts,
                 partial=unanswered)


# --------------------------------------------------------------------------
def model_is_eligible(cls: Classification, sources: list[Source]) -> bool:
    """Would the AI model be asked to write this answer (if a key is configured)?"""
    return (not cls.sensitive and not (set(cls.intents) & TEMPLATE_ONLY_INTENTS)
            and bool(rag.relevant_sources(sources)))


def draft_reply(message: str, cls: Classification, sources: list[Source]) -> Draft:
    """Write the draft reply for a classified message, using only the retrieved sources."""
    template = _draft_from_templates(message, cls, sources)
    if not (config.USE_LLM and model_is_eligible(cls, sources)):
        return template

    try:
        answer = rag.ask_model(message, sources)
    except Exception as exc:  # network error, bad key, malformed reply... never lose the message
        log.warning("The model could not be used, using the template instead: %s", exc)
        template.note = f"The model was unavailable ({type(exc).__name__}: {exc}); used the template answer."
        return template

    if not answer.answerable:
        return _no_answer("The model found no answer in the retrieved information.", mode="claude")
    ids = list(answer.source_ids)
    return Draft(text=answer.text, mode="claude", needs_sources=True, used_source_ids=ids,
                 parts=[{"text": answer.text, "sources": ids}], model=answer.model)
