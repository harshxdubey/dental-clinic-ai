"""Client for the OFFICIAL Meta WhatsApp Cloud API (no unofficial libraries, no scraping).

What lives here
  * checking a webhook's signature and answering Meta's verification handshake
  * turning Meta's JSON into plain messages / delivery updates
  * sending a text message through the Graph API, with careful error handling
  * keeping secrets out of logs

Where the official behaviour is documented (developers.facebook.com):
  * Webhooks:  GET handshake with hub.mode / hub.verify_token / hub.challenge; every POST is signed with
               the App Secret in the `X-Hub-Signature-256` header ("sha256=" + HMAC-SHA256 of the RAW body);
               always answer 200; failed deliveries are retried for up to 36 hours (so de-duplicate).
  * Sending:   POST {graph}/{version}/{phone-number-id}/messages  with  Authorization: Bearer <token>.
  * Free-form replies are only allowed within 24 hours of the patient's last message.

No secret is ever logged or put in an error message: see `redact` and `install_log_redaction`.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

import httpx

from . import config

log = logging.getLogger("clinic_ai.whatsapp")

# Names of the variables each job needs (the VALUES are never shown anywhere).
REQUIRED_TO_RECEIVE = ("WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET", "WHATSAPP_PHONE_NUMBER_ID")
REQUIRED_TO_SEND = ("WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID")
MAX_TEXT_CHARS = 1000        # we keep patient text to the same limit as the simulated chat
MAX_SEND_CHARS = 4096        # WhatsApp's own limit for a text message body
SEND_ATTEMPTS = 3

# A test can plug a fake Graph API in here (an httpx transport). In normal use this stays None.
_transport: Optional[httpx.BaseTransport] = None


def _pause(seconds: float) -> None:
    time.sleep(seconds)    # a separate function so tests can skip the waiting


def set_transport(transport: Optional[httpx.BaseTransport]) -> None:
    global _transport
    _transport = transport


# --------------------------------------------------------------------------
# Mode and configuration
# --------------------------------------------------------------------------
def is_cloud() -> bool:
    return config.WHATSAPP_MODE == "cloud"


def missing_settings(names: tuple = REQUIRED_TO_RECEIVE + REQUIRED_TO_SEND) -> list[str]:
    """Names (never values) of required settings that are empty."""
    return [n for n in dict.fromkeys(names) if not getattr(config, n)]


def status_summary() -> dict:
    """Safe to show anywhere: booleans and names only."""
    return {
        "mode": config.WHATSAPP_MODE,
        "ready_to_receive": not missing_settings(REQUIRED_TO_RECEIVE),
        "ready_to_send": not missing_settings(REQUIRED_TO_SEND),
        "missing": missing_settings() if is_cloud() else [],
        "graph_api_version": config.WHATSAPP_GRAPH_API_VERSION,
        "restricted_to_allowed_senders": bool(config.WHATSAPP_ALLOWED_SENDERS),
    }


# --------------------------------------------------------------------------
# Keeping secrets out of logs
# --------------------------------------------------------------------------
_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")
_META_TOKEN = re.compile(r"\bEA[A-Za-z0-9]{20,}\b")


def redact(text: str) -> str:
    """Replace any configured secret (and anything that looks like a Meta token) with a marker."""
    for secret in config.secret_values():
        text = text.replace(secret, "[redacted]")
    return _META_TOKEN.sub("[redacted-token]", _BEARER.sub("Bearer [redacted]", text))


def mask_phone(phone: str) -> str:
    """Patient phone numbers are personal data: logs only ever show the last 4 digits."""
    return "••••" + phone[-4:] if len(phone) > 4 else "••••"


_redaction_installed = False


def install_log_redaction() -> None:
    """Scrub secrets from EVERY log record in the program (ours, uvicorn's, libraries')."""
    global _redaction_installed
    if _redaction_installed:
        return
    previous = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        try:
            record.msg, record.args = redact(record.getMessage()), ()
        except Exception:  # logging must never crash the app
            pass
        return record

    logging.setLogRecordFactory(factory)
    _redaction_installed = True


# --------------------------------------------------------------------------
# Webhook security: verification handshake and signature
# --------------------------------------------------------------------------
def check_verification(mode: Optional[str], token: Optional[str], challenge: Optional[str]) -> Optional[str]:
    """Meta's GET handshake. Returns the challenge to echo back, or None to refuse."""
    expected = config.WHATSAPP_VERIFY_TOKEN
    if not expected or mode != "subscribe" or token is None or challenge is None:
        return None
    return challenge if hmac.compare_digest(token.encode(), expected.encode()) else None


