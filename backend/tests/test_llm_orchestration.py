from __future__ import annotations

"""内网 LLM 编排：端点校验、脱敏、真取数、失败降级——一条不许模型自己报数。"""

import json

import pytest

from app.services import llm
from app.services.settings import set_setting


@pytest.fixture(autouse=True)
def _no_real_http(monkeypatch):
    """任何情况下都不许真的打网络。"""

    def boom(cfg, payload):
        raise llm.LlmError("LLM_TEST_TRANSPORT", "测试环境禁止真实 HTTP 调用")

    monkeypatch.setattr(llm, "post", boom)


@pytest.fixture(autouse=True)
def _restore_llm_setting(db):
    """本文件的配置改动都是临时的：测完恢复，别把 enabled=true 漏给别的用例。"""
    from app.services.settings import get_setting

    before = get_setting(db, "llm", None)
    yield
    set_setting(db, "llm", before if isinstance(before, dict) else dict(llm.DEFAULT_LLM_CONFIG))
    db.commit()


def _cfg(**over):
    base = dict(llm.DEFAULT_LLM_CONFIG)
    base.update({"enabled": True, "base_url": "https://llm.intra/v1", "model": "qwen2.5-72b-instruct"})
    base.update(over)
    return base


def _enable(db, **over):
    set_setting(db, "llm", _cfg(**over))
    db.commit()


def test_config_defaults_are_disabled(client):
    assert llm.DEFAULT_LLM_CONFIG["enabled"] is False
    assert llm.DEFAULT_LLM_CONFIG["internal_only"] is True


def test_validate_config_rejects_incomplete_and_public_endpoints():
    with pytest.raises(llm.LlmError) as exc:
        llm.validate_config(_cfg(base_url=""))
    assert exc.value.code == "LLM_URL_REQUIRED"

    with pytest.raises(llm.LlmError) as exc:
        llm.validate_config(_cfg(model=""))
    assert exc.value.code == "LLM_MODEL_REQUIRED"

    with pytest.raises(llm.LlmError) as exc:
        llm.validate_config(_cfg(base_url="http://llm.intra/v1"))
    assert exc.value.code == "LLM_URL_INSECURE"

    with pytest.raises(llm.LlmError) as exc:
        llm.validate_config(_cfg(base_url="https://api.openai.com/v1"))
    assert exc.value.code == "LLM_HOST_NOT_INTERNAL"

    with pytest.raises(llm.LlmError) as exc:
        llm.validate_config(_cfg(timeout_seconds=9999))
    assert exc.value.code == "LLM_TIMEOUT_INVALID"

    with pytest.raises(llm.LlmError) as exc:
        llm.validate_config(_cfg(max_steps=40))
    assert exc.value.code == "LLM_STEPS_INVALID"

    assert llm.validate_config(_cfg())["enabled"] is True
    assert llm.validate_config(_cfg(base_url="https://10.20.30.40:8000/v1"))["enabled"] is True
    assert llm.validate_config(_cfg(base_url="http://localhost:11434/v1"))["enabled"] is True
    # internal_only 只管「能不能出内网」，明文传输任何时候都不放行
    assert llm.validate_config(_cfg(base_url="https://gateway.example.com/v1", internal_only=False))["enabled"] is True
    with pytest.raises(llm.LlmError) as exc:
        llm.validate_config(_cfg(base_url="http://public.example/v1", internal_only=False))
    assert exc.value.code == "LLM_URL_INSECURE"


def test_redact_is_reversible_and_leaves_no_plaintext():
    payload = {
        "customer": "中国航发",
        "orders": [{"product_name": "GH4169 涡轮盘", "qty": 12, "customer": "中国航发"}],
        "keep": {"due_date": "2026-12-01T00:00:00"},
    }
    fields = llm.DEFAULT_LLM_CONFIG["redact_fields"]
    masked, mapping = llm.redact(payload, fields)
    dumped = json.dumps(masked, ensure_ascii=False)
    assert "中国航发" not in dumped
    assert "GH4169" not in dumped
    assert "2026-12-01" in dumped  # 非敏感字段原样保留
    assert set(mapping.values()) == {"中国航发", "GH4169 涡轮盘"}
    assert all(k.startswith("«") for k in mapping)

    thought = "先看 «型号#2» 的瓶颈占用，再回到 «客户#1» 的交期"
    restored = llm.restore(thought, mapping)
    assert "中国航发" in restored and "GH4169 涡轮盘" in restored
    assert "«" not in restored


