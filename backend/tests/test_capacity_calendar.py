from __future__ import annotations

"""工作日历与有限产能的正确性测试。

这里断言的是排程「算得对不对」，不是接口返回 200：
日历换算、并行机位占用、超限判定、无能力匹配时阻断。
"""

from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Operation, Order, Product, Resource
from app.services.calendar import (
    CalendarConfigError,
    CalendarHorizonError,
    WorkCalendar,
    normalize_config,
)
from app.services.rules import validate_schedule
from app.services.scheduler import generate_schedule


def monday() -> datetime:
    """以「今天所在周的周一 00:00」为锚点，避免测试依赖具体日历。"""
    today = date.today()
    return datetime.combine(today - timedelta(days=today.weekday()), time(0, 0))


def two_shift() -> WorkCalendar:
    return WorkCalendar.from_config(
        {
            "shifts": [
                {"name": "白班", "start": "08:00", "end": "16:00"},
                {"name": "中班", "start": "16:00", "end": "24:00"},
            ],
            "workdays": [0, 1, 2, 3, 4],
        }
    )


def test_two_shift_adds_across_shifts_and_days():
    cal = two_shift()
    start = monday().replace(hour=8)
    assert cal.add_minutes(start, 8 * 60) == start.replace(hour=16)
    assert cal.add_minutes(start, 9 * 60) == start.replace(hour=17)
    assert cal.day_capacity_minutes(start.date()) == 16 * 60
    # 两班共 960 分钟，做 990 分钟必须滚到次日白班
    assert cal.add_minutes(start, 16 * 60 + 30) == (start + timedelta(days=1)).replace(hour=8, minute=30)


def test_overnight_shift_tail_is_workable_next_morning():
    cal = WorkCalendar.from_config(
        {"shifts": [{"name": "夜班", "start": "22:00", "end": "06:00"}], "workdays": [0, 1, 2, 3, 4]}
    )
    start = monday().replace(hour=22)
    assert cal.add_minutes(start, 8 * 60) == (start + timedelta(days=1)).replace(hour=6)
    tail = (start + timedelta(days=1)).replace(hour=0)
    assert cal.minutes_between(tail, tail + timedelta(hours=7)) == 360
    # 07:00 已下班，下一个可用时段是当天 22:00 的夜班起点
    assert cal.align(tail + timedelta(hours=7)) == tail + timedelta(hours=22)


def test_holiday_and_workday_override():
    base = monday()
    holiday = base.date()
    forced = (base + timedelta(days=5)).date()
    cal = WorkCalendar.from_config(
        {
            "shifts": [{"name": "白班", "start": "08:00", "end": "16:00"}],
            "workdays": [0, 1, 2, 3, 4],
            "holidays": [holiday.isoformat()],
            "workday_overrides": [forced.isoformat()],
        }
    )
    assert cal.day_capacity_minutes(holiday) == 0
    assert cal.day_capacity_minutes(forced) == 480
    assert cal.add_minutes(base.replace(hour=8), 60) == (base + timedelta(days=1)).replace(hour=9)


def test_legacy_shift_setting_maps_to_same_calendar():
    cal = WorkCalendar.from_config(normalize_config({"shift": {"start": 8, "end": 20, "days": 6}}))
    base = monday()
    assert cal.day_capacity_minutes(base.date()) == 12 * 60
    assert cal.is_production_day((base + timedelta(days=5)).date())
    assert not cal.is_production_day((base + timedelta(days=6)).date())


def test_full_shutdown_raises_instead_of_silently_truncating():
    cal = WorkCalendar.from_config(
        {"shifts": [{"name": "白班", "start": "08:00", "end": "16:00"}], "workdays": [], "horizon_days": 30}
    )
    with pytest.raises(CalendarHorizonError):
        cal.align(datetime.now())


