"""Loads the clinic knowledge base and turns it into "entries" the retriever can search.

The raw files (JSON or CSV, see kbstore.py) hold four kinds of information:
treatments (prices), doctors, FAQs and general clinic facts (timings, address, ...).
Each treatment, doctor, FAQ and clinic fact becomes one *entry* with a stable id such as
`treatment:root_canal` or `clinic:timings`. Those ids are the "internal source references"
shown to the receptionist.

The same formatting functions are used to build the text the AI is allowed to quote and to
write template answers, so every number in an answer traces back to its source.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from . import config, kbstore
from .kbstore import KnowledgeBaseError  # noqa: F401  (re-exported for other modules)

SYNONYMS_FILE = "synonyms.json"
_cache: dict = {"stamp": None, "kb": None}

CLINIC_DEFAULTS = {
    "tagline": "", "landmark": "", "maps_link": "", "parking": "", "email": "", "closed_note": "",
    "emergency_note": "", "payment_methods": [], "insurance_note": "", "languages": [],
    "appointment_policy": "", "dummy": False,
}


@dataclass
class Entry:
    id: str          # e.g. "treatment:root_canal"
    kind: str        # treatment | doctor | faq | clinic
    title: str
    text: str        # the facts (the only text the AI may quote)
    file: str        # e.g. "treatments.json"
    keywords: list = field(default_factory=list)
    data: dict = field(default_factory=dict, repr=False)
    dummy: bool = False


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------
def format_inr(amount: int) -> str:
    """Indian digit grouping: 4000 -> '₹4,000', 200000 -> '₹2,00,000'."""
    digits = str(int(amount))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups + [tail])
    return "₹" + digits


def format_price_range(low: int, high: int) -> str:
    return format_inr(low) if low == high else f"{format_inr(low)} – {format_inr(high)}"


def treatment_price_text(treatment: dict) -> str:
    return f"{format_price_range(treatment['price_min'], treatment['price_max'])} {treatment['price_unit']}"


def timings_lines(clinic: dict) -> list[str]:
    return [f"{row['days']}: {row['hours']}" for row in clinic["timings"]]


_PATIENT_DOCTOR = re.compile(r"\b(dr|doctor)\.?\s+([a-z][a-z'’-]{2,})", re.IGNORECASE)
_NOT_A_NAME = frozenset("""is are was the a an any available availability appointment appointments timing timings today tomorrow
    tonight please kaun kya hai hain ka ki ke ko se who what when where which does do can will would may near nearby
    visit visits consultation specialist dentist doctor""".split())


def unknown_doctor_mentions(text: str, kb: dict) -> list[str]:
    """Doctors the PATIENT names ("Is Dr. Sharma available?") who do not work at this clinic.

    A name counts as known if it is any word of a real doctor's name (so "Dr. Neha" and "Dr. Joshi" are both fine).
    "doctor kaun hai" or "Dr. appointment" name nobody, so they are ignored.
    """
    known = {w for d in kb["doctors"] for w in re.split(r"\W+", d["name"].lower()) if w and w != "dr"}
    unknown = []
    for match in _PATIENT_DOCTOR.finditer(text):
        prefix, name = match.group(1), match.group(2)
        word = name.lower()
        # "Dr. Sharma" is a name in any case. "doctor handles children" is not: after the word "doctor" only a
        # Capitalised word is taken as a name (and never in a message typed in capitals).
        if prefix.lower() == "doctor" and (not name[0].isupper() or text.isupper()):
            continue
        if word in _NOT_A_NAME or word in known:
            continue
        unknown.append(f"Dr. {name.capitalize()}")
    return list(dict.fromkeys(unknown))


def doctor_availability(doctor: dict) -> str:
    return f"{', '.join(doctor['available_days'])}, {doctor['available_hours']}"


def treatment_doctors(treatment: dict, kb: dict) -> list[dict]:
    return [kb["doctors_by_id"][i] for i in treatment.get("handled_by", []) if i in kb["doctors_by_id"]]


def describe_treatment(treatment: dict, kb: dict) -> str:
    """Plain-text description of a treatment (this is what the AI is allowed to quote)."""
    parts = [f"{treatment['name']}: {treatment_price_text(treatment)}."]
    if treatment.get("variants"):
        options = "; ".join(
            f"{v['name']} {format_price_range(v['price_min'], v['price_max'])}" for v in treatment["variants"]
        )
        parts.append(f"Options: {options}.")
    if treatment.get("price_notes"):
        parts.append(treatment["price_notes"])
    parts.append(treatment["description"])
    parts.append(f"Typical duration: {treatment['duration']}.")
    doctors = treatment_doctors(treatment, kb)
    if doctors:
        parts.append("Handled by: " + ", ".join(d["name"] for d in doctors) + ".")
    return " ".join(parts)


def describe_doctor(doctor: dict) -> str:
    parts = [f"{doctor['name']}, {doctor['title']}. {doctor['qualification']}.",
             f"{doctor['experience_years']} years of experience.",
             f"Specialties: {', '.join(doctor['specialties'])}.",
             f"Available: {doctor_availability(doctor)}."]
    if doctor.get("languages"):
        parts.append(f"Languages: {', '.join(doctor['languages'])}.")
    return " ".join(parts)


def describe_timings(clinic: dict) -> str:
    return ("Clinic hours - " + "; ".join(timings_lines(clinic)) + ". " + clinic.get("closed_note", "")).strip()


def describe_location(clinic: dict) -> str:
    parts = [f"Address: {clinic['address']}."]
    if clinic.get("landmark"):
        parts.append(f"Landmark: {clinic['landmark']}.")
    if clinic.get("maps_link"):
        parts.append(f"Google Maps: {clinic['maps_link']}.")
    if clinic.get("parking"):
        parts.append(f"Parking: {clinic['parking']}")
    return " ".join(parts)


def describe_contact(clinic: dict) -> str:
    parts = [f"Phone: {clinic['phone']}."]
    if clinic.get("email"):
        parts.append(f"Email: {clinic['email']}.")
    return " ".join(parts)


def describe_payment(clinic: dict) -> str:
    parts = []
    if clinic.get("payment_methods"):
        parts.append("Payment methods: " + ", ".join(clinic["payment_methods"]) + ".")
    if clinic.get("insurance_note"):
        parts.append(clinic["insurance_note"])
    return " ".join(parts)


# --------------------------------------------------------------------------
# Entries
# --------------------------------------------------------------------------
# Words that help a question find each general clinic fact (these are about what the fact IS,
# not about the clinic, so they are part of the program rather than the data).
_CLINIC_HINTS = {
    "timings": ("Clinic hours", ["opening hours", "timings", "open", "close", "holiday", "sunday", "saturday"]),
    "location": ("Address & directions", ["address", "directions", "map", "parking", "landmark", "where"]),
    "contact": ("Contact details", ["phone number", "call", "email", "contact", "reach us"]),
    "payment": ("Payments & insurance", ["payment", "upi", "card", "cash", "insurance", "cashless", "pay"]),
    "policy": ("Appointment policy", ["appointment", "booking", "cancel", "reschedule", "arrive early"]),
    "emergency": ("Emergency guidance", ["emergency", "bleeding", "swelling", "accident", "urgent"]),
}


def _clinic_entries(clinic: dict, file: str) -> list[Entry]:
    texts = {
        "timings": describe_timings(clinic),
        "location": describe_location(clinic),
        "contact": describe_contact(clinic),
        "payment": describe_payment(clinic),
        "policy": clinic.get("appointment_policy", ""),
        "emergency": clinic.get("emergency_note", ""),
    }
    return [
        Entry(id=f"clinic:{key}", kind="clinic", title=_CLINIC_HINTS[key][0], text=text, file=file,
              keywords=_CLINIC_HINTS[key][1], data=clinic, dummy=bool(clinic.get("dummy")))
        for key, text in texts.items() if text
    ]


def build_entries(kb: dict) -> list[Entry]:
    files = kb["files"]
    entries: list[Entry] = []
    for t in kb["treatments"]:
        entries.append(Entry(f"treatment:{t['id']}", "treatment", t["name"], describe_treatment(t, kb),
                             files["treatments"], list(t["aliases"]), t, bool(t.get("dummy"))))
    for d in kb["doctors"]:
        entries.append(Entry(f"doctor:{d['id']}", "doctor", d["name"], describe_doctor(d),
                             files["doctors"], list(d.get("specialty_keywords", [])) + list(d["specialties"]), d,
                             bool(d.get("dummy"))))
    for f in kb["faqs"]:
        entries.append(Entry(f"faq:{f['id']}", "faq", f["question"], f["answer"],
                             files["faqs"], list(f["keywords"]), f, bool(f.get("dummy"))))
    entries += _clinic_entries(kb["clinic"], files["clinic"])
    return entries


def _read_synonyms() -> list[list[str]]:
    path = config.DATA_DIR / SYNONYMS_FILE
    if not path.exists():
        return []
    try:
        groups = json.loads(path.read_text(encoding="utf-8"))["groups"]
        return [[str(w) for w in g] for g in groups if isinstance(g, list)]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise KnowledgeBaseError(f'data/{SYNONYMS_FILE} is not valid: it must look like {{"groups": [["price", "cost"]]}} ({exc})') from None


def load() -> dict:
    """Return the knowledge base. Files are re-read automatically when they change."""
    syn_path = config.DATA_DIR / SYNONYMS_FILE
    paths = [kbstore.find_file(name)[0] for name in kbstore.DATASETS] + [syn_path]
    stamp = tuple((str(p), p.stat().st_mtime_ns if p.exists() else 0) for p in paths)
    if _cache["stamp"] == stamp and _cache["kb"] is not None:
        return _cache["kb"]

    datasets = {name: kbstore.read_dataset(name) for name in kbstore.DATASETS}
    kb = {
        "clinic": {**CLINIC_DEFAULTS, **datasets["clinic"].data},
        "treatments": datasets["treatments"].data,
        "doctors": datasets["doctors"].data,
        "faqs": datasets["faqs"].data,
        "files": {name: ds.path.name for name, ds in datasets.items()},
        "synonyms": _read_synonyms(),
    }
    kb["treatments_by_id"] = {t["id"]: t for t in kb["treatments"]}
    kb["doctors_by_id"] = {d["id"]: d for d in kb["doctors"]}
    kb["entries"] = build_entries(kb)
    kb["entries_by_id"] = {e.id: e for e in kb["entries"]}
    kb["dummy_entries"] = (sum(1 for name in kbstore.LIST_DATASETS for r in kb[name] if r.get("dummy"))
                           + (1 if kb["clinic"].get("dummy") else 0))
    _cache.update(stamp=stamp, kb=kb)
    return kb
