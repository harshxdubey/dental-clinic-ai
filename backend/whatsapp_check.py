"""Check your WhatsApp Cloud API setup.   Run these yourself - they are the live tests.

    python -m backend.whatsapp_check
        Checks that every setting is present, then asks Meta whether the access token and phone-number id
        work (a read-only request: nothing is sent to anyone).

    python -m backend.whatsapp_check --probe https://your-tunnel.example.com
        Checks that the PUBLIC address Meta will call reaches this app and that the verify token and App
        Secret are right. It sends Meta-style requests to your own webhook: a verification handshake, a
        correctly signed (harmless) event, and a badly signed one that must be refused. No patient message
        is created and nothing is sent to WhatsApp.

    python -m backend.whatsapp_check --send-test 9198XXXXXXXX "Hello from the clinic"
        Really sends ONE text message through the Cloud API. With Meta's test number the recipient must be
        on the allowed list; with any number the patient must have messaged you in the last 24 hours.

Secrets are never printed. Only whether each setting is present.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import secrets
import sys

import httpx

from . import config, whatsapp_cloud as wa
from .meta_webhook import WEBHOOK_PATH

OK, BAD = "OK  ", "FAIL"


def _line(ok: bool, text: str) -> bool:
    print(f"  [{OK if ok else BAD}] {text}")
    return ok


def check_settings() -> bool:
    print("1. Settings (values are never shown)")
    good = _line(wa.is_cloud(), f"WHATSAPP_MODE = {config.WHATSAPP_MODE}" + ("" if wa.is_cloud() else "   <- set WHATSAPP_MODE=cloud to go live"))
    descriptions = {
        "WHATSAPP_VERIFY_TOKEN": "verify token (you invent it; paste the same value into Meta)",
        "WHATSAPP_APP_SECRET": "app secret (Meta app > App settings > Basic)",
        "WHATSAPP_ACCESS_TOKEN": "access token (WhatsApp > API Setup)",
        "WHATSAPP_PHONE_NUMBER_ID": "phone number id (WhatsApp > API Setup)",
    }
    for name, description in descriptions.items():
        good &= _line(bool(getattr(config, name)), f"{name}: {description}")
    return good


def check_token() -> bool:
    print("2. Access token and phone-number id (read-only request to Meta)")
    try:
        info = wa.check_connection()
    except wa.DeliveryError as exc:
        return _line(False, str(exc))
    _line(True, f"Meta accepted the token. Number: {info.get('display_phone_number', '?')}, "
                f"name: {info.get('verified_name', '?')}, quality: {info.get('quality_rating', 'n/a')}")
    return True


def probe(client, base_url: str) -> bool:
    """Send Meta-style requests to a webhook URL. `client` is anything with httpx's get/post."""
    print(f"3. Webhook at {base_url}{WEBHOOK_PATH}")
    url = base_url.rstrip("/") + WEBHOOK_PATH
    good = True

    challenge = secrets.token_hex(6)
    try:
        r = client.get(url, params={"hub.mode": "subscribe", "hub.verify_token": config.WHATSAPP_VERIFY_TOKEN, "hub.challenge": challenge})
        good &= _line(r.status_code == 200 and r.text == challenge, f"verification handshake -> HTTP {r.status_code}"
                      + ("" if r.status_code == 200 else " (is WHATSAPP_MODE=cloud and the app running?)"))
        r = client.get(url, params={"hub.mode": "subscribe", "hub.verify_token": "definitely-wrong", "hub.challenge": "1"})
        good &= _line(r.status_code == 403, f"a WRONG verify token is refused -> HTTP {r.status_code}")

        harmless = json.dumps({"object": "whatsapp_business_account", "entry": [{"id": "probe", "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp", "metadata": {"phone_number_id": config.WHATSAPP_PHONE_NUMBER_ID},
            "statuses": [{"id": "wamid.PROBE-" + challenge, "status": "read", "recipient_id": "0"}]}}]}]}).encode()
        signature = "sha256=" + hmac.new(config.WHATSAPP_APP_SECRET.encode(), harmless, hashlib.sha256).hexdigest()
        r = client.post(url, content=harmless, headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature})
        good &= _line(r.status_code == 200, f"a correctly signed event is accepted -> HTTP {r.status_code}"
                      + ("" if r.status_code == 200 else "  (the App Secret in .env does not match the one Meta uses?)"))
        r = client.post(url, content=harmless, headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=" + "0" * 64})
        good &= _line(r.status_code == 403, f"a BADLY signed event is refused -> HTTP {r.status_code}")
    except httpx.HTTPError as exc:
        return _line(False, f"could not reach {url} ({type(exc).__name__}). Is the tunnel running and the URL right?")
    return good


def send_test(to: str, text: str) -> bool:
    print("4. Sending one real test message")
    try:
        delivery = wa.send_text("".join(ch for ch in to if ch.isdigit()), text)
    except wa.DeliveryError as exc:
        return _line(False, str(exc))
    return _line(True, f"Meta accepted the message (id {delivery.wa_message_id}). Check the phone.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check the WhatsApp Cloud API setup.")
    parser.add_argument("--probe", metavar="URL", help="public base URL of this app, e.g. https://abc.ngrok-free.app")
    parser.add_argument("--send-test", nargs=2, metavar=("NUMBER", "TEXT"), help="really send one text message")
    args = parser.parse_args(argv)
    wa.install_log_redaction()

    results = [check_settings()]
    if config.WHATSAPP_ACCESS_TOKEN and config.WHATSAPP_PHONE_NUMBER_ID:
        results.append(check_token())
    if args.probe:
        with httpx.Client(timeout=15) as client:
            results.append(probe(client, args.probe))
    if args.send_test:
        results.append(send_test(*args.send_test))
    print("\nAll checks passed." if all(results) else "\nSome checks failed - fix the lines marked FAIL, then run this again.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
