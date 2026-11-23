"""SQLite storage for conversations, messages and the AI's audit trail.

SQLite is a single file (clinic_ai.db) built into Python - nothing to install or run.

Three tables:
  conversations - one row per patient phone number
  messages      - every chat bubble (patient, AI assistant, receptionist)
  inquiries     - one row per patient message, recording what the AI decided and why
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from . import config

OPEN_STATUSES = ("pending_approval", "escalated")
RESOLVED_STATUSES = ("approved", "replied", "dismissed")
STATUS_FILTERS = {
    "all": None,
    "open": OPEN_STATUSES,
    "pending": ("pending_approval",),
    "escalated": ("escalated",),
    "auto": ("auto_replied",),
    "resolved": RESOLVED_STATUSES,
}
JSON_FIELDS = ("intents", "sources", "checks", "reasons", "audit")
DICT_FIELDS = ("rag",)   # JSON objects (everything above is a JSON list)
INQUIRY_FIELDS = {
    "conversation_id", "message_id", "question", "intent", "intents", "confidence", "urgent", "draft",
    "draft_mode", "draft_note", "sources", "checks", "reasons", "decision", "status", "final_reply",
    "resolved_by", "resolved_at", "rag", "audit",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    phone       TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    channel     TEXT NOT NULL DEFAULT 'simulated',   -- simulated (demo chat page) | whatsapp (a real patient via the Cloud API)
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    role            TEXT NOT NULL,            -- patient | assistant | receptionist
    text            TEXT NOT NULL,
    inquiry_id      INTEGER,
    sources         TEXT NOT NULL DEFAULT '[]',   -- the clinic entries this reply was built from
    meta            TEXT NOT NULL DEFAULT '{}',   -- how it was approved: verified automatically / by whom / edited?
    wa_id           TEXT,                         -- WhatsApp's id for this message (wamid...), real WhatsApp only
    delivery        TEXT NOT NULL DEFAULT '',     -- simulated | sent | delivered | read | failed
    delivery_error  TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS whatsapp_events (      -- every incoming WhatsApp message, once (duplicate protection)
    wa_message_id   TEXT PRIMARY KEY,
    phone           TEXT NOT NULL,
    state           TEXT NOT NULL,                -- processing | done | failed | ignored
    attempts        INTEGER NOT NULL DEFAULT 1,
    error           TEXT NOT NULL DEFAULT '',
    inquiry_id      INTEGER,
    received_at     TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inquiries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    message_id      INTEGER NOT NULL,
    question        TEXT NOT NULL,
    intent          TEXT NOT NULL,
    intents         TEXT NOT NULL DEFAULT '[]',
    confidence      REAL NOT NULL DEFAULT 0,
    urgent          INTEGER NOT NULL DEFAULT 0,
    draft           TEXT NOT NULL DEFAULT '',
    draft_mode      TEXT NOT NULL DEFAULT 'template',
    draft_note      TEXT NOT NULL DEFAULT '',
    sources         TEXT NOT NULL DEFAULT '[]',
    checks          TEXT NOT NULL DEFAULT '[]',
    reasons         TEXT NOT NULL DEFAULT '[]',
    audit           TEXT NOT NULL DEFAULT '[]',   -- timeline: verified, sent, approved, edited, rejected...
    rag             TEXT NOT NULL DEFAULT '{}',   -- how the answer was built: sources used, parts, whether it was answerable
    decision        TEXT NOT NULL,            -- auto_send | needs_approval | escalate
    status          TEXT NOT NULL,            -- auto_replied | pending_approval | escalated | approved | replied | dismissed
    final_reply     TEXT,
    resolved_by     TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    resolved_at     TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id);
CREATE INDEX IF NOT EXISTS idx_inquiries_status ON inquiries(status, id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    conn = sqlite3.connect(config.DATABASE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    config.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        # a database created by an earlier version of the app gets the newer columns added
        for table, column, definition in (("inquiries", "rag", "TEXT NOT NULL DEFAULT '{}'"),
                                          ("inquiries", "audit", "TEXT NOT NULL DEFAULT '[]'"),
                                          ("messages", "sources", "TEXT NOT NULL DEFAULT '[]'"),
                                          ("messages", "meta", "TEXT NOT NULL DEFAULT '{}'"),
                                          ("messages", "wa_id", "TEXT"),
                                          ("messages", "delivery", "TEXT NOT NULL DEFAULT ''"),
                                          ("messages", "delivery_error", "TEXT NOT NULL DEFAULT ''"),
                                          ("conversations", "channel", "TEXT NOT NULL DEFAULT 'simulated'")):
            if column not in {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_wa ON messages(wa_id)")   # after the column is sure to exist
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES ('auto_reply', ?)",
                     ("1" if config.AUTO_REPLY_DEFAULT else "0",))


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
def get_setting(key: str, default: str = "") -> str:
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute("INSERT INTO settings(key, value) VALUES (?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


# --------------------------------------------------------------------------
# Conversations and messages
# --------------------------------------------------------------------------
def get_or_create_conversation(phone: str, name: str, channel: str = "simulated") -> dict:
    """channel: "simulated" (demo chat page) or "whatsapp" (a real patient writing through the Cloud API).

    A conversation that has ever received a real WhatsApp message is a real one: it stays "whatsapp".
    """
    stamp = now()
    with connect() as conn:
        row = conn.execute("SELECT * FROM conversations WHERE phone = ?", (phone,)).fetchone()
        if row is None:
            cur = conn.execute("INSERT INTO conversations(phone, name, channel, created_at, updated_at) VALUES (?,?,?,?,?)",
                               (phone, name, channel, stamp, stamp))
            row = conn.execute("SELECT * FROM conversations WHERE id = ?", (cur.lastrowid,)).fetchone()
        else:
            if name and name != row["name"] and name != "Patient":
                conn.execute("UPDATE conversations SET name = ? WHERE id = ?", (name, row["id"]))
            if channel == "whatsapp" and row["channel"] != "whatsapp":
                conn.execute("UPDATE conversations SET channel = 'whatsapp' WHERE id = ?", (row["id"],))
            row = conn.execute("SELECT * FROM conversations WHERE id = ?", (row["id"],)).fetchone()
        return dict(row)


def find_conversation(phone: str) -> Optional[dict]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM conversations WHERE phone = ?", (phone,)).fetchone()
    return dict(row) if row else None


def _message(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["sources"] = json.loads(data.get("sources") or "[]")
    data["meta"] = json.loads(data.get("meta") or "{}")
    return data


def add_message(conversation_id: int, role: str, text: str, inquiry_id: Optional[int] = None,
                sources: Optional[list] = None, meta: Optional[dict] = None, *,
                wa_id: Optional[str] = None, delivery: str = "") -> dict:
    """Save a chat message. For replies, `sources` lists the clinic entries it came from and `meta`
    records how it was approved - so the conversation history shows where every answer came from.
    `wa_id`/`delivery` are the WhatsApp message id and its delivery state (real WhatsApp only)."""
    stamp = now()
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO messages(conversation_id, role, text, inquiry_id, sources, meta, wa_id, delivery, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (conversation_id, role, text, inquiry_id, json.dumps(sources or [], ensure_ascii=False),
             json.dumps(meta or {}, ensure_ascii=False), wa_id, delivery, stamp))
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (stamp, conversation_id))
        row = conn.execute("SELECT * FROM messages WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _message(row)


_DELIVERY_RANK = {"": 0, "simulated": 0, "sent": 1, "delivered": 2, "read": 3}


def set_delivery(wa_id: str, status: str, error: str = "") -> bool:
    """Apply a WhatsApp delivery update (sent -> delivered -> read, or failed) to a message we sent.

    Updates can arrive out of order, so a message never moves backwards (read is not changed back to delivered).
    """
    with connect() as conn:
        row = conn.execute("SELECT id, delivery FROM messages WHERE wa_id = ? AND role != 'patient'", (wa_id,)).fetchone()
        if row is None:
            return False
        if status != "failed" and _DELIVERY_RANK.get(status, 0) <= _DELIVERY_RANK.get(row["delivery"], 0):
            return True
        conn.execute("UPDATE messages SET delivery = ?, delivery_error = ? WHERE id = ?", (status, error[:300], row["id"]))
    return True


def find_message_by_wa_id(wa_id: str) -> Optional[dict]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM messages WHERE wa_id = ?", (wa_id,)).fetchone()
    return _message(row) if row else None


def last_patient_message_at(conversation_id: int) -> Optional[str]:
    with connect() as conn:
        row = conn.execute("SELECT created_at FROM messages WHERE conversation_id = ? AND role = 'patient' "
                           "ORDER BY id DESC LIMIT 1", (conversation_id,)).fetchone()
    return row["created_at"] if row else None


# ---- duplicate protection for incoming WhatsApp messages ----
def claim_inbound(wa_message_id: str, phone: str, stale_seconds: int = 300) -> str:
    """Register an incoming WhatsApp message. Returns "new", "retry" or "duplicate".

    Meta re-sends a message if we are slow or fail, for up to 36 hours, so the same id can arrive many times.
    The id is the table's primary key, so exactly one delivery can ever win the "new" claim, even if two arrive
    at the same instant. A message that previously FAILED (or whose processing was abandoned for `stale_seconds`)
    may be claimed again as a "retry", so a crash never loses a patient message.
    """
    stamp = now()
    with connect() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO whatsapp_events(wa_message_id, phone, state, attempts, received_at, updated_at) "
            "VALUES (?, ?, 'processing', 1, ?, ?)", (wa_message_id, phone, stamp, stamp))
        if cur.rowcount == 1:
            return "new"
        row = conn.execute("SELECT state, updated_at FROM whatsapp_events WHERE wa_message_id = ?", (wa_message_id,)).fetchone()
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(row["updated_at"])).total_seconds()
        if row["state"] == "failed" or (row["state"] == "processing" and age > stale_seconds):
            conn.execute("UPDATE whatsapp_events SET state = 'processing', attempts = attempts + 1, updated_at = ? "
                         "WHERE wa_message_id = ? AND state = ?", (stamp, wa_message_id, row["state"]))
            return "retry"
        return "duplicate"


def finish_inbound(wa_message_id: str, state: str, error: str = "", inquiry_id: Optional[int] = None) -> None:
    with connect() as conn:
        conn.execute("UPDATE whatsapp_events SET state = ?, error = ?, inquiry_id = ?, updated_at = ? WHERE wa_message_id = ?",
                     (state, error[:300], inquiry_id, now(), wa_message_id))


def mark_interrupted_inbound(stale_seconds: int = 300) -> int:
    """At start-up: a message still "processing" long after it began was interrupted by a crash. Mark it failed
    so it is visible (and can be re-claimed if Meta re-sends it)."""
    cutoff = (datetime.now(timezone.utc).timestamp() - stale_seconds)
    count = 0
    with connect() as conn:
        for row in conn.execute("SELECT wa_message_id, updated_at FROM whatsapp_events WHERE state = 'processing'").fetchall():
            if datetime.fromisoformat(row["updated_at"]).timestamp() < cutoff:
                conn.execute("UPDATE whatsapp_events SET state = 'failed', error = 'interrupted' WHERE wa_message_id = ?",
                             (row["wa_message_id"],))
                count += 1
    return count


def inbound_counts() -> dict:
    with connect() as conn:
        counts = {r["state"]: r["n"] for r in conn.execute("SELECT state, COUNT(*) AS n FROM whatsapp_events GROUP BY state")}
        last = conn.execute("SELECT MAX(received_at) AS t FROM whatsapp_events").fetchone()["t"]
    return {"done": counts.get("done", 0), "failed": counts.get("failed", 0), "processing": counts.get("processing", 0),
            "ignored": counts.get("ignored", 0), "last_received_at": last}


def list_messages(conversation_id: int, after_id: int = 0) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM messages WHERE conversation_id = ? AND id > ? ORDER BY id",
                            (conversation_id, after_id)).fetchall()
    return [_message(r) for r in rows]


def last_clinic_message(conversation_id: int) -> Optional[dict]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM messages WHERE conversation_id = ? AND role != 'patient' "
                           "ORDER BY id DESC LIMIT 1", (conversation_id,)).fetchone()
    return _message(row) if row else None


def open_notice(conversation_id: int) -> Optional[dict]:
    """Tells the patient chat if a person is still working on a message."""
    with connect() as conn:
        row = conn.execute("SELECT status, urgent FROM inquiries WHERE conversation_id = ? AND status IN (?, ?) "
                           "ORDER BY id DESC LIMIT 1", (conversation_id, *OPEN_STATUSES)).fetchone()
    return {"state": row["status"], "urgent": bool(row["urgent"])} if row else None


# --------------------------------------------------------------------------
# Inquiries (one per patient message)
# --------------------------------------------------------------------------
def _inquiry(row: sqlite3.Row) -> dict:
    data = dict(row)
    for key in JSON_FIELDS:
        data[key] = json.loads(data[key]) if data.get(key) else []
    for key in DICT_FIELDS:
        data[key] = json.loads(data[key]) if data.get(key) else {}
    data["urgent"] = bool(data["urgent"])
    return data


def _encode(fields: dict) -> dict:
    unknown = set(fields) - INQUIRY_FIELDS
    if unknown:
        raise ValueError(f"Unknown inquiry fields: {sorted(unknown)}")
    out = dict(fields)
    for key in JSON_FIELDS + DICT_FIELDS:
        if key in out:
            out[key] = json.dumps(out[key], ensure_ascii=False)
    if "urgent" in out:
        out["urgent"] = 1 if out["urgent"] else 0
    return out


_SELECT_INQUIRY = ("SELECT i.*, c.name AS patient_name, c.phone AS patient_phone, c.channel AS patient_channel "
                   "FROM inquiries i JOIN conversations c ON c.id = i.conversation_id ")


def create_inquiry(**fields) -> dict:
    stamp = now()
    data = _encode(fields)
    data.update(created_at=stamp, updated_at=stamp)
    columns = ", ".join(data)
    marks = ", ".join("?" for _ in data)
    with connect() as conn:
        cur = conn.execute(f"INSERT INTO inquiries({columns}) VALUES ({marks})", tuple(data.values()))
        row = conn.execute(_SELECT_INQUIRY + "WHERE i.id = ?", (cur.lastrowid,)).fetchone()
    return _inquiry(row)


def update_inquiry(inquiry_id: int, **fields) -> dict:
    data = _encode(fields)
    data["updated_at"] = now()
    assignments = ", ".join(f"{key} = ?" for key in data)
    with connect() as conn:
        conn.execute(f"UPDATE inquiries SET {assignments} WHERE id = ?", (*data.values(), inquiry_id))
        row = conn.execute(_SELECT_INQUIRY + "WHERE i.id = ?", (inquiry_id,)).fetchone()
    return _inquiry(row)


def add_audit(inquiry_id: int, by: str, event: str, detail: str = "") -> None:
    """Append one line to an inquiry's timeline (who did what, when)."""
    with connect() as conn:
        row = conn.execute("SELECT audit FROM inquiries WHERE id = ?", (inquiry_id,)).fetchone()
        if row is None:
            return
        trail = json.loads(row["audit"] or "[]")
        trail.append({"at": now(), "by": by, "event": event, "detail": detail})
        conn.execute("UPDATE inquiries SET audit = ? WHERE id = ?", (json.dumps(trail, ensure_ascii=False), inquiry_id))


