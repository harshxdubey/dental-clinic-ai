"""The Cloud API building blocks: signatures, the handshake, reading Meta's payloads, sending, error handling,
and keeping secrets out of logs.

IMPORTANT: nothing here talks to Meta. These tests use payloads shaped like Meta's documentation, a fake Graph
API, and (in test_graph_http.py) a local HTTP server. They prove OUR code behaves correctly; they cannot prove
that Meta's real servers accept it. See documentation/WHATSAPP_CLOUD_SETUP.md for the live test.
"""
import logging

import httpx
import pytest
from conftest import CLOUD_SETTINGS, PATIENT, meta_payload, sign, text_message
from fake_graph import graph_error

from backend import config, database
from backend import whatsapp_cloud as wa

TOKEN = CLOUD_SETTINGS["WHATSAPP_ACCESS_TOKEN"]
SECRETS = [TOKEN, CLOUD_SETTINGS["WHATSAPP_APP_SECRET"], CLOUD_SETTINGS["WHATSAPP_VERIFY_TOKEN"]]


# ================================================================ signature
def test_signature_matches_a_published_hmac_test_vector():
    """HMAC-SHA256("key", "The quick brown fox...") - the well-known reference value, independent of our code."""
    body = b"The quick brown fox jumps over the lazy dog"
    header = "sha256=f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8"
    assert wa.verify_signature(body, header, "key") is True


@pytest.mark.parametrize("header,secret,body", [
    (None, "key", b"x"), ("", "key", b"x"), ("sha256=", "key", b"x"), ("garbage", "key", b"x"),
    ("sha1=" + "0" * 40, "key", b"x"), ("sha256=" + "0" * 64, "key", b"x"),
])
def test_bad_or_missing_signatures_are_rejected(header, secret, body):
    assert wa.verify_signature(body, header, secret) is False


def test_a_changed_body_or_wrong_secret_breaks_the_signature():
    body = b'{"a": 1}'
    good = sign(body, "secret-1")
    assert wa.verify_signature(body, good, "secret-1")
    assert not wa.verify_signature(b'{"a": 2}', good, "secret-1")
    assert not wa.verify_signature(body, good, "secret-2")
    assert not wa.verify_signature(body, good, "")          # no secret configured -> nothing is trusted


def test_signature_is_checked_on_the_raw_bytes_not_the_parsed_json():
    body = b'{"a":    1}'                                    # odd spacing must still verify
    assert wa.verify_signature(body, sign(body, "k"), "k")
    assert not wa.verify_signature(b'{"a": 1}', sign(body, "k"), "k")