@pytest.mark.parametrize(
    "config",
    [
        {"shifts": [{"name": "A", "start": "08:00", "end": "16:00"}, {"name": "B", "start": "14:00", "end": "20:00"}]},
        {"shifts": [{"name": "A", "start": "8am", "end": "16:00"}]},
        {"shifts": [{"name": "A", "start": "08:00", "end": "08:00"}]},
        {"shifts": [{"name": "A", "start": "08:00", "end": "25:00"}]},
        {"shifts": [{"name": "A", "start": "08:00", "end": "16:00"}], "workdays": [0, 8]},
        {"shifts": [{"name": "A", "start": "08:00", "end": "16:00"}], "holidays": ["2026-13-45"]},
        {"shifts": []},
    ],
)
def test_invalid_calendar_rejected(config):
    with pytest.raises(CalendarConfigError):
        WorkCalendar.from_config(config)


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _resource(db: Session, code: str, **overrides) -> Resource:
    fields = {
        "code": code,
        "name": f"设备{code}",
        "domain": "机加",
        "capacity_hours": 12.0,
        "efficiency": 1.0,
        "bottleneck": False,
        "status": "running",
        "machine_count": 1,
        "capabilities": ["机加"],
    }
    fields.update(overrides)
    resource = Resource(**fields)
    db.add(resource)
    db.flush()
    return resource


def _item(resource: Resource, start: datetime, end: datetime, seq: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        order_id=1,
        operation_id=None,
        order_no=f"SO-{seq}",
        product_name="试件",
        priority="P1",
        seq=seq,
        name="粗铣",
        domain="机加",
        resource_id=resource.id,
        start=start,
        end=end,
        duration_minutes=(end - start).total_seconds() / 60,
        setup_minutes=0.0,
        risk="normal",
        locked=False,
    )


def test_overlap_beyond_machine_count_is_a_hard_violation(db: Session):
    resource = _resource(db, "MC-01", machine_count=1)
    base = monday()
    items = [
        _item(resource, base.replace(hour=8), base.replace(hour=10), seq=1),
        _item(resource, base.replace(hour=9), base.replace(hour=11), seq=2),
    ]
    result = validate_schedule(db, items)
    hc09 = next(check for check in result["checks"] if check["code"] == "HC-09")
    assert hc09["passed"] is False
    assert result["hard_count"] >= 1

    resource.machine_count = 2
    db.flush()
    result = validate_schedule(db, items)
    hc09 = next(check for check in result["checks"] if check["code"] == "HC-09")
    assert hc09["passed"] is True


def test_touching_intervals_are_not_overlapping(db: Session):
    resource = _resource(db, "MC-02", machine_count=1)
    base = monday()
    items = [
        _item(resource, base.replace(hour=8), base.replace(hour=10), seq=1),
        _item(resource, base.replace(hour=10), base.replace(hour=12), seq=2),
    ]
    result = validate_schedule(db, items)
    assert next(c for c in result["checks"] if c["code"] == "HC-09")["passed"] is True


def _order(db: Session, order_no: str, product: Product, due: datetime) -> Order:
    order = Order(
        order_no=order_no,
        product_id=product.id,
        product_name=product.name,
        qty=1,
        priority="P1",
        due_date=due,
        status="已排产",
        kit_status="齐套",
    )
    db.add(order)
    db.flush()
    return order


def _product(db: Session, code: str, resource_type: str = "机加", std: float = 240.0) -> Product:
    product = Product(
        code=code,
        name=f"产品{code}",
        family="试验族",
        priority_class="P1",
        route=[
            {
                "seq": 1,
                "name": "粗铣",
                "domain": "机加",
                "resource_type": resource_type,
                "std_minutes": std,
                "setup_minutes": 20.0,
                "special": False,
            }
        ],
    )
    db.add(product)
    db.flush()
    return product


def test_parallel_lanes_let_two_orders_run_simultaneously(db: Session):
    product = _product(db, "PT-01")
    _resource(db, "MC-10", machine_count=2)
    due = datetime.now() + timedelta(days=90)
    _order(db, "SO-101", product, due)
    _order(db, "SO-102", product, due)

    result = generate_schedule(db, scenario="A", freeze=False)
    items = result["items"]
    assert len(items) == 2
    assert items[0].start == items[1].start
    assert result["violations"]["hard_count"] == 0


def test_single_lane_forces_serialization(db: Session):
    product = _product(db, "PT-02")
    _resource(db, "MC-20", machine_count=1)
    due = datetime.now() + timedelta(days=90)
    _order(db, "SO-201", product, due)
    _order(db, "SO-202", product, due)

    items = generate_schedule(db, scenario="A", freeze=False)["items"]
    assert len(items) == 2
    assert items[1].start >= items[0].end


