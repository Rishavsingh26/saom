import json
import sys
import os
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SESSIONS_DIR = os.path.join(BASE, "sessions")
LESSONS_PATH = os.path.join(BASE, "lessons", "lessons.jsonl")
NODES_PATH = os.path.join(BASE, "graph", "nodes.json")
EDGES_PATH = os.path.join(BASE, "graph", "edges.json")
INIT_PATH = os.path.join(BASE, "init.json")
LAST_PATH = os.path.join(SESSIONS_DIR, "last.json")
PENDING_PATH = os.path.join(BASE, "working", "pending-writes.json")
THIS_SESSION_PATH = os.path.join(BASE, "working", "this-session.json")

def load_json(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def load_lessons():
    if not os.path.exists(LESSONS_PATH):
        return []
    lessons = []
    with open(LESSONS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                lessons.append(json.loads(line))
    return lessons

def start_context():
    # Load last 2 session summaries
    session_files = sorted(
        [f for f in os.listdir(SESSIONS_DIR) if f.startswith("session-") and f.endswith(".json")],
        reverse=True
    )[:2]

    prev_sessions = []
    for sf in session_files:
        data = load_json(os.path.join(SESSIONS_DIR, sf))
        if data:
            prev_sessions.append({
                "id": data.get("session_id"),
                "summary": data.get("summary", "")[:200],
                "tasks": data.get("tasks", [])[-5:],
                "issues": data.get("issues_found", [])[-3:],
                "completed_at": data.get("completed_at", "")
            })

    # Load last 5 lessons
    lessons = load_lessons()[-5:]

    # Load skill registry for tracking data
    reg_path = os.path.join(BASE, "skills", "registry.json")
    reg = load_json(reg_path)
    underperforming = []
    if reg:
        for skill in reg.get("skills", []):
            uc = skill.get("use_count", 0)
            sc = skill.get("success_count", 0)
            if uc >= 3 and sc / uc < 0.4:
                underperforming.append({"skill": skill["name"], "rate": f"{round(sc/uc*100)}%"})

    # Load pending writes
    pending = load_json(PENDING_PATH) or {}
    pending_node_count = len(pending.get("nodes_to_add", []))

    context = {
        "prev_sessions": prev_sessions,
        "recent_lessons": [
            {
                "summary": l.get("summary", "")[:150],
                "root_cause": l.get("root_cause", "")[:100],
                "outcome": l.get("outcome", "unknown")
            } for l in lessons
        ],
        "underperforming_skills": underperforming,
        "pending_writes": pending_node_count
    }
    return context

def end_session(session_data):
    sid = session_data.get("session_id", 0)
    summary = session_data.get("summary", "Session completed")
    tasks = session_data.get("tasks", [])
    lessons_extracted = session_data.get("lessons_extracted", [])
    skills_used = session_data.get("skills_used", [])
    issues = session_data.get("issues", [])

    # Load active session info
    this_session = load_json(THIS_SESSION_PATH) or {}
    started = this_session.get("started_at", datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"))
    completed = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build session summary
    session_summary = {
        "session_id": sid,
        "started_at": started,
        "completed_at": completed,
        "status": "completed",
        "summary": summary[:500],
        "tasks": tasks[-10:],
        "skills_used": skills_used[-10:],
        "lessons_extracted": lessons_extracted[-10:],
        "issues_found": issues[-5:],
        "lesson_count": len(load_lessons()),
        "performance_notes": session_data.get("notes", "")
    }

    # Write session file
    session_path = os.path.join(SESSIONS_DIR, f"session-{sid}.json")
    save_json(session_path, session_summary)

    # Update last.json
    init = load_json(INIT_PATH) or {}
    save_json(LAST_PATH, {
        "session_id": sid,
        "status": "completed",
        "summary": summary[:300],
        "started_at": started,
        "completed_at": completed,
        "graph_stats": init.get("memory_stats", {})
    })

    # Flush pending writes to graph
    pending = load_json(PENDING_PATH)
    if pending:
        nodes = load_json(NODES_PATH) or []
        edges = load_json(EDGES_PATH) or []

        for node in pending.get("nodes_to_add", []):
            if not any(n["id"] == node["id"] for n in nodes):
                nodes.append(node)
        for edge in pending.get("edges_to_add", []):
            if not any(e["source_id"] == edge["source_id"] and e["target_id"] == edge["target_id"] for e in edges):
                edges.append(edge)

        save_json(NODES_PATH, nodes)
        save_json(EDGES_PATH, edges)

        # Update init.json graph stats
        if init:
            init["memory_stats"]["graph_nodes"] = len(nodes)
            init["memory_stats"]["graph_edges"] = len(edges)
            save_json(INIT_PATH, init)

        # Clear pending writes
        save_json(PENDING_PATH, {"nodes_to_add": [], "edges_to_add": [], "nodes_to_update": []})

    # Update this-session
    save_json(THIS_SESSION_PATH, session_summary)

    return {
        "session_id": sid,
        "summary": summary[:200],
        "graph_nodes_flushed": len(pending.get("nodes_to_add", [])) if pending else 0,
        "graph_edges_flushed": len(pending.get("edges_to_add", [])) if pending else 0,
        "written_to": f"session-{sid}.json"
    }

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"help": "Session continuity tool — manages session start/end, context loading, graph flushing", "modes": ["start", "end"], "usage": "python tool.py <start|end> [json_data]", "default": "Showing help (no default mode)"}, indent=2))
        return
    mode = sys.argv[1]

    if mode == "start":
        result = start_context()
        print(json.dumps(result, indent=2))

    elif mode == "end":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "No session data provided", "usage": 'python tool.py end "<json_data>"'}, indent=2))
            return
        data = json.loads(sys.argv[2])
        result = end_session(data)
        print(json.dumps(result, indent=2))

    else:
        print(f"Unknown mode: {mode}")

if __name__ == "__main__":
    main()
