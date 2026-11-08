"""F6 知识语料入库：按 code upsert、整批拒绝、审计留痕、检索立刻能用。"""

from __future__ import annotations

from app.models import Knowledge
from app.services import knowledge as kb

ROWS = [
    {"code": "KB-T001", "category": "专识", "title": "钛合金刀具寿命",
     "content": "TA15 铣刀单次刃磨寿命不低于 20 分钟，到寿必须换刀。",
     "source_ref": "ZD-01-2026 第 4.2 节", "tags": "机加;刀具", "confidence": "0.95"},
    {"code": "KB-T002", "category": "通识", "title": "军品交期变更审批",
     "content": "P0 订单交期变更须生产指挥部终审并电子签名。",
     "source_ref": "安全合规基线 E2", "confidence": "0.9"},
]


def _import(client, admin, items, dry_run=False):
    return client.post("/api/system/main-data/knowledge", json={"items": items, "dry_run": dry_run}, headers=admin)


def test_knowledge_import_creates_rows_and_search_finds_them(client, admin, db):
    result = _import(client, admin, ROWS)
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload["created"] == 2 and payload["updated"] == 0 and payload["rows"] == 2

    found = kb.search(db, "钛合金 刀具", 5)
    assert found["hits"] >= 1
    assert any(item["code"] == "KB-T001" for item in found["items"])
    assert all(item["source_ref"] for item in found["items"])

    again = _import(client, admin, ROWS)
    assert again.json()["unchanged"] == 2, again.json()


def test_knowledge_import_dry_run_writes_nothing(client, admin, db):
    before = db.query(Knowledge).count()
    result = _import(client, admin, [dict(ROWS[0], code="KB-T009")], dry_run=True)
    assert result.status_code == 200
    assert result.json()["dry_run"] is True
    db.expire_all()
    assert db.query(Knowledge).count() == before
    assert db.query(Knowledge).filter(Knowledge.code == "KB-T009").first() is None


def test_knowledge_import_rejects_bad_rows_wholesale(client, admin, db):
    broken = [dict(ROWS[0]), {"code": "KB-T100", "category": "外星", "title": "x", "content": "y"}]
    result = _import(client, admin, broken)
    assert result.status_code == 422
    assert result.json()["detail"]["code"] == "KB_ROW_INVALID"
    db.expire_all()
    assert db.query(Knowledge).filter(Knowledge.code == "KB-T100").first() is None


def test_knowledge_import_is_admin_only_and_audited(client, admin, commander, db):
    forbidden = client.post("/api/system/main-data/knowledge", json={"items": ROWS}, headers=commander)
    assert forbidden.status_code == 403

    assert _import(client, admin, ROWS).status_code == 200
    logs = client.get("/api/audit", params={"action": "knowledge.import"}, headers=admin).json()
    assert logs["total"] >= 1
    verify = client.get("/api/audit/verify", headers=admin).json()
    assert verify["ok"] is True
