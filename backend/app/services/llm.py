from __future__ import annotations

"""内网大模型客户端与编排（F1/F2/F3/F5）。

只认 OpenAI 兼容的 `POST {base_url}/chat/completions`（vLLM、Ollama 的 openai 兼容层、
自研推理网关都是这个形状）。三条不可让的边界：

1. 模型只负责「怎么想、先查什么、怎么解释」。**所有数字、判定、结论都由本库代码算出来后喂给它**，
   模型不许报数；它挑工具时也只能挑 services/mcp_server 里注册的只读工具。
2. 端点必须是内网地址（默认只允许 https + 私网 IP 或内网后缀），凭据只从环境变量读，
   不进数据库、不进日志、不进提示词。
3. 进模型的字段先脱敏（可逆伪名），出模型的文本再还原；模型不可用时排产照跑，
   运行记录如实标 `mode=fallback`，不会伪装成模型推理。
"""

import ipaddress
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .mcp_server import McpError, call_tool
from .settings import get_setting

DEFAULT_LLM_CONFIG: dict[str, Any] = {
    "enabled": False,
    "base_url": "",
    "model": "",
    "api_key_env": "LISA_LLM_API_KEY",
    "timeout_seconds": 25,
    "max_steps": 8,
    "temperature": 0.2,
    "internal_only": True,
    "internal_suffixes": [".intra", ".internal", ".lan", ".corp", ".local"],
    "redact_fields": ["customer", "product_name", "supplier", "person_name", "drawing_no"],
    "max_observation_chars": 1600,
}

INTERNAL_HOST_RE = re.compile(r"^(localhost|127\.|0\.0\.0\.0|\[::1\])")
PSEUDONYM_LABELS = {
    "customer": "客户",
    "product_name": "型号",
    "supplier": "供应商",
    "person_name": "人员",
    "drawing_no": "图号",
}

SYSTEM_PROMPT = (
    "你是 LISA 排产系统的推理编排器，服务军工内网。规则：\n"
    "1) 你不得自行给出任何数字、日期或判定；数字只能来自我给你 observation 字段。\n"
    "2) observation 里出现「未接入/未校验/待接入」时，如实转述为数据缺口，不得当成满足或为零。\n"
    "3) 你只能从 tools 列表里挑选只读工具，不得请求任何写操作、审批或对外发送。\n"
    "4) 每一步只输出一个 JSON 对象，不要输出解释文字、不要用 Markdown 代码块。\n"
    "5) 涉及处置建议时给出责任部门与时限，不要承诺系统尚未实现的能力。"
)


class LlmError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def config(db: Session) -> dict:
    raw = get_setting(db, "llm", {}) or {}
    merged = dict(DEFAULT_LLM_CONFIG)
    if isinstance(raw, dict):
        merged.update({k: v for k, v in raw.items() if k in DEFAULT_LLM_CONFIG})
    return merged


def validate_config(cfg: dict) -> dict:
    """配置入库前校验：宁可拒收，也不要让内网数据打到公网明文端口。"""
    base_url = str(cfg.get("base_url") or "").strip().rstrip("/")
    suffixes = [str(s).lower() for s in cfg.get("internal_suffixes") or [] if str(s).strip()]
    fields = [str(f).strip() for f in cfg.get("redact_fields") or [] if str(f).strip()]
    if not cfg.get("enabled"):
        return {"enabled": False, "base_url": base_url, "model": str(cfg.get("model") or ""),
                "internal_suffixes": suffixes, "redact_fields": fields}
    if not base_url:
        raise LlmError("LLM_URL_REQUIRED", "启用模型编排必须填写 base_url（内网 OpenAI 兼容端点）")
    if not str(cfg.get("model") or "").strip():
        raise LlmError("LLM_MODEL_REQUIRED", "启用模型编排必须填写模型名（如 qwen2.5-72b-instruct）")
    if not base_url.startswith("https://"):
        host = base_url.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0]
        if not INTERNAL_HOST_RE.match(host):
            raise LlmError("LLM_URL_INSECURE", "模型端点只允许 https（本机调试可用 localhost）")
    if cfg.get("internal_only", True):
        host = base_url.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0].lower()
        if not _is_internal(host, suffixes):
            raise LlmError("LLM_HOST_NOT_INTERNAL", f"端点 {host} 不是内网地址；确认数据出域策略后再放开 internal_only")
    try:
        timeout = int(cfg.get("timeout_seconds") or 25)
    except (TypeError, ValueError):
        raise LlmError("LLM_TIMEOUT_INVALID", "timeout_seconds 必须是整数秒")
    if not 1 <= timeout <= 180:
        raise LlmError("LLM_TIMEOUT_INVALID", "timeout_seconds 需要在 1~180 之间")
    max_steps = _int(cfg.get("max_steps"), 8)
    if not 1 <= max_steps <= 16:
        raise LlmError("LLM_STEPS_INVALID", "max_steps 需要在 1~16 之间")
    return {
        "enabled": True,
        "base_url": base_url,
        "model": str(cfg["model"]).strip(),
        "internal_suffixes": suffixes,
        "redact_fields": fields,
    }


