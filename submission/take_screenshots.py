"""Takes the screenshots used in the e-book from a demo server (see seed_screenshot_data.py).

Needs Playwright with the installed Google Chrome:  pip install playwright   (no browser download: uses channel="chrome")
    python submission/take_screenshots.py http://127.0.0.1:8011
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8011"
OUT = Path(__file__).resolve().parent / "screenshots"
OUT.mkdir(exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    ctx = browser.new_context(viewport={"width": 1360, "height": 900}, device_scale_factor=2)
    page = ctx.new_page()

    # 1. patient chat
    page.goto(f"{BASE}/chat/")
    page.wait_for_timeout(2500)
    page.screenshot(path=str(OUT / "01_patient_chat.png"))

    # 2. dashboard overview
    page.goto(f"{BASE}/dashboard/")
    page.wait_for_timeout(2500)
    page.screenshot(path=str(OUT / "02_dashboard_overview.png"))

    # 3. a held appointment request (approve / edit / reject)
    page.get_by_text("Sneha Kulkarni").first.click()
    page.wait_for_timeout(1200)
    page.screenshot(path=str(OUT / "03_dashboard_pending_approval.png"))

    # 4. an urgent emergency
    page.get_by_text("Amit Shah").first.click()
    page.wait_for_timeout(1200)
    page.screenshot(path=str(OUT / "04_dashboard_urgent.png"))

    # 5. knowledge base page
    page.goto(f"{BASE}/knowledge/")
    page.wait_for_timeout(2500)
    page.screenshot(path=str(OUT / "05_knowledge_base.png"))
    browser.close()
print("saved:", sorted(f.name for f in OUT.glob("*.png")))
