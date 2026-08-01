import json
import sys
import os
import re
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NODES_PATH = os.path.join(BASE, "graph", "nodes.json")
EDGES_PATH = os.path.join(BASE, "graph", "edges.json")
LESSONS_PATH = os.path.join(BASE, "lessons", "lessons.jsonl")
CALIB_PATH = os.path.dirname(os.path.abspath(__file__)) + os.sep + "calibration.json"

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

def load_json(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return []

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

def load_calibration():
    if os.path.exists(CALIB_PATH):
        with open(CALIB_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"entries": [], "total_pairs": 0}

def save_calibration(data):
    os.makedirs(os.path.dirname(CALIB_PATH), exist_ok=True)
    with open(CALIB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def tokenize(text):
    words = re.findall(r'[a-zA-Z][a-zA-Z0-9_-]*', text.lower())
    return [w for w in words if w not in STOP_WORDS and len(w) > 2]

def score_overlap(query_tokens, target_text):
    target_tokens = set(tokenize(target_text))
    if not query_tokens or not target_tokens:
        return 0.0
    match_count = sum(1 for qt in query_tokens if qt in target_tokens)
    return match_count / max(len(query_tokens), 1)

def compute_calibration_correction(cal_data):
    entries = cal_data.get("entries", [])
    if len(entries) < 3:
        return 0.0
    recent = entries[-20:]
    total_err = 0.0
    for e in recent:
        total_err += e["predicted"] - e["actual"]
    avg_err = total_err / len(recent)
    return min(max(avg_err * 0.5, -0.3), 0.3)

def score(task_description, trajectory_features=None):
    query_tokens = tokenize(task_description)
    if not query_tokens:
        return {"confidence": 50, "reasoning": "Could not parse task", "factors": []}

    nodes = load_json(NODES_PATH)
    edges = load_json(EDGES_PATH)
    lessons = load_lessons()
    cal_data = load_calibration()

    factors = []
    base = 50.0

    # Factor 1: Exact task match in graph
    task_matches = [n for n in nodes if n.get("type") == "task" and task_description.lower()[:50] in n.get("label", "").lower()]
    if task_matches:
        last_node = task_matches[-1]
        for e in edges:
            if e.get("source_id") == last_node["id"] and e.get("type") == "produces":
                factors.append({"factor": "Exact task previously succeeded", "delta": +20})
                base += 20
                break
            if e.get("source_id") == last_node["id"] and e.get("type") == "caused":
                factors.append({"factor": "Exact task previously failed", "delta": -30})
                base -= 30
                break

    # Factor 2: Similar tasks from graph
    similar_tasks = []
    for n in nodes:
        if n.get("type") != "task":
            continue
        sim = score_overlap(query_tokens, n.get("label", "") + " " + n.get("summary", ""))
        if sim > 0.15:
            similar_tasks.append((n, sim))
    similar_tasks.sort(key=lambda x: -x[1])

    succ_count = 0
    fail_count = 0
    for t, sim in similar_tasks[:5]:
        tid = t["id"]
        for e in edges:
            if e.get("source_id") == tid:
                if e.get("type") == "produces":
                    succ_count += sim
                elif e.get("type") == "caused":
                    fail_count += sim

    if succ_count > fail_count:
        delta = min(succ_count * 15, 20)
        factors.append({"factor": "Similar tasks succeeded", "delta": round(delta)})
        base += delta
    elif fail_count > succ_count:
        delta = min(fail_count * 15, 20)
        factors.append({"factor": "Similar tasks failed", "delta": -round(delta)})
        base -= delta

    # Factor 3: Lesson match (failure patterns)
    for lesson in lessons:
        outcome = lesson.get("outcome", "")
        sim = score_overlap(query_tokens, json.dumps(lesson))
        if sim > 0.2 and outcome == "failure":
            delta = min(sim * 25, 15)
            factors.append({"factor": "Matching failure lesson found", "delta": -round(delta)})
            base -= delta
            break

    # Factor 4: Trajectory features
    feats = trajectory_features or {}
    dead_ends = feats.get("dead_ends", 0)
    re_reads = feats.get("re_reads", 0)
    re_fetches = feats.get("re_fetches", 0)

    if dead_ends:
        penalty = min(dead_ends * 10, 30)
        factors.append({"factor": f"{dead_ends} dead-end(s) encountered", "delta": -penalty})
        base -= penalty
    if re_reads:
        penalty = min(re_reads * 5, 15)
        factors.append({"factor": f"Re-read {re_reads} time(s)", "delta": -penalty})
        base -= penalty
    if re_fetches:
        penalty = min(re_fetches * 5, 15)
        factors.append({"factor": f"Re-fetched {re_fetches} time(s)", "delta": -penalty})
        base -= penalty

    # Factor 5: Calibration correction
    correction = compute_calibration_correction(cal_data)
    if correction != 0.0:
        delta = round(correction * 100)
        factors.append({"factor": f"Calibration correction ({'overconfident' if correction>0 else 'underconfident'})", "delta": delta})
        base += correction * 100

    # EMA smoothing with stored previous score
    calib_path = os.path.dirname(os.path.abspath(__file__)) + os.sep + "last_score.txt"
    prev_score = 50.0
    if os.path.exists(calib_path):
        try:
            with open(calib_path) as f:
                prev_score = float(f.read().strip())
        except:
            pass

    confidence = round(min(max(base, 1), 99))
    alpha = 0.40
    smoothed = round(alpha * confidence + (1 - alpha) * prev_score)
    try:
        with open(calib_path, "w") as f:
            f.write(str(smoothed))
    except:
        pass

    reasoning_parts = [f"Base: 50"]
    for f in factors:
        reasoning_parts.append(f"{f['delta']:+d} ({f['factor']})")
    reasoning = " -> ".join(reasoning_parts) + f" = {confidence} (smoothed: {smoothed})"

    return {"confidence": smoothed, "raw_score": confidence, "reasoning": reasoning, "factors": factors}

def record(predicted, actual):
    cal_data = load_calibration()
    cal_data.setdefault("entries", []).append({
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "predicted": predicted,
        "actual": actual
    })
    cal_data["total_pairs"] = len(cal_data["entries"])
    if len(cal_data["entries"]) > 200:
        cal_data["entries"] = cal_data["entries"][-200:]
    save_calibration(cal_data)
    avg_err = 0.0
    recent = cal_data["entries"][-20:]
    if recent:
        avg_err = sum(e["predicted"] - e["actual"] for e in recent) / len(recent)
    return {
        "recorded": True,
        "total_pairs": cal_data["total_pairs"],
        "recent_avg_error": round(avg_err, 2)
    }

def stats():
    cal_data = load_calibration()
    entries = cal_data.get("entries", [])
    if not entries:
        return {"total_pairs": 0, "message": "No calibration data yet"}
    recent_20 = entries[-20:]
    avg_pred = sum(e["predicted"] for e in recent_20) / len(recent_20)
    avg_actual = sum(e["actual"] for e in recent_20) / len(recent_20)
    overconfident = sum(1 for e in recent_20 if e["predicted"] > e["actual"] + 0.1)
    underconfident = sum(1 for e in recent_20 if e["predicted"] < e["actual"] - 0.1)
    return {
        "total_pairs": len(entries),
        "recent_20": {
            "avg_predicted": round(avg_pred, 2),
            "avg_actual": round(avg_actual, 2),
            "overconfident_count": overconfident,
            "underconfident_count": underconfident,
            "accuracy": round(avg_actual * 100, 1)
        }
    }

def main():
    if len(sys.argv) < 2:
        result = stats()
        print(json.dumps(result, indent=2))
        return
    mode = sys.argv[1]

    if mode == "score":
        if len(sys.argv) < 3:
            print("Usage: python tool.py score \"<task_description>\" [trajectory_features_json]")
            sys.exit(1)
        task_desc = sys.argv[2]
        traj = json.loads(sys.argv[3]) if len(sys.argv) > 3 else None
        result = score(task_desc, traj)
        print(json.dumps(result, indent=2))

    elif mode == "record":
        if len(sys.argv) < 4:
            print("Usage: python tool.py record <predicted_float> <actual_float>")
            sys.exit(1)
        result = record(float(sys.argv[2]), float(sys.argv[3]))
        print(json.dumps(result, indent=2))

    elif mode == "stats":
        result = stats()
        print(json.dumps(result, indent=2))

    else:
        print(f"Unknown mode: {mode}")

if __name__ == "__main__":
    main()
