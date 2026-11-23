"""The real HTTP code path, over a real socket, against a tiny local imitation of the Graph API.

The other tests replace the network with an in-memory fake. This one uses the actual httpx client, TCP and JSON
on the wire, so a mistake in headers, URLs, encoding or timeouts cannot hide behind a mock.

Still NOT Meta: it proves our requests are well formed and our handling is right, not that Meta accepts them.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from conftest import CLOUD_SETTINGS, PATIENT, meta_payload, sign, text_message

from backend import config, database
from backend import whatsapp_cloud as wa

TOKEN = CLOUD_SETTINGS["WHATSAPP_ACCESS_TOKEN"]


class LocalGraph(BaseHTTPRequestHandler):
    seen = []       # (method, path, headers, parsed body)
    replies = []    # queued (status, json) answers

    def _respond(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"null") if length else None
        LocalGraph.seen.append((self.command, self.path, {k.lower(): v for k, v in self.headers.items()}, body))
        status, payload = LocalGraph.replies.pop(0) if LocalGraph.replies else (200, {
            "messaging_product": "whatsapp", "contacts": [{"wa_id": (body or {}).get("to", "")}],
            "messages": [{"id": f"wamid.HTTP{len(LocalGraph.seen)}"}]})
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_POST = do_GET = _respond

    def log_message(self, *args):   # keep test output quiet
        pass


@pytest.fixture
def local_graph(monkeypatch):
    LocalGraph.seen, LocalGraph.replies = [], []
    server = ThreadingHTTPServer(("127.0.0.1", 0), LocalGraph)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    for key, value in CLOUD_SETTINGS.items():
        monkeypatch.setattr(config, key, value)
    monkeypatch.setattr(config, "WHATSAPP_GRAPH_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    wa.set_transport(None)               # use the real network stack
    monkeypatch.setattr(wa, "_pause", lambda seconds: None)
    yield LocalGraph
    server.shutdown()
    server.server_close()


def test_a_real_http_request_is_well_formed(local_graph):
    delivery = wa.send_text(PATIENT, "Hello from the clinic")
    assert delivery.status == "sent" and delivery.wa_message_id == "wamid.HTTP1"
    method, path, headers, body = local_graph.seen[0]
    assert (method, path) == ("POST", "/v25.0/1055550001/messages")
    assert headers["authorization"] == f"Bearer {TOKEN}" and headers["content-type"].startswith("application/json")
    assert body == {"messaging_product": "whatsapp", "recipient_type": "individual", "to": PATIENT, "type": "text",
                    "text": {"preview_url": False, "body": "Hello from the clinic"}}
    assert TOKEN not in path                                                 # never in the URL


def test_a_non_ascii_reply_survives_the_wire(local_graph):
    wa.send_text(PATIENT, "Root canal: ₹4,000 – ₹9,000 😊 नमस्कार")
    assert local_graph.seen[0][3]["text"]["body"] == "Root canal: ₹4,000 – ₹9,000 😊 नमस्कार"


def test_a_real_error_response_is_handled(local_graph):
    local_graph.replies.append((400, {"error": {"message": "Re-engagement message", "type": "OAuthException", "code": 131047, "fbtrace_id": "T1"}}))
    with pytest.raises(wa.DeliveryError, match="24 hours") as error:
        wa.send_text(PATIENT, "Hi")
    assert error.value.code == 131047 and len(local_graph.seen) == 1


def test_real_server_errors_are_retried_then_succeed(local_graph):
    local_graph.replies.extend([(503, {"error": {"message": "down", "code": 2}}), (500, {"error": {"message": "oops", "code": 1}})])
    assert wa.send_text(PATIENT, "Hi").status == "sent" and len(local_graph.seen) == 3


def test_an_unreachable_server_is_reported_not_crashed(monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_GRAPH_BASE_URL", "http://127.0.0.1:9")      # nothing listens there
    for key, value in CLOUD_SETTINGS.items():
        monkeypatch.setattr(config, key, value)
    wa.set_transport(None)
    monkeypatch.setattr(wa, "_pause", lambda seconds: None)
    with pytest.raises(wa.DeliveryError, match="Could not reach WhatsApp") as error:
        wa.send_text(PATIENT, "Hi")
    assert error.value.retryable


def test_the_connection_check_reads_the_number_details(local_graph):
    local_graph.replies.append((200, {"id": "1055550001", "display_phone_number": "+1 555 000 0001", "verified_name": "Test Clinic"}))
    info = wa.check_connection()
    assert info["verified_name"] == "Test Clinic"
    method, path, headers, _ = local_graph.seen[0]
    assert method == "GET" and path.startswith("/v25.0/1055550001?fields=") and headers["authorization"] == f"Bearer {TOKEN}"


def test_full_flow_over_real_http(local_graph, client):
    """Signed webhook in -> pipeline -> verified reply out over a real socket."""
    body = json.dumps(meta_payload([text_message("What are your timings?")])).encode()
    response = client.post("/whatsapp/webhook", content=body, headers={"X-Hub-Signature-256": sign(body), "Content-Type": "application/json"})
    assert response.status_code == 200 and response.json()["accepted"] == 1

    assert len(local_graph.seen) == 1
    method, path, headers, sent = local_graph.seen[0]
    assert path == "/v25.0/1055550001/messages" and sent["to"] == PATIENT and "10:00 AM" in sent["text"]["body"]
    chat = database.find_conversation(PATIENT)
    assert [m["role"] for m in database.list_messages(chat["id"])] == ["patient", "assistant"]
