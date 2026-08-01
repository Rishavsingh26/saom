import json
import sys
import os
import re
import math
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IMMUNE_DIR = os.path.dirname(os.path.abspath(__file__))
ANTIBODIES_PATH = os.path.join(IMMUNE_DIR, "antibodies.json")
LESSONS_PATH = os.path.join(BASE, "lessons", "lessons.jsonl")
NODES_PATH = os.path.join(BASE, "graph", "nodes.json")
EDGES_PATH = os.path.join(BASE, "graph", "edges.json")

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
    return None

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def load_antibodies():
    data = load_json(ANTIBODIES_PATH)
    if data is None:
        data = {"antibodies": [], "schema_version": "1.0", "last_decay": None, "total_antibodies_ever": 0}
    return data

def save_antibodies(data):
    save_json(ANTIBODIES_PATH, data)

def tokenize(text):
    words = re.findall(r'[a-zA-Z][a-zA-Z0-9_-]*', text.lower())
    return [w for w in words if w not in STOP_WORDS and len(w) > 2]

def compute_overlap(query_tokens, pattern_tokens):
    if not query_tokens or not pattern_tokens:
        return 0.0
    qset = set(query_tokens)
    pset = set(pattern_tokens)
    intersection = qset & pset
    jaccard = len(intersection) / max(len(qset | pset), 1)
    coverage = len(intersection) / max(len(qset), 1)
    return round((jaccard * 0.5 + coverage * 0.5), 3)

def detect(task_description):
    query_tokens = tokenize(task_description)
    if not query_tokens:
        return {"matches": [], "message": "Could not parse task"}

    data = load_antibodies()
    antibodies = data.get("antibodies", [])
    matches = []

    for ab in antibodies:
        pattern = ab.get("pathogen_pattern", {})
        kw_tokens = tokenize(" ".join(pattern.get("keywords", [])))
        domain_tokens = tokenize(pattern.get("domain", ""))
        type_tokens = tokenize(pattern.get("task_type", ""))

        all_pattern_tokens = list(set(kw_tokens + domain_tokens + type_tokens))
        score = compute_overlap(query_tokens, all_pattern_tokens)

        if score > 0.0:
            effective_strength = ab.get("strength", 0.5) * score
            matches.append({
                "id": ab["id"],
                "score": score,
                "effective_strength": round(effective_strength, 3),
                "strength": ab.get("strength", 0.5),
                "countermeasure": ab.get("countermeasure", {}),
                "deploy_count": ab.get("deploy_count", 0),
                "last_deployed": ab.get("last_deployed"),
                "created": ab.get("created")
            })

    matches.sort(key=lambda x: -x["score"])

    auto_deploy = [m for m in matches if m["effective_strength"] >= 0.5]
    suggest = [m for m in matches if 0.25 <= m["effective_strength"] < 0.5]
    noise = [m for m in matches if m["effective_strength"] < 0.25]

    return {
        "matches": matches,
        "auto_deploy": auto_deploy,
        "suggest": suggest,
        "noise": noise,
        "total_matched": len(matches),
        "decision": "auto_deploy" if auto_deploy else ("suggest" if suggest else "none")
    }

def generate_antibody_id(data):
    data["total_antibodies_ever"] = data.get("total_antibodies_ever", 0) + 1
    count = data["total_antibodies_ever"]
    return f"ab:{count}"

