from __future__ import annotations

"""P1-7：密级真的参与查询 + 审计链外部锚点。

断言只看两件事：低密级读者看到的集合是不是严格的子集、被挡住的东西是否「如实报数量」。
"""

import json

import pytest

from app.models import AuditLog, Disturbance, Order, User
from app.services import clearance as clr


def _levels(db):
    return clr.config(db)["levels"]


def _hidden_orders(db, user):
    allowed = clr.allowed_values(user, clr.config(db))
    return db.query(Order).filter(clr._label_expr(Order.clearance, clr.config(db)).notin_(allowed)).all()


def test_unknown_person_level_fails_lowest(db):
    levels = _levels(db)
    nobody = User(username="ghost", clearance="绝密不在表里")
    assert clr.allowed_values(nobody, clr.config(db)) == [levels[0]]


def test_unknown_data_label_is_visible_to_no_one(db):
    cfg = clr.config(db)
    order = db.query(Order).order_by(Order.id).first()
    original = order.clearance
    order.clearance = "绝密"
    try:
        for clearance_level in cfg["levels"]:
            reader = User(username="r", clearance=clearance_level)
            assert clr.can_read(reader, order, cfg) is False
    finally:
        order.clearance = original
        db.flush()


def test_planner_view_is_strict_subset_of_admin(client, db, planner, admin):
    cfg = clr.config(db)
    planner_user = db.query(User).filter(User.username == "planner").one()
    hidden = _hidden_orders(db, planner_user)
    assert hidden, "演示数据必须有高于计划员密级的工单，否则这个用例什么都没测"

    mine = client.get("/api/orders/summary", headers=planner).json()
    all_orders = client.get("/api/orders/summary", headers=admin).json()
    assert all_orders["hidden_by_clearance"] == 0
    assert mine["hidden_by_clearance"] == len(hidden)
    assert mine["total"] == all_orders["total"] - len(hidden)
    assert mine["hidden_by_level"] == {
        level: sum(1 for o in hidden if (o.clearance or cfg["data_default"]) == level)
        for level in cfg["levels"]
        if any((o.clearance or cfg["data_default"]) == level for o in hidden)
    }


def test_hidden_order_detail_denied_and_audited(client, db, planner, admin):
    planner_user = db.query(User).filter(User.username == "planner").one()
    target = _hidden_orders(db, planner_user)[0]
    before = db.query(AuditLog).filter(AuditLog.action == "clearance.denied").count()
    response = client.get(f"/api/orders/{target.id}", headers=planner)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "CLEARANCE_DENIED"
    assert db.query(AuditLog).filter(AuditLog.action == "clearance.denied").count() == before + 1
    assert client.get("/api/audit/verify", headers=admin).json()["ok"] is True


def test_disabled_clearance_restores_full_view(client, db, admin):
    from app.services.settings import get_setting, set_setting

    stored = get_setting(db, "clearance")
    set_setting(db, "clearance", {**stored, "enabled": False})
    db.commit()
    try:
        summary = client.get("/api/orders/summary", headers=admin).json()
        assert summary["hidden_by_clearance"] == 0
        assert summary["clearance_levels"] == []
        assert summary["total"] == db.query(Order).count()
    finally:
        set_setting(db, "clearance", stored)
        db.commit()


def _rpc(client, headers, method, params=None):
    return client.post(
        "/api/mcp/rpc",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
        headers=headers,
    )


def test_mcp_surface_scopes_orders(client, db, planner, admin):
    def rows(headers):
        return _rpc(client, headers, "tools/call", {"name": "list_orders", "arguments": {"limit": 50}}).json()[
            "result"
        ]["structured"]

    mine, all_orders = rows(planner), rows(admin)
    assert mine["total_open"] < all_orders["total_open"]
    assert mine["hidden_by_clearance"] > 0
    levels = set(_levels(db))
    assert {o["clearance"] for o in mine["orders"]} <= set(levels)

    planner_user = db.query(User).filter(User.username == "planner").one()
    hidden_no = _hidden_orders(db, planner_user)[0].order_no
    denied = _rpc(client, planner, "tools/call", {"name": "order_detail", "arguments": {"order_no": hidden_no}})
    payload = denied.json()["result"]
    assert payload["isError"] is True
    assert payload["error"]["code"] == "MCP_CLEARANCE_DENIED"
    assert "不代表该工单不存在" in payload["content"][0]["text"]
    assert db.query(AuditLog).filter(AuditLog.action == "mcp.clearance.denied").count() >= 1


