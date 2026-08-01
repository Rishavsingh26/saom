import json, sys, os, re, shutil
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJECT_SKILLS = os.path.join(BASE, "skills")
SAOM_SKILLS = os.path.join(BASE, "skills")
REGISTRY_PATH = os.path.join(SAOM_SKILLS, "registry.json")
NODES_PATH = os.path.join(BASE, "graph", "nodes.json")
EDGES_PATH = os.path.join(BASE, "graph", "edges.json")
INIT_PATH = os.path.join(BASE, "init.json")
TOOLS_DIR = os.path.join(BASE, "tools")

def load_json(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return default if default is not None else {}

def save_json_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)

def sanitize_name(name):
    s = name.lower().strip().replace(" ", "-").replace("_", "-")
    return re.sub(r"[^a-z0-9-]", "", s)[:60]

def generate_skill_md(name, description, steps, trigger_desc, deps, source_note):
    deps_yaml = ""
    if deps:
        items = [d.strip() for d in deps.split(",") if d.strip()]
        deps_yaml = "\n" + "\n".join(f"    - {d}" for d in items)
    steps_text = steps if steps else "No steps provided."
    return f"""---
name: {name}
description: {description}
license: MIT
compatibility: opencode
metadata:
  crystallized_at: {datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
  source: {source_note}
  trigger: {trigger_desc or description}
  dependencies:{deps_yaml}
  saom_tool: skill-crystallizer
---

# {name}

{steps_text}
"""

def register_in_saom_registry(name, description):
    reg = load_json(REGISTRY_PATH, {"skills": [], "evolved_skills": [], "project_skills": []})
    for section in ("skills", "evolved_skills", "project_skills"):
        for s in reg.get(section, []):
            if s.get("name") == name:
                return {"status": "already_registered", "section": section}
    entry = {
        "name": name,
        "description": description[:120],
        "use_count": 0,
        "success_count": 0,
        "avg_confidence": None,
        "last_used": None,
        "evolved": True,
        "crystallized": True
    }
    reg.setdefault("project_skills", []).append(entry)
    save_json_atomic(REGISTRY_PATH, reg)
    return {"status": "registered", "section": "project_skills"}

