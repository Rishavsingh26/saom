import json
import sys
import os
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LESSONS_PATH = os.path.join(BASE, "lessons", "lessons.jsonl")
NODES_PATH = os.path.join(BASE, "graph", "nodes.json")
EDGES_PATH = os.path.join(BASE, "graph", "edges.json")
INIT_PATH = os.path.join(BASE, "init.json")

SEVERITY_KEYWORDS = {
    "critical": ["crash", "data loss", "security", "breach", "corrupt", "vulnerability", "exploit", "malware"],
    "warning": ["timeout", "slow", "error", "failed", "exception", "bug", "regression"],
}

def classify_severity(text):
    text_lower = text.lower()
    for sev, keywords in SEVERITY_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                return sev
    return "info"

def extract_root_cause(text, outcome):
    if outcome != "failure":
        return "N/A"
    lines = text.strip().split("\n")
    for line in lines[-15:]:
        lowered = line.lower()
        if "error" in lowered or "exception" in lowered or "failed" in lowered:
            return line.strip()[:200]
    if "fail" in text.lower() or "error" in text.lower():
        for line in lines:
            if "fail" in line.lower() or "error" in line.lower():
                return line.strip()[:200]
    return "Unknown failure (check logs)"

def extract_fix_hint(text, outcome):
    if outcome != "failure":
        return "N/A"
    lines = text.strip().split("\n")
    for line in lines[-10:]:
        if "should" in line.lower() or "need" in line.lower() or "instead" in line.lower() or "try" in line.lower():
            return line.strip()[:200]
    return "TODO: determine fix from root cause"

def extract_lesson(interaction_text, outcome, session_id):
    summary = interaction_text.strip().split("\n")[0][:200] if interaction_text.strip() else "No description provided"
    severity = classify_severity(interaction_text)
    root_cause = extract_root_cause(interaction_text, outcome)
    fix = extract_fix_hint(interaction_text, outcome)
    lesson_id = "lesson:" + datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    lesson = {
        "id": lesson_id,
        "type": "lesson",
        "summary": summary,
        "root_cause": root_cause,
        "fix": fix,
        "severity": severity,
        "outcome": outcome,
        "session_id": session_id,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "embedding_keywords": [w for w in summary.lower().split() if len(w) > 3][:10],
        "quality_score": None,
        "reinforced_count": 0,
        "contradicted_count": 0,
        "metadata": {}
    }
    return lesson

def append_to_jsonl(lesson):
    os.makedirs(os.path.dirname(LESSONS_PATH), exist_ok=True)
    with open(LESSONS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(lesson) + "\n")

def add_to_graph(lesson, source_task_id=None):
    os.makedirs(os.path.dirname(NODES_PATH), exist_ok=True)
    nodes = []
    if os.path.exists(NODES_PATH):
        with open(NODES_PATH, encoding="utf-8") as f:
            nodes = json.load(f)
    exists = any(n["id"] == lesson["id"] for n in nodes)
    if not exists:
        nodes.append(lesson)
        with open(NODES_PATH, "w", encoding="utf-8") as f:
            json.dump(nodes, f, indent=2)

    edges = []
    if os.path.exists(EDGES_PATH):
        with open(EDGES_PATH, encoding="utf-8") as f:
            edges = json.load(f)
    if source_task_id:
        edge_exists = any(
            e["source_id"] == source_task_id and e["target_id"] == lesson["id"]
            for e in edges
        )
        if not edge_exists:
            edge_type = "caused" if lesson.get("outcome") == "failure" else "produces"
            edges.append({
                "source_id": source_task_id,
                "target_id": lesson["id"],
                "type": edge_type,
                "weight": 1.0,
                "timestamp": lesson["timestamp"]
            })
            with open(EDGES_PATH, "w", encoding="utf-8") as f:
                json.dump(edges, f, indent=2)

def update_lesson_count():
    if not os.path.exists(INIT_PATH):
        return
    with open(INIT_PATH, encoding="utf-8") as f:
        init = json.load(f)
    count = 0
    if os.path.exists(LESSONS_PATH):
        with open(LESSONS_PATH, encoding="utf-8") as f:
            count = sum(1 for _ in f if _.strip())
    init["lesson_count"] = count
    with open(INIT_PATH, "w", encoding="utf-8") as f:
        json.dump(init, f, indent=2)

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"help": "Lesson extractor tool — saves a structured lesson from a task outcome to the lesson database and graph", "modes": ["<interaction_text> <success|failure> <session_id> [source_task_id]"], "usage": 'python tool.py "<interaction_text>" <success|failure> <session_id> [source_task_id]', "default": "Showing help (no default mode)"}, indent=2))
        return
    if len(sys.argv) < 4:
        print("Usage: python tool.py \"<interaction_text>\" <success|failure> <session_id> [source_task_id]")
        sys.exit(1)
    interaction = sys.argv[1]
    outcome = sys.argv[2].lower()
    if outcome not in ("success", "failure"):
        print(f"Invalid outcome: {outcome}. Must be 'success' or 'failure'.")
        sys.exit(1)
    try:
        session_id = int(sys.argv[3])
    except ValueError:
        print(f"Invalid session_id: {sys.argv[3]}. Must be integer.")
        sys.exit(1)
    source_task_id = sys.argv[4] if len(sys.argv) > 4 else None

    lesson = extract_lesson(interaction, outcome, session_id)
    append_to_jsonl(lesson)
    add_to_graph(lesson, source_task_id)
    update_lesson_count()
    print(json.dumps(lesson, indent=2))

if __name__ == "__main__":
    main()
