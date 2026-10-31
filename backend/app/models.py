from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)

from .database import Base


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    name = Column(String(64), nullable=False)
    role = Column(String(32), nullable=False)
    clearance = Column(String(16), default="内部")
    department = Column(String(64), default="生产运营部")
    avatar_color = Column(String(16), default="#4f9dff")
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now)


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    code = Column(String(32), unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=False)
    family = Column(String(64), nullable=False)
    priority_class = Column(String(8), default="P1")
    route = Column(JSON, nullable=False)


class Resource(Base):
    __tablename__ = "resources"

    id = Column(Integer, primary_key=True)
    code = Column(String(32), unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=False)
    domain = Column(String(32), nullable=False, index=True)
    plant = Column(String(16), default="一厂")
    capacity_hours = Column(Float, default=20.0)
    efficiency = Column(Float, default=0.92)
    bottleneck = Column(Boolean, default=False)
    status = Column(String(24), default="running")
    maintenance_until = Column(DateTime, nullable=True)


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    order_no = Column(String(32), unique=True, nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    product_name = Column(String(128), nullable=False)
    qty = Column(Integer, default=1)
    priority = Column(String(8), default="P1", index=True)
    plant = Column(String(16), default="一厂")
    customer = Column(String(64), default="中国航发")
    due_date = Column(DateTime, nullable=False, index=True)
    status = Column(String(24), default="已排产", index=True)
    progress = Column(Integer, default=0)
    is_military = Column(Boolean, default=True)
    kit_status = Column(String(16), default="齐套")
    created_at = Column(DateTime, default=now)
    released_at = Column(DateTime, default=now)


class Operation(Base):
    __tablename__ = "operations"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    name = Column(String(64), nullable=False)
    domain = Column(String(32), nullable=False, index=True)
    resource_type = Column(String(64), nullable=False)
    std_minutes = Column(Float, default=60.0)
    setup_minutes = Column(Float, default=20.0)
    special = Column(Boolean, default=False)
    status = Column(String(24), default="待开工", index=True)
    planned_start = Column(DateTime, nullable=True)
    planned_end = Column(DateTime, nullable=True)
    actual_start = Column(DateTime, nullable=True)
    actual_end = Column(DateTime, nullable=True)
    resource_id = Column(Integer, ForeignKey("resources.id"), nullable=True)
    locked = Column(Boolean, default=False)
    risk = Column(String(16), default="normal")
    valid_until = Column(DateTime, nullable=True)


Index("ix_operations_order_seq", Operation.order_id, Operation.seq)


class Plan(Base):
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True)
    code = Column(String(40), unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=False)
    type = Column(String(24), default="full")  # full / incremental / change / baseline
    status = Column(String(24), default="draft", index=True)
    scenario = Column(String(8), default="A")
    objective = Column(String(128), default="交期优先")
    weights = Column(JSON, default=dict)
    summary = Column(JSON, default=dict)
    kpi = Column(JSON, default=dict)
    diff = Column(JSON, default=dict)
    created_by = Column(String(64), default="system")
    created_at = Column(DateTime, default=now)
    submitted_at = Column(DateTime, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    applied_at = Column(DateTime, nullable=True)
    baseline = Column(Boolean, default=False)
    batch_id = Column(String(40), nullable=True, index=True)
    change_id = Column(Integer, ForeignKey("disturbances.id"), nullable=True)


class PlanItem(Base):
    __tablename__ = "plan_items"

    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    operation_id = Column(Integer, ForeignKey("operations.id"), nullable=True)
    order_no = Column(String(32), nullable=False)
    product_name = Column(String(128), nullable=False)
    priority = Column(String(8), default="P1")
    seq = Column(Integer, nullable=False)
    name = Column(String(64), nullable=False)
    domain = Column(String(32), nullable=False, index=True)
    resource_id = Column(Integer, ForeignKey("resources.id"), nullable=True)
    resource_code = Column(String(32), nullable=True)
    resource_name = Column(String(128), nullable=True)
    start = Column(DateTime, nullable=False)
    end = Column(DateTime, nullable=False)
    duration_minutes = Column(Float, default=60.0)
    setup_minutes = Column(Float, default=0.0)
    risk = Column(String(16), default="normal")
    locked = Column(Boolean, default=False)
    reason = Column(Text, default="")


Index("ix_plan_items_plan_domain", PlanItem.plan_id, PlanItem.domain)


class Approval(Base):
    __tablename__ = "approvals"

    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False, index=True)
    level = Column(Integer, default=1)
    approver_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    approver_name = Column(String(64), default="")
    role = Column(String(32), default="")
    status = Column(String(24), default="pending", index=True)
    comment = Column(Text, default="")
    signature = Column(String(128), default="")
    deadline = Column(DateTime, nullable=True)
    decided_at = Column(DateTime, nullable=True)
    escalated = Column(Boolean, default=False)


