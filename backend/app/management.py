from __future__ import annotations

"""主数据导入命令行：把台账 CSV 落进数据库。

    python -m app.management ledger ../deploy/templates/产能台账.csv [--dry-run]
    python -m app.management dependencies ../deploy/templates/工序依赖.csv [--dry-run]
    python -m app.management kit-data stock ../deploy/templates/齐套-库存.csv [--dry-run]
    python -m app.management adapters [--force]
    python -m app.management backup [--keep 14]
    python -m app.management backups
    python -m app.management verify lisa-backup-20261103-091200-ab12cd34.json.gz
    python -m app.management restore lisa-backup-20261103-091200-ab12cd34.json.gz --yes

CSV 表头固定为英文（Excel 导出后改列名即可），数值列允许为空，空值表示「不修改该字段」。
"""

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from .database import Base, SessionLocal, engine
from .migrate import sync_new_columns
from .models import User
from .services.kit_data import KIT_COLUMNS, KitDataError, upsert_rows
from .services.knowledge import KNOWLEDGE_COLUMNS, KnowledgeImportError
from .services.maindata import LedgerError, apply_dependencies, apply_machine_ledger

LEDGER_COLUMNS = (
    "code", "machine_count", "capacity_hours", "efficiency", "bottleneck", "capabilities",
)
DEPENDENCY_COLUMNS = (
    "order_no", "seq", "predecessor_order_no", "predecessor_seq", "lag_minutes",
)


