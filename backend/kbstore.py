"""Reads, checks and writes the clinic knowledge base files (JSON or CSV).

Why this file exists: the clinic's information must be easy to change WITHOUT editing code.
There are three ways to do that, and they all end up here:

  1. the Knowledge Base page in the browser (forms; nothing to learn),
  2. a spreadsheet: export a CSV, edit it in Excel/Google Sheets, import it back,
  3. editing the files in data/ by hand (JSON or CSV - the app reads either).

Every write is checked first (so a typo cannot break the assistant) and the previous
version of the file is saved to data/backups/ so a change can always be undone.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from . import config

LIST_DATASETS = ("treatments", "doctors", "faqs")
DATASETS = ("clinic",) + LIST_DATASETS
FILE_BASENAME = {"clinic": "clinic_facts", "treatments": "treatments", "doctors": "doctors", "faqs": "faqs"}
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DUMMY_NOTICE = ('Contains DUMMY SAMPLE entries (marked "dummy": true). They are not real clinic '
                "information - replace them before real use.")
MAX_CSV_BYTES = 1_000_000
KEEP_BACKUPS = 20

# Each dataset: (field, type, required). Types are explained in _coerce().
FIELDS: dict[str, list[tuple[str, str, bool]]] = {
    "treatments": [
        ("id", "id", True), ("name", "str", True), ("short_name", "str", False), ("aliases", "list", True),
        ("price_min", "int", True), ("price_max", "int", True), ("price_unit", "str", True),
        ("price_notes", "str", False), ("variants", "variants", False), ("duration", "str", True),
        ("description", "str", True), ("handled_by", "list", False), ("dummy", "bool", False),
    ],
    "doctors": [
        ("id", "id", True), ("name", "str", True), ("title", "str", True), ("qualification", "str", True),
        ("specialties", "list", True), ("specialty_keywords", "list", False), ("experience_years", "int", True),
        ("languages", "list", True), ("available_days", "days", True), ("available_hours", "str", True),
        ("dummy", "bool", False),
    ],
    "faqs": [
        ("id", "id", True), ("question", "str", True), ("keywords", "list", True), ("answer", "str", True),
        ("dummy", "bool", False),
    ],
    "clinic": [
        ("clinic_name", "str", True), ("short_name", "str", True), ("tagline", "str", False),
        ("address", "str", True), ("landmark", "str", False), ("maps_link", "str", False), ("parking", "str", False),
        ("phone", "str", True), ("email", "str", False), ("timings", "timings", True), ("closed_note", "str", False),
        ("emergency_note", "str", False), ("payment_methods", "list", False), ("insurance_note", "str", False),
        ("languages", "list", False), ("appointment_policy", "str", False), ("dummy", "bool", False),
    ],
}
NAME_FIELD = {"treatments": "name", "doctors": "name", "faqs": "question"}

_lock = threading.RLock()


class KnowledgeBaseError(RuntimeError):
    """A data file is missing or broken. The message is written for a non-programmer."""


class ValidationFailed(Exception):
    """The information submitted has mistakes. `errors` is a list of plain-English messages."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class Dataset:
    name: str
    path: Path
    fmt: str          # "json" or "csv"
    data: Any         # list of records, or a dict for "clinic"


# --------------------------------------------------------------------------
# Finding files
# --------------------------------------------------------------------------
def find_file(dataset: str) -> tuple[Path, str]:
    """data/<name>.json if it exists, otherwise data/<name>.csv. (JSON wins if both exist.)"""
    base = config.DATA_DIR / FILE_BASENAME[dataset]
    for ext in (".json", ".csv"):
        if base.with_suffix(ext).exists():
            return base.with_suffix(ext), ext[1:]
    return base.with_suffix(".json"), "json"


# --------------------------------------------------------------------------
# Cleaning and checking values
# --------------------------------------------------------------------------
def _split_list(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"[|\n]", text) if p.strip()]


def _to_int(value: Any) -> Optional[int]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise ValueError("must be a number")
    if isinstance(value, (int, float)):
        number = value
    else:
        cleaned = re.sub(r"(?i)[₹,\s]|rs\.?|inr", "", str(value))
        try:
            number = float(cleaned)
        except ValueError:
            raise ValueError("must be a whole number (digits only)") from None
    if number != int(number) or number < 0:
        raise ValueError("must be a whole number, zero or more")
    return int(number)


