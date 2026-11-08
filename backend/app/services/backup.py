from __future__ import annotations

"""整库逻辑快照：备份 → 校验 → 恢复，SQLite 与 PostgreSQL 走同一套代码。

    python -m app.management backup [--out DIR] [--keep 14]
    python -m app.management backups
    python -m app.management verify <文件名>
    python -m app.management restore <文件名> --yes

快照是 JSON 而不是二进制：恢复要能落到另一台机器、另一个数据库引擎上。
pg_dump / sqlite3 .backup 这类二进制快照由运维在库侧做，create() 的返回值里
会带上当前引擎对应的原生命令，写进运维手册即可。
"""

import base64
import gzip
import hashlib
import json
import os
import re
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from sqlalchemy import Date, DateTime, Integer, LargeBinary, delete, func, select
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from ..config import APP_VERSION, DATA_DIR, DATABASE_URL, ENVIRONMENT
from ..database import Base
from .audit import verify_chain

FORMAT = "lisa-backup-v1"
FILE_PREFIX = "lisa-backup-"
FILE_PATTERN = re.compile(r"^lisa-backup-\d{8}-\d{6}\.\d{6}-[0-9a-f]{8}\.json\.gz$")
DEFAULT_KEEP = 14
SHA_SUFFIX = ".sha256"
META_SUFFIX = ".meta.json"


class BackupError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def backup_dir() -> Path:
    raw = os.getenv("LISA_BACKUP_DIR", "").strip()
    path = Path(raw) if raw else Path(DATA_DIR) / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def keep_count() -> int:
    raw = os.getenv("LISA_BACKUP_KEEP", str(DEFAULT_KEEP)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_KEEP


def tables() -> list:
    return list(Base.metadata.sorted_tables)


def _encode(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str, list, dict)):
        return value
    # datetime 是 date 的子类，必须先判 datetime
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return "base64:" + base64.b64encode(bytes(value)).decode()
    raise BackupError("BACKUP_VALUE_UNSUPPORTED", f"{type(value).__name__} 写不进快照")


def _decode(column, value: Any) -> Any:
    if value is None:
        return None
    kind = column.type
    if isinstance(value, str):
        if isinstance(kind, DateTime):
            return datetime.fromisoformat(value)
        if isinstance(kind, Date):
            return date.fromisoformat(value)
        if isinstance(kind, LargeBinary) and value.startswith("base64:"):
            return base64.b64decode(value[7:])
    return value


_CREDENTIALS = re.compile(r"^([a-z][a-z0-9+.-]*://)([^/?#@\s]+):([^/?@\s]+)@", re.IGNORECASE)


def _safe_url() -> str:
    """连接串进快照是为了事后对账，密码一律换成 ***。"""
    return _CREDENTIALS.sub(r"\1\2:***@", DATABASE_URL)


def _canonical(data: dict) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _dump_database(db: Session) -> tuple[dict[str, list[dict]], dict[str, int]]:
    data: dict[str, list[dict]] = {}
    counts: dict[str, int] = {}
    for table in tables():
        names = [column.name for column in table.c]
        rows = [{name: _encode(row[name]) for name in names} for row in db.execute(select(table)).mappings()]
        data[table.name] = rows
        counts[table.name] = len(rows)
    return data, counts


def audit_ref(name: str) -> str:
    """文件名去掉固定首尾就是「时间-摘要」，长度正好放得进审计表的 target_id(40)。"""
    return name[len(FILE_PREFIX): -len(".json.gz")]