class Disturbance(Base):
    __tablename__ = "disturbances"

    id = Column(Integer, primary_key=True)
    code = Column(String(40), unique=True, nullable=False, index=True)
    type = Column(String(24), nullable=False, index=True)
    title = Column(String(160), nullable=False)
    detail = Column(Text, default="")
    severity = Column(String(16), default="warning")
    status = Column(String(24), default="评估中", index=True)
    occurred_at = Column(DateTime, default=now)
    payload = Column(JSON, default=dict)
    impact = Column(JSON, default=dict)
    options = Column(JSON, default=dict)
    resolved_at = Column(DateTime, nullable=True)
    reporter = Column(String(64), default="系统事件总线")


class KitCheck(Base):
    __tablename__ = "kit_checks"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    order_no = Column(String(32), nullable=False)
    product_name = Column(String(128), nullable=False)
    checkpoint = Column(String(24), nullable=False, index=True)  # pre_schedule / post_schedule / pre_start
    status = Column(String(16), default="齐套")  # 齐套 / 缺项 / 阻断
    score = Column(Float, default=100.0)
    elements = Column(JSON, default=list)
    gaps = Column(JSON, default=list)
    checked_at = Column(DateTime, default=now)


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)
    code = Column(String(32), unique=True, nullable=False)
    level = Column(String(16), default="warning", index=True)  # fatal / critical / warning / info
    type = Column(String(32), default="system")
    title = Column(String(160), nullable=False)
    message = Column(Text, default="")
    source = Column(String(64), default="LISA")
    related_type = Column(String(32), default="")
    related_id = Column(String(40), default="")
    status = Column(String(16), default="open", index=True)
    created_at = Column(DateTime, default=now, index=True)
    acked_by = Column(String(64), nullable=True)
    acked_at = Column(DateTime, nullable=True)


class Rule(Base):
    __tablename__ = "rules"

    id = Column(Integer, primary_key=True)
    code = Column(String(32), unique=True, nullable=False, index=True)
    kind = Column(String(16), default="rule", index=True)  # rule / hard / soft
    category = Column(String(64), default="计划拉动")
    title = Column(String(160), nullable=False)
    description = Column(Text, default="")
    priority = Column(Integer, default=5)
    trigger = Column(Text, default="")
    action = Column(Text, default="")
    weight = Column(Float, default=0.0)
    domain = Column(String(32), default="全厂")
    enabled = Column(Boolean, default=True)
    hits = Column(Integer, default=0)


class Knowledge(Base):
    __tablename__ = "knowledge"

    id = Column(Integer, primary_key=True)
    code = Column(String(32), unique=True, nullable=False, index=True)
    category = Column(String(32), default="专识", index=True)
    title = Column(String(160), nullable=False)
    content = Column(Text, nullable=False)
    source_ref = Column(String(128), default="")
    trace_version = Column(String(32), default="v1.0")
    tags = Column(JSON, default=list)
    confidence = Column(Float, default=0.9)
    created_at = Column(DateTime, default=now)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True)
    code = Column(String(40), unique=True, nullable=False, index=True)
    agent_code = Column(String(16), nullable=False, index=True)
    agent_name = Column(String(64), nullable=False)
    level = Column(String(8), default="A")
    scenario = Column(String(32), default="full")
    status = Column(String(24), default="succeeded", index=True)
    summary = Column(String(256), default="")
    inputs = Column(JSON, default=dict)
    steps = Column(JSON, default=list)
    output = Column(JSON, default=dict)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=True)
    operator = Column(String(64), default="system")
    started_at = Column(DateTime, default=now)
    ended_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, default=0)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    seq = Column(Integer, unique=True, nullable=False, index=True)
    ts = Column(DateTime, default=now, index=True)
    actor = Column(String(64), default="system")
    role = Column(String(32), default="system")
    action = Column(String(64), nullable=False, index=True)
    target_type = Column(String(32), default="")
    target_id = Column(String(40), default="")
    result = Column(String(16), default="success")
    detail = Column(JSON, default=dict)
    prev_hash = Column(String(64), default="")
    hash = Column(String(64), default="")
    clearance = Column(String(16), default="内部")


class DataSource(Base):
    __tablename__ = "data_sources"

    id = Column(Integer, primary_key=True)
    code = Column(String(32), unique=True, nullable=False)
    name = Column(String(64), nullable=False)
    type = Column(String(32), default="MCP")
    status = Column(String(16), default="online")
    latency_ms = Column(Integer, default=120)
    last_sync = Column(DateTime, default=now)
    records = Column(Integer, default=0)
    quality = Column(Float, default=95.0)
    owner = Column(String(64), default="信息中心")


class QualitySnapshot(Base):
    __tablename__ = "quality_snapshots"

    id = Column(Integer, primary_key=True)
    dimension = Column(String(16), nullable=False, index=True)
    score = Column(Float, nullable=False)
    threshold = Column(Float, default=90.0)
    passed = Column(Boolean, default=True)
    detail = Column(JSON, default=dict)
    checked_at = Column(DateTime, default=now, index=True)


class Setting(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True)
    key = Column(String(64), unique=True, nullable=False)
    value = Column(JSON, default=dict)
    updated_at = Column(DateTime, default=now)