def _parse_variants(value: Any) -> list[dict]:
    """[{"name","price_min","price_max"}] or the text form "Metal braces: 30000-50000 | Ceramic: 50000-80000"."""
    if isinstance(value, str):
        items = []
        for part in _split_list(value):
            match = re.match(r"^(.+?)\s*:\s*([\d,₹]+)\s*-\s*([\d,₹]+)$", part)
            if not match:
                raise ValueError(f'could not read "{part}" - use the form  Name: 30000-50000')
            items.append({"name": match.group(1), "price_min": match.group(2), "price_max": match.group(3)})
        value = items
    out = []
    for item in value or []:
        name = str(item.get("name", "")).strip()
        low, high = _to_int(item.get("price_min")), _to_int(item.get("price_max"))
        if not name:
            continue
        if low is None or high is None:
            raise ValueError(f'option "{name}" needs a minimum and a maximum price')
        if low > high:
            raise ValueError(f'option "{name}": the minimum price is higher than the maximum')
        out.append({"name": name, "price_min": low, "price_max": high})
    return out


def _parse_timings(value: Any) -> list[dict]:
    if isinstance(value, str):
        items = []
        for part in _split_list(value):
            if "=" not in part:
                raise ValueError(f'could not read "{part}" - use the form  Monday to Saturday = 10:00 AM to 8:00 PM')
            days, hours = part.split("=", 1)
            items.append({"days": days, "hours": hours})
        value = items
    out = [{"days": str(i.get("days", "")).strip(), "hours": str(i.get("hours", "")).strip()} for i in value or []]
    out = [i for i in out if i["days"] or i["hours"]]
    if any(not i["days"] or not i["hours"] for i in out):
        raise ValueError("each opening-hours row needs both the days and the hours")
    return out


def _parse_days(value: Any) -> list[str]:
    days = _split_list(value) if isinstance(value, str) else [str(v).strip() for v in value or [] if str(v).strip()]
    out = []
    for day in days:
        match = next((w for w in WEEKDAYS if w.lower() == day.lower() or w[:3].lower() == day[:3].lower()), None)
        if not match:
            raise ValueError(f'"{day}" is not a day of the week')
        out.append(match)
    return out


def _coerce(kind: str, value: Any) -> Any:
    if kind == "str":
        return "" if value is None else str(value).strip()
    if kind == "id":
        text = "" if value is None else str(value).strip().lower()
        if text and not re.fullmatch(r"[a-z0-9][a-z0-9_]*", text):
            raise ValueError("may only contain lowercase letters, numbers and underscores")
        return text
    if kind == "int":
        return _to_int(value)
    if kind == "list":
        if isinstance(value, str):
            return _split_list(value)
        return [str(v).strip() for v in value or [] if str(v).strip()]
    if kind == "bool":
        return value if isinstance(value, bool) else str(value or "").strip().lower() in ("1", "true", "yes", "y")
    if kind == "variants":
        return _parse_variants(value)
    if kind == "timings":
        return _parse_timings(value)
    if kind == "days":
        return _parse_days(value)
    raise ValueError(f"unknown field type {kind}")


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def normalize_record(dataset: str, raw: dict, label: str = "", need_id: bool = True) -> tuple[dict, list[str]]:
    """Clean one record and list its mistakes. Unknown extra fields are kept as they are."""
    errors: list[str] = []
    out: dict = {}
    for field, kind, required in FIELDS[dataset]:
        try:
            value = _coerce(kind, raw.get(field))
        except ValueError as exc:
            errors.append(f'{label}"{field}" {exc}')
            continue
        if required and _empty(value) and not (field == "id" and not need_id):
            errors.append(f'{label}"{field}" is required')
        if kind == "bool":
            if value:
                out[field] = True
        elif not _empty(value) or required:
            out[field] = value
    for key, value in raw.items():
        if key not in out and key not in {f for f, _, _ in FIELDS[dataset]} and not key.startswith("_"):
            out[key] = value
    if dataset == "treatments":
        if out.get("short_name", "") == "":
            out["short_name"] = out.get("name", "")
        low, high = out.get("price_min"), out.get("price_max")
        if low is not None and high is not None and low > high:
            errors.append(f'{label}"price_min" is higher than "price_max"')
    return out, errors


