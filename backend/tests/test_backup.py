from __future__ import annotations

"""备份/恢复：快照可校验、篡改能发现、恢复可跨库，且破坏性动作必须显式确认。

沙箱用独立的 SQLite 文件，恢复是整库清空动作，不能碰会话级共享测试库。
"""

import gzip
import hashlib
import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401 - 建表前先把全部表登记进 metadata
from app.database import Base
from app.models import AuditLog, Order, Product, User
from app.services import backup as bk
from app.services.audit import append_audit


def _box(tmp_path, name="box"):
    engine = create_engine(f"sqlite:///{(tmp_path / f'{name}.db').as_posix()}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    session.add_all(
        [
            User(username="admin", password_hash="x", name="管理员", role="admin", clearance="机密"),
            Product(code="P-1", name="涡扇机匣", family="机匣", route=["下料", "机加"]),
            Order(
                order_no="WO-1",
                product_id=1,
                product_name="涡扇机匣",
                qty=4,
                due_date=datetime.now() + timedelta(days=7),
                clearance="秘密",
            ),
        ]
    )
    append_audit(session, "admin", "admin", "seed.box", "box", "1")
    session.commit()
    return session


@pytest.fixture()
def box(tmp_path, monkeypatch):
    monkeypatch.setenv("LISA_BACKUP_DIR", str(tmp_path / "backups"))
    session = _box(tmp_path)
    yield session
    session.close()


def test_backup_snapshot_is_verifiable(box):
    summary = bk.create(box)
    directory = bk.backup_dir()
    assert summary["total_rows"] == 4
    assert summary["row_counts"]["audit_logs"] == 1
    for suffix in ("", bk.SHA_SUFFIX, bk.META_SUFFIX):
        assert (directory / (summary["file"] + suffix)).is_file()

    meta = json.loads((directory / (summary["file"] + bk.META_SUFFIX)).read_text(encoding="utf-8"))
    assert meta["row_counts"]["users"] == 1
    assert summary["audit_head_hash"] == meta["audit_head_hash"]

    checked = bk.verify(summary["file"])
    assert checked["ok"] and checked["total_rows"] == 4
    assert checked["unknown_tables"] == []
    assert summary["native"]["dump"]
    assert len(summary["audit_ref"]) <= 40


def test_connection_string_never_carries_the_password(monkeypatch):
    monkeypatch.setattr(bk, "DATABASE_URL", "postgresql://lisa:s3cr3t@10.0.0.9:5432/lisa")
    assert bk._safe_url() == "postgresql://lisa:***@10.0.0.9:5432/lisa"


def test_tampering_is_detected_at_both_layers(box):
    summary = bk.create(box)
    path = bk.backup_dir() / summary["file"]
    blob = path.read_bytes()
    tampered = bytearray(blob)
    tampered[40] ^= 0xFF
    path.write_bytes(bytes(tampered))
    with pytest.raises(bk.BackupError) as first:
        bk.verify(summary["file"])
    assert first.value.code == "BACKUP_CHECKSUM_MISMATCH"

    # 攻击者连 .sha256 一起改掉：内容摘要仍然拦得住
    payload = json.loads(gzip.decompress(blob).decode("utf-8"))
    payload["data"]["users"][0]["role"] = "commander"
    forged = gzip.compress(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), mtime=0)
    path.write_bytes(forged)
    (bk.backup_dir() / (summary["file"] + bk.SHA_SUFFIX)).write_text(
        f"{hashlib.sha256(forged).hexdigest()}  {summary['file']}\n", encoding="utf-8"
    )
    with pytest.raises(bk.BackupError) as second:
        bk.verify(summary["file"])
    assert second.value.code == "BACKUP_DIGEST_MISMATCH"


