import json, os, subprocess, sys
from pathlib import Path

from saom.config import llm_config


def _discover_tools(base):
    tools_dir = base / "memory" / "tools"
    registry = tools_dir / "registry.json"
    if registry.exists():
        with open(registry) as f:
            data = json.load(f)
            return data if isinstance(data, list) else data.get("tools", [])
    discovered = []
    for d in sorted(tools_dir.iterdir()):
        if d.is_dir() and (d / "tool.py").exists():
            tj = d / "tool.json"
            if tj.exists():
                with open(tj) as f:
                    info = json.load(f)
                    discovered.append(info)
            else:
                discovered.append({"name": d.name, "description": d.name})
    return discovered


def _build_tool_schemas(tools):
    schemas = []
    for t in tools:
        name = t.get("name", "unknown")
        desc = t.get("description", "")
        trigger = t.get("trigger", {})
        keywords = trigger.get("keywords", [name])
        schemas.append({
            "type": "function",
            "function": {
                "name": f"tool_{name}",
                "description": f"{desc} [triggers: {', '.join(keywords[:5])}]",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": t.get("modes", ["status"]),
                            "description": f"Tool mode. Available: {', '.join(t.get('modes', ['status']))}",
                        },
                        "args": {
                            "type": "string",
                            "description": "Additional arguments as space-separated string",
                        },
                    },
                    "required": ["mode"],
                },
            },
        })
    return schemas


def run_agent(goal):
    cfg = llm_config()
    if not cfg["api_key"]:
        return "ERROR: LLM_API_KEY or OPENAI_API_KEY not set"

    base = Path(__file__).parent
    tools = _discover_tools(base)
    tool_schemas = _build_tool_schemas(tools)

    from openai import OpenAI
    client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])

    messages = [
        {
            "role": "system",
            "content": (
                "You are SAOM, a self-improving agent architecture. "
                "You have access to tools for memory, confidence, failure prediction, "
                "skill tracking, immune system, graph queries, and more. "
                "Analyze the user's goal and use the appropriate tools to accomplish it. "
                "When you use a tool, call it via function calling, then interpret the result."
            ),
        },
        {"role": "user", "content": goal},
    ]

    result_text = ""
    for _ in range(10):
        resp = client.chat.completions.create(
            model=cfg["model"],
            messages=messages,
            tools=tool_schemas if tool_schemas else None,
            tool_choice="auto" if tool_schemas else None,
        )
        msg = resp.choices[0].message

        if not msg.tool_calls:
            result_text = msg.content or ""
            break

        messages.append(msg)
        for tc in msg.tool_calls:
            fn = tc.function
            try:
                params = json.loads(fn.arguments)
                mode = params.get("mode", "")
                args = params.get("args", "").split()
                tool_name = fn.name.replace("tool_", "")
                result = _execute_tool(base, tool_name, mode, args)
            except Exception as e:
                result = {"error": str(e)}
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result),
            })

    else:
        result_text = "Agent reached maximum iteration limit."

    return result_text


def _execute_tool(base, tool_name, mode, args):
    tool_path = base / "memory" / "tools" / tool_name / "tool.py"
    if not tool_path.exists():
        return {"error": f"Tool '{tool_name}' not found"}
    cmd = [sys.executable, str(tool_path), mode] + args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        out = r.stdout.strip()
        try:
            return json.loads(out) if out else {"exit": r.returncode}
        except json.JSONDecodeError:
            return {"output": out[:2000], "exit": r.returncode}
    except subprocess.TimeoutExpired:
        return {"error": "tool timed out"}
    except Exception as e:
        return {"error": str(e)}