def verify_signature(raw_body: bytes, header: Optional[str], app_secret: Optional[str] = None) -> bool:
    """Is this POST really from Meta? `header` is X-Hub-Signature-256; the HMAC is over the RAW bytes."""
    secret = config.WHATSAPP_APP_SECRET if app_secret is None else app_secret
    if not header or not secret:
        return False
    scheme, _, digest = header.strip().partition("=")
    if scheme != "sha256" or not digest:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, digest.strip().lower())


# --------------------------------------------------------------------------
# Reading what Meta sends
# --------------------------------------------------------------------------
@dataclass
class InboundMessage:
    wa_message_id: str      # "wamid...." - unique per message; the key for duplicate protection
    phone: str              # the sender's WhatsApp number (digits, international format)
    name: str               # their WhatsApp profile name ("Patient" if unknown)
    kind: str               # "text" | "unreadable" | "ignore"
    text: str               # what they wrote (text) or what they sent ("a voice message"...)
    phone_number_id: str    # which of OUR numbers they wrote to
    timestamp: str = ""


@dataclass
class StatusUpdate:
    wa_message_id: str      # the id of a message WE sent
    status: str             # sent | delivered | read | failed
    error_code: Optional[int] = None
    error_title: str = ""


_UNREADABLE_LABELS = {
    "image": "a photo", "video": "a video", "document": "a file", "sticker": "a sticker", "location": "a location",
    "contacts": "a contact card", "order": "an order", "audio": "a voice or audio message",
}
_IGNORED_TYPES = {"reaction", "system", "unsupported", "request_welcome", "ephemeral", "unknown"}


def _read_message(raw: dict, names: dict, phone_number_id: str) -> Optional[InboundMessage]:
    wa_id, sender, kind = raw.get("id"), str(raw.get("from", "")), raw.get("type", "")
    if not wa_id or not sender:
        return None
    phone = re.sub(r"\D", "", sender)
    base = dict(wa_message_id=wa_id, phone=phone, name=names.get(sender) or names.get(phone) or "Patient",
                phone_number_id=phone_number_id, timestamp=str(raw.get("timestamp", "")))

    text = None
    if kind == "text":
        text = (raw.get("text") or {}).get("body", "")
    elif kind == "interactive":  # the patient tapped a button or picked a list item
        inter = raw.get("interactive") or {}
        picked = inter.get("button_reply") or inter.get("list_reply") or {}
        text = picked.get("title")
        if text is None:
            return InboundMessage(kind="unreadable", text="an interactive reply", **base)
    elif kind == "button":       # a quick-reply button on one of our template messages
        text = (raw.get("button") or {}).get("text", "")
    elif kind in _UNREADABLE_LABELS:
        return InboundMessage(kind="unreadable", text=_UNREADABLE_LABELS[kind], **base)
    elif kind in _IGNORED_TYPES:
        return InboundMessage(kind="ignore", text="", **base)
    else:
        return InboundMessage(kind="unreadable", text="a message the assistant cannot read", **base)

    text = (text or "").strip()
    if not text:
        return InboundMessage(kind="ignore", text="", **base)
    return InboundMessage(kind="text", text=text[:MAX_TEXT_CHARS], **base)


