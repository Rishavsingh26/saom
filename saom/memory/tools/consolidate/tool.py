import json
import sys
import os
import re
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LESSONS_PATH = os.path.join(BASE, "lessons", "lessons.jsonl")
NODES_PATH = os.path.join(BASE, "graph", "nodes.json")
EDGES_PATH = os.path.join(BASE, "graph", "edges.json")
REGISTRY_PATH = os.path.join(BASE, "skills", "registry.json")
EVOLVED_DIR = os.path.join(os.path.dirname(BASE), "evolved")

STOP_WORDS = {"the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
              "have", "has", "had", "do", "does", "did", "will", "would", "can",
              "could", "shall", "should", "may", "might", "to", "of", "in", "for",
              "on", "with", "at", "by", "from", "as", "into", "through", "during",
              "before", "after", "above", "below", "between", "out", "off", "over",
              "under", "again", "further", "then", "once", "here", "there", "when",
              "where", "why", "how", "all", "each", "every", "both", "few", "more",
              "most", "other", "some", "such", "no", "nor", "not", "only", "own",
              "same", "so", "than", "too", "very", "just", "because", "but", "and",
              "or", "if", "while", "that", "this", "it", "its", "what", "which",
              "who", "whom", "whose", "get", "make", "use", "need", "find", "want"}

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

def tokenize(text):
    words = re.findall(r'[a-zA-Z][a-zA-Z0-9_-]*', text.lower())
    return [w for w in words if w not in STOP_WORDS and len(w) > 3]

def compute_keywords(lesson):
    text = " ".join([
        lesson.get("summary", ""),
        lesson.get("root_cause", ""),
        " ".join(lesson.get("embedding_keywords", []))
    ])
    return set(tokenize(text))

def jaccard_sim(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)

def find_clusters(lessons, min_cluster=3, min_sim=0.1):
    keyword_sets = [compute_keywords(l) for l in lessons]
    clusters = []
    assigned = set()
    for i in range(len(lessons)):
        if i in assigned:
            continue
        cluster = [i]
        assigned.add(i)
        for j in range(i + 1, len(lessons)):
            if j in assigned:
                continue
            sim = jaccard_sim(keyword_sets[i], keyword_sets[j])
            if sim >= min_sim:
                cluster.append(j)
                assigned.add(j)
        if len(cluster) >= min_cluster:
            clusters.append([lessons[idx] for idx in cluster])
    return clusters

def generate_skill_name(cluster):
    all_keywords = set()
    for lesson in cluster:
        all_keywords.update(compute_keywords(lesson))
    top = sorted(all_keywords, key=lambda w: -sum(1 for l in cluster if w in compute_keywords(l)))
    domain_terms = [t for t in top[:5] if len(t) > 4][:3]
    if domain_terms:
        return "-".join(domain_terms)
    return "consolidated-skill"

def generate_skill_description(cluster):
    failures = [l for l in cluster if l.get("outcome") == "failure"]
    successes = [l for l in cluster if l.get("outcome") == "success"]
    causes = set()
    fixes = set()
    for l in failures:
        rc = l.get("root_cause", "")
        if rc and rc != "N/A" and rc != "Unknown failure (check logs)":
            causes.add(rc[:100])
        fix = l.get("fix", "")
        if fix and fix != "N/A" and fix != "TODO: determine fix from root cause":
            fixes.add(fix[:100])
    desc_parts = [f"Consolidated from {len(cluster)} lessons ({len(failures)} failures, {len(successes)} successes)."]
    if causes:
        desc_parts.append("Known failure patterns: " + "; ".join(list(causes)[:3]))
    if fixes:
        desc_parts.append("Proven fixes: " + "; ".join(list(fixes)[:3]))
    return " ".join(desc_parts)

def build_skill_md(cluster, name, description):
    lines = ["---"]
    lines.append(f"name: {name}")
    lines.append(f"description: {description[:200]}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {name}")
    lines.append("")
    lines.append(f"Consolidated skill auto-generated from {len(cluster)} related lessons.")
    lines.append("")
    lines.append("## Failure Patterns")
    lines.append("")
    for i, lesson in enumerate(cluster, 1):
        summary = lesson.get("summary", "N/A")[:150]
        outcome = lesson.get("outcome", "unknown")
        root_cause = lesson.get("root_cause", "N/A")[:150]
        fix = lesson.get("fix", "N/A")[:200]
        lines.append(f"### {i}. {summary}")
        lines.append(f"- Outcome: {outcome}")
        lines.append(f"- Root cause: {root_cause}")
        lines.append(f"- Fix: {fix}")
        lines.append("")
    return "\n".join(lines)

def build_proposal(cluster, idx):
    name = generate_skill_name(cluster)
    description = generate_skill_description(cluster)
    md = build_skill_md(cluster, name, description)
    return {
        "proposal_id": idx,
        "skill_name": name,
        "description": description,
        "lesson_count": len(cluster),
        "failure_count": sum(1 for l in cluster if l.get("outcome") == "failure"),
        "success_count": sum(1 for l in cluster if l.get("outcome") == "success"),
        "lessons": [l.get("summary", "N/A")[:120] for l in cluster],
        "skill_md": md
    }

def scan():
    lessons = load_lessons()
    if not lessons:
        return {"proposals": [], "message": "No lessons found to consolidate"}
    clusters = find_clusters(lessons)
    if not clusters:
        return {"proposals": [], "message": f"Scanned {len(lessons)} lessons, no clusters of 3+ found"}
    proposals = []
    for idx, cluster in enumerate(clusters, 1):
        proposals.append(build_proposal(cluster, idx))
    return {"proposals": proposals, "message": f"Found {len(proposals)} consolidation candidate(s) from {len(lessons)} lessons"}

def apply(proposal_id):
    lessons = load_lessons()
    clusters = find_clusters(lessons)
    if not clusters or proposal_id < 1 or proposal_id > len(clusters):
        print(f"Invalid proposal_id {proposal_id}. Valid: 1-{len(clusters)}")
        return
    cluster = clusters[proposal_id - 1]
    proposal = build_proposal(cluster, proposal_id)
    name = proposal["skill_name"]
    skill_dir = os.path.join(EVOLVED_DIR, name)
    os.makedirs(skill_dir, exist_ok=True)
    md_path = os.path.join(skill_dir, "SKILL.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(proposal["skill_md"])
    print(f"Wrote {md_path}")
    if os.path.exists(REGISTRY_PATH):
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            registry = json.load(f)
    else:
        registry = {"skills": [], "evolved_skills": [], "project_skills": []}
    exists = any(s["name"] == name for s in registry.get("evolved_skills", []))
    if not exists:
        registry.setdefault("evolved_skills", []).append({
            "name": name,
            "path": f"evolved/{name}/",
            "type": "consolidated-skill",
            "version": "1.0.0",
            "created": datetime.utcnow().strftime("%Y-%m-%d")
        })
        with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2)
        print(f"Registered evolved_skills/{name} in registry")
    print("Done. Review the skill before using.")

def main():
    if len(sys.argv) < 2:
        result = scan()
        print(json.dumps(result, indent=2))
        return
    mode = sys.argv[1]
    if mode == "scan":
        result = scan()
        print(json.dumps(result, indent=2))
    elif mode == "apply":
        if len(sys.argv) < 3:
            print("Usage: python tool.py apply <proposal_id>")
            sys.exit(1)
        apply(int(sys.argv[2]))
    else:
        print(f"Unknown mode: {mode}. Use 'scan' or 'apply'.")

if __name__ == "__main__":
    main()