def test_kits_and_gantt_are_scoped(client, db, planner, admin):
    planner_user = db.query(User).filter(User.username == "planner").one()
    hidden_ids = {o.id for o in _hidden_orders(db, planner_user)}
    mine = client.get("/api/kits", headers=planner, params={"limit": 300}).json()
    all_checks = client.get("/api/kits", headers=admin, params={"limit": 300}).json()
    assert {item["order_id"] for item in mine["items"]} <= {item["order_id"] for item in all_checks["items"]}
    assert mine["hidden_orders_by_clearance"] == len(hidden_ids)

    plan = client.get("/api/plans", headers=admin).json()["items"][0]
    mine_plan = client.get(f"/api/plans/{plan['id']}", headers=planner, params={"include_items": True}).json()
    all_plan = client.get(f"/api/plans/{plan['id']}", headers=admin, params={"include_items": True}).json()
    assert all_plan["hidden_items_by_clearance"] == 0
    assert {item["order_id"] for item in mine_plan.get("items", [])}.isdisjoint(hidden_ids)


def test_dashboard_reports_clearance_context(client, db, planner):
    data = client.get("/api/dashboard/overview", headers=planner).json()
    assert data["clearance"]["enabled"] is True
    assert data["clearance"]["your_level"] == "内部"
    assert sum(data["clearance"]["hidden_orders"].values()) > 0


def test_disturbance_inherits_highest_affected_clearance(client, db, planner):
    from app.services.impact import _affected_orders, create_disturbance, relabel_disturbance_clearance
    from app.models import User as UserModel

    planner_user = db.query(UserModel).filter(UserModel.username == "planner").one()
    secret = _hidden_orders(db, planner_user)[0]
    change = create_disturbance(
        db, "order_change", "测试事件：高密级工单变更", "手工用例", "warning",
        {"order_ids": [secret.id], "delay_hours": 5}, reporter="计划员 · 李静",
    )
    db.commit()
    cfg = clr.config(db)
    assert change.clearance == secret.clearance
    assert clr.can_read(planner_user, change, cfg) is False
    # 派生标签可重复计算，且第二次不再改变
    before = {c.id: c.clearance for c in db.query(Disturbance).all()}
    assert relabel_disturbance_clearance(db)["relabelled"] == 0
    assert {c.id: c.clearance for c in db.query(Disturbance).all()} == before
    assert [o.id for o in _affected_orders(db, change)] == [secret.id]
    db.delete(change)
    db.commit()


def test_impact_detail_redacts_but_counts_stay(client, db, planner, admin):
    from app.services.impact import create_disturbance

    planner_user = db.query(User).filter(User.username == "planner").one()
    hidden = _hidden_orders(db, planner_user)[:2]
    change = create_disturbance(
        db, "fault", "测试事件：混密级", "手工用例", "critical",
        {"order_ids": [o.id for o in hidden], "delay_hours": 9}, reporter="计划员 · 李静",
    )
    db.commit()
    cfg = clr.config(db)
    body = client.get(f"/api/changes/{change.id}", headers=planner).json()
    hidden_nos = {o.order_no for o in hidden}
    assert not ({item["order_no"] for item in body["impact"].get("affected_orders", [])} & hidden_nos)
    assert body["redacted_affected"] >= len(hidden)
    # 总数是聚合值，不因遮挡而变 0
    assert body["impact"]["summary"]["affected_orders"] >= len(hidden)
    all_body = client.get(f"/api/changes/{change.id}", headers=admin).json()
    assert all_body["redacted_affected"] == 0
    assert {item["order_no"] for item in all_body["impact"].get("affected_orders", [])} & hidden_nos
    db.delete(change)
    db.commit()


# ------------------------------------------------------------------ 审计外部锚点


@pytest.fixture()
def anchor_env(monkeypatch, tmp_path):
    from app.config import DATA_DIR

    monkeypatch.setenv("LISA_ANCHOR_SECRET", "unit-test-anchor-key")
    monkeypatch.setenv("LISA_ANCHOR_SECRET_ENV", "LISA_ANCHOR_SECRET")
    return DATA_DIR


