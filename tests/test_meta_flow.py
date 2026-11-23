"""The WhatsApp Cloud integration end to end, as Meta would drive it.

A signed webhook POST -> message extraction -> classification -> RAG -> verification -> a reply sent through the
Graph API (a fake one here) -> recorded in the conversation. Plus the unhappy paths: bad signatures, duplicates,
failed deliveries, the 24-hour window, and the dashboard approval flow.

As in test_whatsapp_cloud.py: nothing here reaches Meta. It proves our code, not Meta's servers.
"""
import logging
import sqlite3

import httpx
import pytest
from conftest import CLOUD_SETTINGS, PATIENT, meta_payload, sign, text_message
from fake_graph import graph_error

from backend import config, database, outbound, webhook
from backend import whatsapp_cloud as wa

TOKEN = CLOUD_SETTINGS["WHATSAPP_ACCESS_TOKEN"]
SECRETS = [TOKEN, CLOUD_SETTINGS["WHATSAPP_APP_SECRET"], CLOUD_SETTINGS["WHATSAPP_VERIFY_TOKEN"]]


def conversation():
    return database.find_conversation(PATIENT)


def messages():
    return database.list_messages(conversation()["id"])


def inquiry_ids(client, status="all"):
    return [i["id"] for i in client.get("/api/dashboard/inquiries", params={"status": status}).json()["inquiries"]]


def detail(client, inquiry_id):
    return client.get(f"/api/dashboard/inquiries/{inquiry_id}").json()


# ================================================================ GET: verification handshake
def test_handshake_succeeds_with_the_right_token(cloud):
    response = cloud.client.get("/whatsapp/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": CLOUD_SETTINGS["WHATSAPP_VERIFY_TOKEN"], "hub.challenge": "1158201444"})
    assert response.status_code == 200 and response.text == "1158201444"      # echoed back exactly, as plain text
    assert response.headers["content-type"].startswith("text/plain")


@pytest.mark.parametrize("params", [
    {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"},
    {"hub.mode": "subscribe", "hub.challenge": "1"},
    {"hub.mode": "unsubscribe", "hub.verify_token": CLOUD_SETTINGS["WHATSAPP_VERIFY_TOKEN"], "hub.challenge": "1"},
    {},
])
def test_handshake_is_refused_otherwise(cloud, params):
    assert cloud.client.get("/whatsapp/webhook", params=params).status_code == 403


def test_handshake_without_a_configured_token_is_a_clear_error(cloud, monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_VERIFY_TOKEN", "")
    assert cloud.client.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "1"}).status_code == 503


def test_in_simulated_mode_the_webhook_is_switched_off(client):
    assert client.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "1"}).status_code == 409
    assert client.post("/whatsapp/webhook", content=b"{}").status_code == 409


# ================================================================ POST: signature and basic safety
def test_a_message_with_no_signature_is_refused_and_does_nothing(cloud):
    response = cloud.post(meta_payload([text_message("hello")]), signature=False)
    assert response.status_code == 403
    assert database.find_conversation(PATIENT) is None and cloud.graph.requests == []


@pytest.mark.parametrize("signature", ["sha256=" + "0" * 64, "sha1=abc", "nonsense", "sha256="])
def test_a_message_with_a_wrong_signature_is_refused(cloud, signature):
    assert cloud.post(meta_payload([text_message("hello")]), signature=signature).status_code == 403
    assert database.find_conversation(PATIENT) is None


def test_a_signature_made_with_a_different_secret_is_refused(cloud):
    body = b'{"object": "whatsapp_business_account", "entry": []}'
    assert cloud.post(None, raw=body, signature=sign(body, "someone-elses-secret")).status_code == 403