# ================================================================ handshake
def test_handshake_echoes_the_challenge_only_for_the_right_token(monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_VERIFY_TOKEN", "right-token-1")
    assert wa.check_verification("subscribe", "right-token-1", "1158201444") == "1158201444"
    assert wa.check_verification("subscribe", "wrong-token", "1158201444") is None
    assert wa.check_verification("unsubscribe", "right-token-1", "1") is None
    assert wa.check_verification("subscribe", None, "1") is None
    assert wa.check_verification("subscribe", "right-token-1", None) is None


def test_handshake_refuses_everything_when_no_token_is_configured(monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_VERIFY_TOKEN", "")
    assert wa.check_verification("subscribe", "", "1") is None


# ================================================================ reading Meta's payloads
def parse(*messages, **kw):
    return wa.parse_payload(meta_payload(list(messages), **kw))


def test_text_message_and_sender():
    messages, statuses = parse(text_message("Does it hurt?", "wamid.A"), name="Asha Patil")
    assert statuses == [] and len(messages) == 1
    m = messages[0]
    assert (m.kind, m.text, m.wa_message_id, m.phone, m.name) == ("text", "Does it hurt?", "wamid.A", PATIENT, "Asha Patil")
    assert m.phone_number_id == CLOUD_SETTINGS["WHATSAPP_PHONE_NUMBER_ID"]


def test_sender_without_a_profile_name_is_called_patient():
    payload = meta_payload([text_message("hi")])
    payload["entry"][0]["changes"][0]["value"].pop("contacts")
    assert wa.parse_payload(payload)[0][0].name == "Patient"


def test_phone_is_reduced_to_digits():
    assert parse(text_message("hi", sender="+91 98765 00001"))[0][0].phone == "919876500001"


INTERACTIVE = [
    ({"type": "button_reply", "button_reply": {"id": "b1", "title": "Book a visit"}}, "Book a visit"),
    ({"type": "list_reply", "list_reply": {"id": "l1", "title": "Teeth whitening", "description": "x"}}, "Teeth whitening"),
]


@pytest.mark.parametrize("interactive,expected", INTERACTIVE)
def test_buttons_and_list_choices_are_read_as_text(interactive, expected):
    message = {"from": PATIENT, "id": "wamid.I", "timestamp": "1", "type": "interactive", "interactive": interactive}
    m = parse(message)[0][0]
    assert (m.kind, m.text) == ("text", expected)


def test_template_quick_reply_button_is_read_as_text():
    m = parse({"from": PATIENT, "id": "wamid.B", "timestamp": "1", "type": "button", "button": {"text": "Yes", "payload": "p"}})[0][0]
    assert (m.kind, m.text) == ("text", "Yes")


@pytest.mark.parametrize("kind,label", [
    ("image", "a photo"), ("audio", "a voice or audio message"), ("video", "a video"), ("document", "a file"),
    ("sticker", "a sticker"), ("location", "a location"), ("contacts", "a contact card"),
])
def test_things_the_assistant_cannot_read_are_flagged_for_a_person(kind, label):
    m = parse({"from": PATIENT, "id": "wamid.M", "timestamp": "1", "type": kind, kind: {"id": "media-1"}})[0][0]
    assert (m.kind, m.text) == ("unreadable", label)


@pytest.mark.parametrize("kind", ["reaction", "system", "unsupported", "ephemeral"])
def test_reactions_and_system_events_are_ignored(kind):
    assert parse({"from": PATIENT, "id": "wamid.R", "timestamp": "1", "type": kind})[0][0].kind == "ignore"


def test_an_empty_text_is_ignored_and_a_long_one_is_trimmed():
    assert parse(text_message("   "))[0][0].kind == "ignore"
    assert len(parse(text_message("x" * 5000))[0][0].text) == wa.MAX_TEXT_CHARS


def test_an_unknown_message_type_is_handed_to_a_person_not_dropped():
    m = parse({"from": PATIENT, "id": "wamid.U", "timestamp": "1", "type": "brand_new_type"})[0][0]
    assert m.kind == "unreadable"


def test_delivery_statuses_are_read():
    statuses = wa.parse_payload(meta_payload(statuses=[
        {"id": "wamid.1", "status": "delivered", "recipient_id": PATIENT},
        {"id": "wamid.2", "status": "failed", "recipient_id": PATIENT, "errors": [{"code": 131026, "title": "Message undeliverable"}]},
    ]))[1]
    assert [(s.wa_message_id, s.status) for s in statuses] == [("wamid.1", "delivered"), ("wamid.2", "failed")]
    assert statuses[1].error_code == 131026 and statuses[1].error_title == "Message undeliverable"


def test_several_messages_in_one_request_are_all_read():
    messages = parse(text_message("one", "wamid.1"), text_message("two", "wamid.2"))[0]
    assert [m.text for m in messages] == ["one", "two"]


@pytest.mark.parametrize("payload", [
    {}, [], "text", None, {"object": "page", "entry": []}, {"object": "whatsapp_business_account"},
    {"object": "whatsapp_business_account", "entry": [None, {"changes": [None, {"field": "other"}, {"field": "messages"}]}]},
    {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {"messages": ["x", 5, {}]}}]}]},
])
def test_malformed_payloads_never_raise(payload):
    assert wa.parse_payload(payload) == ([], [])


# ================================================================ sending
@pytest.fixture
def graph(cloud):
    return cloud.graph


def test_the_request_we_send_matches_the_documented_format(graph):
    delivery = wa.send_text(PATIENT, "Hello from the clinic")
    assert delivery == wa.Delivery(status="sent", wa_message_id="wamid.OUT1")
    request = graph.send_requests[0]
    assert request.url.path == "/v25.0/1055550001/messages" and request.method == "POST"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.headers["content-type"].startswith("application/json")
    assert graph.sends[0] == {"messaging_product": "whatsapp", "recipient_type": "individual", "to": PATIENT,
                              "type": "text", "text": {"preview_url": False, "body": "Hello from the clinic"}}


def test_the_token_is_only_ever_in_the_authorization_header(graph):
    wa.send_text(PATIENT, "Hello")
    request = graph.send_requests[0]
    assert TOKEN not in str(request.url) and TOKEN not in request.content.decode()


def test_long_text_is_cut_to_whatsapps_limit(graph):
    wa.send_text(PATIENT, "x" * 9000)
    assert len(graph.sends[0]["text"]["body"]) == wa.MAX_SEND_CHARS


def test_a_success_reply_without_an_id_is_still_a_success(graph):
    import httpx as h
    graph.script.append(h.Response(200, json={"messaging_product": "whatsapp"}))
    assert wa.send_text(PATIENT, "Hi") == wa.Delivery(status="sent", wa_message_id=None)


