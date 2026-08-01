import json, sys, os, re, traceback
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLS_DIR = os.path.join(BASE, "tools")
REGISTRY_PATH = os.path.join(TOOLS_DIR, "registry.json")
INIT_PATH = os.path.join(BASE, "init.json")
NODES_PATH = os.path.join(BASE, "graph", "nodes.json")
EDGES_PATH = os.path.join(BASE, "graph", "edges.json")

USAGE = """Usage: python tool-weaver/tool.py generate <spec_json> [--force]
  spec_json: path to a JSON file or inline JSON string

Spec schema:
{
  "name": "tool-name",
  "description": "What the tool does",
  "params": [
    {"name": "param1", "type": "string", "description": "..."}
  ],
  "logic": "Python code for run(params) function body (indented 4 spaces)",
  "dependencies": ["json"],
  "version": "1.0.0"
}

Examples:
  python tool-weaver/tool.py generate my_spec.json
  python tool-weaver/tool.py generate "{\\"name\\": \\"hello\\", ...}"
"""

TOOL_PY_TEMPLATE = '''import json
import sys
import os
%(imports)s

def run(params):
%(logic)s

if __name__ == "__main__":
    params = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    result = run(params)
    print(json.dumps(result))
'''

TOOL_JSON_TEMPLATE = '''{
  "name": "%(name)s",
  "version": "%(version)s",
  "description": "%(description)s",
  "language": "python",
  "entrypoint": "tool.py",
  "inputs": %(inputs)s,
  "outputs": [
    {"name": "result", "type": "json", "description": "Output of the tool"}
  ],
  "dependencies": %(deps)s,
  "created_at": "%(timestamp)s",
  "last_used": null,
  "success_count": 0,
  "failure_count": 0
}
'''

