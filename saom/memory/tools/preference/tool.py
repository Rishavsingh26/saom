"""Preference tool — observes corrections, generalizes rules, checks tasks."""
import json, os, sys, subprocess

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BRIDGE = os.path.join(BASE, "bridge")
LEARN_PY = os.path.join(BRIDGE, "learn.py")
PREFS_PATH = os.path.join(BRIDGE, "preferences.json")

def call_learn(*args):
    if not os.path.exists(LEARN_PY):
        return {"error": f"learn.py not found at {LEARN_PY}"}
    try:
        r = subprocess.run([sys.executable, LEARN_PY] + list(args), capture_output=True, text=True, timeout=15)
        if r.stdout.strip():
            return json.loads(r.stdout.strip())
        if r.stderr:
            return {"error": r.stderr[:300]}
        return {"raw": r.stdout[:500]}
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}
    except Exception as e:
        return {"error": str(e)[:200]}

def load_prefs():
    if os.path.exists(PREFS_PATH):
        try:
            with open(PREFS_PATH, encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"corrections": [], "rules": []}

def main():
    if len(sys.argv) < 2:
        mode = "status"
    else:
        mode = sys.argv[1]
    if mode == "status":
        data = load_prefs()
        result = {
            "total_corrections": len(data.get("corrections", [])),
            "active_rules": len(data.get("rules", [])),
            "rules": [r["rule_id"] for r in data.get("rules", [])],
            "recent_corrections": [c["user_correction"][:80] for c in data.get("corrections", [])[-3:]]
        }
        print(json.dumps(result, indent=2))
    elif mode == "generalize":
        result = call_learn("generalize")
        print(json.dumps(result, indent=2))
    elif mode == "check":
        task = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
        result = call_learn("check", task)
        print(json.dumps(result, indent=2))
    elif mode == "observe":
        inp = sys.argv[2] if len(sys.argv) > 2 else ""
        out = sys.argv[3] if len(sys.argv) > 3 else ""
        corr = sys.argv[4] if len(sys.argv) > 4 else ""
        result = call_learn("observe", inp, out, corr)
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps({"error": f"Unknown mode: {mode}"}))

if __name__ == "__main__":
    main()
