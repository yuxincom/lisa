from __future__ import annotations

"""P2-9 厂区读取范围：两厂区 / 10 分厂的客户口径，不是 SaaS 多租户。

出厂默认 enabled=False —— 上线时不会因为「厂区清单还没确认」就有人看不见数据；
确认后打开开关，范围才生效，且与密级两条叠加。
"""

import pytest
from sqlalchemy import func

from app.models import Order, User
from app.services import plants as pl
from app.services.settings import get_setting, set_setting


def _enable_plants(db, names=("一厂", "二厂"), default="一厂"):
    original = get_setting(db, "plants")
    set_setting(db, "plants", {"enabled": True, "names": list(names), "data_default": default})
    db.commit()
    return original


@pytest.fixture()
def dispatcher_user(db):
    return db.query(User).filter(User.username == "dispatcher").first()


def test_plant_config_is_validated_on_write(client, db, admin, engineer):
    bad = client.put("/api/system/settings", json={"values": {"plants": {"enabled": True, "names": []}}}, headers=admin)
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "PLANT_NAMES_INVALID"

    bad_default = client.put(
        "/api/system/settings",
        json={"values": {"plants": {"enabled": True, "names": ["一厂"], "data_default": "三厂"}}},
        headers=admin,
    )
    assert bad_default.status_code == 422
    assert bad_default.json()["detail"]["code"] == "PLANT_DEFAULT_INVALID"
    assert client.put("/api/system/settings", json={"values": {"plants": {"enabled": False, "names": ["一厂", "二厂"]}}},
                      headers=engineer).status_code == 403


def test_plant_scope_hides_other_plants_from_orders(client, db, admin, dispatcher_user):
    original = _enable_plants(db)
    try:
        dispatcher_user.plants = ["一厂"]
        db.commit()
        other = db.query(Order).filter(Order.plant == "二厂").first()
        from app.services import clearance as clr

        cfg = clr.config(db)
        readable = clr.allowed_values(db.get(User, dispatcher_user.id), cfg)
        mine = (
            db.query(Order)
            .filter(Order.plant == "一厂", func.coalesce(func.nullif(Order.clearance, ""), cfg["data_default"]).in_(readable))
            .first()
        )
        assert mine is not None, "演示数据里必须有一厂且调度员密级可读的工单"
        headers = _login(client, "dispatcher")

        summary = client.get("/api/orders/summary", headers=headers).json()
        assert summary["plants_enabled"] is True
        assert summary["your_plants"] == ["一厂"]
        assert summary["hidden_by_plant"].get("二厂", 0) >= 1
        assert client.get(f"/api/orders/{other.id}", headers=headers).status_code == 403
        assert client.get(f"/api/orders/{mine.id}", headers=headers).status_code == 200

        listed = client.get("/api/orders", headers=headers, params={"limit": 200}).json()
        assert all(item["plant"] == "一厂" for item in listed["items"])
        assert listed["hidden_by_plant"] >= 1
    finally:
        set_setting(db, "plants", original)
        dispatcher_user.plants = []
        db.commit()


def test_unscoped_account_sees_every_plant(client, db, admin, dispatcher_user):
    original = _enable_plants(db)
    try:
        dispatcher_user.plants = []
        db.commit()
        headers = _login(client, "dispatcher")
        listed = client.get("/api/orders", headers=headers, params={"limit": 200}).json()
        assert all(item["plant"] in ("一厂", "二厂") for item in listed["items"])
        assert {item["plant"] for item in listed["items"]} == {"一厂", "二厂"}
        assert listed["hidden_by_plant"] == 0
    finally:
        set_setting(db, "plants", original)
        db.commit()


def test_unknown_plant_claim_is_fail_closed(client, db, admin, dispatcher_user):
    """勾了一个清单里不存在的厂区：宁可一条都看不到，也不要按「猜一个」去放行。"""
    original = _enable_plants(db)
    try:
        dispatcher_user.plants = ["三厂"]
        db.commit()
        headers = _login(client, "dispatcher")
        listed = client.get("/api/orders", headers=headers).json()
        assert listed["items"] == []
        assert listed["total"] == 0
        assert listed["hidden_by_plant"] >= 1
    finally:
        set_setting(db, "plants", original)
        dispatcher_user.plants = []
        db.commit()


def test_plant_filter_stacks_with_clearance(client, db, admin, dispatcher_user):
    """两条范围必须同时成立：厂区放宽不能把高密级数据放出来，反之也一样。"""
    from app.services import clearance as clr

    original_plants = _enable_plants(db)
    clr_cfg = clr.config(db)
    try:
        dispatcher_user.plants = ["一厂"]
        dispatcher_user.clearance = "公开"
        db.commit()
        headers = _login(client, "dispatcher")
        summary = client.get("/api/orders/summary", headers=headers).json()
        assert summary["clearance_enabled"] is True
        assert summary["hidden_by_clearance"] >= 1
        assert summary["hidden_by_plant"].get("二厂", 0) >= 1
        visible = client.get("/api/orders", headers=headers, params={"limit": 200}).json()["items"]
        allowed = set(clr.allowed_values(db.get(User, dispatcher_user.id), clr_cfg))
        assert all(item["plant"] == "一厂" and (item["clearance"] or clr_cfg["data_default"]) in allowed
                   for item in visible)
    finally:
        set_setting(db, "plants", original_plants)
        dispatcher_user.plants = []
        dispatcher_user.clearance = "内部"
        db.commit()


def test_scope_endpoint_requires_admin_and_valid_plant(client, db, planner, dispatcher_user):
    rejected = client.put("/api/system/users/dispatcher/scope", json={"plants": ["一厂"]}, headers=planner)
    assert rejected.status_code == 403
    assert rejected.json()["detail"]["code"] == "ABAC_DENIED"

    unknown = client.put("/api/system/users/dispatcher/scope", json={"plants": ["九厂"]}, headers=_login(client, "admin"))
    assert unknown.status_code == 422
    assert unknown.json()["detail"]["code"] == "PLANT_SCOPE_INVALID"

    bad_level = client.put("/api/system/users/dispatcher/scope", json={"clearance": "绝密"}, headers=_login(client, "admin"))
    assert bad_level.status_code == 422
    assert bad_level.json()["detail"]["code"] == "CLEARANCE_LEVELS_INVALID"

    ok = client.put("/api/system/users/dispatcher/scope", json={"plants": ["一厂"], "clearance": "秘密"},
                    headers=_login(client, "admin"))
    assert ok.status_code == 200, ok.text
    db.expire_all()
    db.refresh(dispatcher_user)
    assert dispatcher_user.plants == ["一厂"]
    assert dispatcher_user.clearance == "秘密"
    assert client.get("/api/system/users", headers=planner).json()["plants"] == pl.config(db)["names"]


def _login(client, username: str) -> dict:
    response = client.post("/api/auth/login", json={"username": username, "password": f"{username}123"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}