def test_sending_needs_the_settings_and_names_only_the_missing_variables(monkeypatch, graph):
    monkeypatch.setattr(config, "WHATSAPP_ACCESS_TOKEN", "")
    with pytest.raises(wa.DeliveryError) as error:
        wa.send_text(PATIENT, "Hi")
    assert "WHATSAPP_ACCESS_TOKEN" in str(error.value) and TOKEN not in str(error.value)
    assert graph.requests == []


@pytest.mark.parametrize("number", ["abc", "123", "+919876500001", "", "9" * 20])
def test_obviously_wrong_numbers_are_refused_before_any_request(graph, number):
    with pytest.raises(wa.DeliveryError, match="phone number"):
        wa.send_text(number, "Hi")
    assert graph.requests == []


# ---- the error cases a real deployment will hit ----
ERRORS = [
    (190, 401, "access token", False), (131047, 400, "24 hours", False), (131030, 400, "allowed list", False),
    (130429, 429, "rate limiting", True), (131026, 400, "could not deliver", False), (100, 400, "invalid", False),
    (131031, 400, "restricted", False),
]


@pytest.mark.parametrize("code,status,fragment,transient", ERRORS)
def test_graph_errors_become_plain_english(graph, code, status, fragment, transient):
    graph.script.extend([graph_error(code, "details here", status)] * wa.SEND_ATTEMPTS)
    with pytest.raises(wa.DeliveryError) as error:
        wa.send_text(PATIENT, "Hi")
    assert fragment in str(error.value) and error.value.code == code and error.value.trace_id == "AbCdEf123"
    assert len(graph.send_requests) == (wa.SEND_ATTEMPTS if transient else 1)    # only rate limits are retried


def test_server_errors_are_retried_and_can_recover(graph):
    graph.script.extend([httpx.Response(500), httpx.Response(502)])
    assert wa.send_text(PATIENT, "Hi").status == "sent"
    assert len(graph.send_requests) == 3


def test_server_errors_give_up_after_three_attempts(graph):
    graph.script.extend([httpx.Response(503)] * 3)
    with pytest.raises(wa.DeliveryError) as error:
        wa.send_text(PATIENT, "Hi")
    assert error.value.retryable and len(graph.send_requests) == 3 and "servers" in str(error.value)


def test_connection_failures_are_retried_because_nothing_was_sent(graph):
    graph.script.extend([httpx.ConnectError("no route"), httpx.ConnectTimeout("slow")])
    assert wa.send_text(PATIENT, "Hi").status == "sent"
    assert len(graph.send_requests) == 3


def test_a_timeout_while_waiting_is_never_retried_because_it_may_have_been_sent(graph):
    graph.script.append(httpx.ReadTimeout("no answer"))
    with pytest.raises(wa.DeliveryError, match="MAY have been sent"):
        wa.send_text(PATIENT, "Hi")
    assert len(graph.send_requests) == 1            # sending twice to a patient is worse than asking a person to check


def test_an_error_that_echoes_the_token_is_scrubbed(graph):
    graph.script.append(graph_error(100, f"bad request, Authorization: Bearer {TOKEN} was used"))
    with pytest.raises(wa.DeliveryError) as error:
        wa.send_text(PATIENT, "Hi")
    assert TOKEN not in str(error.value)


def test_a_non_json_error_page_does_not_crash(graph):
    graph.script.append(httpx.Response(400, text="<html>Bad gateway</html>"))
    with pytest.raises(wa.DeliveryError):
        wa.send_text(PATIENT, "Hi")


# ================================================================ secrets stay secret
def test_redact_removes_every_configured_secret(cloud):
    line = f"token={TOKEN} secret={CLOUD_SETTINGS['WHATSAPP_APP_SECRET']} verify={CLOUD_SETTINGS['WHATSAPP_VERIFY_TOKEN']}"
    cleaned = wa.redact(line)
    assert not any(s in cleaned for s in SECRETS) and cleaned.count("[redacted]") == 3


def test_redact_catches_tokens_it_was_not_told_about():
    assert "EAAGm0PX4ZCpsBAKexample123456789" not in wa.redact("x EAAGm0PX4ZCpsBAKexample123456789 y")
    assert "abc.def" not in wa.redact("Authorization: Bearer abc.def-123")


def test_every_log_line_is_scrubbed(cloud, caplog):
    caplog.set_level(logging.INFO)
    logging.getLogger("anything.at.all").warning("oops the token was %s", TOKEN)
    logging.getLogger("uvicorn.error").error(f"url had {CLOUD_SETTINGS['WHATSAPP_APP_SECRET']} in it")
    assert not any(s in caplog.text for s in SECRETS)


def test_phone_numbers_are_masked_for_logs():
    assert wa.mask_phone(PATIENT) == "••••0001" and PATIENT not in wa.mask_phone(PATIENT)


