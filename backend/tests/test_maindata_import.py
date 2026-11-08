from __future__ import annotations

"""主数据导入测试（投产配置清单 A1/A2 台账 + C2 工序依赖）。

台账是排产能力的唯一权威来源：导入必须可校验、可留痕、幂等，
并且真正改变排程结果——否则「导入成功」只是数字游戏。
"""

import csv
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.management import read_csv
from app.models import AuditLog, Operation, Order, Product, Resource, User
from app.security import hash_password
from app.services.maindata import LedgerError, apply_dependencies, apply_machine_ledger
from app.services.scheduler import generate_schedule


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    admin = User(
        username="admin", password_hash=hash_password("admin123"), name="信息管理员",
        role="admin", clearance="机密", department="信息科",
    )
    session.add(admin)
    session.flush()
    return session


def _actor(db: Session) -> User:
    return db.query(User).filter(User.role == "admin").first()


def _resource(db: Session, code: str, **overrides) -> Resource:
    fields = {
        "code": code, "name": f"设备{code}", "domain": "机加", "capacity_hours": 12.0,
        "efficiency": 1.0, "bottleneck": False, "status": "running", "machine_count": 1,
    }
    fields.update(overrides)
    resource = Resource(**fields)
    db.add(resource)
    db.flush()
    return resource


def _write_ledger(path: Path, rows: list[dict]) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["code", "name", "domain", "machine_count", "capacity_hours",
                        "efficiency", "bottleneck", "capabilities"],
        )
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_ledger_csv_parses_chinese_flags_and_bom(tmp_path: Path, db: Session):
    path = _write_ledger(
        tmp_path / "ledger.csv",
        [
            {"code": "MC-01", "name": "加工中心", "domain": "机加", "machine_count": "3",
             "capacity_hours": "16", "efficiency": "0.9", "bottleneck": "是", "capabilities": "机加"},
            {"code": "MC-02", "name": "数控车床", "domain": "机加", "machine_count": "1",
             "capacity_hours": "", "efficiency": "", "bottleneck": "否", "capabilities": "机加"},
        ],
    )
    rows = read_csv(path)
    assert len(rows) == 2
    _resource(db, "MC-01")
    _resource(db, "MC-02")
    result = apply_machine_ledger(db, rows, _actor(db))
    assert result["updated"] == 2
    assert result["total_lanes"] == 4
    assert result["multi_lane_resources"] == 1

    mc01 = db.query(Resource).filter(Resource.code == "MC-01").first()
    assert mc01.machine_count == 3
    assert mc01.capacity_hours == 16.0
    assert mc01.efficiency == 0.9
    assert mc01.bottleneck is True
    assert mc01.capabilities == ["机加"]
    assert db.query(AuditLog).filter(AuditLog.action == "maindata.machine_ledger").count() == 2


def test_ledger_reimport_is_idempotent(tmp_path: Path, db: Session):
    rows = [{"code": "MC-01", "machine_count": "2", "capabilities": "机加"}]
    _resource(db, "MC-01")
    assert apply_machine_ledger(db, rows, _actor(db))["updated"] == 1
    again = apply_machine_ledger(db, rows, _actor(db))
    assert again["updated"] == 0
    assert again["unchanged"] == 1


def test_ledger_rejects_bad_master_data(tmp_path: Path, db: Session):
    _resource(db, "MC-01")
    cases = [
        ([], "LEDGER_EMPTY"),
        ([{"code": "MC-01", "machine_count": 1}, {"code": "MC-01", "machine_count": 2}], "LEDGER_DUPLICATE"),
        ([{"code": "MC-01", "machine_count": 0}], "LEDGER_ROW_INVALID"),
        ([{"code": "MC-01", "machine_count": 99}], "LEDGER_ROW_INVALID"),
        ([{"code": "MC-01", "machine_count": 2, "capabilities": "喷涂"}], "LEDGER_DOMAIN_UNKNOWN"),
        ([{"code": "MC-01", "machine_count": 2, "efficiency": "9"}], "LEDGER_ROW_INVALID"),
    ]
    for rows, code in cases:
        with pytest.raises(LedgerError) as exc:
            apply_machine_ledger(db, rows, _actor(db))
        assert exc.value.code == code, rows


def test_ledger_codes_absent_from_db_are_reported(db: Session):
    _resource(db, "MC-01")
    result = apply_machine_ledger(
        db,
        [{"code": "MC-01", "machine_count": 2, "capabilities": []},
         {"code": "GHOST-01", "machine_count": 2, "capabilities": []}],
        _actor(db),
    )
    assert result["unknown_codes"] == ["GHOST-01"]
    assert result["updated"] == 1


