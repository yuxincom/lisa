from __future__ import annotations

"""齐套九要素实算与外部主数据接入测试（P0-5）。

断言的是「缺口算得对不对、能不能追责到部门」，不是接口返回 200：
数据缺失必须显式判为未接入，缺料数量、ETA 覆盖、寿命不足、资质过期都要落到具体数字。
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    Inbound,
    Inspection,
    Material,
    Operation,
    Order,
    Product,
    Qualification,
    Resource,
    StockItem,
    Tool,
    User,
)
from app.services.calendar import align_to_work
from app.services.kit_data import KitDataError, data_freshness, upsert_rows
from app.services.kits import build_check, persist_check
from app.services.rules import validate_schedule


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(User(username="admin", password_hash="x", name="管理员", role="admin", clearance="内部"))
    product = Product(
        code="LY-K01", name="试验件-K01", family="试验族", priority_class="P1",
        route=[{
            "seq": 1, "name": "粗铣", "domain": "机加", "resource_type": "机加",
            "std_minutes": 120.0, "setup_minutes": 20.0, "special": True,
        }],
    )
    session.add(product)
    session.flush()
    session.add(Resource(
        code="MC-K01", name="三轴加工中心", domain="机加", capacity_hours=12.0, efficiency=1.0,
        status="running", machine_count=1, capabilities=["机加"],
    ))
    session.add(Order(
        order_no="MO-K01", product_id=product.id, product_name=product.name, qty=4, priority="P1",
        plant="一厂", customer="试验客户", due_date=datetime.now() + timedelta(days=30),
        status="已排产", progress=0, kit_status="齐套",
    ))
    session.flush()
    return session


def _order(db: Session) -> Order:
    return db.query(Order).first()


def _status(check: dict, key: str) -> str:
    return next(element["status"] for element in check["elements"] if element["key"] == key)


def _gap(check: dict, key: str) -> dict:
    return next(gap for gap in check["gaps"] if gap["key"] == key)


def test_missing_external_data_is_reported_not_faked(db: Session):
    check = build_check(db, _order(db), "pre_schedule")
    assert check["status"] == "待接入"
    # 只有本厂台账能判定的 3 项算分，6 项外部源未接入既不计分也不算通过
    assert check["evaluated_count"] == 3
    assert check["score"] == 33.3
    assert check["gaps"] == []
    assert sorted(check["unevaluated"]) == sorted(["工装", "主材", "辅材", "刀具", "人员资质", "WIP 质量状态"])
    assert _status(check, "equipment") == "ok"
    assert _status(check, "capability") == "ok"
    assert _status(check, "route") == "ok"

    check = persist_check(db, _order(db), "pre_start")
    assert check.status == "待接入"
    assert _order(db).kit_status == "待接入"


def test_material_shortage_is_quantified(db: Session):
    actor = db.query(User).first()
    upsert_rows(db, "materials", [
        {"code": "MT-01", "name": "高温合金棒料", "unit": "kg", "category": "main_material",
         "product_code": "LY-K01", "qty_per": "1.0", "lead_time_days": "45"},
        {"code": "MT-02", "name": "工艺垫片", "unit": "件", "category": "aux_material",
         "product_code": "LY-K01", "qty_per": "2"},
    ], actor)
    upsert_rows(db, "stock", [
        {"material_code": "MT-01", "on_hand": "2.5", "allocated": "0.5", "quality_status": "合格"},
        {"material_code": "MT-02", "on_hand": "8", "allocated": "0", "quality_status": "合格"},
    ], actor)

    check = build_check(db, _order(db), "pre_schedule")
    assert _status(check, "main_material") == "missing"
    assert "缺 2.0kg" in _gap(check, "main_material")["reason"]
    assert _gap(check, "main_material")["owner"] == "采购部"
    assert _gap(check, "main_material")["critical"] is True
    assert _status(check, "aux_material") == "ok"
    assert check["status"] == "缺项"


def test_inbound_eta_decides_pre_start_blocking(db: Session):
    actor = db.query(User).first()
    upsert_rows(db, "materials", [
        {"code": "MT-01", "name": "高温合金棒料", "category": "main_material",
         "product_code": "LY-K01", "qty_per": "1.0"},
    ], actor)
    upsert_rows(db, "stock", [{"material_code": "MT-01", "on_hand": "1", "allocated": "0"}], actor)
    upsert_rows(db, "inbound", [
        {"reference": "PO-9001", "material_code": "MT-01", "qty": "3",
         "eta": (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d %H:%M"), "supplier": "宝特"},
    ], actor)

    before = build_check(db, _order(db), "pre_schedule")
    assert _status(before, "main_material") == "ok"

    start_check = build_check(db, _order(db), "pre_start")
    assert _status(start_check, "main_material") == "missing"
    assert start_check["status"] == "阻断"
    assert start_check["passed"] is False

    db.query(Inbound).update({"status": "延期"})
    db.flush()
    late = build_check(db, _order(db), "pre_schedule")
    assert _status(late, "main_material") == "missing"
    assert "缺 3.0" in _gap(late, "main_material")["reason"]


def test_tooling_cutter_and_quality_gaps_are_attributed(db: Session):
    actor = db.query(User).first()
    upsert_rows(db, "tools", [
        {"code": "TZ-01", "name": "叶盘定位工装", "kind": "tooling", "domain": "机加", "status": "检修"},
        {"code": "CT-01", "name": "硬质合金铣刀", "kind": "cutter", "domain": "机加",
         "status": "可用", "life_remaining": "12"},
    ], actor)
    upsert_rows(db, "inspections", [
        {"order_no": "MO-K01", "seq": "1", "conclusion": "待判", "inspector": "张检"},
    ], actor)

    check = build_check(db, _order(db), "pre_schedule")
    assert _status(check, "tooling") == "missing"
    assert _gap(check, "tooling")["owner"] == "工装室"
    assert _status(check, "cutter") == "missing"
    assert "12%" in _gap(check, "cutter")["reason"]
    assert _status(check, "wip") == "missing"
    assert _gap(check, "wip")["owner"] == "质量部"
    assert _status(check, "equipment") == "ok"


def test_expired_qualification_breaks_skill_and_hc10(db: Session):
    actor = db.query(User).first()
    upsert_rows(db, "qualifications", [
        {"person_name": "王师傅", "capability": "机加", "certificate": "GJ-2024-118",
         "valid_until": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")},
    ], actor)

    check = build_check(db, _order(db), "pre_schedule")
    assert _status(check, "skill") == "missing"
    assert "机加" in _gap(check, "skill")["reason"]

    order = _order(db)
    op = Operation(
        order_id=order.id, seq=1, name="粗铣", domain="机加", resource_type="机加",
        std_minutes=120.0, setup_minutes=20.0, status="待开工", risk="normal",
    )
    db.add(op)
    db.flush()
    # 落在班次内，保证这里唯一的违规来自资质而不是日历
    start = align_to_work(datetime.now() + timedelta(days=1))
    item = SimpleNamespace(
        order_id=order.id, operation_id=op.id, order_no=order.order_no, product_name=order.product_name,
        priority="P1", seq=1, name="粗铣", domain="机加", resource_id=db.query(Resource).first().id,
        start=start, end=align_to_work(start + timedelta(minutes=120)),
        duration_minutes=120.0, setup_minutes=0.0, risk="normal", locked=False, transfer_minutes=0,
    )
    result = validate_schedule(db, [item])
    hc10 = next(c for c in result["checks"] if c["code"] == "HC-10")
    assert hc10["evaluated"] is True
    assert hc10["count"] == 1
    assert result["unevaluated"] == []
    assert result["hard_count"] == 1

    db.query(Qualification).update({"valid_until": datetime.now() + timedelta(days=300)})
    db.flush()
    renewed = validate_schedule(db, [item])
    assert renewed["hard_count"] == 0
    assert _status(build_check(db, order, "pre_schedule"), "skill") == "ok"


def test_kit_data_upsert_is_idempotent_and_tracked(db: Session):
    actor = db.query(User).first()
    rows = [{"material_code": "MT-01", "on_hand": "10", "allocated": "2", "quality_status": "合格"}]
    first = upsert_rows(db, "stock", rows, actor)
    assert (first["created"], first["updated"], first["unchanged"]) == (1, 0, 0)

    again = upsert_rows(db, "stock", rows, actor)
    assert (again["created"], again["updated"], again["unchanged"]) == (0, 0, 1)

    changed = upsert_rows(db, "stock", [{"material_code": "MT-01", "on_hand": "4", "allocated": "0"}], actor)
    assert changed["updated"] == 1
    stock = db.query(StockItem).one()
    assert stock.available == 4.0
    assert len(data_freshness(db)["stock"]["as_of"]) >= 10


@pytest.mark.parametrize(
    "kind,rows,code",
    [
        ("stock", [{"material_code": "MT-01", "on_hand": "-1"}], "KIT_ROW_INVALID"),
        ("stock", [{"material_code": "MT-01", "on_hand": "1", "allocated": "5"}], "KIT_ROW_INVALID"),
        ("stock", [{"material_code": "MT-01", "on_hand": "1", "quality_status": "报废"}], "KIT_ROW_INVALID"),
        ("materials", [{"code": "", "qty_per": "1"}], "KIT_ROW_INVALID"),
        ("materials", [{"code": "MT-09", "qty_per": "0"}], "KIT_ROW_INVALID"),
        ("inbound", [{"reference": "PO-1", "material_code": "MT-01", "qty": "2"}], "KIT_ROW_INVALID"),
        ("inbound", [{"reference": "PO-1", "material_code": "MT-01", "qty": "2", "eta": "下周三"}], "KIT_ROW_INVALID"),
        ("tools", [{"code": "TZ-1", "kind": "夹具"}], "KIT_ROW_INVALID"),
        ("tools", [{"code": "TZ-1", "kind": "cutter", "life_remaining": "180"}], "KIT_ROW_INVALID"),
        ("qualifications", [{"person_name": "", "capability": "机加"}], "KIT_ROW_INVALID"),
        ("inspections", [{"order_no": "MO-1", "seq": "0"}], "KIT_ROW_INVALID"),
        ("materials", [], "KIT_DATA_EMPTY"),
    ],
)
def test_bad_kit_rows_are_rejected(db: Session, kind: str, rows: list[dict], code: str):
    with pytest.raises(KitDataError) as exc:
        upsert_rows(db, kind, rows, db.query(User).first())
    assert exc.value.code == code


def test_bom_without_coverage_is_a_gap_not_a_pass(db: Session):
    actor = db.query(User).first()
    upsert_rows(db, "materials", [
        {"code": "MT-01", "name": "其他产品用料", "category": "main_material",
         "product_code": "LY-OTHER", "qty_per": "1"},
    ], actor)
    check = build_check(db, _order(db), "pre_schedule")
    assert _status(check, "main_material") == "missing"
    assert "未从 ERP 展开" in _gap(check, "main_material")["reason"]


def test_offline_resource_blocks_equipment_element(db: Session):
    resource = db.query(Resource).first()
    resource.status = "故障"
    db.flush()
    check = build_check(db, _order(db), "pre_schedule")
    assert _status(check, "equipment") == "missing"
    assert "MC-K01（故障）" in _gap(check, "equipment")["reason"]

    resource.status = "running"
    resource.maintenance_until = datetime.now() + timedelta(hours=6)
    db.flush()
    check = build_check(db, _order(db), "pre_schedule")
    assert "保养至" in _gap(check, "equipment")["reason"]
