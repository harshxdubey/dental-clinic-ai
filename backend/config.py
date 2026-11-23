"""Central settings.

Everything here can be changed with environment variables. The easiest way is to copy
`.env.example` to `.env` and edit that file - you never need to edit this one.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"          # the clinic knowledge base (JSON files)

# On Vercel (serverless) the project folder is READ-ONLY; only /tmp is writable. So there the knowledge base is copied to /tmp
# (so the Knowledge Base page can still save edits) and the database lives in /tmp too. Both are temporary: they reset when
# the serverless instance is recycled. That is fine for a demo with dummy data and unsuitable for real use.
ON_VERCEL = bool(os.getenv("VERCEL"))
if ON_VERCEL:
    import shutil
    _writable = Path("/tmp/clinic_data")
    if not _writable.exists():
        shutil.copytree(DATA_DIR, _writable, ignore=shutil.ignore_patterns("backups"))
    DATA_DIR = _writable
FRONTEND_DIR = ROOT / "frontend"  # the two web pages


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


# --- Server -----------------------------------------------------------------
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(_env_float("PORT", 8000))

# --- Database (SQLite file that stores chats and the AI's audit trail) -------
DATABASE_PATH = _env_path("DATABASE_PATH", Path("/tmp/clinic_ai.db") if ON_VERCEL else ROOT / "clinic_ai.db")

# --- AI drafting ------------------------------------------------------------
# With no API key the assistant runs in "template mode": answers are built from
# the knowledge base using fixed templates. It works offline and costs nothing.
# With a key, Claude writes the wording of informational answers (still checked
# by the validator). Sensitive topics always use safe templates.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5").strip()
LLM_TIMEOUT_SECONDS = _env_float("LLM_TIMEOUT_SECONDS", 25)
USE_LLM = bool(ANTHROPIC_API_KEY)

# --- Safety rules (used by the validator) -------------------------------------
# Start with auto-reply switched on or off. The dashboard has a switch too.
AUTO_REPLY_DEFAULT = _env_bool("AUTO_REPLY_ENABLED", True)
# Below this intent-confidence the draft goes to a receptionist for approval.
MIN_CLASSIFIER_CONFIDENCE = _env_float("MIN_CLASSIFIER_CONFIDENCE", 0.7)
# A factual answer needs at least one knowledge-base source scoring this high.
MIN_SOURCE_SCORE = _env_float("MIN_SOURCE_SCORE", 0.5)

# If true, answers written by the AI model are ALWAYS held for a receptionist, even when every check
# passes (a cautious setting for the first weeks with a real API key). Template answers are unaffected.
APPROVE_MODEL_ANSWERS = _env_bool("APPROVE_MODEL_ANSWERS", False)

# --- Dashboard ------------------------------------------------------------------
# Used only for the "time saved" estimate on the dashboard.
MINUTES_SAVED_PER_AUTO_REPLY = _env_float("MINUTES_SAVED_PER_AUTO_REPLY", 2)


# --- WhatsApp -----------------------------------------------------------------------------------
# "simulated" (default): the patient chat page imitates WhatsApp; nothing leaves your computer.
# "cloud": the official Meta WhatsApp Cloud API - real patients, real messages. See
#          documentation/WHATSAPP_CLOUD_SETUP.md. Every secret below comes ONLY from environment
#          variables (.env); none is ever written to the database, the logs or the web pages.
WHATSAPP_MODE = os.getenv("WHATSAPP_MODE", "simulated").strip().lower()
if WHATSAPP_MODE not in ("simulated", "cloud"):
    raise SystemExit(f"WHATSAPP_MODE must be 'simulated' or 'cloud' (it is {WHATSAPP_MODE!r}). Check your .env file.")

WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip()      # you invent this; Meta echoes it back
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "").strip()          # signs every webhook (App settings > Basic)
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()      # lets us send messages
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()  # the sending number's id (not the phone number)
WHATSAPP_GRAPH_API_VERSION = os.getenv("WHATSAPP_GRAPH_API_VERSION", "v25.0").strip()
WHATSAPP_GRAPH_BASE_URL = os.getenv("WHATSAPP_GRAPH_BASE_URL", "https://graph.facebook.com").strip().rstrip("/")
WHATSAPP_SEND_TIMEOUT_SECONDS = _env_float("WHATSAPP_SEND_TIMEOUT_SECONDS", 15)
# Optional safety net while testing: only these phone numbers (digits, comma separated) get processed.
WHATSAPP_ALLOWED_SENDERS = {
    "".join(ch for ch in part if ch.isdigit()) for part in os.getenv("WHATSAPP_ALLOWED_SENDERS", "").split(",")
} - {""}

# The dashboard has NO login. If a request arrives through a tunnel / reverse proxy (so possibly from the
# internet), only the WhatsApp webhook is allowed. Setting this to true removes that protection.
ALLOW_PUBLIC_DASHBOARD = _env_bool("ALLOW_PUBLIC_DASHBOARD", False)

# For a PUBLIC DEMO ONLY (for example a student project hosted on the internet with dummy data): on the first start with an
# empty database, load the built-in sample conversations so the dashboard is not empty.
SEED_DEMO_ON_START = _env_bool("SEED_DEMO_ON_START", False)


def secret_values() -> list[str]:
    """Every secret currently configured - used to scrub them out of any log line."""
    return [v for v in (WHATSAPP_ACCESS_TOKEN, WHATSAPP_APP_SECRET, WHATSAPP_VERIFY_TOKEN, ANTHROPIC_API_KEY) if len(v) >= 6]
