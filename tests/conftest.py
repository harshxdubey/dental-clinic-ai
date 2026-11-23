"""Shared test setup. Tests never use the network, a real API key or your real database."""
import hashlib
import hmac
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config, rag, whatsapp_cloud  # noqa: E402
from fake_graph import FakeGraph  # noqa: E402

REAL_DATA = config.DATA_DIR


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    # Every test works on its own COPY of the knowledge base, so tests that add or edit
    # entries can never change the real files in data/.
    shutil.copytree(REAL_DATA, tmp_path / "data", ignore=shutil.ignore_patterns("backups"))
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "USE_LLM", False)                      # template mode, no API calls
    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "test.db")  # throw-away database
    monkeypatch.setattr(config, "AUTO_REPLY_DEFAULT", True)
    monkeypatch.setattr(config, "MIN_CLASSIFIER_CONFIDENCE", 0.7)
    monkeypatch.setattr(config, "MIN_SOURCE_SCORE", 0.5)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as test_client:
        yield test_client


GOOD = ("SOURCES: treatment:root_canal\nANSWER:\nA root canal costs ₹4,000 – ₹9,000 per tooth, depending on the tooth. "
        "The dentist confirms the exact cost after an examination.")


class StubModel:
    """Stands in for the Anthropic client."""

    def __init__(self, reply=GOOD, stop_reason="end_turn", error=None):
        self.reply, self.stop_reason, self.error = reply, stop_reason, error
        self.calls = []
        self.messages = SimpleNamespace(create=lambda **kw: self._respond("plain", kw))
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: self._respond("beta", kw)))

    def _respond(self, route, kwargs):
        self.calls.append({"route": route, **kwargs})
        if self.error:
            raise self.error
        return SimpleNamespace(stop_reason=self.stop_reason, content=[SimpleNamespace(type="text", text=self.reply)])


@pytest.fixture
def model(monkeypatch):
    """Switch the app into 'Claude mode' with a stand-in model. Usage: stub = model(reply=...)."""
    def install(**kwargs):
        stub = StubModel(**kwargs)
        monkeypatch.setattr(config, "USE_LLM", True)
        monkeypatch.setattr(config, "CLAUDE_MODEL", "claude-haiku-5-5")
        monkeypatch.setattr(rag, "_get_client", lambda: stub)
        return stub
    return install


# ---------------------------------------------------------------- WhatsApp Cloud API test kit
CLOUD_SETTINGS = dict(
    WHATSAPP_MODE="cloud", WHATSAPP_VERIFY_TOKEN="verify-me-12345", WHATSAPP_APP_SECRET="app-secret-abcdef123456",
    WHATSAPP_ACCESS_TOKEN="EAAtesttoken1234567890abcdefXYZ", WHATSAPP_PHONE_NUMBER_ID="1055550001",
)
PATIENT = "919876500001"


def text_message(text, wamid="wamid.IN1", sender=PATIENT):
    return {"from": sender, "id": wamid, "timestamp": "1749416383", "type": "text", "text": {"body": text}}


def meta_payload(messages=None, statuses=None, name="Asha Patil", phone_number_id=None, sender=PATIENT):
    """A payload shaped like the ones Meta posts to a WhatsApp webhook."""
    value = {"messaging_product": "whatsapp",
             "metadata": {"display_phone_number": "15550000001",
                          "phone_number_id": phone_number_id or CLOUD_SETTINGS["WHATSAPP_PHONE_NUMBER_ID"]}}
    if messages:
        value["contacts"] = [{"profile": {"name": name}, "wa_id": sender}]
        value["messages"] = messages
    if statuses:
        value["statuses"] = statuses
    return {"object": "whatsapp_business_account", "entry": [{"id": "WABA-ID", "changes": [{"value": value, "field": "messages"}]}]}


def sign(body: bytes, secret=CLOUD_SETTINGS["WHATSAPP_APP_SECRET"]) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class CloudHarness:
    """Talks to the app the way Meta does, and exposes the fake Graph API that receives our replies."""

    def __init__(self, client, graph):
        self.client, self.graph = client, graph

    def post(self, payload, signature=True, raw=None, headers=None):
        body = raw if raw is not None else json.dumps(payload).encode()
        head = {"Content-Type": "application/json", **(headers or {})}
        if signature is True:
            head["X-Hub-Signature-256"] = sign(body)
        elif signature:
            head["X-Hub-Signature-256"] = signature
        return self.client.post("/whatsapp/webhook", content=body, headers=head)

    def say(self, text, wamid="wamid.IN1", sender=PATIENT, name="Asha Patil"):
        return self.post(meta_payload([text_message(text, wamid, sender)], name=name, sender=sender))


@pytest.fixture
def cloud(monkeypatch, client):
    """Switch the app to WhatsApp Cloud mode, with a fake Graph API instead of the internet."""
    for key, value in CLOUD_SETTINGS.items():
        monkeypatch.setattr(config, key, value)
    monkeypatch.setattr(config, "WHATSAPP_ALLOWED_SENDERS", set())
    monkeypatch.setattr(config, "ALLOW_PUBLIC_DASHBOARD", False)
    graph = FakeGraph(CLOUD_SETTINGS["WHATSAPP_PHONE_NUMBER_ID"])
    whatsapp_cloud.set_transport(httpx.MockTransport(graph))
    monkeypatch.setattr(whatsapp_cloud, "_pause", lambda seconds: None)      # retries do not really wait
    yield CloudHarness(client, graph)
    whatsapp_cloud.set_transport(None)