def _label(dataset: str, raw: dict, index: int) -> str:
    name = raw.get(NAME_FIELD.get(dataset, "name")) or raw.get("id") or ""
    return f'{dataset[:-1] if dataset.endswith("s") else dataset} #{index + 1}{f" ({name})" if name else ""}: '


def normalize_dataset(dataset: str, data: Any) -> tuple[Any, list[str]]:
    errors: list[str] = []
    if dataset == "clinic":
        record, errs = normalize_record("clinic", data, "clinic information: ", need_id=False)
        return record, errs
    records, seen = [], set()
    for i, raw in enumerate(data):
        record, errs = normalize_record(dataset, raw, _label(dataset, raw, i))
        errors += errs
        rid = record.get("id")
        if rid in seen:
            errors.append(f'{_label(dataset, raw, i)}the id "{rid}" is used twice - every id must be unique')
        seen.add(rid)
        records.append(record)
    return records, errors


# --------------------------------------------------------------------------
# JSON and CSV files
# --------------------------------------------------------------------------
def _json_text(value: Any, level: int = 0) -> str:
    """Pretty JSON that keeps short lists on one line, so the files stay readable."""
    pad = "  " * level
    if isinstance(value, dict):
        if not value:
            return "{}"
        rows = [f'{pad}  {json.dumps(k, ensure_ascii=False)}: {_json_text(v, level + 1)}' for k, v in value.items()]
        return "{\n" + ",\n".join(rows) + f"\n{pad}}}"
    if isinstance(value, list):
        if not value:
            return "[]"
        if all(not isinstance(x, (dict, list)) for x in value):
            inline = "[" + ", ".join(json.dumps(x, ensure_ascii=False) for x in value) + "]"
            if len(inline) <= 96:
                return inline
        if all(isinstance(x, dict) and all(not isinstance(v, (dict, list)) for v in x.values()) for x in value):
            rows = ["{ " + ", ".join(f'{json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)}'
                                      for k, v in x.items()) + " }" for x in value]
            if all(len(r) <= 110 for r in rows):
                return "[\n" + ",\n".join(f"{pad}  {r}" for r in rows) + f"\n{pad}]"
        return "[\n" + ",\n".join(f"{pad}  {_json_text(x, level + 1)}" for x in value) + f"\n{pad}]"
    return json.dumps(value, ensure_ascii=False)


def _cell(kind: str, value: Any) -> str:
    if kind == "list" or kind == "days":
        return " | ".join(value or [])
    if kind == "variants":
        return " | ".join(f"{v['name']}: {v['price_min']}-{v['price_max']}" for v in value or [])
    if kind == "timings":
        return " | ".join(f"{t['days']} = {t['hours']}" for t in value or [])
    if kind == "bool":
        return "yes" if value else "no"
    return "" if value is None else str(value)


def to_csv(dataset: str, data: Any) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    kinds = {f: k for f, k, _ in FIELDS[dataset]}
    if dataset == "clinic":
        writer.writerow(["key", "value"])
        for field, kind, _ in FIELDS["clinic"]:
            writer.writerow([field, _cell(kind, data.get(field))])
    else:
        fields = [f for f, _, _ in FIELDS[dataset]]
        writer.writerow(fields)
        for record in data:
            writer.writerow([_cell(kinds[f], record.get(f)) for f in fields])
    return out.getvalue()


def from_csv(dataset: str, text: str) -> tuple[Any, list[str]]:
    """Read CSV text into raw records. Returns (records, warnings)."""
    text = text.lstrip("﻿")
    if len(text.encode("utf-8")) > MAX_CSV_BYTES:
        raise KnowledgeBaseError("The CSV file is too large (limit 1 MB).")
    first_line = text.splitlines()[0] if text.strip() else ""
    delimiter = max([",", ";", "\t"], key=first_line.count)
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise KnowledgeBaseError("The CSV file is empty.")
    header = [h.strip().lower() for h in rows[0]]
    warnings: list[str] = []
    known = {f for f, _, _ in FIELDS[dataset]}

    if dataset == "clinic":
        if header[:2] != ["key", "value"]:
            raise KnowledgeBaseError('The first row of the clinic CSV must be:  key,value')
        record = {}
        for row in rows[1:]:
            key = row[0].strip().lower()
            if key not in known:
                warnings.append(f'Ignored the unknown row "{key}".')
                continue
            record[key] = row[1] if len(row) > 1 else ""
        return record, warnings

    unknown = [h for h in header if h and h not in known]
    if unknown:
        warnings.append("Ignored unknown columns: " + ", ".join(unknown))
    missing = [f for f, _, req in FIELDS[dataset] if req and f not in header]
    if missing:
        raise KnowledgeBaseError("The CSV is missing these columns: " + ", ".join(missing))
    records = [{h: (row[i] if i < len(row) else "") for i, h in enumerate(header) if h in known} for row in rows[1:]]
    return records, warnings