def learn(outcome, summary, countermeasure, strength=None):
    data = load_antibodies()
    antibodies = data["antibodies"]
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    summary_lower = summary.lower()
    words = tokenize(summary)

    domain_keywords = {
        "network": ["wifi", "airtel", "password", "crack", "network", "connect", "router", "wpa", "psk", "ssid"],
        "web": ["api", "endpoint", "http", "url", "fetch", "request", "response", "cookie", "token", "auth", "login"],
        "download": ["download", "yt-dlp", "mega", "file", "host", "ad-wall", "rate-limit", "captcha"],
        "auth": ["auth", "login", "signup", "password", "otp", "token", "session", "cookie", "bypass"],
        "install": ["install", "wsl", "pip", "npm", "package", "windows", "feature", "driver"],
        "file": ["file", "read", "write", "parse", "json", "csv", "xml", "encoding", "path"],
        "testing": ["test", "assert", "verify", "check", "validate", "regression", "bug"],
        "ml": ["neural", "model", "train", "predict", "linear", "activation", "network", "learn"],
    }

    detected_domain = "unknown"
    for domain, kws in domain_keywords.items():
        if any(kw in summary_lower for kw in kws):
            detected_domain = domain
            break

    countermeasure_type = "guardrail"
    if "load_skill" in countermeasure or "skill" in countermeasure.get("type", ""):
        countermeasure_type = "load_skill"
    if "apply_patch" in countermeasure or "modify" in countermeasure.get("action", ""):
        countermeasure_type = "behavior_patch"

    default_strength = 0.7 if outcome == "failure" else 0.5

    antibody = {
        "id": generate_antibody_id(data),
        "pathogen_pattern": {
            "keywords": words[:15] if len(words) > 15 else words,
            "domain": detected_domain,
            "task_type": outcome
        },
        "countermeasure": {
            "type": countermeasure_type,
            "message": summary[:300],
            "action": countermeasure.get("action", ""),
            "load_skill": countermeasure.get("load_skill"),
            "apply_patch": countermeasure.get("apply_patch")
        },
        "strength": strength if strength is not None else default_strength,
        "deploy_count": 0,
        "success_count": 0,
        "false_positive_count": 0,
        "created": now,
        "last_deployed": None,
        "last_modified": now,
        "source_lesson": summary[:100]
    }

    antibodies.append(antibody)
    save_antibodies(data)

    return {"antibody_id": antibody["id"], "domain": detected_domain, "strength": antibody["strength"], "total": len(antibodies)}

def deploy(antibody_id, outcome=None):
    data = load_antibodies()
    antibodies = data["antibodies"]
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    for ab in antibodies:
        if ab["id"] == antibody_id:
            ab["deploy_count"] += 1
            ab["last_deployed"] = now
            ab["last_modified"] = now
            if outcome == "success":
                ab["success_count"] += 1
                ab["strength"] = round(min(1.0, ab["strength"] + 0.1), 3)
            elif outcome == "failure":
                ab["false_positive_count"] += 1
                ab["strength"] = round(max(0.1, ab["strength"] - 0.2), 3)
            save_antibodies(data)
            return {"deployed": True, "antibody_id": antibody_id, "new_strength": ab["strength"], "deploy_count": ab["deploy_count"]}

    return {"error": f"Antibody {antibody_id} not found"}

def feedback(antibody_id, correct):
    data = load_antibodies()
    antibodies = data["antibodies"]
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    for ab in antibodies:
        if ab["id"] == antibody_id:
            ab["last_modified"] = now
            if correct:
                ab["success_count"] += 1
                ab["strength"] = round(min(1.0, ab["strength"] + 0.15), 3)
            else:
                ab["false_positive_count"] += 1
                ab["strength"] = round(max(0.05, ab["strength"] - 0.25), 3)
            save_antibodies(data)
            return {"updated": True, "antibody_id": antibody_id, "new_strength": ab["strength"]}

    return {"error": f"Antibody {antibody_id} not found"}

