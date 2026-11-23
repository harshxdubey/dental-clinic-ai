"""Sending replies to patients - the one gate every reply passes through.

Two ways to deliver (WHATSAPP_MODE in .env):
  simulated   nothing leaves your computer. A "sent" reply is saved in the database and the demo chat page
              picks it up. (default - for demos without any Meta account)
  cloud       the official Meta WhatsApp Cloud API delivers it to the patient's phone.

THE RULES (enforced here, not just by convention):
  * a message from the AI assistant can only be sent with a Verdict saying AUTO_SEND for that exact text;
  * the only other assistant messages allowed are the fixed notices ("I don't know, I've asked reception" and
    "I can only read text messages");
  * everything else comes from a receptionist, i.e. a human approved or wrote it;
  * DELIVER FIRST, RECORD SECOND: a reply is saved as sent only if the transport accepted it, so the history
    never claims a delivery that did not happen. A failed delivery raises DeliveryError and the caller keeps
    the item open for a person;
  * a demo ("simulated") conversation is NEVER sent to a real phone number, even in cloud mode.
So no code path - including a future bug - can message a patient with an unverified or modified AI answer.
"""
from __future__ import annotations

from typing import Optional

from . import database, whatsapp_cloud
from .ai_response import FALLBACK_REPLY, NON_TEXT_NOTICE
from .validator import AUTO_SEND, Verdict, hash_text
from .whatsapp_cloud import Delivery, DeliveryError  # noqa: F401  (re-exported for callers)

FIXED_NOTICES = {FALLBACK_REPLY: "not_in_knowledge_base_notice", NON_TEXT_NOTICE: "unreadable_message_notice"}


class UnverifiedMessageError(RuntimeError):
    """Raised when something tries to send an AI answer that has not passed verification."""


def deliver(conversation: dict, text: str) -> Delivery:
    """Hand the text to the transport. Raises DeliveryError if it could not be delivered."""
    real_patient = conversation.get("channel", "simulated") == "whatsapp"
    if whatsapp_cloud.is_cloud():
        if real_patient:
            return whatsapp_cloud.send_text(conversation["phone"], text)
        return Delivery(status="simulated")      # a demo conversation never reaches a real phone
    if real_patient:
        raise DeliveryError("This patient is on real WhatsApp, but WHATSAPP_MODE is 'simulated', so nothing can be "
                            "delivered. Set WHATSAPP_MODE=cloud in .env and restart to reply.")
    return Delivery(status="simulated")


def send_reply(conversation: dict, text: str, role: str, inquiry_id: Optional[int] = None, *,
               verdict: Optional[Verdict] = None, sources: Optional[list] = None, meta: Optional[dict] = None) -> dict:
    """Send a reply and record where it came from.

    role      "assistant" (automatic AI reply) or "receptionist" (a person approved or wrote it)
    verdict   required for "assistant": the verification result for exactly this text
    sources   the clinic entries the reply was built from, as [{"id", "title", "file"}]
    meta      extra record for the conversation history (who approved it, whether it was edited...)
    Raises UnverifiedMessageError (not verified) or DeliveryError (verified, but WhatsApp did not take it).
    """
    if role not in ("assistant", "receptionist"):
        raise ValueError("role must be 'assistant' or 'receptionist'")

    meta = dict(meta or {})
    if role == "assistant":
        if text.strip() in FIXED_NOTICES:
            meta.setdefault("kind", FIXED_NOTICES[text.strip()])
        elif verdict is None or verdict.decision != AUTO_SEND or verdict.text_hash != hash_text(text):
            raise UnverifiedMessageError(
                "Refusing to send: this AI answer has not passed verification (or was changed after it did).")
        else:
            meta.update(verified=True, decision=verdict.decision,
                        checks_passed=sum(1 for c in verdict.checks if c.passed), checks_total=len(verdict.checks))

    delivery = deliver(conversation, text)       # may raise DeliveryError: nothing is recorded in that case
    return database.add_message(conversation["id"], role, text, inquiry_id, sources=sources, meta=meta,
                                wa_id=delivery.wa_message_id, delivery=delivery.status)
