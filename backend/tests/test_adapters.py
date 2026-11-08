from __future__ import annotations

"""外部数据适配器测试（P0-5 数据接入层）。

文件落地、HTTP、中间库三条通道都要真的把数据搬进齐套表；通道坏了只能记录在该通道的
状态里，不能中断整批轮询，也不能让服务崩。
"""

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import DataSource, StockItem, User
from app.services.adapters import AdapterError, _read_http, _read_db, adapter_overview, run_due, source_configs
from app.services.kit_data import KIT_COLUMNS
from app.services.settings import set_setting

STOCK_HEADER = ",".join(KIT_COLUMNS["stock"])


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(User(username="admin", password_hash="x", name="管理员", role="admin", clearance="内部"))
    session.flush()
    return session


def _configure(db, sources: list[dict]) -> None:
    set_setting(db, "adapters", {"sources": sources})
    db.commit()


def _csv(path: Path, rows: list[str]) -> Path:
    path.write_text("\n".join([STOCK_HEADER, *rows]) + "\n", encoding="utf-8-sig")
    return path


def _raw_csv(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return path


def test_file_drop_channel_ingests_kit_data(db, tmp_path):
    actor = db.query(User).first()
    csv_path = _csv(tmp_path / "wms_stock.csv", [
        "MT-01,120,10,合格",
        "MT-02,40,0,待判",
    ])
    _configure(db, [{"name": "WMS 库存", "kind": "stock", "channel": "file",
                    "path": str(csv_path), "interval_minutes": 15, "enabled": True}])

    summary = run_due(db, actor, force=True)
    assert len(summary["ran"]) == 1
    assert summary["ran"][0]["created"] == 2
    assert db.query(StockItem).count() == 2

    overview = adapter_overview(db)
    source = overview["sources"][0]
    assert source["rows"] == 2
    assert source["error"] is None
    assert source["last_sync"] and source["next_sync"]
    assert overview["freshness"]["stock"]["rows"] == 2

    tracked = db.query(DataSource).filter(DataSource.code == "ADP-stock").one()
    assert tracked.status == "online"
    assert tracked.records == 2


def test_broken_channel_is_recorded_not_raised(db, tmp_path):
    actor = db.query(User).first()
    _configure(db, [
        {"name": "缺失文件", "kind": "stock", "channel": "file", "path": str(tmp_path / "nope.csv")},
        {"name": "脏数据", "kind": "stock", "channel": "file",
         "path": str(_csv(tmp_path / "dirty.csv", ["MT-01,abc,0,合格"]))},
        {"name": "空文件", "kind": "stock", "channel": "file", "path": str(_csv(tmp_path / "empty.csv", []))},
        {"name": "表头不对", "kind": "stock", "channel": "file",
         "path": str(_raw_csv(tmp_path / "bad_header.csv", ["code,qty,unit,note", "MT-01,1,件,x"]))},
    ])

    summary = run_due(db, actor, force=True)
    errors = [item["error"]["code"] for item in summary["ran"]]
    assert errors == ["ADAPTER_FILE_MISSING", "KIT_ROW_INVALID", "ADAPTER_FILE_EMPTY", "ADAPTER_HEADER_MISSING"]
    assert db.query(StockItem).count() == 0
    assert db.query(DataSource).filter(DataSource.code == "ADP-stock").one().status == "degraded"


def test_interval_gates_the_next_poll(db, tmp_path):
    actor = db.query(User).first()
    csv_path = _csv(tmp_path / "wms_stock.csv", ["MT-01,10,0,合格"])
    _configure(db, [{"name": "WMS", "kind": "stock", "channel": "file", "path": str(csv_path), "interval_minutes": 30}])

    assert len(run_due(db, actor)["ran"]) == 1
    assert run_due(db, actor)["ran"] == []          # 没到点，跳过
    assert len(run_due(db, actor, force=True)["ran"]) == 1  # 手动触发不受间隔限制


def test_disabled_source_never_runs(db, tmp_path):
    actor = db.query(User).first()
    csv_path = _csv(tmp_path / "wms_stock.csv", ["MT-01,10,0,合格"])
    _configure(db, [{"name": "WMS", "kind": "stock", "channel": "file", "path": str(csv_path), "enabled": False}])
    assert run_due(db, actor, force=True)["ran"] == []
    assert len(source_configs(db)) == 1


def test_http_channel_requires_https():
    with pytest.raises(AdapterError) as exc:
        _read_http("http://10.0.0.8/wms/stock")
    assert exc.value.code == "ADAPTER_URL_INSECURE"


def test_db_link_channel_reads_a_middle_table(db, tmp_path, monkeypatch):
    """中间库直连：源库只暴露一张只读视图/表，LISA 按列名映射进来。"""
    source_dsn = f"sqlite:///{(tmp_path / 'mes_middle.db').as_posix()}"
    engine = create_engine(source_dsn)
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE v_wms_stock (material_code TEXT, on_hand REAL, allocated REAL, quality_status TEXT)"
        ))
        connection.execute(text("INSERT INTO v_wms_stock VALUES ('MT-07', 66, 6, '合格')"))
    engine.dispose()
    monkeypatch.setenv("LISA_DEMO_DSN", source_dsn)

    actor = db.query(User).first()
    _configure(db, [{
        "name": "MES 中间库", "kind": "stock", "channel": "db", "dsn_env": "LISA_DEMO_DSN",
        "sql": "SELECT material_code, on_hand, allocated, quality_status FROM v_wms_stock",
    }])
    summary = run_due(db, actor, force=True)
    assert summary["ran"][0]["created"] == 1
    assert db.query(StockItem).filter(StockItem.material_code == "MT-07").one().available == 60.0


