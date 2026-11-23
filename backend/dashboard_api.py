"""API used by the receptionist dashboard."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import database as db
from . import outbound, validator, webhook, whatsapp_cloud
from .retriever import Source

router = APIRouter(prefix="/api/dashboard", tags=["Reception dashboard"])

# Sample patients for the "Load sample conversations" button. They run through the
# real AI pipeline, so the dashboard shows genuine decisions, sources and checks.
DEMO_MESSAGES = [
    ("919000000101", "Priya Patil", "Hi! What are your clinic timings on Sunday?"),
    ("919000000102", "Rohan Joshi", "root canal ka kharcha kitna hoga?"),
    ("919000000103", "Sneha Kulkarni", "I want to book an appointment for braces this Saturday evening"),
    ("919000000104", "Amit Shah", "Severe pain and swelling since last night, I can't sleep"),
    ("919000000105", "Neha Gupta", "Is teeth whitening safe? How long does it last?"),
    ("919000000106", "Karan Mehta", "Which doctor does implants and what is the cost?"),
    ("919000000107", "Meera Iyer", "I'm very disappointed. I was overcharged on my last visit and want a refund."),
    ("919000000108", "Vikram Rao", "Do you accept insurance? Also where exactly are you located?"),
]


class SendBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)
    acknowledge: bool = Field(False, description="Send even though the checks below flagged problems")


class RejectBody(BaseModel):
    reason: str = Field("", max_length=300)


class SettingsBody(BaseModel):
    auto_reply: bool


def _no_demo_tools_in_cloud_mode() -> None:
    """Demo conversations use made-up numbers and 'reset' deletes everything - never allowed with real patients."""
    if whatsapp_cloud.is_cloud():
        raise HTTPException(status_code=409, detail="Demo tools are switched off while WHATSAPP_MODE=cloud, to protect "
                                                    "real patient conversations.")


def _detail(inquiry_id: int) -> dict:
    inquiry = db.get_inquiry(inquiry_id)
    if inquiry is None:
        raise HTTPException(status_code=404, detail="Message not found.")
    inquiry["thread"] = db.list_messages(inquiry["conversation_id"])
    if whatsapp_cloud.is_cloud() and inquiry.get("patient_channel") == "whatsapp":
        last = db.last_patient_message_at(inquiry["conversation_id"])
        hours = (db.datetime.now(db.timezone.utc) - db.datetime.fromisoformat(last)).total_seconds() / 3600 if last else None
        # WhatsApp only allows a free-form reply within 24 hours of the patient's last message.
        inquiry["whatsapp_window"] = {"open": hours is not None and hours < 24, "hours_since": None if hours is None else round(hours, 1)}
    return inquiry


def _open_inquiry(inquiry_id: int) -> dict:
    inquiry = _detail(inquiry_id)
    if inquiry["status"] not in db.OPEN_STATUSES:
        raise HTTPException(status_code=409, detail="This message has already been handled.")
    return inquiry


@router.get("/stats")
def stats() -> dict:
    return db.stats()


@router.get("/inquiries")
def inquiries(status: str = "all", limit: int = 200) -> dict:
    if status not in db.STATUS_FILTERS:
        raise HTTPException(status_code=422, detail=f"status must be one of {sorted(db.STATUS_FILTERS)}")
    rows = db.list_inquiries(status, min(max(limit, 1), 500))
    for row in rows:  # the list view does not need the heavy fields
        row["failed_checks"] = sum(1 for c in row.get("checks", [])
                                   if not c["passed"] and c["severity"] == "block" and c["name"] != "answer_found")
        for key in ("sources", "checks", "audit"):
            row.pop(key, None)
    return {"inquiries": rows}


@router.get("/inquiries/{inquiry_id}")
def inquiry_detail(inquiry_id: int) -> dict:
    return _detail(inquiry_id)


def _send_warnings(inquiry: dict, text: str, unchanged: bool) -> list[dict]:
    """Problems a person should know about before sending: the draft's failed checks, or - if the reply
    was edited or written by hand - the same code checks run again on the new text."""
    if unchanged:
        failed = [c for c in inquiry["checks"] if not c["passed"] and c["severity"] == "block"]
        return [{"label": c["label"], "detail": c["detail"], "group": c.get("group", "validity")} for c in failed]
    sources = [Source.from_record(s) for s in inquiry["sources"]]
    failed = validator.failed_blocks(validator.check_text(text, sources, inquiry["question"]))
    return [{"label": c.label, "detail": c.detail, "group": c.group} for c in failed]


@router.post("/inquiries/{inquiry_id}/send")
def send(inquiry_id: int, body: SendBody) -> dict:
    """APPROVE or EDIT: a person sends a reply to the patient. Nothing is sent until this is called.

    If the text is unchanged from the AI draft it counts as "approved"; if the receptionist edited or wrote
    it, it counts as "replied". A draft that failed verification, or an edited reply that fails the same
    checks, is only sent when `acknowledge` is true (the dashboard asks the receptionist to confirm)."""
    inquiry = _open_inquiry(inquiry_id)
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Reply is empty.")
    draft = inquiry["draft"].strip()
    unchanged = text == draft

    warnings = _send_warnings(inquiry, text, unchanged)
    if warnings and not body.acknowledge:
        raise HTTPException(status_code=409, detail={"needs_acknowledgement": True, "warnings": warnings})

    conversation = {"id": inquiry["conversation_id"], "phone": inquiry["patient_phone"],
                    "channel": inquiry.get("patient_channel", "simulated")}
    used = [{"id": s["id"], "title": s["title"], "file": s["file"]} for s in inquiry["sources"] if s.get("used")] if draft else []
    meta = {"approved_by": "Receptionist", "edited": not unchanged, "overrode_checks": [w["label"] for w in warnings]}
    try:
        outbound.send_reply(conversation, text, "receptionist", inquiry_id, sources=used, meta=meta)
    except whatsapp_cloud.DeliveryError as exc:
        # WhatsApp did not take the message, so nothing was sent and the item stays open to try again.
        db.add_audit(inquiry_id, "System", "delivery_failed", str(exc))
        raise HTTPException(status_code=502, detail={"delivery_failed": True, "message": str(exc), "code": exc.code}) from None

    status = "approved" if unchanged else "replied"
    db.update_inquiry(inquiry_id, status=status, final_reply=text, resolved_by="Receptionist", resolved_at=db.now())
    detail = ("Approved the AI draft unchanged." if unchanged else "Edited the reply and sent it." if draft else "Wrote and sent a reply.")
    if warnings:
        detail += " Overrode: " + "; ".join(w["label"] for w in warnings) + "."
    db.add_audit(inquiry_id, "Receptionist", "approved" if unchanged else "sent_edited" if draft else "sent_manual", detail)
    return _detail(inquiry_id)


@router.post("/inquiries/{inquiry_id}/reject")
def reject(inquiry_id: int, body: RejectBody) -> dict:
    """REJECT the AI draft. It is never sent. The message stays open so the receptionist can write their own reply."""
    inquiry = _open_inquiry(inquiry_id)
    if not inquiry["draft"].strip():
        raise HTTPException(status_code=409, detail="There is no AI draft to reject.")
    rag = dict(inquiry["rag"], draft_rejected=True, rejected_draft=inquiry["draft"], rejected_reason=body.reason.strip())
    reason = f"The AI draft was rejected by the receptionist{': ' + body.reason.strip() if body.reason.strip() else ''}."
    db.update_inquiry(inquiry_id, status="escalated", draft="", rag=rag, reasons=inquiry["reasons"] + [reason])
    db.add_audit(inquiry_id, "Receptionist", "rejected", reason)
    return _detail(inquiry_id)


@router.post("/inquiries/{inquiry_id}/escalate")
def escalate(inquiry_id: int) -> dict:
    inquiry = _open_inquiry(inquiry_id)
    if inquiry["status"] == "escalated":
        return inquiry
    db.update_inquiry(inquiry_id, status="escalated", reasons=inquiry["reasons"] + ["Escalated by the receptionist."])
    db.add_audit(inquiry_id, "Receptionist", "escalated", "Marked as needing a person (doctor or manager) to handle.")
    return _detail(inquiry_id)


@router.post("/inquiries/{inquiry_id}/dismiss")
def dismiss(inquiry_id: int) -> dict:
    """Close a message without replying (spam, wrong number...)."""
    _open_inquiry(inquiry_id)
    db.update_inquiry(inquiry_id, status="dismissed", resolved_by="Receptionist", resolved_at=db.now())
    db.add_audit(inquiry_id, "Receptionist", "dismissed", "Closed without sending a reply.")
    return _detail(inquiry_id)


@router.get("/settings")
def get_settings() -> dict:
    return {"auto_reply": db.get_setting("auto_reply", "1") == "1"}


@router.post("/settings")
def set_settings(body: SettingsBody) -> dict:
    db.set_setting("auto_reply", "1" if body.auto_reply else "0")
    return get_settings()


@router.post("/seed-demo")
def seed_demo() -> dict:
    _no_demo_tools_in_cloud_mode()
    for phone, name, text in DEMO_MESSAGES:
        webhook.handle_incoming_message(phone, name, text)
    return {"added": len(DEMO_MESSAGES)}


@router.post("/reset")
def reset() -> dict:
    _no_demo_tools_in_cloud_mode()
    db.reset_all()
    return {"ok": True}
