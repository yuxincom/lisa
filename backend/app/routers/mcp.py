from __future__ import annotations

"""MCP 入口：既是一张 REST 门面（给页面和自检用），也是标准 JSON-RPC 2.0 端点。

外部 Agent 框架把本服务当 MCP server 接入时，指向 `POST /api/mcp/rpc`（Bearer = 登录 token）；
工具集只有只读能力，写操作不在这张面上，审批与写保护网关不可绕过。
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import has_permission
from ..database import get_db
from ..deps import get_current_user, require
from ..models import User
from ..services.mcp_server import (
    INSTRUCTIONS,
    PROTOCOL_VERSION,
    SERVER_INFO,
    McpError,
    call_tool,
    handle_request,
    list_tools,
)

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

METHOD_PERMISSION = {
    "initialize": "agents:read",
    "ping": "agents:read",
    "tools/list": "agents:read",
    "tools/call": "agents:run",
}


class McpRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str | None = None
    method: str = Field(min_length=1, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)


class ToolCallRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


def _guard(user: User, permission: str) -> None:
    if not has_permission(user.role, permission):
        raise HTTPException(
            status_code=403,
            detail={"code": "ABAC_DENIED", "message": f"ABAC 策略拒绝：{user.role} 无 {permission} 权限"},
        )


@router.get("/tools")
def tools(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _guard(user, "agents:read")
    registered = list_tools()
    return {
        "protocol_version": PROTOCOL_VERSION,
        "server": SERVER_INFO,
        "instructions": INSTRUCTIONS,
        "read_only": True,
        "endpoint": "/api/mcp/rpc",
        "tools": [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["inputSchema"],
                "read_only": t["annotations"]["readOnlyHint"],
                "when_to_use": t["annotations"]["whenToUse"],
            }
            for t in registered["tools"]
        ],
        "count": len(registered["tools"]),
    }


@router.post("/rpc")
def rpc(
    payload: McpRpcRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    permission = METHOD_PERMISSION.get(payload.method)
    if permission is None and not payload.method.startswith("notifications/"):
        raise HTTPException(
            status_code=400,
            detail={"code": "MCP_METHOD_UNSUPPORTED", "message": f"不支持的 MCP 方法：{payload.method}"},
        )
    if permission:
        _guard(user, permission)
    return handle_request(db, user, payload.model_dump())


@router.post("/tools/{name}/call")
def tool_call(
    name: str,
    payload: ToolCallRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require("agents:run")),
):
    try:
        return {"tool": name, **call_tool(db, user, name, payload.arguments)}
    except McpError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message}) from exc
