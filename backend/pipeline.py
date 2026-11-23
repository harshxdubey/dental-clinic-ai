"""Runs the AI stages in order: classify -> retrieve -> draft (from the retrieved information) -> validate.

This module only *thinks* - it never touches the database or sends anything. That makes
it easy to test (see tests/) and easy to reuse once real WhatsApp is connected.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .ai_response import BOOKING_CTA, Draft, draft_reply
from .classifier import Classification, classify, is_affirmation
from .rag import relevant_sources
from .retriever import Source, retrieve, unexplained_terms
from .textutils import strip_vocative
from .validator import Verdict, validate


@dataclass
class Analysis:
    classification: Classification
    sources: list
    draft: Draft
    verdict: Verdict

    @property
    def holding_reply(self) -> Optional[str]:
        """The "I don't know, I've asked reception" message, when the knowledge base had no answer."""
        return self.draft.text if self.draft.kind == "no_answer" else None

    def to_record(self) -> dict:
        """What we store about the AI's work on one message (also what the dashboard shows)."""
        cls, verdict, draft = self.classification, self.verdict, self.draft
        used = set(draft.used_source_ids)
        given_to_model = {s.id for s in relevant_sources(self.sources)}
        sources = []
        for s in self.sources:
            entry = s.to_dict()
            entry["used"] = s.id in used                  # this entry is part of the answer
            entry["in_context"] = s.id in given_to_model  # this entry would be handed to the AI model
            sources.append(entry)
        return dict(
            intent=cls.intent, intents=cls.intents, confidence=cls.confidence, urgent=cls.urgent,
            draft="" if draft.kind == "no_answer" else draft.text,   # the "I don't know" text is sent, not drafted
            draft_mode=draft.mode, draft_note=draft.note,
            sources=sources, checks=[vars(c) for c in verdict.checks], reasons=list(verdict.reasons),
            decision=verdict.decision,
            rag={
                "kind": draft.kind, "answerable": draft.kind != "no_answer", "mode": draft.mode, "model": draft.model,
                "used_sources": list(draft.used_source_ids), "parts": draft.parts, "partial": draft.partial,
                "holding_reply": self.holding_reply,
            },
        )


# Which topic a general clinic entry belongs to, for questions the keyword rules did not recognise.
_INTENT_FOR_ENTRY = {
    "clinic:timings": "clinic_timings", "clinic:location": "location", "clinic:contact": "contact_info",
    "clinic:payment": "payment_insurance", "clinic:policy": "general_faq", "clinic:emergency": "general_faq",
}


def _promote_unknown(cls: Classification, sources: list[Source], message: str = "") -> None:
    """The keywords did not recognise the question, but the knowledge base did: use what it found."""
    # A stored FAQ that matches the question's own words answers it directly ("send me my X-ray report" -> the reports FAQ),
    # so it is preferred over a treatment that is merely mentioned.
    best = (next((s for s in sources if s.kind == "faq" and s.method == "precise" and s.score >= 0.7), None)
            or next((s for s in sources if s.score >= 0.6), None))
    if best is None:
        return
    if best.kind in ("treatment", "doctor") and unexplained_terms(message, [best]):
        # "What brand of implants do you use?" names a treatment, but the actual question (brand) is not in the clinic's
        # information. Describing the treatment instead would look like an answer. A person should reply.
        return
    # Confidence reflects HOW it matched: a named entry is trusted more than loose word overlap.
    confidence = 0.8 if best.method == "precise" else 0.75 if best.method == "topic" else round(0.4 + 0.35 * best.score, 2)
    if best.kind == "faq":
        cls.intent = "general_faq"
    elif best.kind == "treatment" and best.score >= 0.9:   # the patient just named a treatment, e.g. "braces?"
        cls.intent, confidence = "treatment_info", 0.72
    elif best.kind == "doctor" and best.score >= 0.9:
        cls.intent = "doctor_info"
    elif best.id in _INTENT_FOR_ENTRY:
        cls.intent = _INTENT_FOR_ENTRY[best.id]
    else:
        return
    cls.intents, cls.confidence = [cls.intent], confidence


def _boost_confidence(cls: Classification, sources: list[Source]) -> None:
    """If the knowledge base found exactly what the keywords pointed at, we are more sure."""
    kind = {"treatment_price": "treatment", "treatment_info": "treatment", "doctor_info": "doctor"}.get(cls.intent)
    if kind and not cls.sensitive and any(s.kind == kind and s.score >= 0.9 for s in sources):
        cls.confidence = max(cls.confidence, 0.8)


def _prefer_faq(cls: Classification, sources: list[Source]) -> None:
    """"Can I come without an appointment?" mentions 'appointment' but is a question with a stored answer."""
    if cls.sensitive or cls.intents != ["appointment_booking"]:
        return
    if any(s.kind == "faq" and s.method == "precise" and s.score >= 0.7 for s in sources):
        cls.intent, cls.intents, cls.confidence = "general_faq", ["general_faq"], max(cls.confidence, 0.8)


def analyze(text: str, auto_reply_enabled: bool = True, last_reply: Optional[str] = None) -> Analysis:
    """Analyse one patient message.

    last_reply: the clinic's previous message, so a bare "yes please" after
    "Would you like to book a consultation?" is understood as a booking request.
    """
    classify_text = text
    if last_reply and is_affirmation(text) and BOOKING_CTA.lower() in last_reply.lower():
        classify_text = "I would like to book an appointment"

    classify_text = strip_vocative(classify_text)
    cls = classify(classify_text)
    sources = retrieve(classify_text, cls.intents)
    if cls.intent == "unknown":
        _promote_unknown(cls, sources, classify_text)
    else:
        _boost_confidence(cls, sources)
        _prefer_faq(cls, sources)

    draft = draft_reply(classify_text, cls, sources)
    verdict = validate(draft, cls, sources, text, auto_reply_enabled=auto_reply_enabled)
    return Analysis(cls, sources, draft, verdict)
