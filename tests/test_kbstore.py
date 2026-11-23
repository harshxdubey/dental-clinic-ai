"""Reading, checking and writing the knowledge base files (JSON and CSV)."""
import json

import pytest

from backend import config, kbstore, knowledge
from backend.kbstore import KnowledgeBaseError, ValidationFailed

NEW_FAQ = {"question": "Do you have wheelchair access?", "keywords": ["wheelchair", "step free"],
           "answer": "Yes, there is a ramp at the entrance.", "dummy": True}
NEW_TREATMENT = {"name": "Gum Treatment", "aliases": ["gum treatment", "gum care"], "price_min": 2000, "price_max": 5000,
                 "price_unit": "per session", "duration": "30 minutes", "description": "Care for healthy gums."}


def path(name):
    return config.DATA_DIR / name


# ---------------- reading ----------------
def test_loads_all_sample_data_as_entries():
    kb = knowledge.load()
    assert len(kb["treatments"]) >= 10 and len(kb["doctors"]) == 5 and len(kb["faqs"]) >= 10
    ids = {e.id for e in kb["entries"]}
    assert {"treatment:root_canal", "doctor:dr_neha_joshi", "faq:walk_in", "clinic:timings", "clinic:location"} <= ids
    assert kb["dummy_entries"] == len(kb["treatments"]) + len(kb["doctors"]) + len(kb["faqs"]) + 1


def test_a_broken_json_file_gives_a_friendly_message():
    path("faqs.json").write_text('{"faqs": [ {"id": "x" ]}', encoding="utf-8")
    with pytest.raises(KnowledgeBaseError, match=r"faqs.json is not valid JSON \(line 1"):
        knowledge.load()


