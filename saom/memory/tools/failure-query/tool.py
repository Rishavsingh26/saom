import json
import sys
import os
import re

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

def load_json(name):
    path = os.path.join(BASE, "graph", name)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return []

def load_lessons_jsonl():
    path = os.path.join(BASE, "lessons", "lessons.jsonl")
    if not os.path.exists(path):
        return []
    lessons = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                lessons.append(json.loads(line))
    return lessons

def tokenize(text):
    words = re.findall(r'[a-zA-Z][a-zA-Z0-9_-]*', text.lower())
    return [w for w in words if w not in STOP_WORDS and len(w) > 1]

def score_overlap(query_tokens, target_text):
    target_tokens = set(tokenize(target_text))
    if not query_tokens or not target_tokens:
        return 0.0
    match_count = sum(1 for qt in query_tokens if qt in target_tokens)
    return match_count / max(len(query_tokens), 1)

def query(task_description):
    query_tokens = tokenize(task_description)
    if not query_tokens:
        return {"matches": [], "guardrail": None}

    nodes = load_json("nodes.json")
    edges = load_json("edges.json")
    lessons = load_lessons_jsonl()

    def get_signature(entry):
        summary = entry.get("summary", entry.get("task", ""))
        return summary[:80].strip().lower()

    def has_valid_summary(entry):
        s = entry.get("summary") or entry.get("task") or ""
        return len(s.strip()) > 5 and "N/A" not in s[:10]

    scored_lessons = []
    seen_signatures = set()
    for lesson in lessons:
        if not has_valid_summary(lesson):
            continue
        sig = get_signature(lesson)
        if sig and sig in seen_signatures:
            continue
        if sig:
            seen_signatures.add(sig)
        text = json.dumps(lesson)
        score = score_overlap(query_tokens, text)
        if score > 0.0:
            scored_lessons.append({"lesson": lesson, "score": score, "source": "jsonl"})

    for node in nodes:
        if node.get("type") not in ("lesson", "failure", "task"):
            continue
        if not has_valid_summary(node):
            continue
        sig = get_signature(node)
        if sig and sig in seen_signatures:
            continue
        if sig:
            seen_signatures.add(sig)
        text = json.dumps(node)
        score = score_overlap(query_tokens, text)
        if score > 0.0:
            scored_lessons.append({"lesson": node, "score": score, "source": "graph"})

    scored_lessons.sort(key=lambda x: -x["score"])
    top = scored_lessons[:5]

    if not top:
        return {"matches": [], "guardrail": None}

    task_edge_map = {}
    for e in edges:
        if e["type"] in ("produces", "caused"):
            task_edge_map.setdefault(e["source_id"], []).append(e)

    findings = []
    for item in top:
        lesson = item["lesson"]
        lid = lesson.get("id") or lesson.get("lesson_id")
        root_cause = lesson.get("root_cause", "N/A")
        fix = lesson.get("fix", "N/A")
        summary = lesson.get("summary", lesson.get("task", "N/A"))
        findings.append({
            "summary": summary[:150],
            "root_cause": root_cause[:150] if isinstance(root_cause, str) else "N/A",
            "fix": fix[:200] if isinstance(fix, str) else "N/A",
            "match_score": round(item["score"], 2)
        })

    guardrail_lines = ["KNOWN FAILURE PATTERNS FOUND"]
    guardrail_lines.append("")
    for f in findings:
        guardrail_lines.append(f"- {f['summary']}")
        guardrail_lines.append(f"  Root cause: {f['root_cause']}")
        guardrail_lines.append(f"  Fix: {f['fix']}")
        guardrail_lines.append("")
    guardrail_text = "\n".join(guardrail_lines)

    return {
        "matches": findings,
        "guardrail": guardrail_text,
        "match_count": len(findings),
        "severity": "WARNING" if findings else "CLEAR"
    }

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"help": "Failure query tool — searches lesson database for similar past failures matching a task description", "modes": ["<task_description>"], "usage": 'python tool.py "<task_description>"', "default": "Showing help (no default mode)"}, indent=2))
        return
    task_desc = sys.argv[1]
    result = query(task_desc)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
