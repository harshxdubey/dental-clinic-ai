"""Start the Dental Clinic AI Assistant:   python run.py"""
import os

import uvicorn

from backend import config

if __name__ == "__main__":
    os.chdir(config.ROOT)
    base = f"http://{config.HOST}:{config.PORT}"
    print("\n  Dental Clinic AI Assistant - Pune (prototype)")
    if config.WHATSAPP_MODE == "cloud":
        print("  WhatsApp: REAL (Meta Cloud API). Webhook path: /whatsapp/webhook")
        missing = [n for n in ("WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET", "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID") if not getattr(config, n)]
        if missing:
            print("  !! Missing settings in .env: " + ", ".join(missing))
    else:
        print("  WhatsApp is SIMULATED.")
    print("  Clinic data is DUMMY sample data (until you replace it).")
    print(f"  AI mode: {'Claude (' + config.CLAUDE_MODEL + ')' if config.USE_LLM else 'template (offline, no API key needed)'}\n")
    print(f"  Patient chat          {base}/chat")
    print(f"  Receptionist dashboard {base}/dashboard")
    print(f"  API docs              {base}/docs")
    print("\n  Press Ctrl+C to stop.\n")
    uvicorn.run("backend.main:app", host=config.HOST, port=config.PORT, log_level="warning")