def _read_raw(dataset: str, path: Path, fmt: str) -> Any:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise KnowledgeBaseError(f"Missing knowledge-base file: data/{path.name}") from None
    if fmt == "csv":
        try:
            return from_csv(dataset, text)[0]
        except KnowledgeBaseError as exc:
            raise KnowledgeBaseError(f"data/{path.name}: {exc}") from None
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise KnowledgeBaseError(
            f"data/{path.name} is not valid JSON (line {exc.lineno}, column {exc.colno}): {exc.msg}") from None
    if dataset == "clinic":
        if not isinstance(raw, dict):
            raise KnowledgeBaseError(f"data/{path.name} must contain one object with the clinic details.")
        return {k: v for k, v in raw.items() if not k.startswith("_")}
    try:
        return raw[dataset]
    except (KeyError, TypeError):
        raise KnowledgeBaseError(
            f'data/{path.name} must have a top-level list called "{dataset}". Compare it with the sample file.') from None


def read_dataset(dataset: str) -> Dataset:
    """Load, clean and check one dataset. Raises KnowledgeBaseError with a friendly message."""
    path, fmt = find_file(dataset)
    data, errors = normalize_dataset(dataset, _read_raw(dataset, path, fmt))
    if errors:
        shown = "\n  - ".join(errors[:6])
        more = f"\n  ...and {len(errors) - 6} more" if len(errors) > 6 else ""
        raise KnowledgeBaseError(f"data/{path.name} has problems:\n  - {shown}{more}")
    return Dataset(dataset, path, fmt, data)


def _any_dummy(dataset: str, data: Any) -> bool:
    return bool(data.get("dummy")) if dataset == "clinic" else any(r.get("dummy") for r in data)


def _render(dataset: str, data: Any, fmt: str) -> str:
    if fmt == "csv":
        return to_csv(dataset, data)
    body: dict = {}
    if _any_dummy(dataset, data):
        body["_notice"] = DUMMY_NOTICE
    if dataset == "clinic":
        body.update(data)
    else:
        body[dataset] = data
    return _json_text(body) + "\n"


def _backup(path: Path) -> None:
    if not path.exists():
        return
    folder = config.DATA_DIR / "backups"
    folder.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    (folder / f"{path.stem}-{stamp}{path.suffix}").write_bytes(path.read_bytes())
    old = sorted(folder.glob(f"{path.stem}-*{path.suffix}"))
    for stale in old[:-KEEP_BACKUPS]:
        stale.unlink()


def write_dataset(dataset: str, data: Any) -> Path:
    """Check and save a dataset (keeps the file's format). Raises ValidationFailed."""
    data, errors = normalize_dataset(dataset, data)
    if errors:
        raise ValidationFailed(errors)
    with _lock:
        path, fmt = find_file(dataset)
        text = _render(dataset, data, fmt)
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _backup(path)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8-sig" if fmt == "csv" else "utf-8", newline="\n")
        os.replace(tmp, path)
    return path


# --------------------------------------------------------------------------
# Adding, changing and removing entries
# --------------------------------------------------------------------------
def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "entry"


def create_record(dataset: str, raw: dict) -> dict:
    with _lock:
        records = read_dataset(dataset).data
        record, errors = normalize_record(dataset, raw, need_id=False)
        if errors:
            raise ValidationFailed(errors)
        existing = {r["id"] for r in records}
        if not record.get("id"):
            base = _slug(re.sub(r"(?i)^dr\.?\s+", "", record.get(NAME_FIELD[dataset], "")))
            record["id"], n = base, 2
            while record["id"] in existing:
                record["id"], n = f"{base}_{n}", n + 1
        elif record["id"] in existing:
            raise ValidationFailed([f'An entry with the id "{record["id"]}" already exists.'])
        write_dataset(dataset, records + [record])
        return record


