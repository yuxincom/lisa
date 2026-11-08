from __future__ import annotations

"""外部主数据适配器（D 组接入）：文件落地 / HTTP 拉取 / 中间库直连。

适配器只做一件事——把源系统的数据搬进 LISA 的齐套主数据表，然后更新数据源的时效指标。
它不写 APS/MES，也不参与排产决策；每条通道都可单独开关、单独看上次同步结果。

配置放在设置项 `adapters` 里，凭据只写环境变量名（不落库、不落日志）：
    {"name": "WMS 库存", "kind": "stock", "channel": "file",
     "path": "/data/drop/wms_stock.csv", "interval_minutes": 15, "enabled": true}
    channel=http 需要 url（+ 可选 token_env）；channel=db 需要 dsn_env 与 sql（只允许 SELECT）。
"""

import csv
import json
import os
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..models import DataSource, User
from .audit import log_user_action
from .kit_data import KIT_COLUMNS, KitDataError, data_freshness, upsert_rows
from .settings import get_setting, set_setting

STATUS_KEY = "adapter_status"
DEFAULT_SOURCES: list[dict[str, Any]] = []
MAX_ROWS_PER_RUN = 20000


class AdapterError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def source_configs(db: Session) -> list[dict[str, Any]]:
    config = get_setting(db, "adapters", {}) or {}
    sources = config.get("sources") if isinstance(config, dict) else config
    return list(sources or [])


def status_map(db: Session) -> dict[str, dict[str, Any]]:
    return dict(get_setting(db, STATUS_KEY, {}) or {})


def _source_key(source: dict[str, Any], index: int) -> str:
    return str(source.get("name") or f"{source.get('kind', 'source')}-{index + 1}")


def _interval(source: dict[str, Any]) -> int:
    try:
        return max(1, int(source.get("interval_minutes") or 15))
    except (TypeError, ValueError):
        return 15


def _read_file(path: str) -> list[dict[str, Any]]:
    file = Path(path)
    if not file.is_file():
        raise AdapterError("ADAPTER_FILE_MISSING", f"落地文件不存在：{path}")
    with file.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise AdapterError("ADAPTER_FILE_EMPTY", f"落地文件为空：{path}")
    if len(rows) > MAX_ROWS_PER_RUN:
        raise AdapterError("ADAPTER_TOO_MANY_ROWS", f"{path} 有 {len(rows)} 行，超过单次上限 {MAX_ROWS_PER_RUN}")
    return rows


def _read_http(url: str, token_env: str = "") -> list[dict[str, Any]]:
    if not url.lower().startswith("https://"):
        raise AdapterError("ADAPTER_URL_INSECURE", f"HTTP 通道只允许 https：{url}")
    request = urllib.request.Request(url)
    token = os.getenv(token_env, "") if token_env else ""
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - 源系统异常原样回报，不让轮询崩溃
        raise AdapterError("ADAPTER_HTTP_FAILED", f"拉取 {url} 失败：{exc}") from exc
    rows = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not rows:
        raise AdapterError("ADAPTER_HTTP_EMPTY", f"{url} 未返回数据行")
    return rows[:MAX_ROWS_PER_RUN]


def _read_db(dsn_env: str, sql: str) -> list[dict[str, Any]]:
    from sqlalchemy import create_engine

    dsn = os.getenv(dsn_env, "")
    if not dsn:
        raise AdapterError("ADAPTER_DSN_MISSING", f"环境变量 {dsn_env} 未配置中间库连接串")
    if not sql.strip().lower().startswith("select"):
        raise AdapterError("ADAPTER_SQL_NOT_READONLY", "中间库通道只允许 SELECT 查询")
    connect_args = {"connect_timeout": 10} if dsn.startswith(("postgresql", "oracle")) else {}
    engine = create_engine(dsn, pool_pre_ping=True, connect_args=connect_args)
    try:
        with engine.connect() as connection:
            result = connection.execute(text(sql))
            rows = [dict(mapping) for mapping in result.mappings().all()]
    except Exception as exc:  # noqa: BLE001
        raise AdapterError("ADAPTER_DB_FAILED", f"中间库查询失败：{exc}") from exc
    finally:
        engine.dispose()
    if not rows:
        raise AdapterError("ADAPTER_DB_EMPTY", "中间库查询返回 0 行")
    return rows[:MAX_ROWS_PER_RUN]


