import json
import sys
import os

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def load_nodes():
    path = os.path.join(BASE, "graph", "nodes.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def load_edges():
    path = os.path.join(BASE, "graph", "edges.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def q1_find_last_attempt(param):
    nodes = load_nodes()
    edges = load_edges()
    if not param:
        return []
    hits = [n for n in nodes if param.lower() in json.dumps(n).lower()]
    if not hits:
        return []
    hit_ids = {n["id"] for n in hits}
    chain = []
    for e in sorted(edges, key=lambda x: x.get("timestamp", ""), reverse=True):
        if e["source_id"] in hit_ids or e["target_id"] in hit_ids:
            chain.append(e)
    return {"nodes": hits, "edges": chain[:10]}

def q2_related_skills(param):
    nodes = load_nodes()
    edges = load_edges()
    if not param:
        return []
    matches = [n for n in nodes if param.lower() in json.dumps(n).lower() and n["type"] in ("skill", "concept", "task")]
    if not matches:
        return []
    match_ids = {m["id"] for m in matches}
    skill_ids = set()
    for e in edges:
        if e["source_id"] in match_ids or e["target_id"] in match_ids:
            other = e["target_id"] if e["source_id"] in match_ids else e["source_id"]
            skill_ids.add(other)
    skills = [n for n in nodes if n["id"] in skill_ids and n["type"] == "skill"]
    return skills

def q3_failure_patterns(_param=None):
    nodes = load_nodes()
    edges = load_edges()
    failures = [n for n in nodes if n["type"] == "failure"]
    lessons = [n for n in nodes if n["type"] == "lesson"]
    cause_map = {}
    for e in edges:
        if e["type"] == "caused":
            src = next((n for n in nodes if n["id"] == e["source_id"]), None)
            tgt = next((n for n in nodes if n["id"] == e["target_id"]), None)
            if src and tgt:
                rc = tgt.get("root_cause", "unknown")
                if rc not in cause_map:
                    cause_map[rc] = {"count": 0, "lessons": []}
                cause_map[rc]["count"] += 1
                cause_map[rc]["lessons"].append(tgt.get("summary", ""))
    ranked = sorted(cause_map.items(), key=lambda x: -x[1]["count"])
    return {"failure_count": len(failures), "lesson_count": len(lessons), "patterns": [{"root_cause": k, "count": v["count"], "examples": v["lessons"][:3]} for k, v in ranked]}

def q4_skill_performance(param):
    nodes = load_nodes()
    if not param:
        return {"skills": []}
    skills = [n for n in nodes if n["type"] == "skill" and (param.lower() in n.get("label", "").lower() or param.lower() in n["id"].lower())]
    if not skills:
        return {"error": f"No skill matching '{param}'"}
    results = []
    for s in skills:
        results.append({
            "id": s["id"],
            "label": s.get("label", s["id"]),
            "domain": s.get("domain", ""),
            "quality_score": s.get("quality_score"),
            "origin": s.get("origin", "unknown")
        })
    return {"skills": results}

def q5_skill_gaps(_param=None):
    nodes = load_nodes()
    edges = load_edges()
    concepts = [n for n in nodes if n["type"] == "concept"]
    gaps = []
    for c in concepts:
        connected = set()
        for e in edges:
            if e["source_id"] == c["id"] or e["target_id"] == c["id"]:
                other = e["target_id"] if e["source_id"] == c["id"] else e["source_id"]
                if any(n["id"] == other and n["type"] == "skill" for n in nodes):
                    connected.add(other)
        skill_count = len(connected)
        explored = c.get("explored", False)
        if skill_count < 2:
            gaps.append({
                "concept": c["label"],
                "domain": c.get("domain", ""),
                "connected_skills": skill_count,
                "explored": explored,
                "priority": "HIGH" if skill_count == 0 else "MEDIUM"
            })
    return sorted(gaps, key=lambda x: (x["connected_skills"], not x["explored"]))

QUERIES = {
    "q1": q1_find_last_attempt,
    "q2": q2_related_skills,
    "q3": q3_failure_patterns,
    "q4": q4_skill_performance,
    "q5": q5_skill_gaps,
}

def main():
    if len(sys.argv) < 2:
        result = q3_failure_patterns()
        print(json.dumps(result, indent=2))
        return
    qtype = sys.argv[1]
    param = sys.argv[2] if len(sys.argv) > 2 else None
    if qtype not in QUERIES:
        print(json.dumps({"error": f"Unknown query type: {qtype}. Valid: {list(QUERIES.keys())}"}))
        sys.exit(1)
    result = QUERIES[qtype](param)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