def update_record(dataset: str, record_id: str, raw: dict) -> dict:
    with _lock:
        records = read_dataset(dataset).data
        index = next((i for i, r in enumerate(records) if r["id"] == record_id), None)
        if index is None:
            raise KeyError(record_id)
        record, errors = normalize_record(dataset, {**raw, "id": record_id})
        if errors:
            raise ValidationFailed(errors)
        records[index] = record
        write_dataset(dataset, records)
        return record


def delete_record(dataset: str, record_id: str) -> list[str]:
    """Remove an entry. Returns notes about anything tidied up as a result."""
    with _lock:
        records = read_dataset(dataset).data
        kept = [r for r in records if r["id"] != record_id]
        if len(kept) == len(records):
            raise KeyError(record_id)
        notes: list[str] = []
        if dataset == "doctors":  # don't leave treatments pointing at a doctor who no longer exists
            treatments = read_dataset("treatments").data
            changed = [t for t in treatments if record_id in t.get("handled_by", [])]
            for t in changed:
                t["handled_by"] = [d for d in t["handled_by"] if d != record_id]
            if changed:
                write_dataset("treatments", treatments)
                notes.append(f"Removed this doctor from {len(changed)} treatment(s).")
        write_dataset(dataset, kept)
        return notes


def save_clinic(raw: dict) -> dict:
    with _lock:
        record, errors = normalize_record("clinic", raw, "clinic information: ", need_id=False)
        if errors:
            raise ValidationFailed(errors)
        write_dataset("clinic", record)
        return record


# --------------------------------------------------------------------------
# CSV import / export
# --------------------------------------------------------------------------
def export_csv(dataset: str) -> str:
    return to_csv(dataset, read_dataset(dataset).data)


def import_csv(dataset: str, text: str, dry_run: bool = True) -> dict:
    """Replace a dataset with the contents of a CSV. With dry_run=True nothing is saved."""
    try:
        raw, warnings = from_csv(dataset, text)
    except KnowledgeBaseError as exc:
        return {"ok": False, "errors": [str(exc)], "warnings": []}
    data, errors = normalize_dataset(dataset, raw)
    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings}
    with _lock:
        current = read_dataset(dataset).data
        if dataset == "clinic":
            report = {"added": [], "updated": ["clinic information"] if data != current else [], "removed": []}
        else:
            before, after = {r["id"]: r for r in current}, {r["id"]: r for r in data}
            report = {
                "added": [i for i in after if i not in before],
                "updated": [i for i in after if i in before and after[i] != before[i]],
                "removed": [i for i in before if i not in after],
            }
        if not dry_run:
            write_dataset(dataset, data)
    return {"ok": True, "errors": [], "warnings": warnings, "dry_run": dry_run, **report}


# --------------------------------------------------------------------------
# Gentle warnings (things that are allowed but probably a mistake)
# --------------------------------------------------------------------------
def check_all() -> list[dict]:
    """Cross-checks between datasets. Returns [{"level","dataset","id","message"}]."""
    issues: list[dict] = []

    def add(dataset: str, rid: str, message: str) -> None:
        issues.append({"level": "warning", "dataset": dataset, "id": rid, "message": message})

    treatments, doctors, faqs = (read_dataset(n).data for n in LIST_DATASETS)
    doctor_ids = {d["id"] for d in doctors}
    handled = {i for t in treatments for i in t.get("handled_by", [])}
    seen_alias: dict[str, str] = {}
    for t in treatments:
        for doc in t.get("handled_by", []):
            if doc not in doctor_ids:
                add("treatments", t["id"], f'"{t["name"]}" is handled by "{doc}", who is not in the doctors list.')
        if not t.get("handled_by"):
            add("treatments", t["id"], f'"{t["name"]}" has no doctor assigned, so "who does this?" cannot be answered.')
        for alias in t["aliases"]:
            owner = seen_alias.setdefault(alias.lower(), t["id"])
            if owner != t["id"]:
                add("treatments", t["id"], f'The name "{alias}" is used by both "{owner}" and "{t["id"]}".')
    for d in doctors:
        if d["id"] not in handled:
            add("doctors", d["id"], f'{d["name"]} is not assigned to any treatment.')
    for f in faqs:
        if len(f["keywords"]) < 2:
            add("faqs", f["id"], f'"{f["question"]}" has few keywords; add more phrases patients might type.')
    return issues