def _validate_header(kind: str, rows: list[dict[str, Any]]) -> None:
    required = KIT_COLUMNS.get(kind)
    if not required:
        raise AdapterError("ADAPTER_KIND_UNKNOWN", f"未知的齐套数据类型：{kind}")
    missing = [column for column in required if column not in rows[0]]
    if missing:
        raise AdapterError("ADAPTER_HEADER_MISSING", f"{kind} 缺少必需列：{', '.join(missing)}")


def sync_source(db: Session, source: dict[str, Any], actor: User) -> dict[str, Any]:
    kind = str(source.get("kind") or "")
    channel = str(source.get("channel") or "file")
    started = _now()
    if channel == "file":
        rows = _read_file(str(source.get("path") or ""))
    elif channel == "http":
        rows = _read_http(str(source.get("url") or ""), str(source.get("token_env") or ""))
    elif channel == "db":
        rows = _read_db(str(source.get("dsn_env") or ""), str(source.get("sql") or ""))
    else:
        raise AdapterError("ADAPTER_CHANNEL_UNKNOWN", f"未知通道：{channel}")
    _validate_header(kind, rows)
    result = upsert_rows(db, kind, rows, actor)
    latency = int((datetime.now() - started).total_seconds() * 1000)
    return {**result, "channel": channel, "latency_ms": latency, "synced_at": started.isoformat()}


def _record_status(db: Session, key: str, entry: dict[str, Any]) -> None:
    statuses = status_map(db)
    statuses[key] = entry
    set_setting(db, STATUS_KEY, statuses)


def _touch_data_source(db: Session, kind: str, entry: dict[str, Any], rows: int) -> None:
    row = db.query(DataSource).filter(DataSource.code == f"ADP-{kind}").first()
    if row is None:
        row = DataSource(code=f"ADP-{kind}", name=f"{kind} 适配器", type="Adapter", owner="信息中心")
        db.add(row)
    row.records = rows
    row.last_sync = _now()
    row.latency_ms = int(entry.get("latency_ms") or 0)
    row.status = "online" if not entry.get("error") else "degraded"
    row.quality = 98.0 if not entry.get("error") else 70.0


def run_due(db: Session, actor: User, force: bool = False) -> dict[str, Any]:
    """轮询入口：到点的通道逐个同步，异常记录在该通道的状态里而不是中断整批。"""
    statuses = status_map(db)
    ran: list[dict[str, Any]] = []
    for index, source in enumerate(source_configs(db)):
        if not source.get("enabled", True):
            continue
        key = _source_key(source, index)
        if not force:
            last = statuses.get(key, {}).get("synced_at")
            if last:
                try:
                    if datetime.fromisoformat(last) + timedelta(minutes=_interval(source)) > datetime.now():
                        continue
                except ValueError:
                    pass
        try:
            entry = sync_source(db, source, actor)
            entry["name"] = key
            ran.append(entry)
            _record_status(db, key, entry)
            _touch_data_source(db, str(source.get("kind")), entry, int(entry.get("rows") or 0))
        except (AdapterError, KitDataError) as exc:
            db.rollback()
            entry = {
                "name": key, "kind": source.get("kind"), "channel": source.get("channel"),
                "error": {"code": exc.code, "message": exc.message}, "synced_at": _now().isoformat(),
            }
            ran.append(entry)
            _record_status(db, key, entry)
            _touch_data_source(db, str(source.get("kind")), entry, 0)
    if ran:
        log_user_action(
            db, actor, "adapter.sync", "adapter", ",".join(r["name"] for r in ran),
            detail={"ran": len(ran), "failed": sum(1 for r in ran if r.get("error"))},
        )
        db.commit()
    return {"ran": ran, "skipped": max(0, len([s for s in source_configs(db) if s.get("enabled", True)]) - len(ran))}


def adapter_overview(db: Session) -> dict[str, Any]:
    statuses = status_map(db)
    sources = []
    for index, source in enumerate(source_configs(db)):
        key = _source_key(source, index)
        entry = statuses.get(key, {})
        sources.append({
            "name": key,
            "kind": source.get("kind"),
            "channel": source.get("channel"),
            "interval_minutes": _interval(source),
            "enabled": bool(source.get("enabled", True)),
            "last_sync": entry.get("synced_at"),
            "rows": entry.get("rows"),
            "latency_ms": entry.get("latency_ms"),
            "error": entry.get("error"),
            "next_sync": (
                datetime.fromisoformat(entry["synced_at"]) + timedelta(minutes=_interval(source))
            ).isoformat() if entry.get("synced_at") else None,
        })
    return {"sources": sources, "freshness": data_freshness(db)}
