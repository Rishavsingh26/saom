"""Deep learning: trigger-based MetaClaw-style pattern combiner.
Manually invoked (not auto-scheduled). Reads all bridge data sources
and produces cross-cutting pattern analysis + recommendations.

Usage:
  python deep_learn.py analyze    -> raw pattern data (JSON)
  python deep_learn.py synthesize -> analysis + LLM recommendations
  python deep_learn.py status     -> condensed summary
"""
import json, os, re, sys, urllib.request
from datetime import datetime, timezone

BRIDGE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(BRIDGE)
SELF_PATH = os.path.join(BRIDGE, "self.json")
PREFS_PATH = os.path.join(BRIDGE, "preferences.json")
LESSONS_PATH = os.path.join(BASE, "lessons", "lessons.jsonl")
CIRCUIT_PATH = os.path.join(BRIDGE, "circuit_breaker.json")
REGISTRY_PATH = os.path.join(BASE, "skills", "registry.json")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
MODEL = "openai/gpt-oss-20b"
UA = "Mozilla/5.0 (compatible; SAOM-bot/1.0)"

SEPARATOR = "=" * 48


def _llm(prompt):
    if not GROQ_KEY:
        return "ERROR: no GROQ_API_KEY"
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2048, "temperature": 0.3
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


def load_json(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return default if default is not None else {}


def load_lessons():
    if not os.path.exists(LESSONS_PATH):
        return []
    lessons = []
    with open(LESSONS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    lessons.append(json.loads(line))
                except:
                    pass
    return lessons


def analyze_confidence_trajectory(traj):
    if not traj or len(traj) < 3:
        return {"pattern": "insufficient_data", "trend": "unknown", "volatility": None}
    recent = traj[-5:] if len(traj) >= 5 else traj
    mid = len(recent) // 2
    first_half = sum(recent[:mid]) / max(mid, 1)
    second_half = sum(recent[mid:]) / max(len(recent) - mid, 1)
    diff = second_half - first_half
    trend = "improving" if diff > 15 else ("declining" if diff < -15 else "stable")
    mean = sum(traj) / len(traj)
    variance = sum((x - mean) ** 2 for x in traj) / len(traj)
    volatility = round(variance ** 0.5, 1)
    oscillations = sum(1 for i in range(1, len(recent)) if abs(recent[i] - recent[i-1]) >= 40)
    return {
        "pattern": "oscillating" if oscillations >= 2 else trend,
        "trend": trend,
        "volatility": volatility,
        "oscillation_count": oscillations,
        "current": traj[-1] if traj else None,
        "min": min(traj),
        "max": max(traj),
        "recent_mean": round(sum(recent) / len(recent), 1),
        "values": traj[-10:]
    }


def analyze_mode_patterns(history):
    if not history:
        return {"total_switches": 0, "pattern": "no_data"}
    exe = history.count("execution")
    ref = history.count("reflection")
    return {
        "total_switches": len(history),
        "execution_ratio": round(exe / max(len(history), 1), 2),
        "reflection_ratio": round(ref / max(len(history), 1), 2),
        "last_three": history[-3:] if len(history) >= 3 else history
    }


def analyze_decision_patterns(decisions):
    if not decisions:
        return {"total": 0}
    outcomes = [d.get("outcome") for d in decisions if d.get("outcome")]
    successes = outcomes.count("success")
    failures = outcomes.count("failure")
    with_alts = sum(1 for d in decisions if d.get("alternatives"))
    return {
        "total": len(decisions),
        "success_rate": round(successes / max(len(outcomes), 1) * 100, 1) if outcomes else None,
        "failures": failures,
        "successes": successes,
        "with_alternatives": with_alts,
        "alternative_rate": round(with_alts / max(len(decisions), 1) * 100, 1)
    }


def analyze_failure_patterns(lessons):
    if not lessons:
        return {"total_lessons": 0, "failures": 0}
    from collections import Counter
    failures = [l for l in lessons if l.get("outcome") == "failure"]
    sev = Counter(l.get("severity", "info") for l in lessons)
    causes = [l.get("root_cause", "")[:60] for l in failures if l.get("root_cause")]
    return {
        "total_lessons": len(lessons),
        "total_failures": len(failures),
        "severity_distribution": dict(sev),
        "sample_root_causes": causes[:5],
        "failure_rate": round(len(failures) / max(len(lessons), 1) * 100, 1)
    }


def analyze_correction_patterns(prefs):
    corrs = prefs.get("corrections", [])
    if not corrs:
        return {"total": 0}
    texts = [c.get("user_correction", "")[:80] for c in corrs[-10:]]
    return {
        "total_corrections": len(corrs),
        "recent_corrections": texts,
        "active_rules": len(prefs.get("rules", [])),
        "rule_ids": [r["rule_id"] for r in prefs.get("rules", [])]
    }


def analyze_skill_coverage():
    reg = load_json(REGISTRY_PATH, {})
    skills = reg.get("skills", [])
    if not skills:
        return {"total": 0}
    cats = {}
    for entry in skills:
        cat = entry.get("category", entry.get("origin", "unknown"))
        cats.setdefault(cat, []).append(entry.get("name", "?"))
    return {"total": len(skills), "categories": {k: len(v) for k, v in cats.items()}}


def analyze_tool_reliability():
    cb = load_json(CIRCUIT_PATH, {})
    tools = cb.get("tools", {})
    if not tools:
        return {"total": 0}
    open_t = [k for k, v in tools.items() if v.get("state") == "OPEN"]
    high_fail = [k for k, v in tools.items() if v.get("total_calls", 0) >= 3 and v.get("total_failures", 0) / max(v.get("total_calls", 0), 1) > 0.5]
    return {"total_tools": len(tools), "open": open_t, "high_failure_rate": high_fail}


def analyze():
    """Read all data sources, compute patterns. Returns dict, no print."""
    self_data = load_json(SELF_PATH, {})
    prefs = load_json(PREFS_PATH, {})
    lessons = load_lessons()
    return {
        "session": {
            "session_id": self_data.get("session_id"),
            "mode": self_data.get("mode"),
            "goal": (self_data.get("goal") or "")[:100],
            "mistakes": self_data.get("mistakes_this_session", 0),
            "lessons_this_session": self_data.get("lessons_this_session", 0),
        },
        "confidence": analyze_confidence_trajectory(self_data.get("confidence_trajectory", [])),
        "modes": analyze_mode_patterns(self_data.get("mode_history", [])),
        "decisions": analyze_decision_patterns(self_data.get("decision_history", [])),
        "failures": analyze_failure_patterns(lessons),
        "corrections": analyze_correction_patterns(prefs),
        "skills": analyze_skill_coverage(),
        "tool_reliability": analyze_tool_reliability(),
    }


def synthesize(analysis):
    """Use LLM to turn pattern analysis into actionable recommendations."""
    prompt = f"""You are a MetaClaw-style deep learning agent. Analyze these self-observations and generate concrete improvement recommendations.

SESSION:
- ID: {analysis['session']['session_id']}, Mode: {analysis['session']['mode']}
- Goal: {analysis['session']['goal']}
- Mistakes: {analysis['session']['mistakes']}

CONFIDENCE:
- Trend: {analysis['confidence']['trend']}, Pattern: {analysis['confidence']['pattern']}
- Volatility: {analysis['confidence']['volatility']}, Current: {analysis['confidence']['current']}
- Min/Max: {analysis['confidence']['min']}/{analysis['confidence']['max']}
- Recent values: {analysis['confidence']['values']}

MODES: Total switches: {analysis['modes']['total_switches']}, Exec ratio: {analysis['modes']['execution_ratio']}, Recent: {analysis['modes']['last_three']}

DECISIONS: Total: {analysis['decisions']['total']}, Success rate: {analysis['decisions']['success_rate']}%, Failures: {analysis['decisions']['failures']}, Alt rate: {analysis['decisions']['alternative_rate']}%

FAILURES: Lessons: {analysis['failures']['total_lessons']}, Failure rate: {analysis['failures']['failure_rate']}%, Root causes: {analysis['failures'].get('sample_root_causes', [])}, Severity: {analysis['failures'].get('severity_distribution', {})}

CORRECTIONS: Total: {analysis['corrections']['total_corrections']}, Rules: {analysis['corrections']['active_rules']}, Recent: {analysis['corrections']['recent_corrections'][:3]}

SKILLS: Total: {analysis['skills']['total']}, Categories: {analysis['skills'].get('categories', {})}

TOOLS: Open circuits: {analysis['tool_reliability'].get('open', [])}, High failure: {analysis['tool_reliability'].get('high_failure_rate', [])}

Generate 2-5 specific, actionable recommendations. Not generic advice.
Output ONLY a JSON list:
[{{"type": "rule|behavior|skill|process|tool", "priority": "high|medium|low", "action": "specific action", "rationale": "why (1 sentence)", "trigger": "when to apply"}}]
"""
    raw = _llm(prompt)
    if raw.startswith("ERROR"):
        return {"recommendations": [], "error": raw}
    try:
        m = re.search(r'\[.*\]', raw, re.DOTALL)
        if m:
            recs = json.loads(m.group(0))
        else:
            recs = []
    except:
        recs = []
    return {"recommendations": recs}


def print_report(analysis, recs=None):
    print("DEEP LEARNING REPORT")
    print(SEPARATOR)
    print(f"Session {analysis['session']['session_id']} | Mode: {analysis['session']['mode']}")
    print(f"Goal: {analysis['session']['goal']}")
    print()
    print("1. CONFIDENCE TRAJECTORY")
    print(f"   Trend: {analysis['confidence']['trend']} | Volatility: {analysis['confidence']['volatility']}")
    print(f"   Pattern: {analysis['confidence']['pattern']} | Current: {analysis['confidence']['current']}")
    print(f"   Range: [{analysis['confidence']['min']}..{analysis['confidence']['max']}]")
    print()
    print("2. MODE PATTERNS")
    print(f"   Switches: {analysis['modes']['total_switches']} (Exec: {analysis['modes']['execution_ratio']}, Refl: {analysis['modes']['reflection_ratio']})")
    print()
    print("3. DECISIONS")
    print(f"   Success rate: {analysis['decisions']['success_rate']}% ({analysis['decisions']['successes']}/{analysis['decisions']['total']})")
    print(f"   Alternatives recorded: {analysis['decisions']['alternative_rate']}%")
    print()
    print("4. FAILURE ANALYSIS")
    print(f"   Failure rate: {analysis['failures']['failure_rate']}% ({analysis['failures']['total_failures']}/{analysis['failures']['total_lessons']})")
    print(f"   Severity: {analysis['failures'].get('severity_distribution', {})}")
    if analysis['failures'].get('sample_root_causes'):
        for rc in analysis['failures']['sample_root_causes']:
            print(f"   Root cause: {rc}")
    print()
    print("5. CORRECTIONS & RULES")
    print(f"   {analysis['corrections']['total_corrections']} corrections -> {analysis['corrections']['active_rules']} rules")
    print(f"   Active rules: {analysis['corrections'].get('rule_ids', [])}")
    print()
    print("6. SKILLS")
    print(f"   {analysis['skills']['total']} skills across {len(analysis['skills'].get('categories', {}))} categories")
    print()
    print("7. TOOL RELIABILITY")
    if analysis['tool_reliability'].get('open'):
        print(f"   WARNING: Open circuits: {analysis['tool_reliability']['open']}")
    if analysis['tool_reliability'].get('high_failure_rate'):
        print(f"   WARNING: High failure: {analysis['tool_reliability']['high_failure_rate']}")
    if not analysis['tool_reliability'].get('open') and not analysis['tool_reliability'].get('high_failure_rate'):
        print("   All tools nominal")
    print()
    if recs and recs.get("recommendations"):
        print(SEPARATOR)
        print("RECOMMENDATIONS:")
        for i, r in enumerate(recs["recommendations"], 1):
            print(f"  {i}. [{r.get('priority','?').upper()}] ({r.get('type','?')}) {r.get('action','')}")
            print(f"     Rationale: {r.get('rationale','')}")
            print(f"     Trigger: {r.get('trigger','')}")
    else:
        print("No recommendations generated (LLM unavailable or insufficient data)")


def main():
    if len(sys.argv) < 2:
        print("Usage: python deep_learn.py <analyze|synthesize|status>")
        sys.exit(1)
    mode = sys.argv[1]
    analysis = analyze()
    if mode == "analyze":
        print(json.dumps(analysis, indent=2))
    elif mode == "synthesize":
        recs = synthesize(analysis)
        print_report(analysis, recs)
    elif mode == "status":
        summary = {
            "confidence": {"trend": analysis["confidence"]["trend"], "current": analysis["confidence"]["current"]},
            "decisions": {"success_rate": analysis["decisions"]["success_rate"], "total": analysis["decisions"]["total"]},
            "failures": {"rate": analysis["failures"]["failure_rate"], "total": analysis["failures"]["total_failures"]},
            "modes": {"exec_ratio": analysis["modes"]["execution_ratio"]},
            "open_tools": analysis["tool_reliability"].get("open", []),
            "rules": len(analysis["corrections"].get("rule_ids", [])),
            "skills": analysis["skills"]["total"]
        }
        print(json.dumps(summary, indent=2))
    else:
        print(f"Unknown mode: {mode}")


if __name__ == "__main__":
    main()