def test_restore_rolls_the_box_back_to_the_snapshot(box):
    summary = bk.create(box)
    box.add(Order(order_no="WO-LATE", product_id=1, product_name="后补的单", due_date=datetime.now()))
    append_audit(box, "admin", "admin", "order.create", "order", "WO-LATE")
    box.commit()
    assert box.query(Order).filter(Order.order_no == "WO-LATE").count() == 1

    result = bk.restore(box, summary["file"], confirmed=True)
    box.expire_all()
    assert box.query(Order).filter(Order.order_no == "WO-LATE").count() == 0
    assert box.query(Order).count() == summary["row_counts"]["orders"]
    assert box.query(User).first().role == "admin"
    assert result["audit_chain"]["ok"] is True
    assert result["total_rows"] == summary["total_rows"]

    box.add(Order(order_no="WO-NEXT", product_id=1, product_name="恢复后新增", due_date=datetime.now()))
    box.commit()
    assert box.query(Order).filter(Order.order_no == "WO-NEXT").first().id > 1


def test_restore_into_an_empty_database(tmp_path, box, monkeypatch):
    monkeypatch.setenv("LISA_BACKUP_DIR", str(tmp_path / "backups"))
    summary = bk.create(box)
    other = _box(tmp_path, name="other")
    other.query(Order).delete()
    other.query(User).delete()
    other.commit()

    result = bk.restore(other, summary["file"], confirmed=True)
    other.expire_all()
    assert result["row_counts"] == summary["row_counts"]
    assert other.query(Order).first().clearance == "秘密"
    assert other.query(User).first().username == "admin"
    other.close()


def test_restore_requires_confirmation_and_a_real_file(box):
    summary = bk.create(box)
    with pytest.raises(bk.BackupError) as unconfirmed:
        bk.restore(box, summary["file"])
    assert unconfirmed.value.code == "BACKUP_CONFIRM_REQUIRED"

    with pytest.raises(bk.BackupError) as missing:
        bk.restore(box, "lisa-backup-19700101-000000.000000-abcdef01.json.gz", confirmed=True)
    assert missing.value.code == "BACKUP_FILE_MISSING"


def test_prune_keeps_only_the_newest(box):
    created = [bk.create(box, keep=2)["file"] for _ in range(3)]
    files = [path.name for path in bk.snapshot_files()]
    assert files == [created[2], created[1]]
    assert created[0] not in files
    assert not (bk.backup_dir() / (created[0] + bk.META_SUFFIX)).exists()
    assert [item["file"] for item in bk.list_backups()] == files


def test_resolve_name_refuses_paths_outside_the_backup_dir(box):
    with pytest.raises(bk.BackupError) as traversal:
        bk.resolve_name("../../etc/passwd")
    assert traversal.value.code == "BACKUP_NAME_INVALID"

    bk.create(box)
    newest = bk.snapshot_files()[0]
    assert bk.resolve_name(newest.name).name == newest.name


def test_backup_admin_endpoints(client, admin, planner, db):
    created = client.post("/api/system/backups", headers=admin)
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["total_rows"] > 0 and len(body["checksum"]) == 64

    db.expire_all()
    logged = db.query(AuditLog).filter(AuditLog.action == "backup.create").order_by(AuditLog.seq.desc()).first()
    # PG 上 target_id 只有 40 字符，超长的文件名必须换行放进 detail
    assert logged is not None and len(logged.target_id) <= 40
    assert logged.detail["file"] == body["file"]

    listing = client.get("/api/system/backups", headers=admin)
    assert listing.status_code == 200
    assert body["file"] in [item["file"] for item in listing.json()["items"]]
    assert listing.json()["restore"]

    verified = client.post("/api/system/backups/verify", json={"name": body["file"]}, headers=admin)
    assert verified.status_code == 200 and verified.json()["ok"] is True

    assert client.post("/api/system/backups", headers=planner).status_code == 403
    assert client.get("/api/system/backups", headers=planner).status_code == 403

    traversal = client.post("/api/system/backups/verify", json={"name": "../lisa-test.db"}, headers=admin)
    assert traversal.status_code == 422
    assert traversal.json()["detail"]["code"] == "BACKUP_NAME_INVALID"
    gone = client.post(
        "/api/system/backups/verify", json={"name": "lisa-backup-19700101-000000.000000-abcdef01.json.gz"}, headers=admin
    )
    assert gone.status_code == 404
