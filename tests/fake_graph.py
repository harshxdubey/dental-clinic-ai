"""A stand-in for graph.facebook.com, used by the tests (no network, no Meta account).

It records every request it receives and answers like the real Graph API does. Tests can queue up
errors to see how the app copes (expired token, 24-hour window, outage...).
"""
import json

import httpx


def graph_error(code, message="Something went wrong", status=400, trace="AbCdEf123"):
    """The shape of an error response from the Graph API."""
    return httpx.Response(status, json={"error": {"message": message, "type": "OAuthException", "code": code,
                                                   "fbtrace_id": trace}})


class FakeGraph:
    def __init__(self, phone_number_id):
        self.phone_number_id = phone_number_id
        self.requests = []     # every httpx.Request received, in order
        self.script = []       # responses (or functions) to use for the next sends, before falling back to success
        self.sent_count = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "POST" and request.url.path.endswith(f"/{self.phone_number_id}/messages"):
            if self.script:
                item = self.script.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item(request) if callable(item) else item
            self.sent_count += 1
            to = json.loads(request.content)["to"]
            return httpx.Response(200, json={"messaging_product": "whatsapp", "contacts": [{"input": to, "wa_id": to}],
                                             "messages": [{"id": f"wamid.OUT{self.sent_count}"}]})
        if request.method == "GET" and request.url.path.endswith(f"/{self.phone_number_id}"):
            if self.script:
                return self.script.pop(0)
            return httpx.Response(200, json={"id": self.phone_number_id, "display_phone_number": "+1 555 000 0001",
                                             "verified_name": "Test Clinic", "quality_rating": "GREEN"})
        return httpx.Response(404, json={"error": {"message": "Unknown path", "code": 803}})

    @property
    def sends(self):
        """The JSON bodies of the send-message requests, in order."""
        return [json.loads(r.content) for r in self.requests if r.method == "POST"]

    @property
    def send_requests(self):
        return [r for r in self.requests if r.method == "POST"]
