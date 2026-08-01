import json
import sys
import os
import re

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLS_DIR = os.path.join(BASE, "tools")
NODES_PATH = os.path.join(BASE, "graph", "nodes.json")
EDGES_PATH = os.path.join(BASE, "graph", "edges.json")
LESSONS_PATH = os.path.join(BASE, "lessons", "lessons.jsonl")

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

def tokenize(text):
    words = re.findall(r'[a-zA-Z][a-zA-Z0-9_-]*', text.lower())
    return [w for w in words if w not in STOP_WORDS and len(w) > 2]

def score_overlap(query_tokens, target_text):
    target_tokens = set(tokenize(target_text))
    if not query_tokens or not target_tokens:
        return 0.0
    match_count = sum(1 for qt in query_tokens if qt in target_tokens)
    return match_count / max(len(query_tokens), 1)

def check_immune(task_desc, approach_desc):
    immune_py = os.path.join(TOOLS_DIR, "immune", "tool.py")
    if not os.path.exists(immune_py):
        return None
    import subprocess
    try:
        combined = task_desc + " " + approach_desc if approach_desc else task_desc
        r = subprocess.run(
            [sys.executable, immune_py, "detect", combined],
            capture_output=True, text=True, timeout=10
        )
        data = json.loads(r.stdout)
        return data
    except Exception as e:
        return {"error": str(e)}

def check_curriculum(task_desc):
    curr_py = os.path.join(TOOLS_DIR, "curriculum", "tool.py")
    if not os.path.exists(curr_py):
        return None
    import subprocess
    try:
        r = subprocess.run(
            [sys.executable, curr_py, "status"],
            capture_output=True, text=True, timeout=10
        )
        return json.loads(r.stdout)
    except:
        return None

def check_environment(task_desc):
    qt = tokenize(task_desc)
    risks = []

    token_to_tool = {
        "java": ("java", "JDK/JRE", "Can't execute Java files"),
        "node": ("node", "Node.js", "Can't run JavaScript/Node files"),
        "npm": ("node", "Node.js", "Can't run npm commands"),
        "react": ("node", "Node.js", "React requires Node.js"),
        "dotnet": ("dotnet", ".NET SDK", "Can't compile C#/.NET"),
        "csharp": ("dotnet", ".NET SDK", "Can't compile C#"),
        "c#": ("dotnet", ".NET SDK", "Can't compile C#"),
        "gcc": ("gcc", "GCC compiler", "Can't compile C"),
        "g++": ("gcc", "GCC compiler", "Can't compile C++"),
        "apk": ("android", "Android SDK", "Can't compile APK"),
        "android": ("android", "Android SDK", "Can't compile Android apps"),
        "exe": ("compiler", "Native compiler", "Can't compile native EXE from C/C++"),
        "wsl": ("wsl", "WSL", "WSL is disabled — do NOT install"),
        "hyper-v": ("hyperv", "Hyper-V", "Hyper-V is disabled — do NOT enable"),
    }

    for token, (tool_id, tool_name, reason) in token_to_tool.items():
        if any(token in t for t in qt):
            risks.append({
                "risk": "missing_tool",
                "detail": f"Missing: {tool_name}",
                "reason": reason,
                "critical": True
            })

    return risks

def check_past_failures(task_desc, approach_desc):
    nodes = load_json(NODES_PATH) or []
    edges = load_json(EDGES_PATH) or []
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

    qt = tokenize(task_desc)
    if approach_desc:
        qt += tokenize(approach_desc)

    if not qt:
        return []

    failure_patterns = []

    for lesson in lessons:
        if lesson.get("outcome") != "failure":
            continue
        text = json.dumps(lesson)
        score = score_overlap(qt, text)
        if score > 0.15:
            failure_patterns.append({
                "type": "lesson_match",
                "score": round(score, 3),
                "summary": (lesson.get("summary") or "")[:120],
                "root_cause": (lesson.get("root_cause") or "")[:100],
                "fix": (lesson.get("fix") or "")[:120]
            })

    for node in nodes:
        if node.get("type") not in ("lesson", "failure", "task"):
            continue
        if node.get("outcome") != "failure":
            continue
        text = json.dumps(node)
        score = score_overlap(qt, text)
        if score > 0.15 and not any(
            f.get("summary", "")[:40] == (node.get("summary") or "")[:40]
            for f in failure_patterns
        ):
            failure_patterns.append({
                "type": "graph_match",
                "score": round(score, 3),
                "summary": (node.get("summary") or node.get("label") or "")[:120],
                "root_cause": (node.get("root_cause") or "N/A")[:100],
                "fix": (node.get("fix") or "N/A")[:120]
            })

    failure_patterns.sort(key=lambda x: -x["score"])
    return failure_patterns[:5]

