"""Turns NotebookLM_MindMap_Source.md into NotebookLM_MindMap_Source.pdf (real text, so NotebookLM can read it)."""
import html, re
from pathlib import Path
from playwright.sync_api import sync_playwright

here = Path(__file__).resolve().parent
out, stack = [], []          # stack of open <ul> indent levels


def close(to=-1):
    while stack and stack[-1] > to:
        stack.pop(); out.append("</ul>")


def inline(t):
    t = html.escape(t)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)


for line in (here / "NotebookLM_MindMap_Source.md").read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    if line.startswith("# "):
        close(); out.append(f"<h1>{inline(line[2:])}</h1>")
    elif line.startswith("## "):
        close(); out.append(f"<h2>{inline(line[3:])}</h2>")
    elif re.match(r"\s*- ", line):
        indent = len(line) - len(line.lstrip())
        close(indent)
        if not stack or stack[-1] < indent:
            stack.append(indent); out.append("<ul>")
        out.append(f"<li>{inline(line.strip()[2:])}</li>")
    else:
        close(); out.append(f"<p>{inline(line)}</p>")
close()
css = """@page { size: A4; margin: 18mm 16mm; } body { font-family: Arial, Helvetica, sans-serif; font-size: 11pt; line-height: 1.45; color: #111; }
h1 { font-size: 20pt; color: #134E4A; margin: 0 0 8px; } h2 { font-size: 13.5pt; color: #0F766E; margin: 16px 0 4px; border-bottom: 1px solid #99D5CB; padding-bottom: 2px; page-break-after: avoid; }
ul { margin: 2px 0 6px; padding-left: 20px; } li { margin-bottom: 2px; } p { margin: 4px 0; }"""
doc = f"<!doctype html><html><head><meta charset='utf-8'><title>Dental Clinic AI Assistant - Project Map</title><style>{css}</style></head><body>{''.join(out)}</body></html>"
(here / "mindmap_source.html").write_text(doc, encoding="utf-8")
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True); pg = b.new_page()
    pg.goto((here / "mindmap_source.html").as_uri()); pg.pdf(path=str(here / "NotebookLM_MindMap_Source.pdf"), prefer_css_page_size=True); b.close()
print("ok")