def test_efficiency_stretches_duration(db: Session):
    product = _product(db, "PT-03", std=240.0)
    fast = _resource(db, "MC-30", efficiency=1.0)
    slow = _resource(db, "MC-31", efficiency=0.8, domain="机加")
    due = datetime.now() + timedelta(days=90)
    order = _order(db, "SO-301", product, due)

    fast_result = generate_schedule(db, scenario="A", freeze=False)["items"][0]
    assert fast_result.resource_id == fast.id
    assert fast_result.duration_minutes == pytest.approx(260.0, abs=0.5)

    db.query(Resource).filter(Resource.id == fast.id).update({"status": "offline"})
    db.flush()
    slow_result = generate_schedule(db, scenario="A", freeze=False)["items"][0]
    assert slow_result.resource_id == slow.id
    assert slow_result.duration_minutes == pytest.approx(320.0, abs=0.5)


def test_missing_capability_unassigned_and_blocks(db: Session):
    product = _product(db, "PT-04", resource_type="五轴铣")
    _resource(db, "MC-40", capabilities=["三轴铣"])
    _order(db, "SO-401", product, datetime.now() + timedelta(days=30))

    result = generate_schedule(db, scenario="A", freeze=False)
    assert result["items"] == []
    assert len(result["unassigned"]) == 1
    assert result["summary"]["unassigned_operations"] == 1
    hc09 = next(check for check in result["violations"]["checks"] if check["code"] == "HC-09")
    assert hc09["passed"] is False


def _lane_item(resource, start, end, seq=1, transfer=0):
    item = _item(resource, start, end, seq)
    item.transfer_minutes = transfer
    return item


def test_align_never_moves_a_moment_earlier():
    cal = WorkCalendar.from_config({
        "shifts": [{"name": "白班", "start": "08:00", "end": "20:00"}],
        "workdays": [0, 1, 2, 3, 4, 5],
    })
    inside = monday().replace(hour=9) + timedelta(minutes=30, seconds=30)
    aligned = cal.align(inside)
    assert aligned >= inside
    assert aligned == monday().replace(hour=9, minute=31)
    outside = monday().replace(hour=6, minute=30)
    assert cal.align(outside) == monday().replace(hour=8)


def test_transfer_gap_shortfall_violates_hc12(db: Session):
    resource = _resource(db, "MC-01")
    base = monday()
    first = _lane_item(resource, base, base + timedelta(minutes=60), seq=1)
    second = _lane_item(resource, base + timedelta(minutes=80), base + timedelta(minutes=140), seq=2, transfer=30)
    checks = {c["code"]: c for c in validate_schedule(db, [first, second])["checks"]}
    assert checks["HC-12"]["count"] == 1


def test_transfer_gap_satisfied_is_clean(db: Session):
    resource = _resource(db, "MC-01")
    base = monday()
    first = _lane_item(resource, base, base + timedelta(minutes=60), seq=1)
    second = _lane_item(resource, base + timedelta(minutes=90), base + timedelta(minutes=150), seq=2, transfer=30)
    checks = {c["code"]: c for c in validate_schedule(db, [first, second])["checks"]}
    assert checks["HC-12"]["count"] == 0


def test_cross_order_predecessor_lag_enforced(db: Session):
    product = _product(db, "PT-P")
    order_a = _order(db, "MO-A", product, monday() + timedelta(days=20))
    order_b = _order(db, "MO-B", product, monday() + timedelta(days=20))
    shift_start = monday().replace(hour=8)
    predecessor = Operation(
        order_id=order_a.id, seq=1, name="外协件加工", domain="机加", resource_type="机加",
        std_minutes=60, setup_minutes=10,
        planned_start=shift_start, planned_end=shift_start + timedelta(minutes=90),
    )
    db.add(predecessor)
    db.flush()
    current = Operation(
        order_id=order_b.id, seq=1, name="装配", domain="机加", resource_type="机加",
        std_minutes=60, setup_minutes=10, predecessor_id=predecessor.id, lag_minutes=60,
    )
    db.add(current)
    db.flush()
    resource = _resource(db, "MC-P")
    item = _lane_item(resource, shift_start + timedelta(minutes=120), shift_start + timedelta(minutes=180))
    item.order_id = order_b.id
    item.order_no = order_b.order_no
    item.operation_id = current.id
    checks = {c["code"]: c for c in validate_schedule(db, [item])["checks"]}
    assert checks["HC-12"]["count"] == 1

    current.lag_minutes = 0
    db.flush()
    checks = {c["code"]: c for c in validate_schedule(db, [item])["checks"]}
    assert checks["HC-12"]["count"] == 0


