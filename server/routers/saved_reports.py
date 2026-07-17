"""Saved analysis reports — keep a study's JSON for later or for AI prompts."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import SavedReport

router = APIRouter(prefix="/api/saved-reports", tags=["saved-reports"])


class SavedReportIn(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=200)
    params: dict = {}
    payload: dict


@router.post("", status_code=201)
def save_report(body: SavedReportIn, db: Session = Depends(get_db)):
    rec = SavedReport(kind=body.kind, title=body.title,
                      params_json=json.dumps(body.params, default=str),
                      payload=json.dumps(body.payload, default=str))
    db.add(rec)
    db.commit()
    return {"id": rec.id, "title": rec.title, "created_at": rec.created_at.isoformat()}


@router.get("")
def list_reports(kind: str | None = None, db: Session = Depends(get_db)):
    q = db.query(SavedReport)
    if kind:
        q = q.filter(SavedReport.kind == kind)
    return [{"id": r.id, "kind": r.kind, "title": r.title,
             "params": json.loads(r.params_json or "{}"),
             "created_at": r.created_at.isoformat()}
            for r in q.order_by(SavedReport.created_at.desc()).all()]


@router.get("/{report_id}")
def get_report(report_id: int, db: Session = Depends(get_db)):
    r = db.get(SavedReport, report_id)
    if not r:
        raise HTTPException(404, "Report not found")
    return {"id": r.id, "kind": r.kind, "title": r.title,
            "params": json.loads(r.params_json or "{}"),
            "payload": json.loads(r.payload),
            "created_at": r.created_at.isoformat()}


@router.delete("/{report_id}", status_code=204)
def delete_report(report_id: int, db: Session = Depends(get_db)):
    r = db.get(SavedReport, report_id)
    if not r:
        raise HTTPException(404, "Report not found")
    db.delete(r)
    db.commit()
