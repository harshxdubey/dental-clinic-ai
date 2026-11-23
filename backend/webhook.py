"""STAGE 1 - WEBHOOK: the front door for incoming patient messages.

A "webhook" is simply a URL that another system calls when something happens. With real
WhatsApp, Meta calls your URL whenever a patient sends a message. In this prototype the
patient chat page plays the role of WhatsApp and calls POST /api/webhook/whatsapp itself.

Flow for every message:
    save the message -> run the AI pipeline -> save what the AI decided and which clinic
    information the answer was built from
    -> AUTO_SEND:  reply straight away
    -> otherwise:  leave it in the receptionist dashboard (pending approval / escalated)
    -> if the knowledge base has no answer: tell the patient "I don't know, I've asked
       reception" and forward the question to the receptionist
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import database as db
from . import outbound, pipeline, whatsapp_cloud
from .ai_response import NON_TEXT_NOTICE
from .validator import AUTO_SEND, ESCALATE, NEEDS_APPROVAL
from .whatsapp_cloud import DeliveryError

log = logging.getLogger("clinic_ai.webhook")
router = APIRouter(tags=["Simulated WhatsApp"])

STATUS_FOR_DECISION = {AUTO_SEND: "auto_replied", NEEDS_APPROVAL: "pending_approval", ESCALATE: "escalated"}


class IncomingMessage(BaseModel):
    """The simplified message format used by this prototype.

    When you connect real WhatsApp, convert Meta's payload into this shape in
    `normalize_incoming` and the rest of the app does not need to change.
    """
    phone: str = Field(..., description="Patient phone number, e.g. 919000000001", max_length=25)
    name: str = Field("Patient", description="Patient name", max_length=60)
    text: str = Field(..., description="The message text", min_length=1, max_length=1000)


def clean_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if not 8 <= len(digits) <= 15:
        raise HTTPException(status_code=422, detail="Phone number must have 8 to 15 digits.")
    return digits


def normalize_incoming(payload: IncomingMessage) -> tuple[str, str, str]:
    """Clean up an incoming message. Returns (phone, name, text)."""
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Message text is empty.")
    return clean_phone(payload.phone), payload.name.strip() or "Patient", text


def handle_incoming_message(phone: str, name: str, text: str, wa_message_id: Optional[str] = None,
                            channel: str = "simulated") -> dict:
    """Process one patient message end to end.

    Used by the simulated chat (channel "simulated"), the demo-data button, and the Meta webhook
    (channel "whatsapp", with the WhatsApp message id so the message is recorded exactly once).
    """
    conversation = db.get_or_create_conversation(phone, name, channel)
    last = db.last_clinic_message(conversation["id"])
    patient_message = db.add_message(conversation["id"], "patient", text, wa_id=wa_message_id)
    auto_reply_on = db.get_setting("auto_reply", "1") == "1"
    holding: Optional[str] = None
    analysis = None

    try:
        analysis = pipeline.analyze(text, auto_reply_enabled=auto_reply_on, last_reply=last["text"] if last else None)
        record = analysis.to_record()
        holding = analysis.holding_reply
    except Exception as exc:  # never lose a patient message because of a bug
        log.exception("AI pipeline failed")
        record = dict(
            intent="error", intents=[], confidence=0, urgent=False, draft="", draft_mode="none",
            draft_note="", sources=[], checks=[],
            reasons=[f"The assistant hit an internal error ({type(exc).__name__}: {exc}). A person must reply."],
            decision=ESCALATE, rag={"kind": "error", "answerable": False, "used_sources": [], "parts": []},
        )

    status = STATUS_FOR_DECISION[record["decision"]]
    failed = [c for c in record["checks"] if not c["passed"] and c["severity"] != "info"]
    inquiry = db.create_inquiry(
        conversation_id=conversation["id"], message_id=patient_message["id"], question=text,
        status=status, **record,
    )
    db.add_audit(inquiry["id"], "AI assistant", "verified",
                 f"Decision: {record['decision'].replace('_', ' ')}. {len(record['checks']) - len(failed)} of "
                 f"{len(record['checks'])} checks passed" + (f"; failed: {', '.join(c['name'] for c in failed)}." if failed else "."))

    reply: Optional[dict] = None
    if status == "auto_replied":
        # Verified: deliver it, and record the answer together with the entries it came from.
        used = [{"id": s["id"], "title": s["title"], "file": s["file"]} for s in record["sources"] if s["used"]]
        try:
            reply = outbound.send_reply(conversation, record["draft"], "assistant", inquiry["id"],
                                        verdict=analysis.verdict, sources=used)
            db.add_audit(inquiry["id"], "AI assistant", "sent", "Sent automatically after every check passed.")
        except DeliveryError as exc:
            # The answer is fine but WhatsApp did not take it. Nothing reached the patient, so a person decides.
            status = "pending_approval"
            db.update_inquiry(inquiry["id"], status=status, reasons=record["reasons"] + [
                f"The verified answer could NOT be delivered to the patient: {exc} Nothing was sent. "
                "Approve it to try again, or reply yourself."])
            db.add_audit(inquiry["id"], "System", "delivery_failed", str(exc))
    elif holding and auto_reply_on:
        # The clinic's information has no answer: say so honestly, and the question waits for a person.
        try:
            reply = outbound.send_reply(conversation, holding, "assistant", inquiry["id"])
            db.update_inquiry(inquiry["id"], reasons=record["reasons"] + ["The patient was told the reception team will reply."])
            db.add_audit(inquiry["id"], "AI assistant", "notice_sent", "Told the patient it does not have that information.")
        except DeliveryError as exc:
            db.add_audit(inquiry["id"], "System", "delivery_failed", str(exc))
    else:
        db.add_audit(inquiry["id"], "AI assistant", "held", "Nothing was sent to the patient. Waiting for a receptionist.")

    return {
        "conversation_id": conversation["id"],
        "inquiry_id": inquiry["id"],
        "patient_message": patient_message,
        "reply": reply,
        "status": status,
        "notice": db.open_notice(conversation["id"]),
    }


def handle_unreadable_message(phone: str, name: str, label: str, wa_message_id: Optional[str] = None,
                              channel: str = "whatsapp") -> dict:
    """A voice note, photo, file or location: the assistant cannot read it, so a person must look at it.

    The patient gets one fixed notice (if auto-reply is on); the item goes straight to the receptionist.
    """
    conversation = db.get_or_create_conversation(phone, name, channel)
    patient_message = db.add_message(conversation["id"], "patient", f"[Sent {label}]", wa_id=wa_message_id)
    auto_reply_on = db.get_setting("auto_reply", "1") == "1"
    reason = (f"The patient sent {label}, which the assistant cannot read. Open the conversation in the WhatsApp "
              "Business app to see it, then reply.")
    inquiry = db.create_inquiry(
        conversation_id=conversation["id"], message_id=patient_message["id"], question=f"[Sent {label}]",
        status="escalated", intent="non_text", intents=["non_text"], confidence=0, urgent=False, draft="",
        draft_mode="none", draft_note="", sources=[], checks=[], reasons=[reason], decision=ESCALATE,
        rag={"kind": "non_text", "answerable": False, "used_sources": [], "parts": []})
    db.add_audit(inquiry["id"], "AI assistant", "held", "Not a text message - sent straight to the receptionist.")
    reply: Optional[dict] = None
    if auto_reply_on:
        try:
            reply = outbound.send_reply(conversation, NON_TEXT_NOTICE, "assistant", inquiry["id"])
            db.add_audit(inquiry["id"], "AI assistant", "notice_sent", "Told the patient it can only read text messages.")
        except DeliveryError as exc:
            db.add_audit(inquiry["id"], "System", "delivery_failed", str(exc))
    return {"conversation_id": conversation["id"], "inquiry_id": inquiry["id"], "patient_message": patient_message,
            "reply": reply, "status": "escalated", "notice": db.open_notice(conversation["id"])}


@router.post("/api/webhook/whatsapp", summary="Receive a patient message (simulated WhatsApp)")
def receive_whatsapp_message(payload: IncomingMessage) -> dict:
    if whatsapp_cloud.is_cloud():
        # Otherwise anyone who can reach this URL could make the assistant message arbitrary phone numbers.
        raise HTTPException(status_code=409, detail="The simulated chat is switched off because WHATSAPP_MODE=cloud. "
                                                    "Patients now write to the real WhatsApp number.")
    phone, name, text = normalize_incoming(payload)
    return handle_incoming_message(phone, name, text)


@router.get("/api/chat/{phone}/messages", summary="Messages for the patient chat window")
def chat_messages(phone: str, after_id: int = 0) -> dict:
    """The patient chat page polls this to show new replies."""
    conversation = db.find_conversation(clean_phone(phone))
    if conversation is None:
        return {"messages": [], "notice": None}
    messages = [
        {"id": m["id"], "role": m["role"], "text": m["text"], "created_at": m["created_at"]}
        for m in db.list_messages(conversation["id"], after_id)
    ]
    return {"messages": messages, "notice": db.open_notice(conversation["id"])}