def test_without_an_app_secret_nothing_is_trusted(cloud, monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_APP_SECRET", "")
    response = cloud.post(meta_payload([text_message("hello")]))
    assert response.status_code == 503 and "WHATSAPP_APP_SECRET" in response.json()["detail"]
    assert database.find_conversation(PATIENT) is None


def test_valid_signature_but_broken_json_is_a_400(cloud):
    body = b"{not json"
    assert cloud.post(None, raw=body, signature=sign(body)).status_code == 400


def test_other_kinds_of_events_get_a_200_and_are_ignored(cloud):
    body = b'{"object": "page", "entry": []}'
    response = cloud.post(None, raw=body, signature=sign(body))
    assert response.status_code == 200 and response.json()["accepted"] == 0


def test_an_oversized_body_is_refused(cloud):
    body = b"x" * 1_100_000
    assert cloud.post(None, raw=body, signature=sign(body)).status_code == 413


# ================================================================ a patient writes: the whole pipeline
def test_a_question_is_answered_automatically_through_the_graph_api(cloud):
    response = cloud.say("What are your timings?", wamid="wamid.IN1", name="Asha Patil")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "accepted": 1, "duplicates": 0, "ignored": 0, "statuses": 0}

    # 4. the sender is identified from the payload
    chat = conversation()
    assert (chat["phone"], chat["name"], chat["channel"]) == (PATIENT, "Asha Patil", "whatsapp")
    patient, reply = messages()
    assert patient["role"] == "patient" and patient["text"] == "What are your timings?" and patient["wa_id"] == "wamid.IN1"

    # 5/6. classified, answered from the knowledge base, verified, sent through the Graph API to the patient
    assert len(cloud.graph.sends) == 1
    sent = cloud.graph.sends[0]
    assert sent["to"] == PATIENT and sent["type"] == "text" and sent["text"]["body"] == reply["text"]
    assert "10:00 AM" in reply["text"]
    assert cloud.graph.send_requests[0].headers["authorization"] == f"Bearer {TOKEN}"

    # recorded: the answer, its source, that it was verified, and WhatsApp's id for it
    assert reply["role"] == "assistant" and reply["wa_id"] == "wamid.OUT1" and reply["delivery"] == "sent"
    assert reply["sources"][0]["id"] == "clinic:timings" and reply["meta"]["verified"] is True


def test_nothing_secret_ends_up_in_the_database(cloud):
    cloud.say("What are your timings?")
    cloud.say("I want to book an appointment", wamid="wamid.IN2")
    data = config.DATABASE_PATH.read_bytes()
    for secret in SECRETS:
        assert secret.encode() not in data


def test_a_greeting_gets_a_verified_reply(cloud):
    cloud.say("Hello")
    assert "virtual assistant" in cloud.graph.sends[0]["text"]["body"]


def test_a_new_patient_without_a_profile_name_is_still_handled(cloud):
    payload = meta_payload([text_message("hello")])
    payload["entry"][0]["changes"][0]["value"].pop("contacts")
    assert cloud.post(payload).status_code == 200
    assert conversation()["name"] == "Patient"


def test_several_messages_in_one_request_each_get_handled(cloud):
    response = cloud.post(meta_payload([text_message("What are your timings?", "wamid.A"), text_message("Where are you located?", "wamid.B")]))
    assert response.json()["accepted"] == 2 and len(cloud.graph.sends) == 2


# ---- 7. uncertain questions go to the dashboard, and nothing unverified is sent ----
def test_an_appointment_request_is_held_for_the_receptionist_and_nothing_is_sent(cloud):
    cloud.say("I want to book an appointment for Saturday evening")
    assert cloud.graph.requests == []
    assert [m["role"] for m in messages()] == ["patient"]
    [pending] = inquiry_ids(cloud.client, "pending")
    item = detail(cloud.client, pending)
    assert item["status"] == "pending_approval" and item["draft"] and item["question"].startswith("I want to book")
    assert item["patient_channel"] == "whatsapp"


def test_an_emergency_is_escalated_as_urgent_and_nothing_is_sent(cloud):
    cloud.say("Severe pain and swelling, I can't sleep")
    assert cloud.graph.requests == []
    [item] = cloud.client.get("/api/dashboard/inquiries", params={"status": "escalated"}).json()["inquiries"]
    assert item["urgent"] is True


def test_a_question_the_clinic_cannot_answer_gets_an_honest_notice_and_goes_to_reception(cloud):
    cloud.say("Do you have a wheelchair ramp?")
    assert len(cloud.graph.sends) == 1 and "don't have that information" in cloud.graph.sends[0]["text"]["body"]
    [escalated] = inquiry_ids(cloud.client, "escalated")
    assert detail(cloud.client, escalated)["rag"]["answerable"] is False
    assert messages()[-1]["meta"]["kind"] == "not_in_knowledge_base_notice"