def add_graph_node(name, description):
    nodes = load_json(NODES_PATH, [])
    existing = [n for n in nodes if n.get("label") == f"skill:{name}"]
    if existing:
        return {"node_id": existing[0]["id"], "status": "exists"}
    node_id = f"{name}_{int(datetime.now(timezone.utc).timestamp())}"
    node = {
        "id": node_id,
        "type": "skill",
        "label": f"skill:{name}",
        "properties": {
            "name": name,
            "description": description[:200],
            "crystallized": True,
            "crystallized_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        }
    }
    nodes.append(node)
    save_json_atomic(NODES_PATH, nodes)
    return {"node_id": node_id, "status": "created"}

def link_to_parent_tool(target_id=None):
    edges = load_json(EDGES_PATH, [])
    parent_node_id = "skill-crystallizer"
    new_edge = {
        "source_id": parent_node_id,
        "target_id": target_id if target_id else skill_crystallizer_current_target,
        "type": "produces",
        "weight": 1.0,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_strengthened": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    }
    for e in edges:
        if e.get("source_id") == new_edge["source_id"] and e.get("target_id") == new_edge["target_id"] and e.get("type") == new_edge["type"]:
            return
    edges.append(new_edge)
    save_json_atomic(EDGES_PATH, edges)

skill_crystallizer_current_target = None

def crystallize(name, description, steps, trigger_desc=None, deps=None, source_note="skill-crystallizer"):
    safe_name = sanitize_name(name)
    if not safe_name:
        return {"error": "Invalid name after sanitization"}
    project_dir = os.path.join(PROJECT_SKILLS, safe_name)
    os.makedirs(project_dir, exist_ok=True)
    skill_path = os.path.join(project_dir, "SKILL.md")
    existing = os.path.exists(skill_path)
    steps = steps.replace("\\n", "\n")
    content = generate_skill_md(safe_name, description, steps, trigger_desc, deps, source_note)
    with open(skill_path, "w", encoding="utf-8") as f:
        f.write(content)
    reg_result = register_in_saom_registry(safe_name, description)
    graph_result = add_graph_node(safe_name, description)
    global skill_crystallizer_current_target
    skill_crystallizer_current_target = graph_result.get("node_id", "skill:" + safe_name)
    link_to_parent_tool()
    return {
        "success": True,
        "skill_path": skill_path,
        "created": not existing,
        "registration": reg_result,
        "graph": graph_result,
        "name": safe_name
    }

def list_skills():
    reg = load_json(REGISTRY_PATH, {})
    crystallized = []
    for section in ("skills", "evolved_skills", "project_skills"):
        for s in reg.get(section, []):
            if s.get("crystallized"):
                crystallized.append({"name": s["name"], "description": s.get("description",""), "section": section, "use_count": s.get("use_count",0), "success_rate": round(s.get("success_count",0)/max(s.get("use_count",0),1)*100,1)})
    if not crystallized:
        disk_dir = os.path.join(BASE, "skills")
        if os.path.exists(disk_dir):
            for d in os.listdir(disk_dir):
                sp = os.path.join(disk_dir, d, "SKILL.md")
                if os.path.exists(sp):
                    crystallized.append({"name": d, "path": sp, "section": "disk"})
    return {"skills": crystallized, "total": len(crystallized)}

def view_skill(name):
    safe_name = sanitize_name(name)
    paths = [
        os.path.join(PROJECT_SKILLS, safe_name, "SKILL.md"),
        os.path.join(BASE, "skills", safe_name, "SKILL.md")
    ]
    for p in paths:
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return {"name": safe_name, "path": p, "content": f.read()}
    return {"error": f"Skill '{name}' not found"}

def prune(name):
    safe_name = sanitize_name(name)
    disk_path = os.path.join(PROJECT_SKILLS, safe_name)
    global_path = os.path.join(BASE, "skills", safe_name)
    had_disk = os.path.exists(disk_path)
    had_global = os.path.exists(global_path)
    if had_disk:
        shutil.rmtree(disk_path)
    if had_global:
        shutil.rmtree(global_path)
    reg = load_json(REGISTRY_PATH, {})
    for section in ("skills", "evolved_skills", "project_skills"):
        for s in list(reg.get(section, [])):
            if s.get("name") == safe_name:
                reg[section].remove(s)
    save_json_atomic(REGISTRY_PATH, reg)
    return {"pruned": safe_name, "disk_removed": had_disk or had_global}

def compose(names, new_name, new_description, connector_text):
    safe_new = sanitize_name(new_name)
    safe_names = [sanitize_name(n) for n in names.split(",")]
    parts = []
    for sn in safe_names:
        v = view_skill(sn)
        if "error" not in v:
            parts.append(f"## From {sn}\n{v['content']}")
    if not parts:
        return {"error": "No source skills found to compose"}
    combined = "\n\n---\n\n".join(parts)
    full_steps = f"## Composed Pattern\n\n{connector_text or 'Combined from multiple skills.'}\n\n{combined}"
    subdir = os.path.join(PROJECT_SKILLS, safe_new)
    os.makedirs(subdir, exist_ok=True)
    sp = os.path.join(subdir, "SKILL.md")
    content = generate_skill_md(safe_new, new_description, full_steps, None, names, f"composed from {names}")
    with open(sp, "w", encoding="utf-8") as f:
        f.write(content)
    register_in_saom_registry(safe_new, new_description)
    add_graph_node(safe_new, new_description)
    return {"composed": safe_new, "path": sp, "from": safe_names}

def main():
    if len(sys.argv) < 2:
        result = list_skills()
        print(json.dumps(result, indent=2))
        return
    mode = sys.argv[1]
    if mode == "crystallize":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "crystallize needs <name> <description> <steps> [trigger_desc] [deps] [source_note]"}))
            sys.exit(1)
        name = sys.argv[2]
        desc = sys.argv[3]
        steps = sys.argv[4] if len(sys.argv) > 4 else ""
        trigger_desc = sys.argv[5] if len(sys.argv) > 5 else None
        deps = sys.argv[6] if len(sys.argv) > 6 else None
        source_note = sys.argv[7] if len(sys.argv) > 7 else "skill-crystallizer"
        result = crystallize(name, desc, steps, trigger_desc, deps, source_note)
        print(json.dumps(result, indent=2))
    elif mode == "list":
        result = list_skills()
        print(json.dumps(result, indent=2))
    elif mode == "view":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "view needs <name>"}))
            sys.exit(1)
        result = view_skill(sys.argv[2])
        print(json.dumps(result, indent=2))
    elif mode == "prune":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "prune needs <name>"}))
            sys.exit(1)
        result = prune(sys.argv[2])
        print(json.dumps(result, indent=2))
    elif mode == "compose":
        if len(sys.argv) < 5:
            print(json.dumps({"error": "compose needs <names> <new_name> <new_description> <connector_text>"}))
            sys.exit(1)
        result = compose(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5] if len(sys.argv) > 5 else "")
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps({"error": f"Unknown mode: {mode}"}))

if __name__ == "__main__":
    main()