def test_anchor_roundtrip_and_tamper_detection(client, db, admin, anchor_env):
    from app.services import anchor

    file = anchor.path()
    if file.exists():
        file.unlink()
    record = anchor.append_anchor(db)
    assert record["seq_to"] == db.query(AuditLog).order_by(AuditLog.seq.desc()).first().seq
    assert file.exists() and len(file.read_text(encoding="utf-8").splitlines()) == 1
    assert json.dumps(record)  # 可序列化，且没把密钥写进去
    assert "unit-test-anchor-key" not in file.read_text(encoding="utf-8")

    checked = anchor.verify_anchors(db)
    assert checked["chain_ok"] is True and checked["anchors"] == 1

    # 改锚点文件里任意一个字段 → 自身的 HMAC 链断裂
    lines = file.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["seq_to"] = tampered["seq_to"] + 5
    file.write_text(json.dumps(tampered, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    broken = anchor.verify_anchors(db)
    assert broken["chain_ok"] is False
    assert broken["broken_at"]["line"] == 1

    file.write_text(lines[0] + "\n", encoding="utf-8")


def test_anchor_detects_database_side_rewrite(client, db, admin, anchor_env):
    """攻击者若能改库并重算哈希，库内链自己看不出问题——锚点文件才是独立证据。"""
    from app.services import anchor
    from app.services.audit import GENESIS_HASH, _digest, verify_chain

    file = anchor.path()
    if file.exists():
        file.unlink()
    admin_user = db.query(User).filter(User.username == "admin").one()
    record = anchor.append_anchor(db, admin_user)
    assert anchor.verify_anchors(db)["chain_ok"] is True

    logs = db.query(AuditLog).order_by(AuditLog.seq.asc()).all()
    logs[0].action = "被悄悄改写的动作"
    prev = GENESIS_HASH
    for log in logs:  # 把整条链按新内容重算，库内自检于是「通过」
        log.prev_hash = prev
        log.hash = _digest(prev, log.ts, log.actor, log.action, f"{log.target_type}:{log.target_id}", log.detail or {})
        prev = log.hash
    db.commit()

    assert verify_chain(db)["ok"] is True
    result = anchor.verify_anchors(db)
    assert result["chain_ok"] is False
    assert result["drift"] == "ANCHOR_VS_DB_MISMATCH"


def test_anchor_requires_secret(client, db, admin, commander, monkeypatch):
    from app.services import anchor

    monkeypatch.delenv("LISA_ANCHOR_SECRET", raising=False)
    response = client.post("/api/audit/anchor", headers=commander)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "ANCHOR_SECRET_MISSING"
    denied = client.post("/api/audit/anchor", headers=admin)
    assert denied.status_code == 422

    # 计划员没有 audit:anchor，连试都试不了
    from tests.conftest import _login

    planner = _login(client, "planner", "planner123")
    assert client.post("/api/audit/anchor", headers=planner).status_code == 403


def test_anchor_appends_and_verify_reports_coverage(client, db, commander, monkeypatch, anchor_env):
    from app.services import anchor

    monkeypatch.setenv("LISA_ANCHOR_SECRET", "unit-test-anchor-key")
    file = anchor.path()
    if file.exists():
        file.unlink()
    first = anchor.append_anchor(db, db.query(User).filter(User.username == "commander").one())
    # 锚点之后必须产生新审计记录，否则无事可锚
    second = anchor.append_anchor(db, db.query(User).filter(User.username == "commander").one())
    assert second["seq_from"] == first["seq_to"] + 1
    assert second["prev_anchor_hash"] == first["anchor_hash"]
    # 不带 user 的锚定不产生审计记录，因此连着两次就是「无事可锚」
    anchor.append_anchor(db)
    with pytest.raises(anchor.AnchorError) as nothing_new:
        anchor.append_anchor(db)
    assert nothing_new.value.code == "ANCHOR_NOTHING_NEW"

    checked = anchor.verify_anchors(db)
    assert checked["chain_ok"] is True and checked["anchors"] == 3
    assert checked["unanchored_records"] == 0

    body = client.get("/api/audit/verify", headers=commander).json()
    assert body["anchor"]["anchors"] == 3
    assert body["tamper_evident"] is True
    listed = client.get("/api/audit/anchors", headers=commander).json()
    assert [h["seq_to"] for h in listed["history"]] == [first["seq_to"], second["seq_to"], checked["last"]["seq_to"]]


def test_clearance_levels_editable_from_settings(client, db, admin):
    from app.services.settings import get_setting, set_setting

    original = get_setting(db, "clearance")
    try:
        payload = {**original, "levels": [*original["levels"], "绝密"]}
        response = client.put("/api/system/settings", json={"values": {"clearance": payload}}, headers=admin)
        assert response.status_code == 200, response.text
        assert clr.config(db)["levels"][-1] == "绝密"
        report = client.get("/api/system/security", headers=admin).json()["clearance"]
        assert report["levels"][-1] == "绝密"
        assert report["orders_by_level"]["绝密"] == 0
        assert report["total_levels"] == len(report["levels"])
        assert set(report["users_by_level"]) >= {"内部", "机密"}
    finally:
        set_setting(db, "clearance", original)
        db.commit()


def test_broken_clearance_table_rejected_on_write(client, db, admin):
    from app.services.settings import get_setting, set_setting

    original = get_setting(db, "clearance")
    try:
        for bad in (
            {"levels": ["公开"], "data_default": "公开"},
            {"levels": ["公开", "公开"], "data_default": "公开"},
            {"levels": ["公开", "内部"], "data_default": "机密"},
            {"levels": ["公开", "  "], "data_default": "公开"},
        ):
            response = client.put(
                "/api/system/settings", json={"values": {"clearance": {**original, **bad}}}, headers=admin
            )
            assert response.status_code == 422, bad
            assert response.json()["detail"]["code"] in {"CLEARANCE_LEVELS_INVALID", "CLEARANCE_DEFAULT_INVALID"}
        assert clr.config(db)["levels"] == original["levels"], "被拒绝的写入不能留下半个配置"
    finally:
        set_setting(db, "clearance", original)
        db.commit()


def test_levels_broken_behind_backs_read_fail_closed(client, db, admin):
    """绕过设置接口把等级表配坏（直接改库）时，读取要 503 而不是拿半对的表判「谁能看什么」。"""
    from app.services.settings import get_setting, set_setting

    original = get_setting(db, "clearance")
    set_setting(db, "clearance", {**original, "levels": ["公开", "公开"]})
    db.commit()
    try:
        with pytest.raises(clr.ClearanceError):
            clr.config(db)
        response = client.get("/api/orders/summary", headers=admin)
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "CLEARANCE_LEVELS_INVALID"
        assert client.get("/api/dashboard/overview", headers=admin).status_code == 503
    finally:
        set_setting(db, "clearance", original)
        db.commit()
        assert client.get("/api/orders/summary", headers=admin).status_code == 200


def test_shortened_level_table_makes_out_of_range_data_invisible(client, db, admin):
    """等级表被改短是合法操作，但落在表外的数据必须谁都看不见（fail-closed），并且如实报数。"""
    from app.services.settings import get_setting, set_setting

    original = get_setting(db, "clearance")
    secret = db.query(Order).filter(Order.clearance == "机密").order_by(Order.id).first()
    assert secret is not None, "演示数据里必须有机密工单"
    set_setting(db, "clearance", {**original, "levels": ["公开", "内部", "秘密"], "data_default": "内部"})
    db.commit()
    try:
        mine = client.get("/api/orders/summary", headers=admin).json()
        assert mine["hidden_by_level"].get("机密", 0) >= 1
        assert client.get(f"/api/orders/{secret.id}", headers=admin).status_code == 403
    finally:
        set_setting(db, "clearance", original)
        db.commit()
        assert client.get(f"/api/orders/{secret.id}", headers=admin).status_code == 200


def test_relabel_endpoint_recomputes_derived_labels(client, db, engineer, commander):
    """事件密级是派生值：改了工单密级或等级表后要能重算，且只给有审批权的角色动手的口子。"""
    from app.services.impact import _affected_orders
    from app.services.settings import get_setting, set_setting

    original = get_setting(db, "clearance")
    event = next(
        (c for c in db.query(Disturbance).order_by(Disturbance.id).all() if _affected_orders(db, c)), None
    )
    assert event is not None, "演示数据里必须有一条带受影响工单的事件"
    affected = _affected_orders(db, event)
    levels = clr.config(db)["levels"]
    top = levels[-1]
    before = {order.id: order.clearance for order in affected}
    try:
        for order in affected:
            order.clearance = top
        event.clearance = levels[0]
        db.commit()

        assert client.post("/api/changes/relabel", headers=engineer).status_code == 403

        result = client.post("/api/changes/relabel", headers=commander).json()
        assert result["relabelled"] >= 1
        db.expire_all()  # 本库 sessionmaker 是 expire_on_commit=False，接口在另一个会话里改的要主动过期
        assert event.clearance == top, "事件密级应跟到受影响工单里的最高一级"

        again = client.post("/api/changes/relabel", headers=commander).json()
        assert again["relabelled"] == 0, "重标必须幂等，不能每次都说自己改了东西"

        # 等级表改短后，表外标签按最高级重算（fail_high），只会高标不会低估
        set_setting(db, "clearance", {**original, "levels": levels[:2], "data_default": levels[1]})
        db.commit()
        client.post("/api/changes/relabel", headers=commander)
        db.expire_all()
        assert event.clearance == levels[1]
    finally:
        set_setting(db, "clearance", original)
        for order in db.query(Order).filter(Order.id.in_(list(before))).all():
            order.clearance = before[order.id]
        db.commit()
        client.post("/api/changes/relabel", headers=commander)