def _is_internal(host: str, suffixes: list[str]) -> bool:
    if INTERNAL_HOST_RE.match(host):
        return True
    if any(host.endswith(suffix if suffix.startswith(".") else f".{suffix}") for suffix in suffixes):
        return True
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def endpoint(cfg: dict) -> str:
    return str(cfg.get("base_url", "")).rstrip("/") + "/chat/completions"


def _auth_header(cfg: dict) -> str | None:
    env_name = str(cfg.get("api_key_env") or "").strip()
    token = os.getenv(env_name, "") if env_name else ""
    return f"Bearer {token}" if token else None


def post(cfg: dict, payload: dict) -> dict:
    """唯一的 HTTP 缝隙：测试用假实现替掉它，生产走 urllib（无额外依赖）。"""
    url = endpoint(cfg)
    if not url.startswith("https://") and not INTERNAL_HOST_RE.match(url.split("://", 1)[-1].split("/")[0].split(":")[0]):
        raise LlmError("LLM_URL_INSECURE", f"拒绝向非内网明文端点发送数据：{url}")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    auth = _auth_header(cfg)
    if auth:
        request.add_header("Authorization", auth)
    try:
        with urllib.request.urlopen(request, timeout=_int(cfg.get("timeout_seconds"), 25)) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:200].decode("utf-8", "ignore") if exc.fp else ""
        raise LlmError("LLM_HTTP_ERROR", f"模型服务返回 {exc.code}：{detail}") from exc
    except urllib.error.URLError as exc:
        raise LlmError("LLM_UNREACHABLE", f"模型服务不可达：{exc.reason}") from exc
    except TimeoutError as exc:
        raise LlmError("LLM_TIMEOUT", "模型服务响应超时，本步改用确定性推理") from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise LlmError("LLM_BAD_RESPONSE", "模型服务返回的不是合法 JSON") from exc


