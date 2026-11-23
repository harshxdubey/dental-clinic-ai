"""The URLs Meta's servers call: verification (GET) and incoming events (POST).

Callback URL to give Meta:   https://<your-public-domain>/whatsapp/webhook

The rules this file follows (from Meta's webhook documentation):
  * GET  - echo back `hub.challenge` if `hub.verify_token` matches the token YOU chose;
  * POST - verify the `X-Hub-Signature-256` signature BEFORE trusting anything in the body;
  * always answer 200 quickly (Meta treats slow or failing endpoints as failed and re-sends the same
    event for up to 36 hours), so the real work happens AFTER the response, in the background;
  * because of those re-sends, every message id is claimed exactly once (see database.claim_inbound).

No secret, phone number or message text is written to the logs.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from . import config
from . import database as db
from . import webhook
from . import whatsapp_cloud as wa

log = logging.getLogger("clinic_ai.whatsapp")
router = APIRouter(tags=["WhatsApp Cloud API"])

WEBHOOK_PATH = "/whatsapp/webhook"
MAX_BODY_BYTES = 1_000_000


def _cloud_only() -> None:
    if not wa.is_cloud():
        raise HTTPException(status_code=409, detail="WhatsApp Cloud mode is off (WHATSAPP_MODE=simulated). "
                                                    "Set WHATSAPP_MODE=cloud in .env and restart.")


@router.get(WEBHOOK_PATH, response_class=PlainTextResponse, summary="Meta's verification handshake")
def verify(request: Request) -> PlainTextResponse:
    """Meta calls this once, when you press 'Verify and save' in the dashboard."""
    _cloud_only()
    if not config.WHATSAPP_VERIFY_TOKEN:
        raise HTTPException(status_code=503, detail="WHATSAPP_VERIFY_TOKEN is not set.")
    params = request.query_params
    challenge = wa.check_verification(params.get("hub.mode"), params.get("hub.verify_token"), params.get("hub.challenge"))
    if challenge is None:
        log.warning("Webhook verification refused: wrong verify token or mode")
        raise HTTPException(status_code=403, detail="Verification token mismatch.")
    log.info("Webhook verified by Meta")
    return PlainTextResponse(challenge)


@router.post(WEBHOOK_PATH, summary="Incoming WhatsApp events from Meta")
async def receive(request: Request, background: BackgroundTasks) -> JSONResponse:
    _cloud_only()
    if not config.WHATSAPP_APP_SECRET:
        # Without the App Secret we cannot tell Meta from an attacker, so we refuse rather than trust.
        raise HTTPException(status_code=503, detail="WHATSAPP_APP_SECRET is not set, so incoming messages cannot be "
                                                    "verified and are refused.")
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Body too large.")
    if not wa.verify_signature(raw, request.headers.get("x-hub-signature-256")):
        log.warning("Rejected a webhook POST: missing or invalid signature")
        raise HTTPException(status_code=403, detail="Invalid signature.")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Body is not valid JSON.") from None

    messages, statuses = wa.parse_payload(payload)
    summary = {"accepted": 0, "duplicates": 0, "ignored": 0, "statuses": len(statuses)}
    for status in statuses:
        _apply_status(status)
    for message in messages:
        outcome = _admit(message)
        summary[outcome] += 1
        if outcome == "accepted":
            background.add_task(process_inbound, message)
    return JSONResponse({"status": "ok", **summary})   # always 200 for a validly signed request


# --------------------------------------------------------------------------
def _admit(message: wa.InboundMessage) -> str:
    """Decide what to do with one incoming message: "accepted", "duplicates" or "ignored"."""
    if message.kind == "ignore":
        return "ignored"                                    # a reaction, an empty message...
    if config.WHATSAPP_PHONE_NUMBER_ID and message.phone_number_id != config.WHATSAPP_PHONE_NUMBER_ID:
        log.warning("Ignored a message addressed to a different WhatsApp number")
        return "ignored"
    if not 8 <= len(message.phone) <= 15:
        log.warning("Ignored a message with an invalid sender number")
        return "ignored"
    if config.WHATSAPP_ALLOWED_SENDERS and message.phone not in config.WHATSAPP_ALLOWED_SENDERS:
        log.info("Ignored a message from %s (not in WHATSAPP_ALLOWED_SENDERS)", wa.mask_phone(message.phone))
        return "ignored"
    claim = db.claim_inbound(message.wa_message_id, message.phone)
    if claim == "duplicate":
        log.info("Skipped duplicate message %s (already received)", message.wa_message_id)
        return "duplicates"
    if claim == "retry":
        log.info("Re-processing message %s (its earlier attempt did not finish)", message.wa_message_id)
    return "accepted"


def process_inbound(message: wa.InboundMessage) -> None:
    """Run one accepted message through classification, retrieval, verification and (if safe) a reply."""
    try:
        if message.kind == "unreadable":
            result = webhook.handle_unreadable_message(message.phone, message.name, message.text, message.wa_message_id)
        else:
            result = webhook.handle_incoming_message(message.phone, message.name, message.text,
                                                     wa_message_id=message.wa_message_id, channel="whatsapp")
        db.finish_inbound(message.wa_message_id, "done", inquiry_id=result["inquiry_id"])
        log.info("Processed message %s from %s -> %s", message.wa_message_id, wa.mask_phone(message.phone), result["status"])
    except Exception as exc:  # the webhook already answered 200: record the failure so it is visible, never raise
        db.finish_inbound(message.wa_message_id, "failed", error=type(exc).__name__)
        log.error("Could not process message %s (%s)", message.wa_message_id, type(exc).__name__, exc_info=True)


def _apply_status(status: wa.StatusUpdate) -> None:
    """A delivery update for a message WE sent: sent / delivered / read / failed."""
    error = f"{status.error_title} (code {status.error_code})" if status.status == "failed" else ""
    if not db.set_delivery(status.wa_message_id, status.status, error):
        return   # not one of ours (or already forgotten)
    if status.status != "failed":
        return
    log.warning("WhatsApp reported message %s as failed (code %s)", status.wa_message_id, status.error_code)
    message = db.find_message_by_wa_id(status.wa_message_id)
    if not message or not message["inquiry_id"]:
        return
    inquiry = db.get_inquiry(message["inquiry_id"])
    detail = wa.explain_error(status.error_code, None, status.error_title)
    db.add_audit(inquiry["id"], "System", "delivery_failed", f"WhatsApp reported this message as not delivered: {detail}")
    if inquiry["status"] == "auto_replied" and message["role"] == "assistant":
        # The patient never got our automatic answer, so it is not "done": hand it to a person.
        db.update_inquiry(inquiry["id"], status="pending_approval",
                          reasons=inquiry["reasons"] + [f"WhatsApp could not deliver the automatic reply: {detail}"])


@router.get("/api/whatsapp/status", summary="Is WhatsApp connected? (never shows secrets)")
def status() -> dict:
    return {**wa.status_summary(), "webhook_path": WEBHOOK_PATH, "events": db.inbound_counts()}


@router.get("/healthz", include_in_schema=False)
def healthz() -> dict:
    return {"ok": True}