def parse_payload(payload: dict) -> tuple[list[InboundMessage], list[StatusUpdate]]:
    """Meta's JSON -> (messages from patients, delivery updates for messages we sent).

    Tolerant of anything unexpected: a malformed part is skipped, never an exception.
    """
    messages: list[InboundMessage] = []
    statuses: list[StatusUpdate] = []
    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        return messages, statuses
    for entry in payload.get("entry") or []:
        for change in (entry or {}).get("changes") or []:
            if (change or {}).get("field") != "messages":
                continue
            value = change.get("value") or {}
            number_id = str((value.get("metadata") or {}).get("phone_number_id", ""))
            names = {str(c.get("wa_id", "")): (c.get("profile") or {}).get("name", "") for c in value.get("contacts") or []
                     if isinstance(c, dict)}
            for raw in value.get("messages") or []:
                parsed = _read_message(raw, names, number_id) if isinstance(raw, dict) else None
                if parsed:
                    messages.append(parsed)
            for raw in value.get("statuses") or []:
                if isinstance(raw, dict) and raw.get("id") and raw.get("status"):
                    error = (raw.get("errors") or [{}])[0] if raw.get("errors") else {}
                    statuses.append(StatusUpdate(raw["id"], str(raw["status"]), error.get("code"),
                                                 str(error.get("title") or error.get("message") or "")))
    return messages, statuses


# --------------------------------------------------------------------------
# Sending
# --------------------------------------------------------------------------
class DeliveryError(RuntimeError):
    """A message could not be delivered. str(error) is a plain-English explanation safe to show anyone."""

    def __init__(self, message: str, *, code: Optional[int] = None, http_status: Optional[int] = None,
                 retryable: bool = False, trace_id: Optional[str] = None):
        super().__init__(message)
        self.code, self.http_status, self.retryable, self.trace_id = code, http_status, retryable, trace_id


@dataclass
class Delivery:
    status: str                           # "simulated" | "sent"
    wa_message_id: Optional[str] = None   # Meta's id for the message we sent


def explain_error(code: Optional[int], http_status: Optional[int], detail: str = "") -> str:
    """Turn a Graph API error into something a receptionist can act on. Never includes secrets."""
    if code in (190, 102) or http_status == 401:
        return ("WhatsApp rejected our access token (it is invalid or has expired). Create a new token in the Meta "
                "dashboard and update WHATSAPP_ACCESS_TOKEN.")
    if code == 131047:
        return ("More than 24 hours have passed since the patient's last message, so WhatsApp does not allow a "
                "free-form reply. Use an approved message template, or wait for the patient to write again.")
    if code == 131030:
        return ("This number is not on the allowed list. While you use Meta's test number, add the patient's number "
                "under API Setup > 'To' and verify it.")
    if code in (130429, 131056, 80007, 4, 17, 32, 613) or http_status == 429:
        return "WhatsApp is rate limiting us (too many messages, too fast). Try again in a minute."
    if code in (131026,):
        return "WhatsApp could not deliver to this number (it may not be on WhatsApp, or the patient blocked us)."
    if code in (131031, 368):
        return "The WhatsApp Business account is restricted or locked. Check the account status in Meta Business Suite."
    if code in (100, 131008, 131009, 33):
        return f"WhatsApp rejected the request as invalid (code {code}): {redact(detail)[:160]}"
    if http_status and http_status >= 500:
        return "WhatsApp's servers had a problem. Try again shortly."
    suffix = f" (code {code})" if code else ""
    return f"WhatsApp refused the message{suffix}: {redact(detail)[:160] or 'no details given'}"


def _graph_url(path: str) -> str:
    return f"{config.WHATSAPP_GRAPH_BASE_URL}/{config.WHATSAPP_GRAPH_API_VERSION}/{path}"


def _error_fields(response: httpx.Response) -> tuple[Optional[int], str, Optional[str]]:
    try:
        error = response.json().get("error") or {}
    except ValueError:
        return None, response.text[:200], None
    return error.get("code"), str(error.get("message") or error.get("error_data", {}).get("details") or ""), error.get("fbtrace_id")