def chat(cfg: dict, messages: list[dict], tools: list[dict] | None = None) -> dict:
    """一次补全。返回 {content, tool_calls, usage, model}，失败一律抛 LlmError。"""
    payload = {
        "model": cfg.get("model") or "",
        "messages": messages,
        "temperature": float(cfg.get("temperature") or 0.2),
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    data = post(cfg, payload)
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LlmError("LLM_BAD_RESPONSE", "模型响应缺少 choices")
    message = (choices[0].get("message") or {}) if isinstance(choices[0], dict) else {}
    return {
        "content": message.get("content") or "",
        "tool_calls": message.get("tool_calls") or [],
        "usage": data.get("usage") or {},
        "model": data.get("model") or payload["model"],
    }


# --------------------------------------------------------------------- 脱敏


def redact(value: Any, fields: list[str], mapping: dict[str, str] | None = None) -> tuple[Any, dict[str, str]]:
    """可逆伪名脱敏：字段名命中就换成「型号#1」这种稳定占位，映射只留在本次进程内存里。"""
    table = mapping if mapping is not None else {}

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            out = {}
            for key, item in node.items():
                label = PSEUDONYM_LABELS.get(str(key))
                if label and isinstance(item, (str, int, float)) and str(item).strip():
                    text = str(item)
                    pseudonym = next((fake for fake, original in table.items() if original == text), None)
                    if pseudonym is None:
                        pseudonym = f"«{label}#{len(table) + 1}»"
                        table[pseudonym] = text
                    out[key] = pseudonym
                else:
                    out[key] = walk(item)
            return out
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(value), table


def restore(text: str, mapping: dict[str, str]) -> str:
    if not text or not mapping:
        return text
    for pseudonym, original in mapping.items():
        text = text.replace(pseudonym, original)
    return text


def _compact(value: Any, limit: int) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "…（已截断）"


def _parse_json(text: str) -> dict:
    body = (text or "").strip()
    if body.startswith("```"):
        body = re.sub(r"^```[a-zA-Z]*\s*", "", body)
        body = re.sub(r"\s*```$", "", body)
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end <= start:
        raise LlmError("LLM_UNPARSEABLE", "模型没有返回可解析的 JSON 决策")
    try:
        parsed = json.loads(body[start : end + 1])
    except ValueError as exc:
        raise LlmError("LLM_UNPARSEABLE", f"模型返回的 JSON 无法解析：{exc}") from exc
    if not isinstance(parsed, dict):
        raise LlmError("LLM_UNPARSEABLE", "模型返回的顶层结构不是对象")
    return parsed


# --------------------------------------------------------------------- 编排


def orchestrate(db: Session, user: Any, stages: list[dict], brief: dict, tool_names: list[str] | None = None) -> dict:
    """把「确定性阶段」交给内网模型逐步思考；模型只能选只读工具，取数一律由代码执行。

    返回 mode=llm（真实模型推理）或 mode=fallback（模型不可用/被拒，保留确定性叙述并记录原因）。
    """
    from .mcp_server import TOOLS

    cfg = config(db)
    deterministic = [dict(stage) for stage in stages]
    meta: dict[str, Any] = {
        "mode": "fallback",
        "model": None,
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "reason": "未启用内网模型（设置项 llm.enabled=false）",
        "error": None,
    }
    if not cfg.get("enabled"):
        return {"mode": "fallback", "steps": deterministic, "meta": meta}

    mapping: dict[str, str] = {}
    fields = list(cfg.get("redact_fields") or [])
    sent_brief, mapping = redact(brief, fields)
    allowed = [
        {"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]}
        for t in TOOLS
        if (tool_names is None or t["name"] in tool_names)
    ]
    tools_payload = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                       "parameters": t["inputSchema"]}} for t in allowed]
    limit = _int(cfg.get("max_steps"), 8)
    history: list[dict] = []
    steps: list[dict] = []
    names = {t["name"] for t in allowed}

    try:
        for index, stage in enumerate(deterministic):
            if index >= limit:
                meta["reason"] = f"到达 max_steps={limit}，其余阶段改用确定性叙述"
                steps.extend({**stage, "reasoning": "deterministic"} for stage in deterministic[index:])
                break
            ask = {
                "brief": _compact(sent_brief, 2400),
                "stage": {"index": index + 1, "phase": stage.get("phase"), "title": stage.get("title"),
                          "goal": stage.get("goal") or stage.get("title")},
                "previous": history[-3:],
                "tools": sorted(names),
                "output_schema": {"thought": "为什么这一步这么做（≤80字）",
                                  "tool": "只读工具名或 null", "arguments": {}},
            }
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(ask, ensure_ascii=False)},
            ]
            started = datetime.now()
            reply = chat(cfg, messages, tools_payload)
            elapsed = int((datetime.now() - started).total_seconds() * 1000)
            decision = _parse_json(reply["content"])
            thought = restore(str(decision.get("thought") or "").strip(), mapping)
            requested = str(decision.get("tool") or "").strip()
            observation = stage.get("observation") or ""
            action = stage.get("action") or ""
            tool_meta = None
            if requested and requested in names:
                arguments = decision.get("arguments") if isinstance(decision.get("arguments"), dict) else {}
                try:
                    result = call_tool(db, user, requested, arguments, commit=False)
                    payload = result["structured"]
                    observation = _compact(payload, _int(cfg.get("max_observation_chars"), 1600))
                    action = f"mcp.{requested}({json.dumps(arguments, ensure_ascii=False)})"
                    tool_meta = {"tool": requested, "ms": result["latency_ms"], "chars": len(observation)}
                except (McpError, LlmError) as exc:
                    observation = f"工具 {requested} 调用失败：{exc.code} {exc.message}"
                    tool_meta = {"tool": requested, "error": exc.code}
            elif requested and requested not in names:
                tool_meta = {"tool": requested, "error": "MCP_TOOL_UNKNOWN"}
            steps.append(
                {
                    **{k: v for k, v in stage.items()},
                    "thought": thought or stage.get("thought", ""),
                    "action": action,
                    "observation": observation,
                    "duration_ms": elapsed or stage.get("duration_ms", 0),
                    "reasoning": "llm",
                    "tool": tool_meta,
                }
            )
            sent_observation = _compact(redact({"observation": observation}, fields)[0], 900)
            history.append({"stage": stage.get("title"), "thought": thought, "observation": sent_observation})
            usage = reply.get("usage") or {}
            meta["calls"] += 1
            meta["model"] = reply.get("model") or cfg.get("model")
            meta["prompt_tokens"] += _int(usage.get("prompt_tokens"), 0)
            meta["completion_tokens"] += _int(usage.get("completion_tokens"), 0)
        meta["mode"] = "llm" if meta["calls"] else meta["mode"]
        meta["reason"] = None if meta["mode"] == "llm" else meta["reason"]
    except LlmError as exc:
        meta["error"] = {"code": exc.code, "message": exc.message}
        meta["reason"] = f"模型不可用，已降级为确定性编排：{exc.code}"
        remaining = deterministic[len(steps):]
        for stage in remaining:
            copied = dict(stage)
            copied["reasoning"] = "fallback"
            copied["fallback_reason"] = exc.code
            steps.append(copied)
        return {"mode": "fallback", "steps": steps, "meta": meta}

    return {"mode": meta["mode"], "steps": steps, "meta": meta}


def test_connection(db: Session, override: dict | None = None) -> dict:
    """给「测试连接」按钮用：一次最小补全，如实回报延迟与模型名。"""
    cfg = config(db)
    if override:
        cfg.update({k: v for k, v in override.items() if k in DEFAULT_LLM_CONFIG})
    validate_config(cfg)
    if not cfg.get("enabled"):
        raise LlmError("LLM_DISABLED", "未启用内网模型编排，请先配置 llm 设置项")
    started = datetime.now()
    reply = chat(
        cfg,
        [{"role": "user", "content": '只回复一个 JSON 对象：{"ok": true, "model": "你的模型名"}，不要其他文字。'}],
    )
    elapsed = int((datetime.now() - started).total_seconds() * 1000)
    return {
        "ok": True,
        "model": reply.get("model"),
        "latency_ms": elapsed,
        "echo": (reply.get("content") or "")[:120],
        "endpoint": endpoint(cfg),
        "credentials": "来自环境变量 " + str(cfg.get("api_key_env")),
    }
