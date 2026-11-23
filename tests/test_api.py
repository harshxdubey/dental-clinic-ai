"""End-to-end tests: patient message -> AI decision -> dashboard action -> patient sees reply."""

PHONE = "919000000001"


def send(client, text, phone=PHONE, name="Aarav"):
    response = client.post("/api/webhook/whatsapp", json={"phone": phone, "name": name, "text": text})
    assert response.status_code == 200, response.text
    return response.json()


def chat(client, phone=PHONE, after=0):
    return client.get(f"/api/chat/{phone}/messages", params={"after_id": after}).json()


def test_safe_question_is_answered_automatically(client):
    result = send(client, "What are your timings?")
    assert result["status"] == "auto_replied"
    assert result["reply"]["role"] == "assistant"
    assert "10:00 AM" in result["reply"]["text"]
    assert result["notice"] is None


def test_appointment_waits_for_approval_and_nothing_is_sent(client):
    result = send(client, "I want to book an appointment for Saturday")
    assert result["status"] == "pending_approval"
    assert result["reply"] is None
    assert result["notice"]["state"] == "pending_approval"
    assert [m["role"] for m in chat(client)["messages"]] == ["patient"]


def test_emergency_is_escalated_and_urgent(client):
    result = send(client, "Severe pain and swelling, I can't sleep")
    assert result["status"] == "escalated" and result["reply"] is None
    assert result["notice"]["urgent"] is True
    inquiry = client.get(f"/api/dashboard/inquiries/{result['inquiry_id']}").json()
    assert inquiry["urgent"] and inquiry["intent"] == "emergency"
    assert inquiry["draft"]  # a suggested reply is prepared for the receptionist
    assert inquiry["sources"] and inquiry["checks"] and inquiry["reasons"]


def test_receptionist_approves_the_ai_draft(client):
    inquiry_id = send(client, "I want to book an appointment")["inquiry_id"]
    detail = client.get(f"/api/dashboard/inquiries/{inquiry_id}").json()

    done = client.post(f"/api/dashboard/inquiries/{inquiry_id}/send", json={"text": detail["draft"]}).json()
    assert done["status"] == "approved" and done["resolved_by"] == "Receptionist"

    messages = chat(client)
    assert messages["messages"][-1]["role"] == "receptionist"
    assert messages["notice"] is None  # the "waiting for reception" notice disappears


def test_edited_reply_counts_as_replied(client):
    inquiry_id = send(client, "my tooth hurts")["inquiry_id"]
    done = client.post(f"/api/dashboard/inquiries/{inquiry_id}/send", json={"text": "Please come in today at 5."}).json()
    assert done["status"] == "replied" and done["final_reply"] == "Please come in today at 5."


def test_a_message_cannot_be_handled_twice(client):
    inquiry_id = send(client, "I want a refund")["inquiry_id"]
    assert client.post(f"/api/dashboard/inquiries/{inquiry_id}/send", json={"text": "Sorry!"}).status_code == 200
    assert client.post(f"/api/dashboard/inquiries/{inquiry_id}/send", json={"text": "Again"}).status_code == 409
    assert client.post(f"/api/dashboard/inquiries/{inquiry_id}/dismiss").status_code == 409


def test_escalate_and_dismiss(client):
    pending = send(client, "I want to book an appointment")["inquiry_id"]
    assert client.post(f"/api/dashboard/inquiries/{pending}/escalate").json()["status"] == "escalated"
    assert client.post(f"/api/dashboard/inquiries/{pending}/dismiss").json()["status"] == "dismissed"
    assert [m["role"] for m in chat(client)["messages"]] == ["patient"]  # nothing sent on dismiss


def test_auto_reply_switch(client):
    assert client.get("/api/dashboard/settings").json() == {"auto_reply": True}
    client.post("/api/dashboard/settings", json={"auto_reply": False})
    result = send(client, "What are your timings?")
    assert result["status"] == "pending_approval" and result["reply"] is None
    client.post("/api/dashboard/settings", json={"auto_reply": True})
    assert send(client, "Where are you located?")["status"] == "auto_replied"


