from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require
from ..models import Knowledge, Rule, User
from ..services import knowledge as kb
from ..services.rules import rule_catalog, serialize_rule

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    top_k: int = Field(default=8, ge=1, le=30)


@router.get("/catalog")
def catalog(db: Session = Depends(get_db), user: User = Depends(require("knowledge:read"))):
    data = rule_catalog(db)
    total_knowledge = db.query(Knowledge).count()
    data["summary"]["knowledge_items"] = total_knowledge
    data["summary"]["dataset_scale"] = {"general": 54400, "expert": 68884, "phase2": 160160}
    return data


@router.get("/items")
def items(
    category: str | None = None,
    q: str = "",
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require("knowledge:read")),
):
    query = db.query(Knowledge)
    if category:
        query = query.filter(Knowledge.category == category)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (Knowledge.title.like(like)) | (Knowledge.content.like(like)) | (Knowledge.code.like(like))
        )
    rows = query.order_by(Knowledge.code.asc()).limit(limit).all()
    return {
        "items": [
            {
                "id": r.id,
                "code": r.code,
                "category": r.category,
                "title": r.title,
                "content": r.content,
                "source_ref": r.source_ref,
                "trace_version": r.trace_version,
                "tags": r.tags or [],
                "confidence": r.confidence,
            }
            for r in rows
        ],
        "total": len(rows),
    }


@router.post("/search")
def search(payload: SearchRequest, db: Session = Depends(get_db), user: User = Depends(require("knowledge:read"))):
    return kb.search(db, payload.query, payload.top_k)


@router.get("/rules/{code}")
def rule_detail(code: str, db: Session = Depends(get_db), user: User = Depends(require("knowledge:read"))):
    rule = db.query(Rule).filter(Rule.code == code).first()
    if not rule:
        raise HTTPException(status_code=404, detail={"code": "RULE_NOT_FOUND", "message": "规则不存在"})
    return serialize_rule(rule)