def forget(antibody_id=None):
    data = load_antibodies()
    antibodies = data["antibodies"]

    if antibody_id:
        before = len(antibodies)
        data["antibodies"] = [ab for ab in antibodies if ab["id"] != antibody_id]
        removed = before - len(data["antibodies"])
        save_antibodies(data)
        return {"forgotten": removed > 0, "antibody_id": antibody_id, "message": f"Removed {removed} antibody" if removed else "Not found"}
    else:
        before = len(antibodies)
        threshold = 0.15
        data["antibodies"] = [ab for ab in antibodies if ab["strength"] >= threshold or ab.get("deploy_count", 0) > 0]
        data["last_decay"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        removed = before - len(data["antibodies"])
        save_antibodies(data)
        return {"pruned": removed, "remaining": len(data["antibodies"]), "threshold": threshold}

def status():
    data = load_antibodies()
    antibodies = data["antibodies"]

    by_domain = {}
    for ab in antibodies:
        domain = ab.get("pathogen_pattern", {}).get("domain", "unknown")
        by_domain.setdefault(domain, []).append(ab)

    domain_summary = {}
    for domain, abs_list in by_domain.items():
        domain_summary[domain] = {
            "count": len(abs_list),
            "avg_strength": round(sum(ab["strength"] for ab in abs_list) / len(abs_list), 3),
            "total_deploys": sum(ab.get("deploy_count", 0) for ab in abs_list)
        }

    return {
        "total_antibodies": len(antibodies),
        "by_domain": domain_summary,
        "strong_antibodies": len([ab for ab in antibodies if ab["strength"] >= 0.7]),
        "weak_antibodies": len([ab for ab in antibodies if ab["strength"] < 0.3]),
        "total_deployments": sum(ab.get("deploy_count", 0) for ab in antibodies),
        "last_decay": data.get("last_decay"),
        "antibodies": [
            {
                "id": ab["id"],
                "domain": ab.get("pathogen_pattern", {}).get("domain", "unknown"),
                "strength": ab["strength"],
                "deploy_count": ab.get("deploy_count", 0),
                "success_count": ab.get("success_count", 0),
                "fp_count": ab.get("false_positive_count", 0),
                "countermeasure_type": ab.get("countermeasure", {}).get("type", "guardrail"),
                "keywords": ab.get("pathogen_pattern", {}).get("keywords", [])[:5],
                "last_deployed": ab.get("last_deployed"),
                "created": ab.get("created")
            }
            for ab in sorted(antibodies, key=lambda x: -x["strength"])
        ]
    }

def seed_from_lessons():
    antibodies_data = load_antibodies()
    existing_sources = {ab.get("source_lesson", "") for ab in antibodies_data.get("antibodies", [])}

    lessons = []
    if os.path.exists(LESSONS_PATH):
        with open(LESSONS_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        lessons.append(json.loads(line))
                    except:
                        pass

    seeded = 0
    for lesson in lessons:
        summary = lesson.get("summary", "")
        if not summary or summary[:100] in existing_sources:
            continue
        existing_sources.add(summary[:100])
        outcome = lesson.get("outcome", "failure")
        countermeasure = {
            "action": lesson.get("fix", "Review lesson before repeating this task"),
            "type": "guardrail"
        }
        result = learn(outcome, summary, countermeasure)
        if result:
            seeded += 1

    final_data = load_antibodies()
    return {"seeded": seeded, "total_antibodies": len(final_data.get("antibodies", []))}

def main():
    if len(sys.argv) < 2:
        result = status()
        print(json.dumps(result, indent=2))
        return
    mode = sys.argv[1]

    if mode == "detect":
        if len(sys.argv) < 3:
            print("Usage: python tool.py detect \"<task_description>\"")
            sys.exit(1)
        result = detect(sys.argv[2])
        print(json.dumps(result, indent=2))

    elif mode == "learn":
        if len(sys.argv) < 4:
            print("Usage: python tool.py learn <failure|success> \"<summary>\" [action_string] [strength]")
            sys.exit(1)
        outcome = sys.argv[2]
        summary = sys.argv[3]
        action = sys.argv[4] if len(sys.argv) > 4 else ""
        cm = {"action": action, "type": "guardrail"}
        strength = float(sys.argv[5]) if len(sys.argv) > 5 else None
        result = learn(outcome, summary, cm, strength)
        print(json.dumps(result, indent=2))

    elif mode == "deploy":
        if len(sys.argv) < 3:
            print("Usage: python tool.py deploy <antibody_id> [success|failure]")
            sys.exit(1)
        outcome = sys.argv[3] if len(sys.argv) > 3 else None
        result = deploy(sys.argv[2], outcome)
        print(json.dumps(result, indent=2))

    elif mode == "feedback":
        if len(sys.argv) < 4:
            print("Usage: python tool.py feedback <antibody_id> <true|false>")
            sys.exit(1)
        correct = sys.argv[3].lower() == "true"
        result = feedback(sys.argv[2], correct)
        print(json.dumps(result, indent=2))

    elif mode == "forget":
        ab_id = sys.argv[2] if len(sys.argv) > 2 else None
        result = forget(ab_id)
        print(json.dumps(result, indent=2))

    elif mode == "status":
        result = status()
        print(json.dumps(result, indent=2))

    elif mode == "seed":
        result = seed_from_lessons()
        print(json.dumps(result, indent=2))

    else:
        print(f"Unknown mode: {mode}")

if __name__ == "__main__":
    main()
    try:
        import subprocess
        record_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_record_usage.py")
        subprocess.run([sys.executable, record_path, "immune"], capture_output=True, timeout=5)
    except:
        pass