def create(db: Session, out_dir: Path | None = None, keep: int | None = None) -> dict:
    directory = Path(out_dir) if out_dir else backup_dir()
    directory.mkdir(parents=True, exist_ok=True)
    data, counts = _dump_database(db)
    digest = hashlib.sha256(_canonical(data).encode("utf-8")).hexdigest()
    audit_rows = data.get("audit_logs", [])
    head = max(audit_rows, key=lambda row: row.get("seq") or 0) if audit_rows else {}
    moment = datetime.now()
    stamp = moment.replace(microsecond=0)
    header = {
        "format": FORMAT,
        "app_version": APP_VERSION,
        "environment": ENVIRONMENT,
        "created_at": stamp.isoformat(),
        "dialect": db.get_bind().dialect.name,
        "database": _safe_url(),
        "payload_digest": digest,
        "table_order": [table.name for table in tables()],
        "row_counts": counts,
        "total_rows": sum(counts.values()),
        "audit_head_seq": head.get("seq", 0),
        "audit_head_hash": head.get("hash", ""),
    }
    name = f"{FILE_PREFIX}{moment:%Y%m%d-%H%M%S}.{moment.microsecond:06d}-{digest[:8]}.json.gz"
    path = directory / name
    blob = gzip.compress(json.dumps({"header": header, "data": data}, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), mtime=0)
    path.write_bytes(blob)
    file_digest = hashlib.sha256(blob).hexdigest()
    (directory / (name + SHA_SUFFIX)).write_text(f"{file_digest}  {name}\n", encoding="utf-8")
    (directory / (name + META_SUFFIX)).write_text(json.dumps(header, ensure_ascii=False, indent=2), encoding="utf-8")
    removed = prune(directory, keep if keep is not None else keep_count())
    return {
        "file": name,
        "audit_ref": audit_ref(name),
        "path": str(path),
        "bytes": len(blob),
        "checksum": file_digest,
        "payload_digest": digest,
        "created_at": header["created_at"],
        "dialect": header["dialect"],
        "total_rows": header["total_rows"],
        "row_counts": counts,
        "audit_head_seq": header["audit_head_seq"],
        "audit_head_hash": header["audit_head_hash"],
        "pruned": removed,
        "native": native_commands(),
    }


def prune(directory: Path, keep: int) -> list[str]:
    removed: list[str] = []
    for old in snapshot_files(directory)[keep:]:
        for sibling in (old, directory / (old.name + SHA_SUFFIX), directory / (old.name + META_SUFFIX)):
            sibling.unlink(missing_ok=True)
        removed.append(old.name)
    return removed


def snapshot_files(directory: Path | None = None) -> list[Path]:
    root = Path(directory) if directory else backup_dir()
    return sorted((p for p in root.glob(FILE_PREFIX + "*.json.gz") if FILE_PATTERN.match(p.name)), reverse=True)


def _header_of(path: Path) -> dict:
    meta = path.with_name(path.name + META_SUFFIX)
    if meta.is_file():
        return json.loads(meta.read_text(encoding="utf-8"))
    header, _ = _read(path)
    return header


def list_backups(directory: Path | None = None) -> list[dict]:
    root = Path(directory) if directory else backup_dir()
    items: list[dict] = []
    for path in snapshot_files(root):
        try:
            header = _header_of(path)
        except (BackupError, json.JSONDecodeError, OSError):
            items.append({"file": path.name, "unreadable": True})
            continue
        items.append(
            {
                "file": path.name,
                "created_at": header.get("created_at"),
                "app_version": header.get("app_version"),
                "dialect": header.get("dialect"),
                "total_rows": header.get("total_rows"),
                "tables": len(header.get("row_counts", {})),
                "audit_head_seq": header.get("audit_head_seq"),
                "bytes": path.stat().st_size,
                "has_checksum": (root / (path.name + SHA_SUFFIX)).is_file(),
            }
        )
    return items


