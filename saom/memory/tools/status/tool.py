import json, os, sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def load_json(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return default if default is not None else {}

def get_compact_summary():
    init = load_json(os.path.join(BASE, "init.json"), {})
    reg = load_json(os.path.join(BASE, "tools", "registry.json"), {})
    skill_reg = load_json(os.path.join(BASE, "skills", "registry.json"), {})
    self_data = load_json(os.path.join(BASE, "bridge", "self.json"), {})
    nodes = load_json(os.path.join(BASE, "graph", "nodes.json"), [])
    edges = load_json(os.path.join(BASE, "graph", "edges.json"), [])
    lessons_path = os.path.join(BASE, "lessons", "lessons.jsonl")
    lesson_count = 0
    if os.path.exists(lessons_path):
        with open(lessons_path, encoding="utf-8") as f:
            lesson_count = sum(1 for line in f if line.strip())
    vault_data = load_json(os.path.join(BASE, "vault", "vault.json"), {})

    tools_info = []
    for t in reg.get("tools", []):
        tools_info.append({
            "name": t["name"],
            "phases": t.get("triggers", {}).get("phases", []),
            "modes": t.get("triggers", {}).get("modes", []),
            "used": t.get("last_used") is not None
        })

    skills_info = []
    for s in skill_reg.get("skills", []):
        skills_info.append({
            "name": s["name"],
            "origin": s.get("origin", "unknown"),
            "used": s.get("last_used") is not None
        })
    for s in skill_reg.get("evolved_skills", []):
        skills_info.append({
            "name": s["name"],
            "origin": "evolved",
            "used": s.get("last_used") is not None
        })

    return {
        "version": init.get("version", "unknown"),
        "sessions": init.get("session_count", 0),
        "tools_total": len(reg.get("tools", [])),
        "tools_used": sum(1 for t in tools_info if t["used"]),
        "skills_total": len(skills_info),
        "skills_used": sum(1 for s in skills_info if s["used"]),
        "graph_nodes": len(nodes),
        "graph_edges": len(edges),
        "lessons_total": lesson_count,
        "vault_entries": len(vault_data.get("secrets", [])),
        "dispatch_online": init.get("dispatch_available", False),
        "current_session": self_data.get("session_id"),
        "current_mode": self_data.get("mode"),
        "current_confidence": self_data.get("confidence"),
        "crystallized_skills": init.get("crystallized_skills", []),
        "tools": tools_info,
        "skills": skills_info
    }

def main():
    print(json.dumps(get_compact_summary(), indent=2))

if __name__ == "__main__":
    main()
