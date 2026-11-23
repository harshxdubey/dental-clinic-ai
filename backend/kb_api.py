"""API behind the Knowledge Base page: add, change and remove clinic information without touching code."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import database as db
from . import explain, kbstore, knowledge

router = APIRouter(prefix="/api/kb", tags=["Knowledge base"])

LABELS = {"clinic": "Clinic info", "treatments": "Treatments", "doctors": "Doctors", "faqs": "FAQs"}


class AskBody(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)


class ImportBody(BaseModel):
    csv: str = Field(..., max_length=kbstore.MAX_CSV_BYTES)
    dry_run: bool = True


def _dataset(name: str) -> str:
    if name not in kbstore.DATASETS:
        raise HTTPException(status_code=404, detail=f"Unknown dataset '{name}'.")
    return name


def _list_dataset(name: str) -> str:
    if _dataset(name) not in kbstore.LIST_DATASETS:
        raise HTTPException(status_code=404, detail="This dataset is a single form, not a list of entries.")
    return name


@router.get("/summary")
def summary() -> dict:
    items = []
    for name in kbstore.DATASETS:
        ds = kbstore.read_dataset(name)
        if name == "clinic":
            count, dummy = 1, 1 if ds.data.get("dummy") else 0
        else:
            count, dummy = len(ds.data), sum(1 for r in ds.data if r.get("dummy"))
        items.append({"name": name, "label": LABELS[name], "file": ds.path.name, "format": ds.fmt,
                      "count": count, "dummy_count": dummy})
    return {"datasets": items, "issues": kbstore.check_all(), "dummy_entries": knowledge.load()["dummy_entries"]}


@router.get("/gaps")
def gaps() -> dict:
    """Recent patient questions the knowledge base could not (fully) answer - things worth adding."""
    seen, out = set(), []
    for row in db.list_inquiries("all", 300):
        rag = row.get("rag") or {}
        if rag.get("kind") in ("non_text", "error"):
            continue   # a voice note or a crash is not a gap in the clinic's information
        if rag.get("answerable") is False or rag.get("partial"):
            key = row["question"].strip().lower()
            if key not in seen:
                seen.add(key)
                out.append({"id": row["id"], "question": row["question"], "created_at": row["created_at"],
                            "partial": bool(rag.get("partial")) and rag.get("answerable") is not False})
    return {"questions": out[:15]}


@router.post("/ask")
def ask(body: AskBody) -> dict:
    """Show how the assistant would answer a question: what it retrieved and how the answer was built."""
    return explain.trace(body.question.strip())


@router.get("/{dataset}")
def read(dataset: str) -> dict:
    ds = kbstore.read_dataset(_dataset(dataset))
    key = "record" if dataset == "clinic" else "records"
    return {"dataset": dataset, "file": ds.path.name, "format": ds.fmt, key: ds.data}


@router.get("/{dataset}/export.csv")
def export_csv(dataset: str) -> Response:
    text = kbstore.export_csv(_dataset(dataset))
    return Response(content="﻿" + text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{kbstore.FILE_BASENAME[dataset]}.csv"'})


@router.post("/{dataset}/import")
def import_csv(dataset: str, body: ImportBody) -> dict:
    """Replace a dataset with a CSV. Use dry_run=true first to preview what would change."""
    return kbstore.import_csv(_dataset(dataset), body.csv, dry_run=body.dry_run)


@router.post("/{dataset}", status_code=201)
def create(dataset: str, body: dict[str, Any]) -> dict:
    return kbstore.create_record(_list_dataset(dataset), body)


@router.put("/clinic")
def save_clinic(body: dict[str, Any]) -> dict:
    return kbstore.save_clinic(body)


@router.put("/{dataset}/{record_id}")
def update(dataset: str, record_id: str, body: dict[str, Any]) -> dict:
    try:
        return kbstore.update_record(_list_dataset(dataset), record_id, body)
    except KeyError:
        raise HTTPException(status_code=404, detail="That entry no longer exists.") from None


@router.delete("/{dataset}/{record_id}")
def delete(dataset: str, record_id: str) -> dict:
    try:
        return {"ok": True, "notes": kbstore.delete_record(_list_dataset(dataset), record_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="That entry no longer exists.") from None
