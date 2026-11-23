"""Fills a SEPARATE demo server (never your real database) with a realistic day for the screenshots.

    DATABASE_PATH=/tmp/shots.db PORT=8011 python run.py        # in one terminal
    python submission/seed_screenshot_data.py http://127.0.0.1:8011
"""
import json
import sys
import urllib.request

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8011"


def call(path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def say(phone, name, text):
    return call("/api/webhook/whatsapp", {"phone": phone, "name": name, "text": text})


call("/api/dashboard/seed-demo", {})                      # the 8 sample conversations built into the app
more = [
    ("919000000109", "Anil Desai", "Do you have a wheelchair ramp?"),
    ("919000000110", "Pooja Nair", "Is Dr. Sharma available this week?"),
    ("919000000111", "Rahul Verma", "Mujhe kal ke liye appointment chahiye"),
    ("919000000112", "Sunita More", "Which painkiller should I take for my toothache?"),
    ("919000000113", "Kabir Singh", "Aapki clinic kab khulti hai?"),
    ("919000000114", "Tara Bose", "How much are clear aligners?"),
]
for phone, name, text in more:
    say(phone, name, text)

# The patient-chat conversation (Aarav Sharma is the chat page's first patient)
A = ("919000000001", "Aarav Sharma")
say(*A, "Hi")
say(*A, "How much does a root canal cost?")
say(*A, "Where are you located and is there parking?")
booking = say(*A, "Can I book Dr. Neha tomorrow at 5 PM for braces?")
call(f"/api/dashboard/inquiries/{booking['inquiry_id']}/send", {
    "text": "Hi Aarav! Dr. Neha has a free slot tomorrow at 5:00 PM and I have booked it for you. Please arrive 10 minutes early. - Reception, Sample Dental Clinic",
    "acknowledge": True})
say(*A, "Do you have a wheelchair ramp?")
print(json.dumps(call("/api/dashboard/stats") if False else {"ok": True}))
