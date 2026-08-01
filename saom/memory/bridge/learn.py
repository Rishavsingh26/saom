"""Preference learner: auto-observes corrections, uses LLM for pattern extraction."""
import json, os, re, sys, urllib.request
from datetime import datetime

BRIDGE = os.path.dirname(os.path.abspath(__file__))
PREFS_PATH = os.path.join(BRIDGE, "preferences.json")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
MODEL = "openai/gpt-oss-20b"
UA = "Mozilla/5.0 (compatible; SAOM-bot/1.0)"

def _llm(prompt):
    """Call Groq with a prompt, return text response."""
    if not GROQ_KEY:
        return "ERROR: no GROQ_API_KEY"
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1024, "temperature": 0.3
    }).encode()
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json", "User-Agent": UA},
        method="POST"
    )
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
        return resp['choices'][0]['message']['content'].strip()
    except Exception as e:
        return f"ERROR: {e}"

def load():
    if os.path.exists(PREFS_PATH):
        try:
            with open(PREFS_PATH, encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"corrections": [], "rules": [], "last_updated": None}

def save(data):
    os.makedirs(os.path.dirname(PREFS_PATH), exist_ok=True)
    with open(PREFS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def observe(raw_input, assistant_output, user_correction):
    """Record a correction and auto-generalize if enough data."""
    data = load()
    entry = {
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "raw_input": raw_input[:300],
        "assistant_output": assistant_output[:300],
        "user_correction": user_correction[:300],
        "pattern": None,
        "rule_applied": False
    }
    data["corrections"].append(entry)
    if len(data["corrections"]) > 200:
        data["corrections"] = data["corrections"][-200:]
    save(data)

    # Auto-generalize if at least 2 corrections
    rules_before = len(data.get("rules", []))
    if len(data["corrections"]) >= 2:
        g = generalize(silent=True)
        rules_now = g.get("rules", 0)
        return {"recorded": len(data["corrections"]), "rules_updated": rules_now > rules_before, "new_rules": g.get("new", 0)}
    return {"recorded": len(data["corrections"]), "rules_updated": False}

def generalize(silent=False):
    """Use LLM to analyze ALL corrections and extract coherent preference rules."""
    data = load()
    corrs = data["corrections"]
    if len(corrs) < 2:
        r = {"rules": len(data.get("rules", [])), "new": 0, "message": "Need 2+ corrections"}
        if not silent: print(json.dumps(r, indent=2))
        return r

    # Build correction summary for LLM
    corr_text = "\n".join(
        f"{i+1}. User said: {c['user_correction'][:200]}" for i, c in enumerate(corrs[-10:])
    )

    prompt = f"""You are a behavior-pattern analyzer. Below are the last {min(len(corrs), 10)} user corrections directed at an AI assistant.

{corr_text}

Extract 1-4 distinct preference rules the user is teaching. For each, output ONLY a JSON object with:
- rule_id: short unique identifier (e.g., "be_concise", "no_latex", "test_first")
- description: what the rule means (one sentence)
- trigger: when this rule applies (e.g., "math questions", "code output", "all responses")
- check_before: question to ask before responding (one sentence)

Output a JSON list ONLY, no other text:
[{{"rule_id": "...", "description": "...", "trigger": "...", "check_before": "..."}}]
"""

    raw = _llm(prompt)
    if raw.startswith("ERROR"):
        if not silent: print(json.dumps({"error": raw}, indent=2))
        return {"rules": len(data.get("rules", [])), "new": 0, "error": raw}

    # Parse LLM response
    try:
        # Find JSON array in response
        json_match = re.search(r'\[.*\]', raw, re.DOTALL)
        if not json_match:
            if not silent: print(json.dumps({"error": "No JSON in LLM response", "raw": raw[:200]}, indent=2))
            return {"rules": len(data.get("rules", [])), "new": 0}
        new_rules = json.loads(json_match.group(0))
    except json.JSONDecodeError as e:
        if not silent: print(json.dumps({"error": f"JSON parse: {e}", "raw": raw[:200]}, indent=2))
        return {"rules": len(data.get("rules", [])), "new": 0}

    existing_ids = {r["rule_id"] for r in data.get("rules", [])}
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    new_count = 0
    for nr in new_rules:
        nr["created"] = now
        nr["source_count"] = len(corrs)
        if nr["rule_id"] in existing_ids:
            for r in data["rules"]:
                if r["rule_id"] == nr["rule_id"]:
                    r.update({k: v for k, v in nr.items() if k in ["description", "trigger", "check_before"]})
                    r["last_triggered"] = now
                    r["source_count"] = len(corrs)
        else:
            data["rules"].append(nr)
            new_count += 1
            existing_ids.add(nr["rule_id"])

    data["last_updated"] = now
    save(data)

    result = {"rules": len(data["rules"]), "new": new_count, "rule_ids": [r["rule_id"] for r in data["rules"]]}
    if not silent: print(json.dumps(result, indent=2))
    return result

def check(task_description):
    """Use LLM to check which learned rules apply to this task."""
    data = load()
    if not data.get("rules"):
        return {"warnings": [], "safe": True}

    rules_text = "\n".join(
        f"- {r['rule_id']}: {r['description']} (trigger: {r.get('trigger','any')})"
        for r in data["rules"]
    )

    prompt = f"""Given these learned preference rules:

{rules_text}

And the task: "{task_description}"

Which rules should the assistant follow for this specific task? Return ONLY a JSON list of rule_ids that apply:
["rule_id_1", "rule_id_2"]

Base it on the trigger description. If none apply, return [].
"""

    raw = _llm(prompt)
    if raw.startswith("ERROR"):
        return {"warnings": [{"rule": "llm_error", "message": "Could not check preferences", "check": ""}], "safe": False}

    try:
        json_match = re.search(r'\[.*\]', raw, re.DOTALL)
        if json_match:
            applicable = json.loads(json_match.group(0))
        else:
            applicable = []
    except:
        applicable = []

    rule_map = {r["rule_id"]: r for r in data["rules"]}
    warnings = []
    for rid in applicable:
        if rid in rule_map:
            r = rule_map[rid]
            warnings.append({
                "rule": rid,
                "message": r["description"],
                "check": r.get("check_before", "Does this follow the rule?")
            })

    result = {"warnings": warnings, "safe": len(warnings) == 0}
    print(json.dumps(result, indent=2))
    return result

def status():
    data = load()
    result = {
        "total_corrections": len(data["corrections"]),
        "active_rules": len(data.get("rules", [])),
        "rules": [{"id": r["rule_id"], "desc": r["description"][:80], "trigger": r.get("trigger","")[:40]} for r in data.get("rules", [])],
        "recent_corrections": [{
            "time": c["timestamp"],
            "correction": c["user_correction"][:100]
        } for c in data["corrections"][-5:]]
    }
    print(json.dumps(result, indent=2))
    return result

def main():
    if len(sys.argv) < 2:
        print("Usage: python learn.py <observe|generalize|check|status> [args]")
        sys.exit(1)
    mode = sys.argv[1]
    if mode == "observe":
        inp = sys.argv[2] if len(sys.argv) > 2 else ""
        out = sys.argv[3] if len(sys.argv) > 3 else ""
        corr = sys.argv[4] if len(sys.argv) > 4 else ""
        r = observe(inp, out, corr)
        print(json.dumps(r, indent=2))
    elif mode == "generalize":
        generalize(silent=False)
    elif mode == "check":
        task = sys.argv[2] if len(sys.argv) > 2 else ""
        check(task)
    elif mode == "status":
        status()
    else:
        print(json.dumps({"error": f"Unknown mode: {mode}"}))

if __name__ == "__main__":
    main()