def get_inquiry(inquiry_id: int) -> Optional[dict]:
    with connect() as conn:
        row = conn.execute(_SELECT_INQUIRY + "WHERE i.id = ?", (inquiry_id,)).fetchone()
    return _inquiry(row) if row else None


def list_inquiries(status: str = "all", limit: int = 200) -> list[dict]:
    statuses = STATUS_FILTERS.get(status)
    query = _SELECT_INQUIRY
    params: list = []
    if statuses:
        query += f"WHERE i.status IN ({', '.join('?' for _ in statuses)}) "
        params += list(statuses)
    # Work still waiting for a person: urgent first, then oldest first. Everything else: newest first.
    query += "ORDER BY i.urgent DESC, i.id ASC " if status in ("open", "pending", "escalated") else "ORDER BY i.id DESC "
    query += "LIMIT ?"
    params.append(limit)
    with connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_inquiry(r) for r in rows]


def stats() -> dict:
    with connect() as conn:
        by_status = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM inquiries GROUP BY status")}
        by_intent = {r["intent"]: r["n"] for r in conn.execute(
            "SELECT intent, COUNT(*) AS n FROM inquiries GROUP BY intent ORDER BY n DESC")}
        urgent_open = conn.execute("SELECT COUNT(*) AS n FROM inquiries WHERE urgent = 1 AND status IN (?, ?)",
                                   OPEN_STATUSES).fetchone()["n"]
        newest = conn.execute("SELECT COALESCE(MAX(id), 0) AS n FROM inquiries").fetchone()["n"]

    total = sum(by_status.values())
    auto = by_status.get("auto_replied", 0)
    pending = by_status.get("pending_approval", 0)
    escalated = by_status.get("escalated", 0)
    resolved = sum(by_status.get(s, 0) for s in RESOLVED_STATUSES)
    return {
        "total": total,
        "auto_replied": auto,
        "pending": pending,
        "escalated": escalated,
        "resolved": resolved,
        "urgent_open": urgent_open,
        "auto_rate": round(100 * auto / total) if total else 0,
        "minutes_saved": round(auto * config.MINUTES_SAVED_PER_AUTO_REPLY),
        "by_intent": by_intent,
        "newest_inquiry_id": newest,
        "counts": {"all": total, "open": pending + escalated, "pending": pending, "escalated": escalated,
                   "auto": auto, "resolved": resolved},
    }


def reset_all() -> None:
    """Delete all chats and AI records (the demo reset button). Settings are kept."""
    with connect() as conn:
        conn.execute("DELETE FROM inquiries")
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM conversations")