def test_with_auto_reply_switched_off_nothing_is_sent_automatically(cloud):
    cloud.client.post("/api/dashboard/settings", json={"auto_reply": False})
    cloud.say("What are your timings?")
    assert cloud.graph.requests == []
    assert inquiry_ids(cloud.client, "pending")


# ---- 8. the receptionist approves; the reply goes to the ORIGINAL patient ----
def test_an_approved_reply_is_delivered_to_the_original_patient(cloud):
    cloud.say("I want to book an appointment for Saturday evening", sender="919811122233", name="Ravi")
    [pending] = inquiry_ids(cloud.client, "pending")
    draft = detail(cloud.client, pending)["draft"]

    result = cloud.client.post(f"/api/dashboard/inquiries/{pending}/send", json={"text": draft})
    assert result.status_code == 200 and result.json()["status"] == "approved"

    assert len(cloud.graph.sends) == 1
    assert cloud.graph.sends[0]["to"] == "919811122233" and cloud.graph.sends[0]["text"]["body"] == draft
    reply = database.list_messages(database.find_conversation("919811122233")["id"])[-1]
    assert reply["role"] == "receptionist" and reply["wa_id"] == "wamid.OUT1" and reply["delivery"] == "sent"
    assert reply["meta"]["approved_by"] == "Receptionist"


def test_an_edited_reply_is_what_the_patient_receives(cloud):
    cloud.say("I want to book an appointment for Saturday evening")
    [pending] = inquiry_ids(cloud.client, "pending")
    cloud.client.post(f"/api/dashboard/inquiries/{pending}/send", json={"text": "Yes, Saturday 5 PM works. See you then!"})
    assert cloud.graph.sends[0]["text"]["body"] == "Yes, Saturday 5 PM works. See you then!"


def test_a_rejected_draft_is_never_sent(cloud):
    cloud.say("I want to book an appointment for Saturday evening")
    [pending] = inquiry_ids(cloud.client, "pending")
    cloud.client.post(f"/api/dashboard/inquiries/{pending}/reject", json={"reason": "wrong"})
    assert cloud.graph.requests == []


# ================================================================ non-text messages
def voice_note(wamid="wamid.V1"):
    return {"from": PATIENT, "id": wamid, "timestamp": "1", "type": "audio", "audio": {"id": "media-1", "voice": True}}


def test_a_voice_note_goes_straight_to_the_receptionist_with_one_fixed_notice(cloud):
    assert cloud.post(meta_payload([voice_note()])).json()["accepted"] == 1
    [escalated] = inquiry_ids(cloud.client, "escalated")
    item = detail(cloud.client, escalated)
    assert item["intent"] == "non_text" and "cannot read" in item["reasons"][0] and item["question"] == "[Sent a voice or audio message]"
    assert len(cloud.graph.sends) == 1 and "only read text messages" in cloud.graph.sends[0]["text"]["body"]
    assert messages()[-1]["meta"]["kind"] == "unreadable_message_notice"
    assert cloud.client.get("/api/kb/gaps").json()["questions"] == []        # not a knowledge-base gap


def test_reactions_and_empty_messages_are_ignored_entirely(cloud):
    reaction = {"from": PATIENT, "id": "wamid.R", "timestamp": "1", "type": "reaction", "reaction": {"emoji": "👍"}}
    response = cloud.post(meta_payload([reaction, text_message("   ", "wamid.E")]))
    assert response.json()["ignored"] == 2 and database.find_conversation(PATIENT) is None and cloud.graph.requests == []


def test_button_replies_are_answered_like_typed_text(cloud):
    message = {"from": PATIENT, "id": "wamid.BTN", "timestamp": "1", "type": "interactive",
               "interactive": {"type": "button_reply", "button_reply": {"id": "1", "title": "What are your timings?"}}}
    cloud.post(meta_payload([message]))
    assert "10:00 AM" in cloud.graph.sends[0]["text"]["body"]


# ================================================================ 9. duplicate protection
def test_meta_resending_the_same_message_is_processed_only_once(cloud):
    first = cloud.say("What are your timings?", wamid="wamid.DUP")
    second = cloud.say("What are your timings?", wamid="wamid.DUP")
    third = cloud.say("What are your timings?", wamid="wamid.DUP")
    assert first.json()["accepted"] == 1 and second.json()["duplicates"] == 1 and third.json()["duplicates"] == 1
    assert [m["role"] for m in messages()] == ["patient", "assistant"]
    assert len(cloud.graph.sends) == 1 and len(inquiry_ids(cloud.client)) == 1