def _read(path: Path) -> tuple[dict, dict]:
    raw = path.read_bytes()
    sidecar = path.with_name(path.name + SHA_SUFFIX)
    if sidecar.is_file():
        expected = sidecar.read_text(encoding="utf-8").split()[0]
        if hashlib.sha256(raw).hexdigest() != expected:
            raise BackupError("BACKUP_CHECKSUM_MISMATCH", f"{path.name} 的字节和 .sha256 对不上：文件被改过或传坏了")
    try:
        payload = json.loads(gzip.decompress(raw).decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise BackupError("BACKUP_FILE_CORRUPT", f"{path.name} 不是可读的 gzip JSON：{exc}")
    header, data = payload.get("header") or {}, payload.get("data") or {}
    if header.get("format") != FORMAT:
        raise BackupError("BACKUP_FORMAT_UNKNOWN", f"快照格式 {header.get('format')!r} 不是 {FORMAT}")
    if hashlib.sha256(_canonical(data).encode("utf-8")).hexdigest() != header.get("payload_digest"):
        raise BackupError("BACKUP_DIGEST_MISMATCH", f"{path.name} 里的表数据和头部摘要对不上，拒绝使用")
    return header, data


def verify(path: Path | str, directory: Path | None = None) -> dict:
    """名字里的摘要已经覆盖表内容，这里再核一遍字节、行数和审计链落点。"""
    root = Path(directory) if directory else backup_dir()
    target = Path(path) if os.path.isabs(str(path)) else root / str(path)
    if not target.is_file():
        raise BackupError("BACKUP_FILE_MISSING", f"找不到快照文件：{target.name}")
    header, data = _read(target)
    counts = header.get("row_counts") or {}
    mismatched = {name: (counts.get(name), len(rows)) for name, rows in data.items() if counts.get(name) != len(rows)}
    if mismatched:
        raise BackupError("BACKUP_ROW_COUNT_MISMATCH", f"行数对不上：{', '.join(mismatched)}")
    known = {table.name for table in tables()}
    unknown = sorted(set(data) - known)
    missing = sorted(known - set(data))
    return {
        "ok": True,
        "file": target.name,
        "created_at": header.get("created_at"),
        "app_version": header.get("app_version"),
        "dialect": header.get("dialect"),
        "total_rows": header.get("total_rows"),
        "payload_digest": header.get("payload_digest"),
        "checksum": hashlib.sha256(target.read_bytes()).hexdigest(),
        "audit_head_seq": header.get("audit_head_seq"),
        "audit_head_hash": header.get("audit_head_hash"),
        "unknown_tables": unknown,
        "missing_tables": missing,
    }


def _reset_sequences(db: Session, order: list) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    for table in order:
        keys = list(table.primary_key.columns)
        if len(keys) != 1 or not isinstance(keys[0].type, Integer):
            continue
        column = keys[0]
        sequence = db.execute(
            sql_text("SELECT pg_get_serial_sequence(:t, :c)"), {"t": table.name, "c": column.name}
        ).scalar()
        if not sequence:
            continue
        db.execute(
            sql_text(
                f'SELECT setval(:s, (SELECT COALESCE(MAX("{column.name}"), 0) + 1 FROM "{table.name}"), false)'
            ),
            {"s": sequence},
        )


def restore(db: Session, path: Path | str, *, confirmed: bool = False, directory: Path | None = None) -> dict:
    if not confirmed:
        raise BackupError("BACKUP_CONFIRM_REQUIRED", "恢复会清空当前业务表，必须显式确认（CLI 加 --yes）")
    root = Path(directory) if directory else backup_dir()
    target = Path(path) if os.path.isabs(str(path)) else root / str(path)
    if not target.is_file():
        raise BackupError("BACKUP_FILE_MISSING", f"找不到快照文件：{target.name}")
    header, data = _read(target)
    known = {table.name: table for table in tables()}
    unknown = sorted(set(data) - set(known))
    if unknown:
        raise BackupError("BACKUP_TABLE_UNKNOWN", f"快照里有当前版本不认识的表：{', '.join(unknown)}，先用对应版本的程序恢复")
    listed = {name for name in header.get("table_order", []) if name in known}
    order = [known[name] for name in header.get("table_order", []) if name in listed]
    order += [table for name, table in known.items() if name not in listed]

    for table in reversed(order):
        db.execute(delete(table))
    restored: dict[str, int] = {}
    counts = header.get("row_counts") or {}
    for table in order:
        rows = data.get(table.name, [])
        columns = list(table.c)
        names = {c.name for c in columns}
        extra = {key for row in rows for key in row if key not in names}
        if extra:
            db.rollback()
            raise BackupError(
                "BACKUP_COLUMN_UNKNOWN",
                f"{table.name} 里有当前版本没有的列：{', '.join(sorted(extra))}，别用旧程序覆盖新数据",
            )
        if rows:
            db.execute(table.insert(), [{c.name: _decode(c, row.get(c.name)) for c in columns} for row in rows])
        restored[table.name] = len(rows)
        expected = counts.get(table.name)
        if expected is not None and expected != len(rows):
            db.rollback()
            raise BackupError("BACKUP_ROW_COUNT_MISMATCH", f"{table.name} 声明 {expected} 行，实际只有 {len(rows)} 行")
    _reset_sequences(db, order)

    mismatched: dict[str, tuple[int, int]] = {}
    for table in order:
        in_db = db.execute(select(func.count()).select_from(table)).scalar() or 0
        if in_db != restored[table.name]:
            mismatched[table.name] = (restored[table.name], in_db)
    if mismatched:
        db.rollback()
        detail = ", ".join(f"{name} 快照 {want} 行/库里 {got} 行" for name, (want, got) in mismatched.items())
        raise BackupError("BACKUP_RESTORE_INCOMPLETE", f"写回后库里读到的行数与快照不符：{detail}")
    chain = verify_chain(db)
    if not chain["ok"]:
        db.rollback()
        raise BackupError(
            "BACKUP_AUDIT_CHAIN_BROKEN",
            f"恢复后审计链在第 {chain['broken_at']} 条断开：密级和审计数据不能带着缺口上线",
        )
    db.commit()
    return {
        "file": target.name,
        "audit_ref": audit_ref(target.name),
        "restored_at": datetime.now().replace(microsecond=0).isoformat(),
        "total_rows": sum(restored.values()),
        "row_counts": restored,
        "audit_chain": chain,
        "snapshot_created_at": header.get("created_at"),
        "dialect": header.get("dialect"),
    }


def native_commands() -> dict:
    """逻辑快照之外的二进制备份命令：库侧照着执行即可，凭据走环境变量不进手册。"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dump = str(backup_dir() / f"lisa-native-{stamp}")
    if DATABASE_URL.startswith("postgresql"):
        return {
            "dump": f'pg_dump --format=custom --no-owner --file="{dump}.dump" "$DATABASE_URL"',
            "restore": f'pg_restore --no-owner --clean --if-exists --dbname="$DATABASE_URL" "{dump}.dump"',
            "note": "pg_dump 是库侧一致性快照，恢复会重建全部对象；逻辑快照用于跨引擎搬迁",
        }
    db_path = DATABASE_URL.replace("sqlite:///", "")
    return {
        "dump": f'sqlite3 "{db_path}" ".backup \'{dump}.sqlite\'"',
        "restore": f'停止服务后用 {dump}.sqlite 覆盖 {db_path}，再重启容器',
        "note": "SQLite 在线热备请使用 .backup，不要直接 cp 数据文件",
    }


def resolve_name(name: str, directory: Path | None = None) -> Path:
    """HTTP 侧只允许传文件名，路径穿越一律拒绝。"""
    cleaned = str(name).strip()
    if not FILE_PATTERN.match(cleaned):
        raise BackupError("BACKUP_NAME_INVALID", f"不是合法的快照文件名：{cleaned}")
    root = Path(directory) if directory else backup_dir()
    path = (root / cleaned).resolve()
    if root.resolve() not in path.parents:
        raise BackupError("BACKUP_NAME_INVALID", "快照文件必须位于备份目录内")
    return path