def test_dangling_predecessor_flagged_as_hc04(db: Session):
    product = _product(db, "PT-D")
    order = _order(db, "MO-D", product, monday() + timedelta(days=20))
    op = Operation(
        order_id=order.id, seq=1, name="悬空工序", domain="机加", resource_type="机加",
        std_minutes=60, setup_minutes=10, predecessor_id=424242,
    )
    db.add(op)
    db.flush()
    resource = _resource(db, "MC-01")
    item = _lane_item(resource, monday(), monday() + timedelta(minutes=60))
    item.order_id = order.id
    item.order_no = order.order_no
    item.operation_id = op.id
    checks = {c["code"]: c for c in validate_schedule(db, [item])["checks"]}
    assert checks["HC-04"]["count"] >= 1


def test_qualification_check_reported_unevaluated(db: Session):
    result = validate_schedule(db, [])
    hc10 = [c for c in result["checks"] if c["code"] == "HC-10"][0]
    assert hc10["evaluated"] is False
    assert hc10["count"] == 0
    assert result["hard_count"] == 0
    assert [u["code"] for u in result["unevaluated"]] == ["HC-10"]


def test_negative_progress_breaks_quantity_balance(db: Session):
    product = _product(db, "PT-Q")
    order = _order(db, "MO-Q", product, monday() + timedelta(days=20))
    order.progress = -5
    db.flush()
    resource = _resource(db, "MC-01")
    item = _lane_item(resource, monday(), monday() + timedelta(minutes=60))
    item.order_id = order.id
    item.order_no = order.order_no
    checks = {c["code"]: c for c in validate_schedule(db, [item])["checks"]}
    assert checks["HC-14"]["count"] >= 1

def _operation(db: Session, order: Order, name: str = "粗铣", std: float = 120.0) -> Operation:
    op = Operation(
        order_id=order.id, seq=1, name=name, domain="机加", resource_type="机加",
        std_minutes=std, setup_minutes=20.0, status="待开工", risk="normal", locked=False,
    )
    db.add(op)
    db.flush()
    return op


def test_cross_order_dependency_defines_the_successor_start(db: Session):
    """并行机位足够时，跨订单前置 + lag 仍决定后继最早开工时刻。"""
    due = datetime.now() + timedelta(days=90)
    product = _product(db, "PT-DEP", std=120.0)
    first_order = _order(db, "SO-DEP-1", product, due)
    second_order = _order(db, "SO-DEP-2", product, due)
    _resource(db, "MC-DEP", machine_count=2)
    first_op = _operation(db, first_order)
    second_op = _operation(db, second_order)

    free = {i.order_no: i for i in generate_schedule(db, scenario="A", freeze=False)["items"]}
    assert free["SO-DEP-1"].start == free["SO-DEP-2"].start

    second_op.predecessor_id = first_op.id
    second_op.lag_minutes = 60.0
    db.flush()
    result = generate_schedule(db, scenario="A", freeze=False)
    forced = {i.order_no: i for i in result["items"]}
    assert forced["SO-DEP-2"].start >= forced["SO-DEP-1"].end + timedelta(minutes=60)
    assert result["violations"]["hard_count"] == 0
    assert result["summary"]["dependency_cycles"] == []


def test_dependency_cycle_is_reported_and_still_scheduled(db: Session):
    """成环依赖不能锁死求解：按基线顺序兜底，并把环写进方案说明。"""
    due = datetime.now() + timedelta(days=90)
    product = _product(db, "PT-CYC", std=120.0)
    a = _order(db, "SO-CYC-1", product, due)
    b = _order(db, "SO-CYC-2", product, due)
    _resource(db, "MC-CYC", machine_count=2)
    a_op, b_op = _operation(db, a), _operation(db, b)
    a_op.predecessor_id = b_op.id
    b_op.predecessor_id = a_op.id
    db.flush()

    result = generate_schedule(db, scenario="A", freeze=False)
    assert len(result["items"]) == 2
    assert result["summary"]["dependency_cycles"] == ["SO-CYC-1", "SO-CYC-2"]