def read_csv(path: Path, required: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise LedgerError("LEDGER_EMPTY", f"{path.name} 没有表头")
        header = {(name or "").strip(): (name or "") for name in reader.fieldnames}
        if required is None:
            required = LEDGER_COLUMNS if "code" in header else DEPENDENCY_COLUMNS
        missing = [column for column in required if column not in header]
        if missing:
            raise LedgerError("LEDGER_HEADER_MISSING", f"{path.name} 缺少列：{', '.join(missing)}")
        rows: list[dict[str, Any]] = []
        for raw in reader:
            row = {key.strip(): (value or "").strip() for key, value in raw.items() if key}
            if not any(row.values()):
                continue
            rows.append(row)
    if not rows:
        raise LedgerError("LEDGER_EMPTY", f"{path.name} 只有表头，没有数据行")
    return rows


def _actor(db: Any) -> User:
    user = db.query(User).filter(User.role == "admin").order_by(User.id).first()
    if user is None:
        raise LedgerError("LEDGER_NO_ACTOR", "数据库中没有系统管理员，导入必须留痕到具体的人")
    return user


def _backup_cli(args: Any) -> int:
    """备份/恢复单独走一条路：它不吃 CSV，失败原因要原样打给运维。"""
    from .services import backup as bk
    from .services.audit import log_user_action

    if args.command == "backups":
        print(json.dumps({"backup_dir": str(bk.backup_dir()), "items": bk.list_backups()}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "verify":
        try:
            print(json.dumps({**bk.verify(bk.resolve_name(args.name)), "native": bk.native_commands()}, ensure_ascii=False, indent=2))
        except bk.BackupError as exc:
            print(json.dumps({"ok": False, "code": exc.code, "message": exc.message}, ensure_ascii=False))
            return 2
        return 0

    db = SessionLocal()
    try:
        actor = _actor(db)
        if args.command == "backup":
            summary, action = bk.create(db, out_dir=args.out, keep=args.keep), "backup.create"
        else:
            summary, action = bk.restore(db, bk.resolve_name(args.name), confirmed=args.yes), "backup.restore"
        log_user_action(db, actor, action, "backup", summary["audit_ref"], detail={
            "file": summary["file"],
            "total_rows": summary["total_rows"],
            "checksum": summary.get("checksum") or summary.get("audit_chain", {}).get("last_hash"),
        })
        db.commit()
    except (bk.BackupError, LedgerError) as exc:
        db.rollback()
        code = getattr(exc, "code", "BACKUP_FAILED")
        message = getattr(exc, "message", str(exc))
        print(json.dumps({"ok": False, "code": code, "message": message}, ensure_ascii=False))
        return 2
    finally:
        db.close()
    print(json.dumps({"ok": True, **summary}, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.management")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("ledger", "导入产能台账（A1/A2）"),
        ("dependencies", "导入工序依赖邻接表（C2）"),
    ):
        step = sub.add_parser(name, help=help_text)
        step.add_argument("csv_path", type=Path)
        step.add_argument("--dry-run", action="store_true", help="只校验并回滚，不写入数据库")
    kit = sub.add_parser("kit-data", help="导入齐套外部主数据（D 组：BOM/库存/在途/工装/资质/检验）")
    kit.add_argument("kind", choices=tuple(KIT_COLUMNS))
    kit.add_argument("csv_path", type=Path)
    kit.add_argument("--dry-run", action="store_true", help="只校验并回滚，不写入数据库")
    adapters = sub.add_parser("adapters", help="运行到点的外部数据适配器（可由 cron/systemd timer 调用）")
    adapters.add_argument("--force", action="store_true", help="忽略间隔，立即全量拉一次")
    kb = sub.add_parser("knowledge", help="导入知识语料（F6：工艺规范 / 故障案例 / 制度文件条目）")
    kb.add_argument("csv_path", type=Path)
    kb.add_argument("--dry-run", action="store_true", help="只校验并回滚，不写入数据库")
    bk = sub.add_parser("backup", help="生成整库逻辑快照（JSON.gz + .sha256 + .meta.json）")
    bk.add_argument("--out", type=Path, default=None, help="快照目录，默认 LISA_BACKUP_DIR 或 data/backups")
    bk.add_argument("--keep", type=int, default=None, help="保留最近几份，默认 LISA_BACKUP_KEEP 或 14")
    sub.add_parser("backups", help="列出本地快照")
    vf = sub.add_parser("verify", help="校验快照的校验和、摘要与行数")
    vf.add_argument("name")
    rs = sub.add_parser("restore", help="用快照整库回滚：会清空当前业务表")
    rs.add_argument("name")
    rs.add_argument("--yes", action="store_true", help="确认清空当前数据，缺这个参数不动手")
    args = parser.parse_args(argv)

    # 导入通道要能在一台刚装好、还没起过服务的机器上直接跑：先把表结构对齐
    Base.metadata.create_all(bind=engine)
    sync_new_columns()

    if args.command in ("backup", "backups", "verify", "restore"):
        return _backup_cli(args)

    if args.command == "adapters":
        from .services.adapters import AdapterError, run_due

        db = SessionLocal()
        try:
            summary = run_due(db, _actor(db), force=args.force)
        except (AdapterError, LedgerError) as exc:
            db.rollback()
            print(json.dumps({"ok": False, "code": exc.code, "message": exc.message}, ensure_ascii=False))
            return 2
        finally:
            db.close()
        print(json.dumps({"ok": True, **summary}, ensure_ascii=False, indent=2))
        return 0

    kind = getattr(args, "kind", None)
    if args.command == "knowledge":
        rows = read_csv(args.csv_path, KNOWLEDGE_COLUMNS)
    else:
        rows = read_csv(args.csv_path, KIT_COLUMNS.get(kind)) if kind else read_csv(args.csv_path)
    db = SessionLocal()
    try:
        actor = _actor(db)
        if args.command == "ledger":
            result = apply_machine_ledger(db, rows, actor)
        elif args.command == "dependencies":
            result = apply_dependencies(db, rows, actor)
        elif args.command == "knowledge":
            from .services.knowledge import import_rows as import_knowledge

            result = import_knowledge(db, rows, actor)
        else:
            result = upsert_rows(db, kind, rows, actor)
        if args.dry_run:
            db.rollback()
            result["dry_run"] = True
        else:
            db.commit()
    except (LedgerError, KitDataError, KnowledgeImportError) as exc:
        db.rollback()
        print(json.dumps({"ok": False, "code": exc.code, "message": exc.message}, ensure_ascii=False))
        return 2
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
