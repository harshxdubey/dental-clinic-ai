"""The Knowledge Base API: add/change/delete clinic information without touching code."""
import io
import sqlite3

NEW_FAQ = {"question": "Do you have wheelchair access?", "keywords": ["wheelchair", "step free"],
           "answer": "Yes, there is a ramp at the entrance.", "dummy": True}


def ask(client, question):
    response = client.post("/api/kb/ask", json={"question": question})
    assert response.status_code == 200, response.text
    return response.json()


def test_summary_lists_every_dataset_and_counts_dummy_entries(client):
    summary = client.get("/api/kb/summary").json()
    assert [d["name"] for d in summary["datasets"]] == ["clinic", "treatments", "doctors", "faqs"]
    assert all(d["file"].endswith(".json") for d in summary["datasets"])
    assert summary["dummy_entries"] == sum(d["dummy_count"] for d in summary["datasets"]) > 0
    assert client.get("/api/meta").json()["dummy_entries"] == summary["dummy_entries"]


def test_read_each_dataset(client):
    assert len(client.get("/api/kb/treatments").json()["records"]) >= 10
    assert client.get("/api/kb/clinic").json()["record"]["phone"]
    assert client.get("/api/kb/nonsense").status_code == 404


def test_adding_an_faq_makes_the_assistant_answer_a_question_it_could_not_before(client):
    before = ask(client, "Do you have a wheelchair ramp?")
    assert before["answerable"] is False and before["retrieved"] == [] and before["decision"] == "escalate"
    assert before["holding_reply"] and before["generation"]["kind"] == "no_answer"

    created = client.post("/api/kb/faqs", json=NEW_FAQ)
    assert created.status_code == 201 and created.json()["id"] == "do_you_have_wheelchair_access"

    after = ask(client, "Do you have a wheelchair ramp?")
    assert after["answerable"] is True and "ramp at the entrance" in after["answer"]
    assert after["used_sources"] == ["faq:do_you_have_wheelchair_access"]
    source = after["retrieved"][0]
    assert source["used"] and source["dummy"] and source["file"] == "faqs.json" and source["why"]

    assert client.delete("/api/kb/faqs/do_you_have_wheelchair_access").json()["ok"]
    assert ask(client, "Do you have a wheelchair ramp?")["answerable"] is False


def test_changing_a_price_changes_the_answer(client):
    record = client.get("/api/kb/treatments").json()["records"]
    root_canal = next(r for r in record if r["id"] == "root_canal")
    assert "₹4,000" in ask(client, "how much is a root canal")["answer"]
    assert client.put("/api/kb/treatments/root_canal", json={**root_canal, "price_min": 5000, "price_max": 10000}).status_code == 200
    answer = ask(client, "how much is a root canal")["answer"]
    assert "₹5,000 – ₹10,000" in answer and "₹4,000" not in answer


def test_changing_the_clinic_phone_changes_replies(client):
    clinic = client.get("/api/kb/clinic").json()["record"]
    client.put("/api/kb/clinic", json={**clinic, "phone": "+91 98765 43210"})
    assert "98765 43210" in ask(client, "what is your phone number")["answer"]


def test_mistakes_come_back_as_a_list_of_plain_messages(client):
    response = client.post("/api/kb/faqs", json={"question": "", "keywords": [], "answer": ""})
    assert response.status_code == 422
    errors = response.json()["detail"]["errors"]
    assert len(errors) == 3 and all("required" in e for e in errors)
    assert client.put("/api/kb/faqs/missing", json=NEW_FAQ).status_code == 404
    assert client.delete("/api/kb/faqs/missing").status_code == 404
    assert client.post("/api/kb/clinic", json={}).status_code == 404   # the clinic is one form, not a list


