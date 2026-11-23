"""The web application: wires the API and the two web pages together.

Start it with:  python run.py
Then open:      http://127.0.0.1:8000
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, dashboard_api, database, kb_api, kbstore, knowledge, meta_webhook, webhook, whatsapp_cloud


@asynccontextmanager
async def lifespan(app: FastAPI):
    whatsapp_cloud.install_log_redaction()      # no secret can ever appear in a log line
    if config.ALLOW_PUBLIC_DASHBOARD and whatsapp_cloud.is_cloud():
        # A dashboard with no login that can reply to real patients must never be reachable from the internet.
        raise RuntimeError("ALLOW_PUBLIC_DASHBOARD=true is only for the simulated demo. It cannot be combined with "
                           "WHATSAPP_MODE=cloud (the dashboard has no login and could message real patients).")
    _prepare()
    interrupted = database.mark_interrupted_inbound()
    log = logging.getLogger("clinic_ai.whatsapp")
    if whatsapp_cloud.is_cloud():
        missing = whatsapp_cloud.missing_settings()
        log.info("WhatsApp Cloud API mode ON (Graph %s)%s", config.WHATSAPP_GRAPH_API_VERSION,
                 f"; MISSING SETTINGS: {', '.join(missing)}" if missing else "; configuration complete")
    if interrupted:
        log.warning("%s incoming message(s) were interrupted by a restart and are marked failed", interrupted)
    yield


def _prepare() -> None:
    """Start-up work shared by the normal start (lifespan) and Vercel (which may not run lifespan events)."""
    database.init_db()
    if config.SEED_DEMO_ON_START and not whatsapp_cloud.is_cloud() and database.stats()["total"] == 0:
        for phone, name, text in dashboard_api.DEMO_MESSAGES:
            webhook.handle_incoming_message(phone, name, text)


app = FastAPI(
    title="Dental Clinic AI Assistant - Pune (prototype)",
    description="Student prototype. WhatsApp is SIMULATED and all clinic data is DUMMY sample data. "
                "Interactive API docs: this page. Patient chat: /chat. Receptionist dashboard: /dashboard.",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(webhook.router)
app.include_router(dashboard_api.router)
app.include_router(kb_api.router)
app.include_router(meta_webhook.router)


@app.exception_handler(knowledge.KnowledgeBaseError)
async def knowledge_error_handler(request: Request, exc: knowledge.KnowledgeBaseError):
    return JSONResponse(status_code=500, content={"detail": f"Knowledge base problem: {exc}"})


@app.exception_handler(kbstore.ValidationFailed)
async def validation_error_handler(request: Request, exc: kbstore.ValidationFailed):
    return JSONResponse(status_code=422, content={"detail": {"errors": exc.errors}})


# Headers that tunnels (ngrok, Cloudflare...) and reverse proxies add. Their presence means the request came
# from outside this computer, possibly from the internet.
_PROXY_HEADERS = ("x-forwarded-for", "x-forwarded-host", "forwarded", "cf-connecting-ip", "x-real-ip")
_PUBLIC_PATHS = {meta_webhook.WEBHOOK_PATH, "/healthz"}


@app.middleware("http")
async def only_the_webhook_is_public(request: Request, call_next):
    """The dashboard and knowledge-base editor have NO login. So when you expose the app to Meta through a
    tunnel, everything except the WhatsApp webhook is refused for requests that arrive through that tunnel."""
    if (not config.ALLOW_PUBLIC_DASHBOARD and request.url.path not in _PUBLIC_PATHS
            and any(h in request.headers for h in _PROXY_HEADERS)):
        return JSONResponse(status_code=403, content={"detail": "This page is only available on the computer running the app. "
                                                                "Only the WhatsApp webhook is reachable from the internet."})
    return await call_next(request)


@app.middleware("http")
async def no_cache_for_pages(request: Request, call_next):
    """Always load the latest HTML/CSS/JS while you are editing the prototype."""
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/api/meta", tags=["Info"])
def meta() -> dict:
    kb = knowledge.load()
    clinic = kb["clinic"]
    return {
        "clinic_name": clinic["clinic_name"],
        "short_name": clinic["short_name"],
        "tagline": clinic.get("tagline", ""),
        "dummy_entries": kb["dummy_entries"],
        "dummy_notice": kbstore.DUMMY_NOTICE if kb["dummy_entries"] else "",
        "whatsapp_mode": config.WHATSAPP_MODE,
        "whatsapp": whatsapp_cloud.status_summary(),     # booleans and names only - never a secret
        "ai_mode": "claude" if config.USE_LLM else "template",
        "model": config.CLAUDE_MODEL if config.USE_LLM else None,
        "minutes_saved_per_auto_reply": config.MINUTES_SAVED_PER_AUTO_REPLY,
    }


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(config.FRONTEND_DIR / "index.html")


app.mount("/shared", StaticFiles(directory=config.FRONTEND_DIR / "shared"), name="shared")
app.mount("/chat", StaticFiles(directory=config.FRONTEND_DIR / "patient_chat", html=True), name="chat")
app.mount("/knowledge", StaticFiles(directory=config.FRONTEND_DIR / "knowledge_base", html=True), name="knowledge")
app.mount("/dashboard", StaticFiles(directory=config.FRONTEND_DIR / "reception_dashboard", html=True), name="dashboard")


if config.ON_VERCEL:      # serverless: prepare the temporary database as soon as the function starts
    _prepare()