def check_complexity_risk(task_desc):
    qt = tokenize(task_desc)
    complexity_indicators = {
        "system": ["install", "compile", "build", "deploy", "configure", "setup"],
        "api": ["api", "oauth", "jwt", "webhook", "endpoint", "rest", "graphql"],
        "network": ["wifi", "airtel", "router", "connect", "ssh", "port", "proxy"],
        "auth": ["bypass", "crack", "password", "login", "hack", "exploit", "inject"],
        "ml": ["train", "neural", "model", "predict", "classifier", "tensor", "gradient"],
        "gui": ["window", "ui", "gui", "button", "form", "dialog", "popup", "desktop"],
        "download": ["download", "yt-dlp", "mega", "stream", "video", "movie"],
    }

    matched_categories = []
    for category, indicators in complexity_indicators.items():
        matches = [i for i in indicators if any(i in t for t in qt)]
        if matches:
            matched_categories.append({"category": category, "indicators": matches[:3]})

    if not matched_categories:
        return {"risk_level": "low", "categories": []}

    high_risk_categories = {"auth", "network", "gui", "download", "system"}
    max_risk = "low"
    for mc in matched_categories:
        if mc["category"] in high_risk_categories:
            max_risk = "high"
            break
        max_risk = "medium"

    return {"risk_level": max_risk, "categories": matched_categories}

def predict(task_desc, approach_desc=None):
    qt = tokenize(task_desc)
    factors = []
    total_risk = 0.0
    max_risk = 0.0

    # Factor 1: Immune system match
    immune = check_immune(task_desc, approach_desc)
    if immune:
        auto = immune.get("auto_deploy", [])
        suggest = immune.get("suggest", [])
        if auto:
            weight = sum(m.get("effective_strength", 0) for m in auto) / len(auto)
            factors.append({
                "factor": "Immune system — auto-deploy triggered",
                "risk": round(weight, 3),
                "detail": auto[0].get("countermeasure", {}).get("message", "")[:150]
            })
            total_risk += weight * 1.5
            max_risk = max(max_risk, weight * 1.5)
        elif suggest:
            weight = sum(m.get("effective_strength", 0) for m in suggest) / len(suggest)
            factors.append({
                "factor": "Immune system — similar failure pattern found",
                "risk": round(weight, 3),
                "detail": suggest[0].get("countermeasure", {}).get("message", "")[:150]
            })
            total_risk += weight * 1.2
            max_risk = max(max_risk, weight * 1.2)

    # Factor 2: Environment constraints
    env_risks = check_environment(task_desc)
    for env in env_risks:
        factors.append({
            "factor": "Environment — " + env["detail"],
            "risk": 0.9,
            "detail": env["reason"]
        })
        total_risk += 0.9
        max_risk = max(max_risk, 0.9)

    # Factor 3: Past failure patterns
    failures = check_past_failures(task_desc, approach_desc)
    if failures:
        avg_score = sum(f["score"] for f in failures) / len(failures)
        factors.append({
            "factor": f"Past failures — {len(failures)} similar failure(s) found",
            "risk": round(avg_score, 3),
            "detail": failures[0]["summary"][:150],
            "matches": failures[:3]
        })
        total_risk += avg_score * 1.3
        max_risk = max(max_risk, avg_score * 1.3)

    # Factor 4: Complexity risk
    complexity = check_complexity_risk(task_desc)
    if complexity["risk_level"] == "high":
        risk_val = 0.7
        factors.append({
            "factor": "High-complexity domain",
            "risk": risk_val,
            "detail": f"Domains: {', '.join(c['category'] for c in complexity['categories'])}"
        })
        total_risk += risk_val
        max_risk = max(max_risk, risk_val)
    elif complexity["risk_level"] == "medium":
        risk_val = 0.4
        factors.append({
            "factor": "Medium-complexity domain",
            "risk": risk_val,
            "detail": f"Domains: {', '.join(c['category'] for c in complexity['categories'])}"
        })
        total_risk += risk_val

    # Factor 5: Curriculum readiness (contextual — only if relevant domain skills are low)
    curriculum = check_curriculum(task_desc)
    if curriculum and curriculum.get("tracks"):
        domain_to_skills = {
            "system": ["debugging", "php-development", "tool-forager"],
            "api": ["web-surfing", "web-scraping", "auth-bypass"],
            "network": ["auth-bypass", "tool-forager", "debugging"],
            "auth": ["auth-bypass", "web-scraping", "debugging"],
            "ml": ["math-reasoning", "verification", "debugging"],
            "gui": ["php-development"],
            "download": ["web-surfing", "tool-forager", "debugging"],
        }
        task_domains = [c["category"] for c in complexity.get("categories", [])]
        relevant_skills = set()
        for d in task_domains:
            relevant_skills.update(domain_to_skills.get(d, []))
        if relevant_skills:
            unused_relevant = 0
            for track in curriculum["tracks"]:
                for s in track.get("skills", []):
                    if s["name"] in relevant_skills and s["mastery"]["level"] == "unused":
                        unused_relevant += 1
            if unused_relevant > 0:
                risk_val = round(min(0.3, 0.1 * unused_relevant), 3)
                factors.append({
                    "factor": f"Curriculum — {unused_relevant} relevant skill(s) unused",
                    "risk": risk_val,
                    "detail": f"Skills needed for {', '.join(task_domains)} have never been used"
                })
                total_risk += risk_val

    # Compute final verdict
    num_factors = max(len(factors), 1)
    avg_risk = total_risk / num_factors
    peak_risk = max_risk

    combined = (avg_risk * 0.4 + peak_risk * 0.6)

    if combined >= 0.7:
        verdict = "WILL_FAIL"
        confidence = round(min(combined * 100, 95))
    elif combined >= 0.4:
        verdict = "HIGH_RISK"
        confidence = round(combined * 100)
    elif combined >= 0.2:
        verdict = "LOW_RISK"
        confidence = round((1 - combined) * 60 + 20)
    else:
        verdict = "LIKELY_SUCCEED"
        confidence = round(85)

    return {
        "task": task_desc[:100] + ("..." if len(task_desc) > 100 else ""),
        "approach": (approach_desc[:100] + ("..." if len(approach_desc) > 100 else "")) if approach_desc else None,
        "verdict": verdict,
        "confidence": confidence,
        "combined_risk": round(combined, 3),
        "factors": factors,
        "recommendation": generate_recommendation(verdict, factors, locals().get('failures'))
    }