def test_export_and_import_csv(client):
    exported = client.get("/api/kb/treatments/export.csv")
    assert exported.status_code == 200 and exported.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="treatments.csv"' in exported.headers["content-disposition"]
    text = exported.text.lstrip("﻿")
    assert text.splitlines()[0].startswith("id,name,short_name,aliases,price_min")

    edited = text.replace("4000,9000", "4100,9100")
    preview = client.post("/api/kb/treatments/import", json={"csv": edited, "dry_run": True}).json()
    assert preview["ok"] and preview["updated"] == ["root_canal"] and preview["dry_run"] is True
    assert "₹4,000" in ask(client, "how much is a root canal")["answer"]      # a preview changes nothing

    done = client.post("/api/kb/treatments/import", json={"csv": edited, "dry_run": False}).json()
    assert done["ok"] and "₹4,100" in ask(client, "how much is a root canal")["answer"]


def test_importing_a_broken_csv_is_refused(client):
    result = client.post("/api/kb/faqs/import", json={"csv": "id,question\nx,y\n", "dry_run": False}).json()
    assert result["ok"] is False and result["errors"]


def test_ask_shows_the_full_trace_and_saves_nothing(client):
    trace = ask(client, "How much does a root canal cost and which doctor does it?")
    assert set(trace) >= {"question", "understood", "retrieved", "context", "prompt", "generation", "answer", "parts",
                          "used_sources", "answerable", "decision", "reasons", "checks"}
    assert trace["understood"]["intents"] == ["treatment_price", "doctor_info"]
    assert [s["id"] for s in trace["retrieved"][:2]] == ["treatment:root_canal", "doctor:dr_rahul_kulkarni"]
    assert "[treatment:root_canal]" in trace["context"] and "ONLY the clinic information" in trace["prompt"]["system"]
    assert trace["generation"]["mode"] == "template" and "No AI model was called" in trace["generation"]["how"]
    assert client.get("/api/dashboard/stats").json()["total"] == 0


def test_questions_the_assistant_could_not_answer_are_listed_for_the_staff(client):
    for text in ("Do you have a wheelchair ramp?", "do you have a wheelchair ramp?", "What are your timings?",
                 "how much is a hair transplant and what are your timings"):
        client.post("/api/webhook/whatsapp", json={"phone": "919000000001", "text": text})
    questions = client.get("/api/kb/gaps").json()["questions"]
    # newest first; the duplicated question appears once (its most recent wording)
    assert [q["question"] for q in questions] == ["how much is a hair transplant and what are your timings", "do you have a wheelchair ramp?"]
    assert questions[0]["partial"] is True and questions[1]["partial"] is False   # duplicates are merged


def test_edits_are_backed_up_and_the_files_stay_readable(client, tmp_path):
    client.post("/api/kb/faqs", json=NEW_FAQ)
    assert list((tmp_path / "data" / "backups").glob("faqs-*.json"))
    text = (tmp_path / "data" / "faqs.json").read_text(encoding="utf-8")
    assert '"keywords": ["wheelchair", "step free"]' in text   # short lists stay on one line


def test_an_old_database_is_upgraded(tmp_path, monkeypatch):
    from backend import config, database

    old = tmp_path / "old.db"
    connection = sqlite3.connect(old)
    connection.executescript(database.SCHEMA.replace("    rag             TEXT NOT NULL DEFAULT '{}',   -- how the answer was built: sources used, parts, whether it was answerable\n", ""))
    connection.close()
    monkeypatch.setattr(config, "DATABASE_PATH", old)
    database.init_db()
    columns = {row[1] for row in sqlite3.connect(old).execute("PRAGMA table_info(inquiries)")}
    assert "rag" in columns


def test_command_line_trace(capsys):
    from backend import explain

    explain.main.__globals__["__name__"]  # the module imports cleanly
    text = explain.format_trace(explain.trace("How much does a root canal cost?"), show_prompt=True)
    assert "treatment:root_canal" in text and "USED" in text and "SOURCE REFERENCES" in text and "AUTO_SEND" in text
    nothing = explain.format_trace(explain.trace("Do you have a wheelchair ramp?"))
    assert "nothing relevant found" in nothing and "FORWARDED TO RECEPTION" in nothing