def test_a_duplicate_inside_one_request_is_also_caught(cloud):
    response = cloud.post(meta_payload([text_message("hello", "wamid.TWICE"), text_message("hello", "wamid.TWICE")]))
    assert response.json()["accepted"] == 1 and response.json()["duplicates"] == 1


def test_a_different_message_with_the_same_words_is_not_a_duplicate(cloud):
    cloud.say("What are your timings?", wamid="wamid.1")
    cloud.say("What are your timings?", wamid="wamid.2")
    assert len(cloud.graph.sends) == 2


def test_a_crash_never_loses_the_message_and_a_resend_recovers_it(cloud, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(webhook, "handle_incoming_message", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        assert cloud.say("What are your timings?", wamid="wamid.CRASH").status_code == 200       # Meta still gets its 200
    assert database.inbound_counts()["failed"] == 1
    assert cloud.client.get("/api/whatsapp/status").json()["events"]["failed"] == 1               # ...and it is visible

    response = cloud.say("What are your timings?", wamid="wamid.CRASH")                            # Meta re-sends it
    assert response.json()["accepted"] == 1
    assert database.inbound_counts() == {**database.inbound_counts(), "failed": 0, "done": 1}
    assert len(cloud.graph.sends) == 1


# ================================================================ routing of who may write
def test_a_message_for_a_different_whatsapp_number_is_ignored(cloud):
    response = cloud.post(meta_payload([text_message("hello")], phone_number_id="9999999999"))
    assert response.json()["ignored"] == 1 and database.find_conversation(PATIENT) is None


def test_allowed_senders_restricts_who_gets_replies(cloud, monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_ALLOWED_SENDERS", {"919000000999"})
    assert cloud.say("hello", sender=PATIENT).json()["ignored"] == 1
    assert cloud.say("hello", wamid="wamid.OK", sender="919000000999").json()["accepted"] == 1
    assert len(cloud.graph.sends) == 1 and cloud.graph.sends[0]["to"] == "919000000999"


# ================================================================ delivery statuses from WhatsApp
def statuses(cloud, wamid, status, errors=None):
    entry = {"id": wamid, "status": status, "recipient_id": PATIENT}
    if errors:
        entry["errors"] = errors
    return cloud.post(meta_payload(statuses=[entry]))


def test_delivered_and_read_updates_reach_the_message(cloud):
    cloud.say("What are your timings?")
    assert statuses(cloud, "wamid.OUT1", "delivered").json()["statuses"] == 1
    assert messages()[-1]["delivery"] == "delivered"
    statuses(cloud, "wamid.OUT1", "read")
    statuses(cloud, "wamid.OUT1", "delivered")                       # late, out-of-order update
    assert messages()[-1]["delivery"] == "read"


def test_updates_for_unknown_messages_are_harmless(cloud):
    assert statuses(cloud, "wamid.NOT-OURS", "read").status_code == 200


def test_a_reported_failure_hands_the_automatic_reply_to_a_person(cloud):
    cloud.say("What are your timings?")
    statuses(cloud, "wamid.OUT1", "failed", [{"code": 131026, "title": "Message undeliverable"}])
    assert messages()[-1]["delivery"] == "failed" and "131026" in messages()[-1]["delivery_error"]
    [pending] = inquiry_ids(cloud.client, "pending")
    item = detail(cloud.client, pending)
    assert any("could not deliver" in r.lower() or "could not be delivered" in r.lower() for r in item["reasons"])
    assert item["audit"][-1]["event"] == "delivery_failed"


# ================================================================ failures when sending
def test_if_whatsapp_refuses_the_automatic_reply_nothing_is_claimed_as_sent(cloud):
    cloud.graph.script.append(graph_error(190, "Error validating access token", 401))
    cloud.say("What are your timings?")
    assert [m["role"] for m in messages()] == ["patient"]                    # no phantom reply in the history
    [pending] = inquiry_ids(cloud.client, "pending")
    item = detail(cloud.client, pending)
    assert item["status"] == "pending_approval" and item["draft"]            # the verified answer is kept for a retry
    assert "could NOT be delivered" in " ".join(item["reasons"]) and "access token" in " ".join(item["reasons"])
    assert item["audit"][-1]["event"] == "delivery_failed"

    # the receptionist fixes the token and presses "Approve & send" to retry
    retry = cloud.client.post(f"/api/dashboard/inquiries/{pending}/send", json={"text": item["draft"]})
    assert retry.status_code == 200 and messages()[-1]["role"] == "receptionist" and messages()[-1]["delivery"] == "sent"


def test_a_receptionist_reply_that_fails_to_send_keeps_the_item_open(cloud):
    cloud.say("I want to book an appointment for Saturday evening")
    [pending] = inquiry_ids(cloud.client, "pending")
    draft = detail(cloud.client, pending)["draft"]

    cloud.graph.script.append(graph_error(190, "token expired", 401))
    response = cloud.client.post(f"/api/dashboard/inquiries/{pending}/send", json={"text": draft})
    assert response.status_code == 502
    assert response.json()["detail"]["delivery_failed"] and "access token" in response.json()["detail"]["message"]
    assert TOKEN not in response.text

    item = detail(cloud.client, pending)
    assert item["status"] == "pending_approval" and [m["role"] for m in item["thread"]] == ["patient"]
    assert item["audit"][-1]["event"] == "delivery_failed"

    assert cloud.client.post(f"/api/dashboard/inquiries/{pending}/send", json={"text": draft}).status_code == 200   # retry works


def old_patient_message():
    with database.connect() as conn:
        conn.execute("UPDATE messages SET created_at = '2020-01-01T10:00:00+00:00' WHERE role = 'patient'")


def test_a_reply_after_the_24_hour_window_is_explained_not_lost(cloud):
    cloud.say("I want to book an appointment for Saturday evening")
    [pending] = inquiry_ids(cloud.client, "pending")
    assert detail(cloud.client, pending)["whatsapp_window"]["open"] is True

    old_patient_message()
    window = detail(cloud.client, pending)["whatsapp_window"]
    assert window["open"] is False and window["hours_since"] > 24

    cloud.graph.script.append(graph_error(131047, "Re-engagement message", 400))
    response = cloud.client.post(f"/api/dashboard/inquiries/{pending}/send", json={"text": "Hello, are you still interested?"})
    assert response.status_code == 502 and "24 hours" in response.json()["detail"]["message"]
    assert detail(cloud.client, pending)["status"] == "pending_approval"


def test_transient_failures_are_retried_before_giving_up(cloud):
    cloud.graph.script.extend([httpx.Response(500), httpx.Response(503)])
    cloud.say("What are your timings?")
    assert len(cloud.graph.send_requests) == 3 and messages()[-1]["role"] == "assistant"      # the 3rd attempt worked


# ================================================================ demo conversations vs real patients
def test_a_demo_conversation_is_never_sent_to_a_real_phone_even_in_cloud_mode(cloud):
    demo = database.get_or_create_conversation("919000000555", "Demo patient")                 # channel: simulated
    message = outbound.send_reply(demo, "Hello demo", "receptionist")
    assert message["delivery"] == "simulated" and cloud.graph.requests == []


def test_a_real_patient_cannot_be_replied_to_while_in_simulated_mode(cloud, monkeypatch):
    cloud.say("I want to book an appointment for Saturday evening")
    [pending] = inquiry_ids(cloud.client, "pending")
    monkeypatch.setattr(config, "WHATSAPP_MODE", "simulated")
    response = cloud.client.post(f"/api/dashboard/inquiries/{pending}/send", json={"text": "Hello"})
    assert response.status_code == 502 and "WHATSAPP_MODE" in response.json()["detail"]["message"]
    assert cloud.graph.requests == []


def test_a_real_message_from_a_number_used_in_the_demo_makes_it_a_real_conversation(cloud):
    database.get_or_create_conversation(PATIENT, "Old demo")
    cloud.say("What are your timings?")
    assert conversation()["channel"] == "whatsapp" and len(cloud.graph.sends) == 1


def test_the_simulated_chat_and_demo_tools_are_disabled_in_cloud_mode(cloud):
    assert cloud.client.post("/api/webhook/whatsapp", json={"phone": "919000000555", "text": "hi"}).status_code == 409
    assert cloud.client.post("/api/dashboard/seed-demo").status_code == 409
    assert cloud.client.post("/api/dashboard/reset").status_code == 409
    assert cloud.graph.requests == [] and database.find_conversation("919000000555") is None


def test_simulated_mode_still_works_exactly_as_before(client):
    response = client.post("/api/webhook/whatsapp", json={"phone": "919000000001", "name": "Aarav", "text": "What are your timings?"})
    assert response.status_code == 200 and response.json()["reply"]["delivery"] == "simulated"
    assert client.post("/api/dashboard/seed-demo").status_code == 200


def test_the_send_gate_still_refuses_unverified_ai_answers_in_cloud_mode(cloud):
    chat = database.get_or_create_conversation(PATIENT, "A", "whatsapp")
    with pytest.raises(outbound.UnverifiedMessageError):
        outbound.send_reply(chat, "A root canal costs ₹1,500.", "assistant")
    assert cloud.graph.requests == []


# ================================================================ the dashboard must not be exposed through a tunnel
PUBLIC = {"X-Forwarded-For": "203.0.113.9", "X-Forwarded-Host": "abc123.ngrok-free.app"}


@pytest.mark.parametrize("method,path", [
    ("get", "/"), ("get", "/dashboard/"), ("get", "/knowledge/"), ("get", "/chat/"), ("get", "/docs"), ("get", "/openapi.json"),
    ("get", "/api/dashboard/stats"), ("get", "/api/dashboard/inquiries"), ("get", "/api/kb/treatments"), ("get", "/api/meta"),
    ("get", "/api/whatsapp/status"), ("post", "/api/dashboard/reset"), ("post", "/api/dashboard/seed-demo"),
    ("post", "/api/webhook/whatsapp"), ("delete", "/api/kb/faqs/walk_in"), ("get", "/api/kb/faqs/export.csv"),
])
def test_requests_that_came_through_a_tunnel_cannot_reach_anything_but_the_webhook(cloud, method, path):
    response = getattr(cloud.client, method)(path, headers=PUBLIC)
    assert response.status_code == 403 and "only available on the computer" in response.json()["detail"], path


@pytest.mark.parametrize("header", ["X-Forwarded-For", "X-Real-IP", "CF-Connecting-IP", "Forwarded", "X-Forwarded-Host"])
def test_any_proxy_header_triggers_the_guard(cloud, header):
    assert cloud.client.get("/dashboard/", headers={header: "203.0.113.9"}).status_code == 403


def test_the_webhook_and_health_check_stay_reachable_through_the_tunnel(cloud):
    ok = cloud.client.get("/whatsapp/webhook", headers=PUBLIC, params={
        "hub.mode": "subscribe", "hub.verify_token": CLOUD_SETTINGS["WHATSAPP_VERIFY_TOKEN"], "hub.challenge": "77"})
    assert ok.status_code == 200 and ok.text == "77"
    assert cloud.post(meta_payload([text_message("What are your timings?")]), headers=PUBLIC).status_code == 200
    assert cloud.client.get("/healthz", headers=PUBLIC).json() == {"ok": True}


def test_local_use_is_unaffected_by_the_guard(cloud):
    for path in ("/", "/dashboard/", "/knowledge/", "/docs", "/api/dashboard/stats", "/api/meta"):
        assert cloud.client.get(path).status_code == 200, path


def test_the_guard_can_be_switched_off_deliberately(cloud, monkeypatch):
    monkeypatch.setattr(config, "ALLOW_PUBLIC_DASHBOARD", True)
    assert cloud.client.get("/dashboard/", headers=PUBLIC).status_code == 200


# ================================================================ no secrets, no personal data in logs or pages
def test_the_status_and_meta_endpoints_never_reveal_a_secret(cloud):
    for path in ("/api/meta", "/api/whatsapp/status"):
        text = cloud.client.get(path).text
        assert not any(s in text for s in SECRETS) and CLOUD_SETTINGS["WHATSAPP_PHONE_NUMBER_ID"] not in text, path
    status = cloud.client.get("/api/whatsapp/status").json()
    assert status["mode"] == "cloud" and status["ready_to_receive"] and status["ready_to_send"] and status["missing"] == []
    assert status["webhook_path"] == "/whatsapp/webhook"


def test_status_names_what_is_missing_without_values(cloud, monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_APP_SECRET", "")
    status = cloud.client.get("/api/whatsapp/status").json()
    assert status["missing"] == ["WHATSAPP_APP_SECRET"] and status["ready_to_receive"] is False


def test_logs_contain_no_secrets_no_phone_numbers_and_no_message_text(cloud, caplog):
    caplog.set_level(logging.DEBUG)
    cloud.say("What are your timings on Sunday?", wamid="wamid.LOG1")
    cloud.post(meta_payload([text_message("hello", "wamid.LOG2")]), signature="sha256=" + "0" * 64)    # a rejected request
    cloud.graph.script.append(graph_error(190, f"Invalid OAuth access token {TOKEN}", 401))
    cloud.say("I want to book a visit", wamid="wamid.LOG3")
    cloud.graph.script.append(graph_error(190, "x", 401))
    cloud.client.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"})

    logs = caplog.text
    assert "wamid.LOG1" in logs                                                    # we do log which message we handled...
    assert not any(secret in logs for secret in SECRETS)                          # ...but never a secret
    assert PATIENT not in logs and wa.mask_phone(PATIENT) in logs                 # numbers are masked
    assert "timings on Sunday" not in logs and "book a visit" not in logs          # and never what a patient wrote


# ================================================================ the status endpoint
def test_status_counts_events(cloud):
    cloud.say("hello", wamid="wamid.1")
    cloud.say("hello", wamid="wamid.1")
    events = cloud.client.get("/api/whatsapp/status").json()["events"]
    assert events["done"] == 1 and events["failed"] == 0 and events["last_received_at"]


# ================================================================ the setup checker you will run for real
def test_the_checker_passes_when_everything_is_right(cloud, capsys):
    from backend import whatsapp_check as check

    assert check.check_settings() and check.check_token()
    assert check.probe(cloud.client, "http://testserver")
    out = capsys.readouterr().out
    assert "Meta accepted the token" in out and "BADLY signed event is refused" in out
    assert not any(secret in out for secret in SECRETS)                             # it never prints a secret


def test_the_checker_reports_a_bad_token(cloud, capsys):
    from backend import whatsapp_check as check

    cloud.graph.script.append(graph_error(190, "Invalid OAuth access token", 401))
    assert check.check_token() is False
    assert "access token" in capsys.readouterr().out


def test_the_checker_reports_missing_settings_by_name(monkeypatch, capsys):
    from backend import whatsapp_check as check

    monkeypatch.setattr(config, "WHATSAPP_MODE", "cloud")
    monkeypatch.setattr(config, "WHATSAPP_APP_SECRET", "")
    assert check.check_settings() is False
    assert "[FAIL] WHATSAPP_APP_SECRET" in capsys.readouterr().out


def test_the_probe_causes_no_side_effects(cloud):
    from backend import whatsapp_check as check

    check.probe(cloud.client, "http://testserver")
    assert database.inbound_counts()["done"] == 0 and cloud.graph.requests == [] and cloud.client.get("/api/dashboard/stats").json()["total"] == 0


def test_the_probe_fails_clearly_when_cloud_mode_is_off(client, capsys):
    from backend import whatsapp_check as check

    assert check.probe(client, "http://testserver") is False
    assert "[FAIL] verification handshake -> HTTP 409" in capsys.readouterr().out


# ================================================================ old databases keep working
def test_a_database_from_before_whatsapp_is_upgraded_in_place(tmp_path, monkeypatch):
    old = tmp_path / "before.db"
    connection = sqlite3.connect(old)
    connection.executescript("""
        CREATE TABLE conversations (id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT UNIQUE, name TEXT, created_at TEXT, updated_at TEXT);
        INSERT INTO conversations VALUES (1, '919000000001', 'Demo', 'x', 'x');
        CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id INTEGER, role TEXT, text TEXT, inquiry_id INTEGER,
                               sources TEXT NOT NULL DEFAULT '[]', meta TEXT NOT NULL DEFAULT '{}', created_at TEXT);
        INSERT INTO messages (conversation_id, role, text, created_at) VALUES (1, 'patient', 'hi', 'x');
    """)
    connection.close()
    monkeypatch.setattr(config, "DATABASE_PATH", old)
    database.init_db()
    demo = database.find_conversation("919000000001")
    assert demo["channel"] == "simulated"                                 # existing conversations are demo conversations
    assert database.list_messages(1)[0]["delivery"] == "" and database.list_messages(1)[0]["wa_id"] is None
