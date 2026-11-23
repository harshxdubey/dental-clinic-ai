# Submission pack

| File | What it is |
|---|---|
| `Dental_Clinic_AI_Workbook.xlsx` | Knowledge & Testing Workbook: 8 tabs (problem statement, clinic knowledge base, RAG database, query classification, 265 test cases, verification results, human handoff, performance metrics). Metrics are live Excel formulas. |
| `Dental_Clinic_AI_Project_Report.pdf` | 12-page project report & user guide. |
| `Dental_Clinic_AI_Source.zip` | Source code (no `.env`, no database, no virtual environment). |
| `screenshots/` | Full-size PNGs of the patient chat, dashboard (overview, held approval, urgent), knowledge base, "show your work" trace. |
| `../README.md`, `../.env.example` | How to run; configuration names with no secrets. |

Not included (yours to add): the screen recording (follow `../documentation/DEMO_SCRIPT.md`) and your approved handwritten design sheet.

## Rebuild

    ./.venv/bin/python -m qa.run_qa --round all --json qa/results/all_final.json   # re-run the tests
    ./.venv/bin/python -m qa.make_report                                          # QA report
    ./.venv/bin/python submission/build_workbook.py                               # workbook (needs xlsxwriter)
    # screenshots + e-book need Playwright and Google Chrome:  pip install playwright
    DATABASE_PATH=/tmp/shots.db PORT=8011 ./.venv/bin/python run.py &             # a SEPARATE demo server
    python submission/seed_screenshot_data.py http://127.0.0.1:8011
    python submission/take_screenshots.py http://127.0.0.1:8011
    python submission/build_ebook.py
