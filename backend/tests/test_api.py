from __future__ import annotations


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_login_rejects_bad_password(client):
    response = client.post("/api/auth/login", json={"username": "planner", "password": "wrong-password"})
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "LOGIN_FAILED"


def test_protected_route_requires_token(client):
    assert client.get("/api/dashboard/overview").status_code == 401


def test_dashboard_overview(client, planner):
    response = client.get("/api/dashboard/overview", headers=planner)
    assert response.status_code == 200
    data = response.json()
    assert len(data["kpis"]) >= 6
    assert data["baseline"] is not None
    assert data["quality"]["gate"]["passed"] is True
    assert "resource_load" in data
    assert "audit_tail" in data


def test_plans_pending_and_gantt(client, planner):
    batches = client.get("/api/plans/batches/pending", headers=planner)
    assert batches.status_code == 200
    payload = batches.json()
    assert payload["total"] >= 1
    plan = payload["items"][0]["plans"][0]

    gantt = client.get(f"/api/plans/{plan['id']}/gantt", headers=planner)
    assert gantt.status_code == 200
    data = gantt.json()
    assert len(data["items"]) > 0
    assert data["stats"]["operations"] == len(data["items"])

    lineage = client.get(f"/api/plans/{plan['id']}/lineage", headers=planner)
    assert lineage.status_code == 200
    assert len(lineage.json()["nodes"]) >= 3


def test_plan_approval_signature_and_write_shield(client, planner):
    pending = client.get("/api/plans?status=pending&limit=20", headers=planner).json()["items"]
    assert pending, "seeded pending plans are required"
    plan = pending[0]

    bad = client.post(
        f"/api/plans/{plan['id']}/approve",
        headers=planner,
        json={"plan_id": plan["id"], "action": "approve", "password": "wrong-signature"},
    )
    assert bad.status_code == 403
    assert bad.json()["detail"]["code"] == "SIGNATURE_FAILED"

    blocked = client.post(f"/api/plans/{plan['id']}/write-attempt", headers=planner)
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "WRITE_SHIELD_BLOCKED"

    approved = client.post(
        f"/api/plans/{plan['id']}/approve",
        headers=planner,
        json={"plan_id": plan["id"], "action": "approve", "comment": "自动化验收", "password": "planner123"},
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["ok"] is True
    assert body["plan"]["status"] in {"approved", "applied"}
    assert body["apply"]["operations_updated"] > 0

    baseline = client.get("/api/plans/baseline", headers=planner)
    assert baseline.status_code == 200
    assert baseline.json()["id"] == plan["id"]


def test_agent_full_run(client, planner):
    response = client.post("/api/agents/run", headers=planner, json={"scenario": "full", "options": {}})
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] == "succeeded"
    assert run["agent_code"]
    assert run["steps"]

    catalog = client.get("/api/agents/catalog", headers=planner)
    assert catalog.status_code == 200
    assert catalog.json()["summary"]["total"] > 0


def test_change_lifecycle(client, planner):
    created = client.post(
        "/api/changes",
        headers=planner,
        json={
            "type": "fault",
            "title": "五轴加工中心主轴报警",
            "detail": "MCH-03 主轴振动超阈值，预计停机 6 小时，需评估在制订单影响。",
            "severity": "critical",
            "payload": {"resource_code": "MCH-03", "delay_hours": 6},
        },
    )
    assert created.status_code == 200, created.text
    change = created.json()

    assessed = client.post(f"/api/changes/{change['id']}/assess", headers=planner)
    assert assessed.status_code == 200
    assert assessed.json()["impact"]["summary"]["affected_orders"] >= 0

    options = client.post(f"/api/changes/{change['id']}/plans", headers=planner)
    assert options.status_code == 200
    assert len(options.json()["plans"]) >= 1

    resolved = client.post(f"/api/changes/{change['id']}/resolve", headers=planner)
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "已关闭"