def test_yes_after_a_price_answer_starts_a_booking(client):
    send(client, "how much is a root canal")
    result = send(client, "yes please")
    assert result["status"] == "pending_approval"


def test_dashboard_lists_and_stats(client):
    send(client, "What are your timings?")
    send(client, "I want to book an appointment", phone="919000000002", name="Priya")
    send(client, "Severe pain", phone="919000000003", name="Rohan")

    stats = client.get("/api/dashboard/stats").json()
    assert (stats["total"], stats["auto_replied"], stats["pending"], stats["escalated"]) == (3, 1, 1, 1)
    assert stats["urgent_open"] == 1 and stats["auto_rate"] == 33 and stats["minutes_saved"] == 2

    open_items = client.get("/api/dashboard/inquiries", params={"status": "open"}).json()["inquiries"]
    assert [i["patient_name"] for i in open_items] == ["Rohan", "Priya"]  # urgent first
    assert "sources" not in open_items[0]  # the list stays light
    assert len(client.get("/api/dashboard/inquiries", params={"status": "all"}).json()["inquiries"]) == 3
    assert client.get("/api/dashboard/inquiries", params={"status": "bogus"}).status_code == 422


def test_conversations_are_separate_per_phone(client):
    send(client, "hello", phone="919000000001")
    send(client, "hello", phone="919000000002", name="Priya")
    assert len(chat(client, "919000000001")["messages"]) == 2
    assert len(chat(client, "919000000002")["messages"]) == 2


def test_chat_polling_only_returns_new_messages(client):
    first = send(client, "hello")
    newer = chat(client, after=first["reply"]["id"])
    assert newer["messages"] == []


def test_bad_input_is_rejected(client):
    post = lambda body: client.post("/api/webhook/whatsapp", json=body).status_code  # noqa: E731
    assert post({"phone": "12", "text": "hi"}) == 422
    assert post({"phone": PHONE, "text": ""}) == 422
    assert post({"phone": PHONE, "text": "   "}) == 422
    assert post({"phone": PHONE, "text": "x" * 1001}) == 422
    assert post({"text": "hi"}) == 422


def test_phone_formats_are_normalised(client):
    send(client, "hello", phone="+91 90000 00001")
    assert len(chat(client, "919000000001")["messages"]) == 2


def test_seed_and_reset(client):
    assert client.post("/api/dashboard/seed-demo").json()["added"] >= 5
    assert client.get("/api/dashboard/stats").json()["total"] >= 5
    client.post("/api/dashboard/reset")
    assert client.get("/api/dashboard/stats").json()["total"] == 0


def test_meta_and_pages_are_served(client):
    meta = client.get("/api/meta").json()
    assert meta["whatsapp_mode"] == "simulated" and meta["ai_mode"] == "template"
    assert "DUMMY" in meta["dummy_notice"]
    for path in ("/", "/chat/", "/dashboard/", "/shared/theme.css"):
        assert client.get(path).status_code == 200, path


def test_a_crash_in_the_ai_never_loses_the_message(client, monkeypatch):
    from backend import pipeline

    def boom(*args, **kwargs):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(pipeline, "analyze", boom)
    result = send(client, "hello")
    assert result["status"] == "escalated" and result["reply"] is None
    inquiry = client.get(f"/api/dashboard/inquiries/{result['inquiry_id']}").json()
    assert "internal error" in inquiry["reasons"][0]


def test_public_demo_mode_cannot_be_combined_with_real_whatsapp(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config
    from backend.main import app
    monkeypatch.setattr(config, "ALLOW_PUBLIC_DASHBOARD", True)
    monkeypatch.setattr(config, "WHATSAPP_MODE", "cloud")
    import pytest
    with pytest.raises(RuntimeError, match="only for the simulated demo"):
        with TestClient(app):
            pass


def test_demo_data_is_seeded_on_first_start_only_when_asked(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, database
    from backend.main import app
    monkeypatch.setattr(config, "SEED_DEMO_ON_START", True)
    with TestClient(app):
        assert database.stats()["total"] == 8
    with TestClient(app):                     # a second start must not add them again
        assert database.stats()["total"] == 8
