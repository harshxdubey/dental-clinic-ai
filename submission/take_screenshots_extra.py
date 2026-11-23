"""Two extra screenshots: the 'show your work' trace on the Knowledge Base page, and the dashboard's verification checks."""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8011"
OUT = Path(__file__).resolve().parent / "screenshots"
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    page = b.new_context(viewport={"width": 1360, "height": 1000}, device_scale_factor=2).new_page()
    page.goto(f"{BASE}/knowledge/"); page.wait_for_timeout(1500)
    page.get_by_text("Test a question").first.click(); page.wait_for_timeout(500)
    box = page.locator("textarea, input[type=text]").first
    box.fill("How much does a root canal cost and are you open on Sunday?")
    page.get_by_role("button", name="Ask").first.click() if page.get_by_role("button", name="Ask").count() else box.press("Enter")
    page.wait_for_timeout(2000)
    page.screenshot(path=str(OUT / "06_show_your_work.png"))
    page.goto(f"{BASE}/dashboard/"); page.wait_for_timeout(2000)
    page.get_by_text("Pooja Nair").first.click(); page.wait_for_timeout(1000)
    page.locator("#detail").evaluate("e => { const s = e.querySelector('.detail-scroll, .detail-body') || e; s.scrollTop = 900; }")
    page.wait_for_timeout(500)
    page.screenshot(path=str(OUT / "07_verification_checks.png"))
    b.close()