def test_kits_check(client, planner):
    orders = client.get("/api/orders?limit=3", headers=planner).json()["items"]
    assert orders
    response = client.post(
        "/api/kits/check",
        headers=planner,
        json={"order_id": orders[0]["id"], "checkpoint": "pre_start"},
    )
    assert response.status_code == 200
    check = response.json()
    assert check["status"] in {"齐套", "缺项", "阻断"}
    assert len(check["elements"]) == 9

    overview = client.get("/api/kits/overview", headers=planner)
    assert overview.status_code == 200
    assert len(overview.json()["by_checkpoint"]) == 3


def test_orders_summary_and_detail(client, planner):
    summary = client.get("/api/orders/summary", headers=planner)
    assert summary.status_code == 200
    assert summary.json()["total"] > 0

    order = client.get("/api/orders?limit=1", headers=planner).json()["items"][0]
    detail = client.get(f"/api/orders/{order['id']}", headers=planner)
    assert detail.status_code == 200
    assert len(detail.json()["operations"]) > 0


def test_data_quality_gate(client, planner):
    quality = client.get("/api/data/quality", headers=planner)
    assert quality.status_code == 200
    data = quality.json()
    assert len(data["dimensions"]) == 5
    assert data["gate"]["passed"] is True

    checked = client.post("/api/data/quality/check", headers=planner)
    assert checked.status_code == 200
    assert len(checked.json()["run"]) == 5

    coverage = client.get("/api/data/coverage", headers=planner)
    assert coverage.status_code == 200
    assert coverage.json()["interface_count"] == 111


def test_knowledge_catalog_and_search(client, planner):
    catalog = client.get("/api/knowledge/catalog", headers=planner)
    assert catalog.status_code == 200
    summary = catalog.json()["summary"]
    assert summary["rules"] == 68
    assert summary["hard"] == 14
    assert summary["soft"] == 13

    search = client.post("/api/knowledge/search", headers=planner, json={"query": "交期 保供", "top_k": 5})
    assert search.status_code == 200
    result = search.json()
    assert result["hits"] >= 1
    assert all(item["source_ref"] for item in result["items"])


def test_audit_chain_verify_and_export(client, planner):
    verify = client.get("/api/audit/verify", headers=planner)
    assert verify.status_code == 200
    assert verify.json()["ok"] is True
    assert verify.json()["total"] > 0

    stats = client.get("/api/audit/stats", headers=planner)
    assert stats.status_code == 200
    assert stats.json()["total"] > 0

    export = client.get("/api/system/export/audit.csv", headers=planner)
    assert export.status_code == 200
    assert "text/csv" in export.headers["content-type"]


def test_alerts_summary_and_ack(client, commander):
    summary = client.get("/api/alerts/summary", headers=commander)
    assert summary.status_code == 200

    alerts = client.get("/api/alerts?status=open&limit=20", headers=commander).json()["items"]
    if alerts:
        ack = client.post(f"/api/alerts/{alerts[0]['id']}/ack", headers=commander)
        assert ack.status_code == 200
        assert ack.json()["status"] == "acked"

    shielded = client.post("/api/system/write-shield/test", headers=commander)
    assert shielded.status_code == 200
    assert shielded.json()["blocked"] is True


def test_settings_update_requires_admin(client, admin, engineer):
    forbidden = client.get("/api/system/settings", headers=engineer)
    assert forbidden.status_code == 403

    payload = {
        "values": {
            "freeze_days": 4,
            "thresholds": {"data_quality": 90, "confidence": 0.7, "kit": 100},
            "weights": {"delivery": 0.4, "bottleneck": 0.25, "changeover": 0.2, "cost": 0.15},
            "shift": {"start": 8, "end": 20, "days": 6},
            "approval_timeout_minutes": 15,
            "solver_timeout_seconds": 15,
            "auto_escalate": True,
            "write_shield": True,
        }
    }
    updated = client.put("/api/system/settings", headers=admin, json=payload)
    assert updated.status_code == 200, updated.text
    assert updated.json()["values"]["freeze_days"] == 4
    assert "freeze_days" in updated.json()["updated"]


def test_spa_static_serving(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "LISA" in response.text