def test_a_missing_required_field_is_explained():
    data = json.loads(path("treatments.json").read_text(encoding="utf-8"))
    del data["treatments"][0]["price_min"]
    path("treatments.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(KnowledgeBaseError, match='"price_min" is required'):
        knowledge.load()


# ---------------- add / change / delete ----------------
def test_create_faq_generates_an_id_and_is_used_immediately():
    record = kbstore.create_record("faqs", NEW_FAQ)
    assert record["id"] == "do_you_have_wheelchair_access"
    assert "faq:do_you_have_wheelchair_access" in knowledge.load()["entries_by_id"]


def test_create_treatment_normalises_values():
    record = kbstore.create_record("treatments", {**NEW_TREATMENT, "price_min": "₹2,000", "price_max": "5000", "aliases": "gum treatment\ngum care"})
    assert (record["price_min"], record["price_max"], record["aliases"]) == (2000, 5000, ["gum treatment", "gum care"])
    assert record["short_name"] == "Gum Treatment" and record["id"] == "gum_treatment"


def test_ids_are_made_unique():
    first = kbstore.create_record("faqs", NEW_FAQ)
    second = kbstore.create_record("faqs", NEW_FAQ)
    assert first["id"] != second["id"] and second["id"].endswith("_2")


def test_update_keeps_the_id_and_changes_the_content():
    updated = kbstore.update_record("treatments", "root_canal", {**knowledge.load()["treatments_by_id"]["root_canal"], "price_min": 5000})
    assert updated["id"] == "root_canal" and knowledge.load()["treatments_by_id"]["root_canal"]["price_min"] == 5000
    assert "₹5,000" in knowledge.load()["entries_by_id"]["treatment:root_canal"].text


def test_update_of_missing_entry_raises():
    with pytest.raises(KeyError):
        kbstore.update_record("faqs", "nope", NEW_FAQ)


def test_delete_a_doctor_also_removes_the_references():
    notes = kbstore.delete_record("doctors", "dr_neha_joshi")
    assert notes and "treatment" in notes[0]
    kb = knowledge.load()
    assert "dr_neha_joshi" not in kb["doctors_by_id"]
    assert all("dr_neha_joshi" not in t.get("handled_by", []) for t in kb["treatments"])


def test_save_clinic_changes_the_phone_number():
    clinic = dict(knowledge.load()["clinic"], phone="+91 98765 43210")
    kbstore.save_clinic(clinic)
    assert "98765" in knowledge.load()["entries_by_id"]["clinic:contact"].text


# ---------------- validation ----------------
@pytest.mark.parametrize("dataset,record,message", [
    ("faqs", {"question": "", "keywords": ["a"], "answer": "x"}, '"question" is required'),
    ("faqs", {"question": "Q?", "keywords": [], "answer": "x"}, '"keywords" is required'),
    ("treatments", {**NEW_TREATMENT, "price_min": "abc"}, "whole number"),
    ("treatments", {**NEW_TREATMENT, "price_min": 9000, "price_max": 1000}, "higher than"),
    ("treatments", {**NEW_TREATMENT, "variants": "Metal braces: 50000-30000"}, "minimum price is higher"),
    ("doctors", {"name": "Dr X", "title": "t", "qualification": "q", "specialties": ["s"], "experience_years": 3,
                 "languages": ["English"], "available_days": ["Funday"], "available_hours": "9 to 5"}, "not a day of the week"),
    ("faqs", {**NEW_FAQ, "id": "Bad Id!"}, "lowercase letters"),
    ("faqs", {**NEW_FAQ, "id": "walk_in"}, "already exists"),
])
def test_mistakes_are_rejected_with_a_plain_message(dataset, record, message):
    with pytest.raises(ValidationFailed) as error:
        kbstore.create_record(dataset, record)
    assert message in " ".join(error.value.errors)


def test_a_rejected_change_does_not_touch_the_file():
    before = path("faqs.json").read_text(encoding="utf-8")
    with pytest.raises(ValidationFailed):
        kbstore.create_record("faqs", {"question": "", "keywords": [], "answer": ""})
    assert path("faqs.json").read_text(encoding="utf-8") == before


def test_clinic_needs_opening_hours():
    with pytest.raises(ValidationFailed, match="timings"):
        kbstore.save_clinic({**knowledge.load()["clinic"], "timings": []})


# ---------------- dummy flags and backups ----------------
def test_dummy_flag_is_only_written_when_true_and_notice_follows():
    faqs = [{k: v for k, v in r.items() if k != "dummy"} for r in kbstore.read_dataset("faqs").data]
    kbstore.write_dataset("faqs", faqs)
    text = path("faqs.json").read_text(encoding="utf-8")
    assert "dummy" not in text and "_notice" not in text   # nothing is sample data any more
    kbstore.create_record("faqs", NEW_FAQ)
    assert '"_notice"' in path("faqs.json").read_text(encoding="utf-8")


def test_every_write_keeps_a_backup_of_the_previous_version():
    kbstore.create_record("faqs", NEW_FAQ)
    backups = list((config.DATA_DIR / "backups").glob("faqs-*.json"))
    assert len(backups) == 1 and "wheelchair" not in backups[0].read_text(encoding="utf-8")


def test_old_backups_are_pruned():
    for i in range(kbstore.KEEP_BACKUPS + 5):
        kbstore.create_record("faqs", {**NEW_FAQ, "question": f"Question {i}?"})
    assert len(list((config.DATA_DIR / "backups").glob("faqs-*.json"))) == kbstore.KEEP_BACKUPS


# ---------------- CSV ----------------
@pytest.mark.parametrize("dataset", kbstore.DATASETS)
def test_csv_round_trip_changes_nothing(dataset):
    text = kbstore.export_csv(dataset)
    report = kbstore.import_csv(dataset, text, dry_run=True)
    assert report["ok"], report["errors"]
    assert (report["added"], report["updated"], report["removed"]) == ([], [], [])


def test_edit_a_price_in_the_spreadsheet_and_import():
    text = kbstore.export_csv("treatments").replace("4000,9000", "4500,9500")
    preview = kbstore.import_csv("treatments", text, dry_run=True)
    assert preview["updated"] == ["root_canal"]
    assert knowledge.load()["treatments_by_id"]["root_canal"]["price_min"] == 4000   # a preview changes nothing
    kbstore.import_csv("treatments", text, dry_run=False)
    assert knowledge.load()["treatments_by_id"]["root_canal"]["price_min"] == 4500


def test_importing_reports_added_and_removed_rows():
    lines = kbstore.export_csv("faqs").splitlines()
    removed_id = lines[1].split(",")[0]
    text = "\n".join(lines[:1] + lines[2:] + ['new_one,"A new question?",new phrase,"A new answer.",no']) + "\n"
    report = kbstore.import_csv("faqs", text, dry_run=True)
    assert report["added"] == ["new_one"] and report["removed"] == [removed_id]


def test_bad_csv_is_reported_and_nothing_is_changed():
    before = path("faqs.json").read_text(encoding="utf-8")
    report = kbstore.import_csv("faqs", "id,question\nx,Only two columns\n", dry_run=False)
    assert not report["ok"] and "missing these columns" in report["errors"][0]
    bad_price = kbstore.export_csv("treatments").replace("4000,9000", "cheap,9000")
    assert not kbstore.import_csv("treatments", bad_price, dry_run=False)["ok"]
    assert path("faqs.json").read_text(encoding="utf-8") == before


def test_excel_style_csv_is_accepted():
    """European Excel saves CSV with semicolons and a byte-order mark. Both must work."""
    import csv
    import io

    rows = list(csv.reader(io.StringIO(kbstore.export_csv("faqs"))))
    rows.append(["parking_bikes", "Is there bike parking?", "bike parking | two wheeler", "Yes, in front of the building.", "no"])
    out = io.StringIO()
    csv.writer(out, delimiter=";", lineterminator="\n").writerows(rows)

    report = kbstore.import_csv("faqs", "\ufeff" + out.getvalue(), dry_run=True)
    assert report["ok"], report["errors"]
    assert (report["added"], report["updated"], report["removed"]) == (["parking_bikes"], [], [])


def test_the_app_can_run_from_csv_files_alone():
    """Requirement: read the clinic information from JSON *or* CSV."""
    for name in ("clinic", "treatments", "doctors", "faqs"):
        csv_text = kbstore.export_csv(name)
        path(kbstore.FILE_BASENAME[name] + ".json").unlink()
        path(kbstore.FILE_BASENAME[name] + ".csv").write_text(csv_text, encoding="utf-8")
    kb = knowledge.load()
    assert kb["files"] == {"clinic": "clinic_facts.csv", "treatments": "treatments.csv", "doctors": "doctors.csv", "faqs": "faqs.csv"}
    assert "treatment:root_canal" in kb["entries_by_id"] and kb["entries_by_id"]["clinic:timings"].text

    # edits are saved back in the same (CSV) format, and are used straight away
    kbstore.create_record("faqs", NEW_FAQ)
    assert not path("faqs.json").exists() and "wheelchair" in path("faqs.csv").read_text(encoding="utf-8-sig")
    from backend.pipeline import analyze
    assert analyze("do you have wheelchair access").draft.used_source_ids == ["faq:do_you_have_wheelchair_access"]


# ---------------- gentle warnings ----------------
def test_check_all_flags_probable_mistakes():
    treatments = kbstore.read_dataset("treatments").data
    treatments[0]["handled_by"] = ["dr_nobody"]
    kbstore.write_dataset("treatments", treatments)
    messages = " ".join(i["message"] for i in kbstore.check_all())
    assert "dr_nobody" in messages
