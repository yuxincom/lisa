from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require
from ..models import Knowledge, Rule, User
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


def _tokens(query: str) -> list[str]:
    raw = query.strip().lower()
    parts = [part for part in re.split(r"[\s,，、;；/]+", raw) if part]
    if not parts:
        return [raw] if raw else []
    tokens = list(parts)
    if len(parts) == 1 and len(parts[0]) >= 4:
        tokens.extend(parts[0][index : index + 2] for index in range(0, len(parts[0]) - 1, 2))
    return list(dict.fromkeys(tokens))


def _match_score(tokens: list[str], title: str, haystack: str, tags: list[str]) -> float:
    lowered_title = title.lower()
    lowered_tags = [(tag or "").lower() for tag in tags]
    matched = 0
    score = 0.0
    for token in tokens:
        hits = haystack.count(token)
        if hits == 0:
            continue
        matched += 1
        score += hits * 2.5
        if token in lowered_title:
            score += 6
        if any(token in tag for tag in lowered_tags):
            score += 4
    if matched == 0:
        return 0.0
    coverage = matched / len(tokens)
    if coverage < 0.5 and len(tokens) > 1:
        return 0.0
    return score * (0.6 + 0.4 * coverage)


@router.post("/search")
def search(payload: SearchRequest, db: Session = Depends(get_db), user: User = Depends(require("knowledge:read"))):
    tokens = _tokens(payload.query)
    results = []
    for item in db.query(Knowledge).all():
        tags = item.tags or []
        haystack = f"{item.title} {item.content} {' '.join(tags)}".lower()
        score = _match_score(tokens, item.title, haystack, tags)
        if score <= 0:
            continue
        results.append(
            {
                "kind": "knowledge",
                "code": item.code,
                "title": item.title,
                "content": item.content,
                "source_ref": item.source_ref,
                "trace_version": item.trace_version,
                "tags": tags,
                "confidence": item.confidence,
                "score": round(score + float(item.confidence or 0.8), 2),
            }
        )
    for rule in db.query(Rule).filter(Rule.kind == "rule").all():
        haystack = f"{rule.code} {rule.title} {rule.description} {rule.category}".lower()
        score = _match_score(tokens, rule.title, haystack, [rule.category])
        if score <= 0:
            continue
        results.append(
            {
                "kind": "rule",
                "code": rule.code,
                "title": rule.title,
                "content": rule.description,
                "source_ref": f"ZD-01-2026 · {rule.category}",
                "trace_version": "v1.0",
                "tags": [rule.category, f"优先级 {rule.priority}"],
                "confidence": 1.0,
                "score": round(score + rule.priority * 0.1, 2),
            }
        )
    results.sort(key=lambda x: x["score"], reverse=True)
    top = results[: payload.top_k]
    return {
        "query": payload.query,
        "items": top,
        "hits": len(top),
        "mode": "RAG 本地检索（多词加权 + 溯源字段）",
        "note": "结果均携带 source_ref / trace_version，可回查原始专识条目",
    }


@router.get("/rules/{code}")
def rule_detail(code: str, db: Session = Depends(get_db), user: User = Depends(require("knowledge:read"))):
    rule = db.query(Rule).filter(Rule.code == code).first()
    if not rule:
        raise HTTPException(status_code=404, detail={"code": "RULE_NOT_FOUND", "message": "规则不存在"})
    return serialize_rule(rule)