def load_json(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return [] if path.endswith(".json") and ("nodes" in path or "edges" in path or "registry" in path) else {}

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def normalize_name(name):
    return re.sub(r'[^a-z0-9-]', '', name.lower().replace(' ', '-'))

def generate_tool_py(spec):
    name = normalize_name(spec["name"])
    logic = spec.get("logic", "    pass")
    deps = spec.get("dependencies", ["json"])
    if "json" not in deps:
        deps = ["json"] + deps
    stdlib = {"json", "sys", "os", "re", "math", "datetime", "collections", "itertools", "functools", "pathlib", "csv", "io", "textwrap", "copy", "random", "statistics", "string", "typing"}
    seen = set()
    imports = []
    for d in deps:
        if d not in seen:
            seen.add(d)
            if d in stdlib:
                imports.append("import " + d)
            else:
                imports.append("import " + d)
    imports_line = "\n".join(imports)
    return TOOL_PY_TEMPLATE % {
        "imports": imports_line,
        "logic": logic
    }

def generate_tool_json(spec, timestamp):
    name = normalize_name(spec["name"])
    params = spec.get("params", [])
    inputs_json = json.dumps(params, indent=2)
    deps_json = json.dumps(spec.get("dependencies", ["json"]))
    desc = spec.get("description", "").replace('"', '\\"')
    return TOOL_JSON_TEMPLATE % {
        "name": name,
        "version": spec.get("version", "1.0.0"),
        "description": desc,
        "inputs": inputs_json,
        "deps": deps_json,
        "timestamp": timestamp
    }

def validate_python(code, name):
    try:
        compile(code, f"<{name}>", "exec")
        return {"valid": True, "errors": []}
    except SyntaxError as e:
        return {"valid": False, "errors": [{"line": e.lineno, "msg": e.msg, "text": e.text.strip() if e.text else ""}]}

def update_registry(tool_entry):
    registry = load_json(REGISTRY_PATH)
    if isinstance(registry, dict) and "tools" in registry:
        tools = registry["tools"]
    elif isinstance(registry, list):
        tools = registry
    else:
        tools = []
    existing = [t for t in tools if t["name"] == tool_entry["name"]]
    if existing:
        existing[0].update(tool_entry)
    else:
        tools.append(tool_entry)
    save_json(REGISTRY_PATH, {"tools": tools, "total_tools": len(tools), "last_tool_created": tool_entry.get("created_at", "")})

def update_init(tool_name):
    init = load_json(INIT_PATH)
    if init:
        init["tools_count"] = (init.get("tools_count", 0)) + 1
        init["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        save_json(INIT_PATH, init)

def add_graph_node(tool_name, description):
    nodes = load_json(NODES_PATH)
    edges = load_json(EDGES_PATH)
    node_id = f"tool:{normalize_name(tool_name)}"
    existing = [n for n in nodes if n["id"] == node_id]
    if existing:
        return node_id
    new_node = {
        "id": node_id,
        "type": "tool",
        "label": tool_name,
        "summary": description,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session_id": None,
        "quality_score": None,
        "embedding_keywords": [tool_name.lower()] + description.lower().split()[:5],
        "metadata": {}
    }
    nodes.append(new_node)
    save_json(NODES_PATH, nodes)
    link_edge = {
        "source_id": node_id,
        "target_id": "session-current",
        "type": "employs",
        "weight": 1.0,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_strengthened": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    }
    edges.append(link_edge)
    save_json(EDGES_PATH, edges)
    return node_id

def generate(spec_path, force=False):
    if os.path.exists(spec_path):
        with open(spec_path, encoding="utf-8") as f:
            spec = json.load(f)
    else:
        spec = json.loads(spec_path)

    required = ["name", "description", "logic"]
    missing = [r for r in required if r not in spec]
    if missing:
        return {"success": False, "error": f"Missing required fields: {missing}"}

    name = normalize_name(spec["name"])
    tool_dir = os.path.join(TOOLS_DIR, name)
    tool_py_path = os.path.join(tool_dir, "tool.py")
    tool_json_path = os.path.join(tool_dir, "tool.json")

    if os.path.exists(tool_dir) and not force:
        return {"success": False, "error": f"Tool '{name}' already exists at {tool_dir}. Use --force to overwrite."}

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    py_code = generate_tool_py(spec)
    validation = validate_python(py_code, f"{name}/tool.py")
    if not validation["valid"]:
        return {"success": False, "error": "Syntax validation failed", "validation": validation, "generated_code": py_code}

    json_content = generate_tool_json(spec, timestamp)

    os.makedirs(tool_dir, exist_ok=True)
    with open(tool_py_path, "w", encoding="utf-8") as f:
        f.write(py_code)
    with open(tool_json_path, "w", encoding="utf-8") as f:
        f.write(json_content)

    tool_entry = {
        "name": name,
        "version": spec.get("version", "1.0.0"),
        "description": spec.get("description", ""),
        "language": "python",
        "entrypoint": f"memory/tools/{name}/tool.py",
        "created_at": timestamp,
        "last_used": None,
        "success_count": 0,
        "failure_count": 0
    }
    update_registry(tool_entry)
    update_init(name)
    node_id = add_graph_node(name, spec.get("description", ""))

    return {
        "success": True,
        "tool_name": name,
        "tool_dir": tool_dir,
        "files_created": ["tool.py", "tool.json"],
        "validation": "passed",
        "registry_updated": True,
        "graph_node_id": node_id,
        "location": f"memory/tools/{name}/"
    }

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "No mode specified", "usage": "generate <spec_path> [--force]", "modes": ["generate"]}, indent=2))
        return
    if len(sys.argv) < 3 and sys.argv[1] == "generate":
        print(USAGE)
        return
    mode = sys.argv[1]
    if mode == "generate":
        spec = sys.argv[2]
        force = "--force" in sys.argv
        result = generate(spec, force)
        print(json.dumps(result, indent=2))
        if not result.get("success"):
            sys.exit(1)
    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)

if __name__ == "__main__":
    main()