def test_ledger_lanes_change_the_schedule(db: Session):
    """导入 2 个并行机位后，两张单必须真的能同时开工。"""
    route = [{
        "seq": 1, "name": "粗铣", "domain": "机加", "resource_type": "机加",
        "std_minutes": 120.0, "setup_minutes": 20.0, "special": False,
    }]
    product = Product(code="PT-LANE", name="并行试验件", family="试验族", priority_class="P1", route=route)
    db.add(product)
    db.flush()
    due = datetime.now() + timedelta(days=90)
    for no in ("SO-LANE-1", "SO-LANE-2"):
        db.add(Order(order_no=no, product_id=product.id, product_name=product.name, qty=1,
                     priority="P1", due_date=due, status="已排产", kit_status="齐套"))
    _resource(db, "MC-LANE")
    db.flush()

    serial = generate_schedule(db, scenario="A", freeze=False)["items"]
    assert len(serial) == 2 and serial[0].start != serial[1].start

    apply_machine_ledger(db, [{"code": "MC-LANE", "machine_count": 2, "capabilities": []}], _actor(db))
    parallel = generate_schedule(db, scenario="A", freeze=False)
    assert [i.start for i in parallel["items"]] == [parallel["items"][0].start] * 2
    assert parallel["summary"]["resource_lanes"] == 2
    assert parallel["violations"]["hard_count"] == 0


def test_dependency_csv_wires_cross_order_operations(db: Session):
    route = [{
        "seq": 1, "name": "粗铣", "domain": "机加", "resource_type": "机加",
        "std_minutes": 120.0, "setup_minutes": 20.0, "special": False,
    }]
    product = Product(code="PT-DEP", name="依赖试验件", family="试验族", priority_class="P1", route=route)
    db.add(product)
    db.flush()
    due = datetime.now() + timedelta(days=90)
    orders = {}
    for no in ("SO-D-1", "SO-D-2", "SO-D-3"):
        order = Order(order_no=no, product_id=product.id, product_name=product.name, qty=1,
                      priority="P1", due_date=due, status="已排产", kit_status="齐套")
        db.add(order)
        db.flush()
        orders[no] = order
        db.add(Operation(order_id=order.id, seq=1, name="粗铣", domain="机加", resource_type="机加",
                         std_minutes=120.0, setup_minutes=20.0, status="待开工", risk="normal"))
    db.flush()

    result = apply_dependencies(
        db,
        [
            {"order_no": "SO-D-2", "seq": "1", "predecessor_order_no": "SO-D-1",
             "predecessor_seq": "1", "lag_minutes": "90"},
            {"order_no": "SO-D-3", "seq": "1", "predecessor_order_no": "SO-MISSING",
             "predecessor_seq": "1", "lag_minutes": "0"},
            {"order_no": "SO-D-1", "seq": "1", "predecessor_order_no": "SO-D-1",
             "predecessor_seq": "1", "lag_minutes": "0"},
        ],
        _actor(db),
    )
    assert result["linked"] == 1
    assert result["missing_orders"] == ["SO-MISSING"]
    assert result["self_references"] == ["SO-D-1#1"]

    second = db.query(Operation).filter(Operation.order_id == orders["SO-D-2"].id).first()
    assert second.predecessor_id == db.query(Operation).filter(
        Operation.order_id == orders["SO-D-1"].id
    ).first().id
    assert second.lag_minutes == 90.0
    assert db.query(AuditLog).filter(AuditLog.action == "maindata.operation_dependency").count() == 1

    _resource(db, "MC-DEP", machine_count=2)
    scheduled = generate_schedule(db, scenario="A", freeze=False)
    by_order = {i.order_no: i for i in scheduled["items"]}
    assert by_order["SO-D-2"].start >= by_order["SO-D-1"].end + timedelta(minutes=90)
    assert scheduled["summary"]["dependency_cycles"] == []


def test_dependency_rejects_negative_gap(db: Session):
    with pytest.raises(LedgerError) as exc:
        apply_dependencies(
            db,
            [{"order_no": "A", "seq": 1, "predecessor_order_no": "B", "predecessor_seq": 1, "lag_minutes": "-1"}],
            _actor(db),
        )
    assert exc.value.code == "LEDGER_ROW_INVALID"


def test_cli_dry_run_leaves_database_unchanged(tmp_path: Path):
    """干跑必须只校验、不落库——投产前先让计划员看见差分。"""
    from app import management
    from app.management import main

    scratch = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(scratch)
    session = sessionmaker(bind=scratch)()
    session.add(User(username="admin", password_hash=hash_password("x"), name="管理员", role="admin"))
    session.add(Resource(code="MC-DRY", name="干跑设备", domain="机加", capacity_hours=12.0,
                         efficiency=1.0, machine_count=1, status="running"))
    session.commit()
    original = management.SessionLocal
    management.SessionLocal = sessionmaker(bind=scratch)
    try:
        path = _write_ledger(tmp_path / "dry.csv", [{"code": "MC-DRY", "machine_count": "5", "capabilities": ""}])
        assert main(["ledger", str(path), "--dry-run"]) == 0
        assert session.query(Resource).filter(Resource.code == "MC-DRY").first().machine_count == 1
        audit_rows = session.query(AuditLog).count()
        assert main(["ledger", str(path)]) == 0
        assert session.query(Resource).filter(Resource.code == "MC-DRY").first().machine_count == 5
        assert session.query(AuditLog).count() > audit_rows
    finally:
        management.SessionLocal = original
        session.close()