def test_chat_parses_openai_shape(monkeypatch):
    seen = {}

    def fake_post(cfg, payload):
        seen["payload"] = payload
        return {
            "model": "qwen2.5-72b-instruct",
            "choices": [{"message": {"content": '{"thought":"先看最紧的 P0","tool":"list_orders","arguments":{}'}}],
            "usage": {"prompt_tokens": 310, "completion_tokens": 42},
        }

    monkeypatch.setattr(llm, "post", fake_post)
    reply = llm.chat(_cfg(), [{"role": "user", "content": "hi"}], tools=[{"type": "function"}])
    assert "先看最紧的 P0" in reply["content"]
    assert reply["usage"]["prompt_tokens"] == 310
    assert seen["payload"]["tools"] == [{"type": "function"}]
    assert seen["payload"]["tool_choice"] == "auto"


def test_orchestrate_keeps_deterministic_steps_when_disabled(db):
    stages = [{"index": 1, "phase": "感知", "title": "读取订单", "thought": "脚本叙述",
               "action": "mcp.query", "observation": "52 单", "duration_ms": 10, "status": "done"}]
    result = llm.orchestrate(db, None, stages, {"scenario": "x"})
    assert result["mode"] == "fallback"
    assert result["steps"] == stages
    assert "未启用" in result["meta"]["reason"]
    assert result["meta"]["calls"] == 0