def send_text(to: str, text: str) -> Delivery:
    """Send a free-form text message to a patient who has messaged us in the last 24 hours.

    Retries only when it is safe (the request never reached WhatsApp, or WhatsApp said it failed with a 5xx / 429).
    A timeout while waiting for the answer is NOT retried: the message may already have been sent, and
    sending it twice to a patient is worse than asking a person to check.
    """
    missing = missing_settings(REQUIRED_TO_SEND)
    if missing:
        raise DeliveryError("WhatsApp sending is not set up (missing: " + ", ".join(missing) + ").")
    if not re.fullmatch(r"\d{8,15}", to):
        raise DeliveryError("That does not look like a WhatsApp phone number.")

    body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to,
            "type": "text", "text": {"preview_url": False, "body": text[:MAX_SEND_CHARS]}}
    headers = {"Authorization": f"Bearer {config.WHATSAPP_ACCESS_TOKEN}", "Content-Type": "application/json"}
    url = _graph_url(f"{config.WHATSAPP_PHONE_NUMBER_ID}/messages")

    for attempt in range(1, SEND_ATTEMPTS + 1):
        try:
            with httpx.Client(transport=_transport, timeout=config.WHATSAPP_SEND_TIMEOUT_SECONDS) as client:
                response = client.post(url, json=body, headers=headers)
        except (httpx.ConnectError, httpx.ConnectTimeout):       # never reached WhatsApp: safe to retry
            if attempt < SEND_ATTEMPTS:
                _pause(attempt)
                continue
            raise DeliveryError("Could not reach WhatsApp (network problem). The message was not sent.", retryable=True) from None
        except httpx.TimeoutException:
            raise DeliveryError("WhatsApp did not answer in time. The message MAY have been sent - check the "
                                "conversation before trying again.") from None
        except httpx.HTTPError as exc:
            raise DeliveryError(f"Network error while contacting WhatsApp ({type(exc).__name__}). The message was not confirmed.") from None

        if response.status_code == 200:
            try:
                wa_id = (response.json().get("messages") or [{}])[0].get("id")
            except (ValueError, AttributeError):
                wa_id = None
            log.info("Sent a WhatsApp message to %s (id %s)", mask_phone(to), wa_id or "unknown")
            return Delivery(status="sent", wa_message_id=wa_id)

        code, detail, trace = _error_fields(response)
        transient = response.status_code >= 500 or response.status_code == 429
        if transient and attempt < SEND_ATTEMPTS:
            _pause(attempt)
            continue
        log.warning("WhatsApp send failed: http %s, code %s, trace %s", response.status_code, code, trace)
        raise DeliveryError(explain_error(code, response.status_code, detail), code=code,
                            http_status=response.status_code, retryable=transient, trace_id=trace)
    raise DeliveryError("The message could not be sent.")   # unreachable, keeps type checkers calm


def check_connection() -> dict:
    """A read-only check that the token and phone-number id work (sends nothing). Used by whatsapp_check.py."""
    missing = missing_settings(REQUIRED_TO_SEND)
    if missing:
        raise DeliveryError("Missing settings: " + ", ".join(missing))
    url = _graph_url(config.WHATSAPP_PHONE_NUMBER_ID)
    headers = {"Authorization": f"Bearer {config.WHATSAPP_ACCESS_TOKEN}"}
    try:
        with httpx.Client(transport=_transport, timeout=config.WHATSAPP_SEND_TIMEOUT_SECONDS) as client:
            response = client.get(url, params={"fields": "display_phone_number,verified_name,quality_rating"}, headers=headers)
    except httpx.HTTPError as exc:
        raise DeliveryError(f"Could not reach the Graph API ({type(exc).__name__}).") from None
    if response.status_code != 200:
        code, detail, trace = _error_fields(response)
        raise DeliveryError(explain_error(code, response.status_code, detail), code=code, http_status=response.status_code, trace_id=trace)
    return response.json()
