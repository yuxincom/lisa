from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import AuditLog, User

SENSITIVE_KEYS = {"password", "signature", "token", "secret", "credential"}
GENESIS_HASH = "0" * 64


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("***" if k.lower() in SENSITIVE_KEYS else _sanitize(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    return value


def _digest(prev_hash: str, ts: datetime, actor: str, action: str, target: str, detail: dict) -> str:
    raw = "|".join(
        [
            prev_hash,
            ts.isoformat(),
            actor,
            action,
            target,
            json.dumps(detail, sort_keys=True, ensure_ascii=False, separators=(",", ":")),
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def append_audit(
    db: Session,
    actor: str,
    role: str,
    action: str,
    target_type: str = "",
    target_id: str = "",
    result: str = "success",
    detail: dict | None = None,
    clearance: str = "内部",
) -> AuditLog:
    last = db.query(AuditLog).order_by(AuditLog.seq.desc()).first()
    seq = (last.seq + 1) if last else 1
    prev_hash = last.hash if last else GENESIS_HASH
    ts = datetime.now().replace(microsecond=0)
    clean_detail = _sanitize(detail or {})
    target = f"{target_type}:{target_id}"
    digest = _digest(prev_hash, ts, actor, action, target, clean_detail)
    log = AuditLog(
        seq=seq, ts=ts, actor=actor, role=role, action=action, target_type=target_type,
        target_id=str(target_id), result=result, detail=clean_detail, prev_hash=prev_hash,
        hash=digest, clearance=clearance,
    )
    db.add(log)
    db.flush()
    return log


def log_user_action(db: Session, user: User, action: str, target_type: str = "", target_id: str = "", **kwargs):
    return append_audit(
        db,
        actor=user.username,
        role=user.role,
        action=action,
        target_type=target_type,
        target_id=target_id,
        clearance=user.clearance,
        **kwargs,
    )


def verify_chain(db: Session) -> dict:
    logs = db.query(AuditLog).order_by(AuditLog.seq.asc()).all()
    prev = GENESIS_HASH
    broken_at = None
    for log in logs:
        expected = _digest(prev, log.ts, log.actor, log.action, f"{log.target_type}:{log.target_id}", log.detail or {})
        if log.prev_hash != prev or log.hash != expected:
            broken_at = log.seq
            break
        prev = log.hash
    return {
        "ok": broken_at is None,
        "total": len(logs),
        "broken_at": broken_at,
        "last_hash": prev,
        "algorithm": "SHA-256 哈希链",
        "verified_at": datetime.now().replace(microsecond=0).isoformat(),
    }


def audit_stats(db: Session) -> dict:
    total = db.query(func.count(AuditLog.id)).scalar() or 0
    actions = (
        db.query(AuditLog.action, func.count(AuditLog.id))
        .group_by(AuditLog.action)
        .order_by(func.count(AuditLog.id).desc())
        .limit(8)
        .all()
    )
    last = db.query(AuditLog).order_by(AuditLog.seq.desc()).first()
    return {
        "total": total,
        "last_hash": last.hash if last else GENESIS_HASH,
        "last_ts": last.ts.isoformat() if last else None,
        "actions": [{"action": a, "count": c} for a, c in actions],
    }