def test_orchestrate_uses_model_thought_and_real_tool_data(db, planner_user, monkeypatch):
    _enable(db)
    calls = []

    def fake_post(cfg, payload):
        calls.append(payload)
        n = len(calls)
        if n == 1:
            content = json.dumps({"thought": "先按 P0 拉最紧的工单", "tool": "list_orders",
                                  "arguments": {"priority": "P0", "limit": 3}}, ensure_ascii=False)
        else:
            content = "```json\n" + json.dumps({"thought": "门禁结论已给，检查九要素", "tool": None,
                                                "arguments": {}}, ensure_ascii=False) + "\n```"
        return {"model": cfg["model"], "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 200, "completion_tokens": 30}}

    monkeypatch.setattr(llm, "post", fake_post)
    stages = [
        {"index": 1, "phase": "感知", "title": "拉取在制订单", "thought": "脚本叙述1", "action": "script.a",
         "observation": "脚本观测1", "duration_ms": 5, "status": "done"},
        {"index": 2, "phase": "点检", "title": "数据门禁", "thought": "脚本叙述2", "action": "script.b",
         "observation": "综合得分 92.5%", "duration_ms": 5, "status": "done"},
    ]
    result = llm.orchestrate(db, planner_user, stages, {"scenario": "full", "quality_gate": {"overall": 92.5}})
    assert result["mode"] == "llm"
    assert result["meta"]["calls"] == 2
    assert result["meta"]["model"] == "qwen2.5-72b-instruct"
    first, second = result["steps"]
    assert first["thought"] == "先按 P0 拉最紧的工单"
    assert first["reasoning"] == "llm"
    assert first["action"].startswith("mcp.list_orders")
    assert "order_no" in first["observation"]  # 数字来自工具实算，不是模型编的
    assert first["tool"]["tool"] == "list_orders"
    assert second["thought"] == "门禁结论已给，检查九要素"
    assert second["observation"] == "综合得分 92.5%"  # 模型不挑工具时沿用确定性观测

    system_prompt = calls[0]["messages"][0]["content"]
    assert "不得自行给出任何数字" in system_prompt
    assert "lisa_health" in json.dumps(calls[0]["tools"], ensure_ascii=False)


def test_orchestrate_refuses_write_tools_and_reports_unknown(db, planner_user, monkeypatch):
    _enable(db)

    def fake_post(cfg, payload):
        content = json.dumps({"thought": "我想直接应用方案", "tool": "apply_plan", "arguments": {"plan_code": "P-1"}})
        return {"model": cfg["model"], "choices": [{"message": {"content": content}}], "usage": {}}

    monkeypatch.setattr(llm, "post", fake_post)
    stages = [{"index": 1, "phase": "决策", "title": "写基线", "thought": "脚本叙述", "action": "script",
               "observation": "脚本观测", "duration_ms": 1, "status": "done"}]
    result = llm.orchestrate(db, planner_user, stages, {"scenario": "full"})
    step = result["steps"][0]
    assert step["tool"]["error"] == "MCP_TOOL_UNKNOWN"
    assert step["observation"] == "脚本观测"  # 没有被模型牵着走
    assert result["mode"] == "llm"


def test_orchestrate_degrades_honestly_when_model_is_down(db, planner_user, monkeypatch):
    _enable(db)

    def fake_post(cfg, payload):
        raise llm.LlmError("LLM_UNREACHABLE", "模型服务不可达：connection refused")

    monkeypatch.setattr(llm, "post", fake_post)
    stages = [
        {"index": 1, "phase": "感知", "title": "a", "thought": "t1", "action": "a1", "observation": "o1",
         "duration_ms": 1, "status": "done"},
        {"index": 2, "phase": "求解", "title": "b", "thought": "t2", "action": "a2", "observation": "o2",
         "duration_ms": 1, "status": "done"},
    ]
    result = llm.orchestrate(db, planner_user, stages, {"scenario": "full"})
    assert result["mode"] == "fallback"
    assert result["meta"]["error"]["code"] == "LLM_UNREACHABLE"
    assert [s["thought"] for s in result["steps"]] == ["t1", "t2"]
    assert all(s["reasoning"] == "fallback" for s in result["steps"])
    assert all(s["fallback_reason"] == "LLM_UNREACHABLE" for s in result["steps"])


def test_orchestrate_respects_max_steps(db, planner_user, monkeypatch):
    _enable(db, max_steps=1)

    def fake_post(cfg, payload):
        return {"model": cfg["model"], "choices": [{"message": {"content": '{"thought":"只想一步"}'}}], "usage": {}}

    monkeypatch.setattr(llm, "post", fake_post)
    stages = [{"index": i + 1, "phase": "p", "title": f"t{i}", "thought": f"脚本{i}", "action": "a",
               "observation": "o", "duration_ms": 1, "status": "done"} for i in range(4)]
    result = llm.orchestrate(db, planner_user, stages, {"scenario": "full"})
    assert result["meta"]["calls"] == 1
    assert len(result["steps"]) == 4
    assert result["steps"][0]["thought"] == "只想一步"
    assert result["steps"][1]["thought"] == "脚本1"


def test_unparseable_model_output_degrades(db, planner_user, monkeypatch):
    _enable(db)
    monkeypatch.setattr(llm, "post", lambda cfg, payload: {
        "model": cfg["model"], "choices": [{"message": {"content": "我认为应该直接加班赶工"}}], "usage": {}})
    result = llm.orchestrate(db, planner_user, [
        {"index": 1, "phase": "p", "title": "a", "thought": "脚本", "action": "x", "observation": "o",
         "duration_ms": 1, "status": "done"}], {"scenario": "full"})
    assert result["mode"] == "fallback"
    assert result["meta"]["error"]["code"] == "LLM_UNPARSEABLE"


def test_llm_settings_endpoints_validate_and_are_admin_only(client, planner, admin):
    denied = client.put("/api/agents/llm", json={"values": {"enabled": True}}, headers=planner)
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "ABAC_DENIED"

    secret_key = client.put("/api/agents/llm", json={"values": {"api_key": "sk-should-never-be-stored"}}, headers=admin)
    assert secret_key.status_code == 422
    assert secret_key.json()["detail"]["code"] == "LLM_KEY_UNKNOWN"

    public = client.put(
        "/api/agents/llm",
        json={"values": {"enabled": True, "base_url": "https://api.openai.com/v1", "model": "gpt-4o"}},
        headers=admin,
    )
    assert public.status_code == 422
    assert public.json()["detail"]["code"] == "LLM_HOST_NOT_INTERNAL"

    ok = client.put(
        "/api/agents/llm",
        json={"values": {"enabled": True, "base_url": "https://llm.intra/v1", "model": "qwen2.5-72b-instruct"}},
        headers=admin,
    )
    assert ok.status_code == 200, ok.text
    status = client.get("/api/agents/llm", headers=planner).json()
    assert status["config"]["enabled"] is True
    assert "api_key" not in status["config"]
    assert status["config"]["api_key_env"] == "LISA_LLM_API_KEY"
    assert status["credential_present"] in (True, False)
    assert len(status["mcp"]["tools"]) >= 12
    assert status["runs"]["fallback"] >= 0


def test_llm_test_connection_reports_honestly(client, admin, monkeypatch):
    client.put(
        "/api/agents/llm",
        json={"values": {"enabled": True, "base_url": "https://llm.intra/v1", "model": "fake-intranet-1"}},
        headers=admin,
    )
    monkeypatch.setattr(
        llm, "post",
        lambda cfg, payload: {"model": cfg["model"], "choices": [{"message": {"content": '{"ok": true}'}}], "usage": {}},
    )
    good = client.post("/api/agents/llm/test", json={"values": {}}, headers=admin)
    assert good.status_code == 200, good.text
    assert good.json()["model"] == "fake-intranet-1"
    assert "环境变量" in good.json()["credentials"]

    def unreachable(cfg, payload):
        raise llm.LlmError("LLM_UNREACHABLE", "模型服务不可达")

    monkeypatch.setattr(llm, "post", unreachable)
    bad = client.post("/api/agents/llm/test", json={"values": {}}, headers=admin)
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "LLM_UNREACHABLE"


def test_agent_run_records_real_llm_orchestration(client, admin, monkeypatch, run_agent):
    saved = client.put(
        "/api/agents/llm",
        json={"values": {"enabled": True, "base_url": "https://llm.intra/v1", "model": "fake-intranet-1"}},
        headers=admin,
    )
    assert saved.status_code == 200
    seen = {"n": 0}

    def fake_post(cfg, payload):
        seen["n"] += 1
        if seen["n"] == 1:
            content = json.dumps({"thought": "先取一次全厂齐套概览", "tool": "kit_summary", "arguments": {}},
                                 ensure_ascii=False)
        else:
            content = json.dumps({"thought": "结论够了，按缺口分派责任部门", "tool": None, "arguments": {}},
                                 ensure_ascii=False)
        return {"model": cfg["model"], "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 24}}

    monkeypatch.setattr(llm, "post", fake_post)
    data = run_agent(admin, "kit")
    meta = data["output"]["llm"]
    assert meta["mode"] == "llm"
    assert meta["model"] == "fake-intranet-1"
    assert meta["calls"] >= 1
    assert meta["prompt_tokens"] >= 120
    llm_steps = [step for step in data["steps"] if step.get("reasoning") == "llm"]
    assert llm_steps, data["steps"]
    assert any((step.get("tool") or {}).get("tool") == "kit_summary" for step in llm_steps)
    assert all("thought" in step and step["thought"] for step in llm_steps)


def test_agent_run_still_works_with_model_disabled(client, admin, run_agent):
    client.put("/api/agents/llm", json={"values": {"enabled": False}}, headers=admin)
    data = run_agent(admin, "local", options={"domain": "机加"})
    assert data["output"]["llm"]["mode"] == "fallback"
    assert "未启用" in data["output"]["llm"]["reason"]
    assert all(step.get("reasoning") != "llm" for step in data["steps"])