def test_db_link_channel_rejects_writes_and_missing_dsn(db, monkeypatch):
    with pytest.raises(AdapterError) as exc:
        _read_db("LISA_UNDEFINED_DSN", "SELECT 1")
    assert exc.value.code == "ADAPTER_DSN_MISSING"

    monkeypatch.setenv("LISA_DEMO_DSN", "sqlite://")
    with pytest.raises(AdapterError) as exc:
        _read_db("LISA_DEMO_DSN", "DELETE FROM stock_items")
    assert exc.value.code == "ADAPTER_SQL_NOT_READONLY"


def test_adapter_status_survives_restart_like_rerun(db, tmp_path):
    actor = db.query(User).first()
    csv_path = _csv(tmp_path / "wms_stock.csv", ["MT-01,10,0,合格"])
    _configure(db, [{"name": "WMS", "kind": "stock", "channel": "file", "path": str(csv_path)}])
    run_due(db, actor, force=True)
    stamp = adapter_overview(db)["sources"][0]["last_sync"]
    assert stamp.startswith(datetime.now().strftime("%Y-%m-%d"))


def test_adapter_endpoints_validate_and_run_over_http(client, admin, planner, tmp_path):
    url = "/api/system/main-data/adapters"
    assert client.put(url, headers=planner, json={"sources": []}).status_code == 403

    insecure = client.put(url, headers=admin, json={"sources": [{"kind": "stock", "channel": "http", "url": "http://x/y"}]})
    assert insecure.status_code == 422
    assert insecure.json()["detail"]["code"] == "ADAPTER_URL_INSECURE"

    writable = client.put(url, headers=admin, json={"sources": [{"kind": "stock", "channel": "db", "dsn_env": "X", "sql": "DROP TABLE t"}]})
    assert writable.status_code == 422
    assert writable.json()["detail"]["code"] == "ADAPTER_SQL_NOT_READONLY"

    unknown = client.put(url, headers=admin, json={"sources": [{"kind": "salary", "channel": "file", "path": "x"}]})
    assert unknown.status_code == 422
    assert unknown.json()["detail"]["code"] == "ADAPTER_KIND_UNKNOWN"

    csv_path = _csv(tmp_path / "wms_stock.csv", ["MT-API-01,88,8,合格"])
    saved = client.put(url, headers=admin, json={"sources": [
        {"name": "WMS 库存", "kind": "stock", "channel": "file", "path": str(csv_path), "interval_minutes": 5}
    ]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["sources"] == 1

    ran = client.post(f"{url}/run", headers=admin, json={"force": True})
    assert ran.status_code == 200, ran.text
    assert ran.json()["ran"][0]["rows"] == 1

    overview = client.get(url, headers=admin).json()
    assert overview["sources"][0]["error"] is None
    assert overview["sources"][0]["rows"] == 1
    assert overview["freshness"]["stock"]["rows"] >= 1

    assert client.put(url, headers=planner, json={"sources": []}).status_code == 403
