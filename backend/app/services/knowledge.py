from __future__ import annotations

"""知识/规则检索：条目与规则同库打分，命中结果一律带 source_ref 与 trace_version。

这里刻意用可解释的词面加权而不是向量库：军工内网不允许把语料送到外部嵌入服务，
且调度员需要「为什么命中这条」。等 F6 给出真实语料后，同一次序可直接换成向量召回。
"""

import re

from sqlalchemy.orm import Session

from ..models import Knowledge, Rule


def tokens(query: str) -> list[str]:
    raw = query.strip().lower()
    parts = [part for part in re.split(r"[\s,，、;；/]+", raw) if part]
    if not parts:
        return [raw] if raw else []
    found = list(parts)
    if len(parts) == 1 and len(parts[0]) >= 4:
        found.extend(parts[0][index : index + 2] for index in range(0, len(parts[0]) - 1, 2))
    return list(dict.fromkeys(found))


def match_score(word_list: list[str], title: str, haystack: str, tags: list[str]) -> float:
    lowered_title = title.lower()
    lowered_tags = [(tag or "").lower() for tag in tags]
    matched = 0
    score = 0.0
    for token in word_list:
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
    coverage = matched / len(word_list)
    if coverage < 0.5 and len(word_list) > 1:
        return 0.0
    return score * (0.6 + 0.4 * coverage)


def search(db: Session, query: str, top_k: int = 8) -> dict:
    word_list = tokens(query)
    results: list[dict] = []
    for item in db.query(Knowledge).all():
        tags = item.tags or []
        haystack = f"{item.title} {item.content} {' '.join(tags)}".lower()
        score = match_score(word_list, item.title, haystack, tags)
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
        score = match_score(word_list, rule.title, haystack, [rule.category])
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
    top = results[: max(1, top_k)]
    return {
        "query": query,
        "items": top,
        "hits": len(top),
        "mode": "本地检索（多词加权 + 溯源字段）",
        "note": "结果均携带 source_ref / trace_version，可回查原始专识条目",
    }


def digest(db: Session, query: str, top_k: int = 4, max_chars: int = 1200) -> str:
    """给模型当上下文用的纯文本摘要：条号 + 出处，不带内容全文，避免语料整体出域。"""
    found = search(db, query, top_k)
    if not found["items"]:
        return ""
    lines = []
    for item in found["items"]:
        body = (item["content"] or "")[:200]
        lines.append(f"- [{item['kind']} {item['code']}] {item['title']}｜{body}｜出处 {item['source_ref']}")
    text = "\n".join(lines)
    return text[:max_chars]


KNOWLEDGE_COLUMNS = (
    "code", "category", "title", "content", "source_ref", "trace_version", "tags", "confidence",
)
CATEGORIES = ("专识", "通识")


class KnowledgeImportError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _cell(row: dict, key: str) -> str:
    return str(row.get(key) or "").strip()


def _knowledge_row(row: dict) -> dict:
    code = _cell(row, "code")
    title = _cell(row, "title")
    content = _cell(row, "content")
    if not code or not title or not content:
        raise KnowledgeImportError("KB_ROW_INVALID", f"第 {row.get('_line', '?')} 行缺少 code/title/content")
    category = _cell(row, "category") or "专识"
    if category not in CATEGORIES:
        raise KnowledgeImportError("KB_ROW_INVALID", f"{code} 的 category={category!r} 只允许 {list(CATEGORIES)}")
    confidence = _cell(row, "confidence")
    value = 0.9 if confidence == "" else float(confidence)
    if not 0 <= value <= 1:
        raise KnowledgeImportError("KB_ROW_INVALID", f"{code} 的 confidence 必须在 0~1 之间")
    tags = [tag.strip() for tag in re.split(r"[;；,，|]+", _cell(row, "tags")) if tag.strip()]
    return {
        "code": code,
        "category": category,
        "title": title[:160],
        "content": content,
        "source_ref": (_cell(row, "source_ref") or "内部台账")[:128],
        "trace_version": (_cell(row, "trace_version") or "v1.0")[:32],
        "tags": tags,
        "confidence": value,
    }


def import_rows(db: Session, rows: list[dict], actor) -> dict:
    """F6 语料入库：按 code upsert，整批校验，非法行拒绝并留审计。"""
    from datetime import datetime

    from ..models import Knowledge as KnowledgeModel
    from .audit import log_user_action

    if not rows:
        raise KnowledgeImportError("KB_EMPTY", "语料为空，拒绝写入")
    prepared = [_knowledge_row({**row, "_line": index + 1}) for index, row in enumerate(rows)]
    existing = {item.code: item for item in db.query(KnowledgeModel).all()}
    created = updated = unchanged = 0
    for payload in prepared:
        current = existing.get(payload["code"])
        if current is None:
            record = KnowledgeModel(**payload, created_at=datetime.now().replace(microsecond=0))
            db.add(record)
            existing[payload["code"]] = record
            created += 1
            continue
        changed = False
        for field, value in payload.items():
            if getattr(current, field, None) != value:
                setattr(current, field, value)
                changed = True
        updated += 1 if changed else 0
        unchanged += 0 if changed else 1
    db.flush()
    log_user_action(
        db, actor, "knowledge.import", "knowledge", "corpus",
        detail={"rows": len(prepared), "created": created, "updated": updated, "unchanged": unchanged},
    )
    return {"rows": len(prepared), "created": created, "updated": updated, "unchanged": unchanged,
            "columns": list(KNOWLEDGE_COLUMNS)}
