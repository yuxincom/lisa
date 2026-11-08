from __future__ import annotations

"""MCP 只读工具面：JSON-RPC 握手、工具白名单、ABAC 拦截、错误码与审计留痕。"""

import pytest

from app.services import mcp_server


def _rpc(client, headers, method, params=None, request_id=1):
    return client.post(
        "/api/mcp/rpc",
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}},
        headers=headers,
    )


def test_tools_are_registered_and_all_read_only(client, planner):
    response = client.get("/api/mcp/tools", headers=planner)
    assert response.status_code == 200, response.text
    data = response.json()
    names = {tool["name"] for tool in data["tools"]}
    assert {"lisa_health", "list_orders", "order_detail", "kit_check", "resource_load"} <= names
    assert len(names) >= 12
    assert data["read_only"] is True
    assert all(tool["read_only"] for tool in data["tools"])
    assert all(not name.startswith(mcp_server.WRITE_PREFIXES) for name in names)


def test_decorator_refuses_write_shaped_tools():
    with pytest.raises(mcp_server.McpError) as exc:
        @mcp_server.tool("apply_schedule", "写基线（不应允许注册）")
        def _handler(db, user, args):
            return {}

    assert exc.value.code == "MCP_TOOL_WRITE_DENIED"


def test_initialize_announces_protocol_and_limits(client, planner):
    response = _rpc(client, planner, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["protocolVersion"] == mcp_server.PROTOCOL_VERSION
    assert result["serverInfo"]["name"] == "lisa-aps"
    assert "只读" in result["instructions"]
    assert "tools" in result["capabilities"]


def test_notifications_are_acknowledged_without_payload(client, planner):
    response = _rpc(client, planner, "notifications/initialized")
    assert response.status_code == 200
    assert response.json() is None


def test_ping_and_unsupported_method(client, planner):
    assert _rpc(client, planner, "ping").json()["result"] == {}
    unknown = _rpc(client, planner, "prompts/list")
    assert unknown.status_code == 400
    assert unknown.json()["detail"]["code"] == "MCP_METHOD_UNSUPPORTED"


def test_tools_list_over_rpc_matches_registry(client, planner):
    listed = _rpc(client, planner, "tools/list").json()["result"]["tools"]
    assert [tool["name"] for tool in listed] == [tool["name"] for tool in mcp_server.TOOLS]
    sample = next(tool for tool in listed if tool["name"] == "kit_check")
    assert sample["inputSchema"]["required"] == ["order_no"]
    assert "checkpoint" in sample["inputSchema"]["properties"]


def test_health_and_orders_tools_return_real_numbers(client, planner):
    health = _rpc(client, planner, "tools/call", {"name": "lisa_health", "arguments": {}})
    payload = health.json()["result"]["structured"]
    assert payload["counts"]["orders"] > 0
    assert payload["counts"]["resources"] > 0
    assert health.json()["result"]["isError"] is False

    orders = _rpc(client, planner, "tools/call", {"name": "list_orders", "arguments": {"priority": "P0", "limit": 5}})
    rows = orders.json()["result"]["structured"]["orders"]
    assert len(rows) <= 5
    assert all(row["priority"] == "P0" for row in rows)


def test_tool_call_errors_are_reported_as_is_error(client, planner):
    unknown = _rpc(client, planner, "tools/call", {"name": "no_such_tool", "arguments": {}})
    result = unknown.json()["result"]
    assert result["isError"] is True
    assert result["error"]["code"] == "MCP_TOOL_UNKNOWN"

    missing = _rpc(client, planner, "tools/call", {"name": "kit_check", "arguments": {"order_no": "MO-NOPE"}})
    assert missing.json()["result"]["error"]["code"] == "MCP_ORDER_NOT_FOUND"

    order_no = _rpc(client, planner, "tools/call", {"name": "list_orders", "arguments": {"limit": 1}}).json()[
        "result"
    ]["structured"]["orders"][0]["order_no"]
    bad_checkpoint = _rpc(client, planner, "tools/call", {"name": "kit_check",
                                                          "arguments": {"order_no": order_no, "checkpoint": "mid_night"}})
    assert bad_checkpoint.json()["result"]["error"]["code"] == "MCP_CHECKPOINT_UNKNOWN"


def test_kit_and_plan_tools_expose_unevaluated_state(client, planner):
    orders = _rpc(client, planner, "tools/call", {"name": "list_orders", "arguments": {"limit": 1}}).json()["result"]
    order_no = orders["structured"]["orders"][0]["order_no"]
    check = _rpc(client, planner, "tools/call", {"name": "kit_check",
                                                "arguments": {"order_no": order_no, "checkpoint": "pre_start"}})
    result = check.json()["result"]["structured"]
    assert result["status"] in ("齐套", "缺项", "缺料", "阻断", "待接入")
    assert len(result["elements"]) == 9
    assert all(element["status"] in ("ok", "missing", "unknown") for element in result["elements"])

    scan = _rpc(client, planner, "tools/call", {"name": "hard_constraint_scan", "arguments": {}}).json()["result"]
    codes = {c["code"] for c in scan["structured"]["checks"]}
    assert {"HC-01", "HC-02", "HC-05", "HC-10"} <= codes
    assert scan["structured"]["unevaluated"] == [] or isinstance(scan["structured"]["unevaluated"], list)


def test_order_detail_expands_operations_and_three_checkpoints(client, planner):
    order_no = _rpc(client, planner, "tools/call", {"name": "list_orders", "arguments": {"limit": 1}}).json()[
        "result"
    ]["structured"]["orders"][0]["order_no"]
    detail = _rpc(client, planner, "tools/call", {"name": "order_detail", "arguments": {"order_no": order_no}})
    assert detail.json()["result"]["isError"] is False, detail.json()
    payload = detail.json()["result"]["structured"]
    assert payload["order"]["order_no"] == order_no
    assert payload["operations"], "seeded orders always carry an operation chain"
    assert all(isinstance(op["std_minutes"], float) for op in payload["operations"])
    assert [row["checkpoint"] for row in payload["kit"]] == ["pre_schedule", "post_schedule", "pre_start"]
    for row in payload["kit"]:
        assert row["status"] in ("齐套", "缺项", "缺料", "阻断", "待接入")
        assert 0 <= row["score"] <= 100
        assert row["evaluated_elements"] + row["unevaluated"] <= 9


def test_rest_tool_call_endpoint_wraps_structured_payload(client, planner):
    response = client.post(
        "/api/mcp/tools/kit_summary/call", json={"arguments": {}}, headers=planner
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["tool"] == "kit_summary"
    assert data["structured"]["by_checkpoint"]


def test_abac_blocks_tool_calls_for_read_only_roles(client, engineer, planner):
    listed = _rpc(client, engineer, "tools/list")
    assert listed.status_code == 200
    denied = _rpc(client, engineer, "tools/call", {"name": "lisa_health", "arguments": {}})
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "ABAC_DENIED"
    assert _rpc(client, planner, "tools/call", {"name": "lisa_health", "arguments": {}}).status_code == 200


def test_anonymous_rpc_is_rejected(client):
    assert _rpc(client, {}, "tools/list").status_code == 401


def test_tool_calls_are_audited(client, admin):
    _rpc(client, admin, "tools/call", {"name": "data_quality", "arguments": {}})
    logs = client.get("/api/audit", params={"action": "mcp.tool_call"}, headers=admin).json()
    assert logs["total"] >= 1
    assert any(log["target_id"] == "data_quality" for log in logs["items"])
    verify = client.get("/api/audit/verify", headers=admin).json()
    assert verify["ok"] is True


def test_knowledge_and_rule_tools_carry_provenance(client, planner):
    hits = _rpc(client, planner, "tools/call", {"name": "search_knowledge",
                                                "arguments": {"query": "真空热处理 变形", "top_k": 3}})
    items = hits.json()["result"]["structured"]["items"]
    assert items, hits.text
    assert all(item["source_ref"] for item in items)

    rule = _rpc(client, planner, "tools/call", {"name": "rule_detail", "arguments": {"code": "HC-04"}})
    payload = rule.json()["result"]["structured"]
    assert payload["code"] == "HC-04"

    missing = _rpc(client, planner, "tools/call", {"name": "rule_detail", "arguments": {"code": "HC-99"}})
    assert missing.json()["result"]["error"]["code"] == "MCP_RULE_NOT_FOUND"
