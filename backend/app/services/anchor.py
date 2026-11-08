from __future__ import annotations

"""审计链外部锚点：把链尾哈希按只追加的方式写到库外文件，形成库内/库外双份对账。

链本身只能证明「库内相邻两条没被改过」；有人若能直接改数据库，可以连哈希一起重算。
锚点文件在库外，且自身用 HMAC 串成第二条链：改了库里任意一条，锚点记录的链尾哈希就对不上；
改了锚点文件，锚点自己的 HMAC 就对不上。要同时伪造两边，需要同时拿到库和这个文件——
这正是等保三级对审计记录「不可篡改 + 异地/异介质备份」的最低要求。

密钥只从环境变量读（默认变量名 LISA_ANCHOR_SECRET），文件里只存变量名，绝不存密钥本身。
没有密钥时一律拒绝锚定并明确报 ANCHOR_SECRET_MISSING：宁可没有锚点，也不要一个
谁都能重算的「假锚点」。
"""

import hashlib
import hmac
import json
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import DATA_DIR
from ..models import AuditLog, User
from .audit import GENESIS_HASH, audit_stats, log_user_action

ANCHOR_SECRET_ENV = os.getenv("LISA_ANCHOR_SECRET_ENV", "LISA_ANCHOR_SECRET")
ALGORITHM = "HMAC-SHA256"


class AnchorError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def path() -> Path:
    return Path(DATA_DIR) / "audit_anchor.jsonl"


def secret_configured() -> bool:
    return bool(os.getenv(ANCHOR_SECRET_ENV, "").strip())


def _secret() -> bytes:
    value = os.getenv(ANCHOR_SECRET_ENV, "").strip()
    if not value:
        raise AnchorError(
            "ANCHOR_SECRET_MISSING",
            f"未设置环境变量 {ANCHOR_SECRET_ENV}，锚点无法签名（不签名等于没有防篡改）",
        )
    return value.encode()


def _digest(prev_anchor_hash: str, record: dict) -> str:
    body = {k: v for k, v in record.items() if k != "anchor_hash"}
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    raw = f"{prev_anchor_hash}|{canonical}".encode()
    return hmac.new(_secret(), raw, hashlib.sha256).hexdigest()


def _read_lines() -> list[dict]:
    file = path()
    if not file.exists():
        return []
    rows: list[dict] = []
    for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise AnchorError("ANCHOR_FILE_CORRUPT", f"锚点文件第 {number} 行不是合法 JSON：{exc}") from exc
    return rows


def append_anchor(db: Session, user: User | None = None) -> dict:
    """把当前链尾锚定一条。已锚定到 seq=N 时再来一次，只补 N 之后的新记录；无新记录则拒绝。"""
    rows = _read_lines()
    last = rows[-1] if rows else None
    last_anchored = int(last["seq_to"]) if last else 0
    head = db.query(AuditLog).order_by(AuditLog.seq.desc()).first()
    if head is None:
        raise AnchorError("ANCHOR_NO_LOGS", "审计链还没有任何记录，无可锚定内容")
    if head.seq <= last_anchored:
        raise AnchorError(
            "ANCHOR_NOTHING_NEW",
            f"审计链已锚定到 seq={last_anchored}，期间没有新记录（当前链尾 seq={head.seq}）",
        )
    count = db.query(AuditLog).filter(AuditLog.seq > last_anchored).count()
    record = {
        "v": 1,
        "seq_from": last_anchored + 1,
        "seq_to": head.seq,
        "records": count,
        "chain_hash": head.hash,
        "prev_anchor_hash": last["anchor_hash"] if last else GENESIS_HASH,
        "algo": ALGORITHM,
        "secret_env": ANCHOR_SECRET_ENV,
        "ts": datetime.now().replace(microsecond=0).isoformat(),
        "actor": getattr(user, "username", "") or "system",
    }
    record["anchor_hash"] = _digest(record["prev_anchor_hash"], record)
    with path().open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    if user is not None:
        log_user_action(
            db, user, "audit.anchor", "audit_chain", str(record["seq_to"]),
            detail={"seq_from": record["seq_from"], "records": record["records"],
                    "chain_hash": record["chain_hash"][:16], "algo": ALGORITHM},
        )
        db.commit()
    return record


def verify_anchors(db: Session | None = None) -> dict:
    """校验锚点文件自身的 HMAC 链，并与库内链尾哈希对账。"""
    file = path()
    result = {
        "file": str(file),
        "exists": file.exists(),
        "anchors": 0,
        "anchored_records": 0,
        "chain_ok": True,
        "broken_at": None,
        "algo": ALGORITHM,
        "secret_env": ANCHOR_SECRET_ENV,
        "secret_configured": secret_configured(),
    }
    if not file.exists():
        result["chain_ok"] = False
        result["reason"] = "ANCHOR_FILE_ABSENT"
        result["message"] = "还没有任何锚点：锚点文件不存在，审计链目前只有库内一份"
        return result
    if not secret_configured():
        result["chain_ok"] = False
        result["reason"] = "ANCHOR_SECRET_MISSING"
        result["message"] = (
            f"锚点文件有 {result['anchors']} 条，但没有 {ANCHOR_SECRET_ENV} 无法验签——"
            "验不了就是验不了，不当作通过"
        )
        return result
    prev = GENESIS_HASH
    for number, record in enumerate(_read_lines(), start=1):
        result["anchors"] += 1
        expected = _digest(prev, record)
        if record.get("anchor_hash") != expected or record.get("prev_anchor_hash") != prev:
            result["chain_ok"] = False
            result["broken_at"] = {"line": number, "seq_to": record.get("seq_to")}
            break
        prev = record["anchor_hash"]
        result["anchored_records"] = int(record.get("seq_to", 0))
        result["last"] = {
            "seq_from": record["seq_from"], "seq_to": record["seq_to"], "records": record["records"],
            "chain_hash": record["chain_hash"], "ts": record["ts"],
        }
    if result["chain_ok"] and db is not None:
        head = db.query(AuditLog).order_by(AuditLog.seq.desc()).first()
        last = result.get("last") or {}
        result["db_total"] = db.query(AuditLog).count()
        result["db_head_hash"] = head.hash if head else None
        result["unanchored_records"] = (head.seq - int(last["seq_to"])) if head and last else 0
        if last:
            row = db.query(AuditLog).filter(AuditLog.seq == int(last["seq_to"])).first()
            if row is None:
                result["chain_ok"] = False
                result["drift"] = "ANCHOR_RANGE_MISSING"
                result["message"] = f"锚点声称覆盖到 seq={last['seq_to']}，但库里这一条已经不存在"
            elif row.hash != last["chain_hash"]:
                result["chain_ok"] = False
                result["drift"] = "ANCHOR_VS_DB_MISMATCH"
                result["message"] = "锚点记录的链尾哈希与库内同一条的哈希不一致：库或锚点至少有一边被改动过"
            else:
                result["drift"] = None
    return result


def summary(db: Session) -> dict:
    """给自检/仪表盘用的最小口径：锚了几条、链是否完好、密钥是否配置。"""
    result = verify_anchors(db)
    stats = audit_stats(db)
    return {
        **result,
        "audit_total": stats["total"],
        "coverage": round(result["anchored_records"] / stats["total"] * 100, 1) if stats["total"] else 0.0,
    }
