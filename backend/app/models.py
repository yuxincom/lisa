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
    plants = Column(JSON, default=list)
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
    machine_count = Column(Integer, default=1)
    capabilities = Column(JSON, default=list)
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
    clearance = Column(String(16), default="内部", index=True)
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
    predecessor_id = Column(Integer, ForeignKey("operations.id"), nullable=True)
    lag_minutes = Column(Float, default=0.0)


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
    transfer_minutes = Column(Integer, default=0)
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
    clearance = Column(String(16), default="内部", index=True)


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


class Material(Base):
    """ERP BOM 展开后的物料需求（齐套的需求侧）。"""

    __tablename__ = "materials"

    id = Column(Integer, primary_key=True)
    code = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(128), default="")
    unit = Column(String(16), default="件")
    category = Column(String(24), default="main_material")  # main_material / aux_material
    product_code = Column(String(64), default="", index=True)  # 归属产品（products.code）
    qty_per = Column(Float, default=1.0)  # 单台用量
    lead_time_days = Column(Float, default=0.0)
    source_system = Column(String(32), default="ERP")
    updated_at = Column(DateTime, default=now)


class StockItem(Base):
    """WMS 库存快照（齐套的供给侧）。"""

    __tablename__ = "stock_items"

    id = Column(Integer, primary_key=True)
    material_code = Column(String(64), unique=True, nullable=False, index=True)
    on_hand = Column(Float, default=0.0)
    allocated = Column(Float, default=0.0)
    quality_status = Column(String(16), default="合格")  # 合格 / 待判 / 隔离
    batch = Column(String(64), default="")
    location = Column(String(64), default="")
    source_system = Column(String(32), default="WMS")
    updated_at = Column(DateTime, default=now)

    @property
    def available(self) -> float:
        return max(0.0, float(self.on_hand or 0.0) - float(self.allocated or 0.0))


class Inbound(Base):
    """在途/采购到货承诺：ETA 早于需求的时点才算供给。"""

    __tablename__ = "inbounds"

    id = Column(Integer, primary_key=True)
    reference = Column(String(64), default="", index=True)  # 采购单/送货单号，作为自然键
    material_code = Column(String(64), default="", index=True)
    qty = Column(Float, default=0.0)
    eta = Column(DateTime, nullable=True)
    supplier = Column(String(128), default="")
    status = Column(String(16), default="在途")  # 在途 / 已到料 / 延期
    updated_at = Column(DateTime, default=now)


class Tool(Base):
    """工装/刀具台账（kind 区分两类要素）。"""

    __tablename__ = "tools"

    id = Column(Integer, primary_key=True)
    code = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(128), default="")
    kind = Column(String(16), default="tooling")  # tooling / cutter
    domain = Column(String(32), default="", index=True)  # 对应资源能力域
    status = Column(String(16), default="可用")  # 可用 / 检修 / 未归位
    life_remaining = Column(Float, nullable=True)  # 刀具剩余寿命百分比
    owner = Column(String(64), default="")
    updated_at = Column(DateTime, default=now)


class Qualification(Base):
    """HR 技能矩阵（配置清单 C4）：有数据后 HC-10 才真正参与校验。"""

    __tablename__ = "qualifications"

    id = Column(Integer, primary_key=True)
    person_name = Column(String(64), nullable=False)
    capability = Column(String(32), default="", index=True)  # 对应 resource_type / 能力域
    certificate = Column(String(64), default="")
    level = Column(Integer, default=1)
    valid_until = Column(DateTime, nullable=True)
    active = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=now)


class Inspection(Base):
    """QMS 检验结论：上道工序未判定或不合格即阻断开工。"""

    __tablename__ = "inspections"

    id = Column(Integer, primary_key=True)
    order_no = Column(String(32), nullable=False, index=True)
    seq = Column(Integer, default=1)
    conclusion = Column(String(16), default="合格")  # 合格 / 待判 / 不合格
    inspector = Column(String(64), default="")
    detail = Column(JSON, default=dict)
    checked_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now)


class Job(Base):
    """后台任务队列的持久化行。

    状态只走 queued → running → succeeded/failed（+ cancelled）；
    queued 行落在库里意味着「重启后仍未做的事」，worker 起来会接着claim，
    不像进程内队列那样一掉电就丢任务。
    """

    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True)
    kind = Column(String(48), nullable=False, index=True)
    status = Column(String(16), default="queued", index=True)
    payload = Column(JSON, default=dict)
    result = Column(JSON, default=dict)
    error = Column(JSON, default=dict)
    progress = Column(Integer, default=0)
    attempt = Column(Integer, default=0)
    max_attempts = Column(Integer, default=1)
    worker = Column(String(64), default="")
    created_by = Column(String(64), default="")
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    clearance = Column(String(16), default="内部")
    queued_at = Column(DateTime, default=now)
    started_at = Column(DateTime, nullable=True)
    heartbeat_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