def generate_recommendation(verdict, factors, failures=None):
    if verdict == "WILL_FAIL":
        blocking = [f for f in factors if f["risk"] >= 0.7]
        lines = ["This approach will likely fail. Blocking factors:"]
        for b in blocking:
            lines.append(f"  - {b['factor']}: {b['detail'][:100]}")
        lines.append("")
        lines.append("Recommended: Pivot to a different approach.")
        if failures:
            best = failures[0].get("fix", "")
            if best:
                lines.append(f"From past failure: {best[:200]}")
        return "\n".join(lines)

    elif verdict == "HIGH_RISK":
        lines = ["Proceed with caution. Risk factors:"]
        for f in factors:
            lines.append(f"  - [{f['risk']:.0%}] {f['factor']}")
        lines.append("")
        lines.append("Recommended: Check immune guardrails, verify prerequisites, or use parallel mode.")
        return "\n".join(lines)

    elif verdict == "LOW_RISK":
        return "Minor risks detected. Proceed normally but watch for: " + "; ".join(
            f["detail"][:80] for f in factors
        )
    else:
        return "No significant risks detected. Proceed."

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"help": "Failure prediction tool — checks immune system, environment, past failures, complexity, curriculum to predict task outcome", "modes": ["predict", "check-env", "check-complexity"], "usage": "python tool.py predict \"<task_description>\" [\"<approach_description>\"]", "default": "Showing help (no default mode)"}, indent=2))
        return
    mode = sys.argv[1]

    if mode == "predict":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "No task description provided", "usage": 'python tool.py predict "<task_description>" ["<approach_description>"]'}, indent=2))
            return
        task = sys.argv[2]
        approach = sys.argv[3] if len(sys.argv) > 3 else None
        result = predict(task, approach)
        print(json.dumps(result, indent=2))

    elif mode == "check-env":
        task = sys.argv[2] if len(sys.argv) > 2 else ""
        result = check_environment(task)
        print(json.dumps(result, indent=2))

    elif mode == "check-complexity":
        task = sys.argv[2] if len(sys.argv) > 2 else ""
        result = check_complexity_risk(task)
        print(json.dumps(result, indent=2))

    else:
        print(f"Unknown mode: {mode}")

if __name__ == "__main__":
    main()
    try:
        import subprocess
        record_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_record_usage.py")
        subprocess.run([sys.executable, record_path, "failure-predict"], capture_output=True, timeout=5)
    except:
        pass