def test_status_summary_contains_names_and_booleans_but_no_values(monkeypatch):
    for key, value in CLOUD_SETTINGS.items():
        monkeypatch.setattr(config, key, value)
    monkeypatch.setattr(config, "WHATSAPP_ACCESS_TOKEN", "")
    summary = wa.status_summary()
    assert summary["missing"] == ["WHATSAPP_ACCESS_TOKEN"] and summary["ready_to_send"] is False and summary["ready_to_receive"] is True
    assert not any(v in str(summary) for v in CLOUD_SETTINGS.values() if v not in ("cloud",))


def test_the_env_example_file_has_the_variable_names_but_no_secrets():
    text = (config.ROOT / ".env.example").read_text(encoding="utf-8")
    for name in ("WHATSAPP_MODE", "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET", "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID"):
        assert f"\n{name}=" in text, name
    values = {line.split("=", 1)[0]: line.split("=", 1)[1].strip() for line in text.splitlines()
              if line.strip() and not line.startswith("#") and "=" in line}
    for secret in ("WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET", "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "ANTHROPIC_API_KEY"):
        assert values[secret] == "", f"{secret} must be empty in .env.example"
    assert values["WHATSAPP_MODE"] == "simulated"            # the safe default
    assert "EAA" not in text


def test_no_secret_or_token_variable_appears_in_any_web_page():
    for path in (config.FRONTEND_DIR).rglob("*"):
        if path.is_file() and path.suffix in (".js", ".html", ".css"):
            content = path.read_text(encoding="utf-8")
            assert "ACCESS_TOKEN" not in content and "APP_SECRET" not in content and "VERIFY_TOKEN" not in content, path.name
            assert "Bearer " not in content, path.name


def test_a_bad_mode_is_refused_at_start_up(monkeypatch):
    import importlib

    monkeypatch.setenv("WHATSAPP_MODE", "live")
    with pytest.raises(SystemExit, match="WHATSAPP_MODE"):
        importlib.reload(config)
    monkeypatch.setenv("WHATSAPP_MODE", "simulated")
    importlib.reload(config)
    assert config.WHATSAPP_MODE == "simulated"


# ================================================================ the database side of duplicate protection
def test_the_same_message_can_only_be_claimed_once(client):
    assert database.claim_inbound("wamid.X", PATIENT) == "new"
    assert database.claim_inbound("wamid.X", PATIENT) == "duplicate"
    database.finish_inbound("wamid.X", "done")
    assert database.claim_inbound("wamid.X", PATIENT) == "duplicate"


def test_when_many_copies_arrive_at_the_same_instant_exactly_one_wins(client):
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: database.claim_inbound("wamid.RACE", PATIENT), range(48)))
    assert results.count("new") == 1 and results.count("duplicate") == 47


def test_a_message_that_failed_can_be_claimed_again(client):
    database.claim_inbound("wamid.F", PATIENT)
    database.finish_inbound("wamid.F", "failed", error="RuntimeError")
    assert database.claim_inbound("wamid.F", PATIENT) == "retry"
    assert database.claim_inbound("wamid.F", PATIENT) == "duplicate"         # now being processed again


def test_a_message_whose_processing_was_abandoned_can_be_claimed_again(client):
    database.claim_inbound("wamid.S", PATIENT)
    with database.connect() as conn:
        conn.execute("UPDATE whatsapp_events SET updated_at = '2020-01-01T00:00:00+00:00' WHERE wa_message_id = 'wamid.S'")
    assert database.claim_inbound("wamid.S", PATIENT) == "retry"


def test_start_up_marks_interrupted_messages_as_failed(client):
    database.claim_inbound("wamid.OLD", PATIENT)
    database.claim_inbound("wamid.NEW", PATIENT)
    with database.connect() as conn:
        conn.execute("UPDATE whatsapp_events SET updated_at = '2020-01-01T00:00:00+00:00' WHERE wa_message_id = 'wamid.OLD'")
    assert database.mark_interrupted_inbound() == 1
    assert database.inbound_counts()["failed"] == 1 and database.inbound_counts()["processing"] == 1


def test_delivery_status_never_goes_backwards(client):
    conversation = database.get_or_create_conversation(PATIENT, "A", "whatsapp")
    database.add_message(conversation["id"], "assistant", "hi", wa_id="wamid.D", delivery="sent")
    for status, expected in (("delivered", "delivered"), ("read", "read"), ("delivered", "read"), ("sent", "read")):
        database.set_delivery("wamid.D", status)
        assert database.find_message_by_wa_id("wamid.D")["delivery"] == expected
    database.set_delivery("wamid.D", "failed", "boom")
    assert database.find_message_by_wa_id("wamid.D")["delivery"] == "failed"
    assert database.set_delivery("wamid.UNKNOWN", "read") is False
