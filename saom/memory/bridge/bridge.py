import json
import os
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(BASE, "tools")
BRIDGE = os.path.dirname(os.path.abspath(__file__))
SELF_PATH = os.path.join(BRIDGE, "self.json")
INIT_PATH = os.path.join(BASE, "init.json")
LESSONS_PATH = os.path.join(BASE, "lessons", "lessons.jsonl")
RULES_DIR = os.path.join(BASE, "rules")
AUTO_RULES_PATH = os.path.join(RULES_DIR, "auto_rules.json")
LEARN_PATH = os.path.join(BRIDGE, "learn.py")
DEEP_LEARN_PATH = os.path.join(BRIDGE, "deep_learn.py")
PRM_SCORER_PATH = os.path.join(BRIDGE, "prm_scorer.py")
SKILL_GEN_PATH = os.path.join(BRIDGE, "skill_generator.py")

class CircuitBreaker:
    """3-state circuit breaker per tool.
    CLOSED -> OPEN (after 5 failures in rolling window of 10)
    OPEN -> HALF_OPEN (after backoff cooldown)
    HALF_OPEN -> CLOSED (on probe success) or -> OPEN (on probe failure)
    """
    STATE_FILE = os.path.join(BRIDGE, "circuit_breaker.json")
    WINDOW_SIZE = 10
    TRIP_THRESHOLD = 5
    BASE_BACKOFF = 30
    MAX_BACKOFF = 300

    def __init__(self):
        self.state = self._load_state()
        self._last_cleanup = 0

    def _load_state(self):
        if os.path.exists(self.STATE_FILE):
            try:
                with open(self.STATE_FILE, encoding="utf-8") as f:
                    return json.load(f)
            except:
                pass
        return {"tools": {}}

    def _save_state(self):
        try:
            os.makedirs(os.path.dirname(self.STATE_FILE), exist_ok=True)
            with open(self.STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
        except:
            pass

    def _ensure_tool(self, tool_name):
        if tool_name not in self.state["tools"]:
            self.state["tools"][tool_name] = {
                "state": "CLOSED",
                "window": [],
                "last_open_time": None,
                "backoff_seconds": self.BASE_BACKOFF,
                "total_calls": 0,
                "total_failures": 0
            }

    def should_allow(self, tool_name):
        self._ensure_tool(tool_name)
        t = self.state["tools"][tool_name]

        if t["state"] == "CLOSED":
            return True

        if t["state"] == "OPEN":
            since_open = time.time() - (t["last_open_time"] or 0)
            if since_open >= t.get("backoff_seconds", self.BASE_BACKOFF):
                t["state"] = "HALF_OPEN"
                t["probe_count"] = 0
                self._save_state()
                return True
            return False

        if t["state"] == "HALF_OPEN":
            t["probe_count"] = t.get("probe_count", 0) + 1
            if t["probe_count"] == 1 or t["probe_count"] % 3 == 1:
                return True
            return False

        return False

    def record_success(self, tool_name):
        self._ensure_tool(tool_name)
        t = self.state["tools"][tool_name]
        t["window"].append({"outcome": "success", "timestamp": time.time()})
        self._prune_window(t)
        t["total_calls"] = t.get("total_calls", 0) + 1

        if t["state"] in ("HALF_OPEN", "OPEN"):
            t["state"] = "CLOSED"
            t["backoff_seconds"] = self.BASE_BACKOFF
        self._save_state()

    def record_failure(self, tool_name):
        self._ensure_tool(tool_name)
        t = self.state["tools"][tool_name]
        t["window"].append({"outcome": "failure", "timestamp": time.time()})
        self._prune_window(t)
        t["total_calls"] = t.get("total_calls", 0) + 1
        t["total_failures"] = t.get("total_failures", 0) + 1

        recent_failures = sum(1 for w in t["window"] if w["outcome"] == "failure")

        if recent_failures >= self.TRIP_THRESHOLD and t["state"] == "CLOSED":
            t["state"] = "OPEN"
            t["last_open_time"] = time.time()
            t["backoff_seconds"] = min(
                t.get("backoff_seconds", self.BASE_BACKOFF) * 2, self.MAX_BACKOFF
            )
            t["backoff_seconds"] += random.uniform(0, min(t["backoff_seconds"] * 0.1, 10))
        elif recent_failures >= self.TRIP_THRESHOLD and t["state"] == "HALF_OPEN":
            t["state"] = "OPEN"
            t["last_open_time"] = time.time()
            t["backoff_seconds"] = min(
                t.get("backoff_seconds", self.BASE_BACKOFF) * 2, self.MAX_BACKOFF
            )
            t["backoff_seconds"] += random.uniform(0, min(t["backoff_seconds"] * 0.1, 10))
        self._save_state()

    def _prune_window(self, t):
        if len(t["window"]) > self.WINDOW_SIZE:
            t["window"] = t["window"][-self.WINDOW_SIZE:]

    def get_status(self, tool_name=None):
        if tool_name:
            self._ensure_tool(tool_name)
            t = self.state["tools"][tool_name]
            return {
                "tool": tool_name,
                "state": t["state"],
                "total_calls": t.get("total_calls", 0),
                "total_failures": t.get("total_failures", 0),
                "backoff": round(t.get("backoff_seconds", self.BASE_BACKOFF), 1),
                "window_size": len(t["window"])
            }
        return {k: v["state"] for k, v in self.state["tools"].items()}

    def reset(self, tool_name=None):
        if tool_name:
            self.state["tools"].pop(tool_name, None)
        else:
            self.state["tools"] = {}
        self._save_state()

    def degraded_response(self, tool_name, *args):
        return {
            "error": f"circuit_breaker: {tool_name} is OPEN ({self.state['tools'].get(tool_name, {}).get('state', '?')})",
            "degraded": True,
            "fallback": True,
            "tool": tool_name
        }

def load_json(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return default if default is not None else {}

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

_cb = CircuitBreaker()

def call_tool(tool_name, *args):
    """Call a tool with circuit breaker protection."""
    if not _cb.should_allow(tool_name):
        return _cb.degraded_response(tool_name, *args)

    tool_py = os.path.join(TOOLS, tool_name, "tool.py")
    if not os.path.exists(tool_py):
        _cb.record_failure(tool_name)
        return {"error": f"Tool not found: {tool_py}"}
    try:
        r = subprocess.run(
            [sys.executable, tool_py] + list(args),
            capture_output=True, text=True, timeout=15
        )
        out = r.stdout.strip()
        if out:
            try:
                result = json.loads(out)
                _cb.record_success(tool_name)
                return result
            except:
                pass
            separator = '=' * 60
            if separator in out:
                out = out.split(separator)[0].strip()
            try:
                result = json.loads(out)
                _cb.record_success(tool_name)
                return result
            except:
                pass
            _cb.record_failure(tool_name)
            return {"raw": out[:500]}
        if r.stderr:
            _cb.record_failure(tool_name)
            return {"error": r.stderr[:500]}
        _cb.record_failure(tool_name)
        return {"error": "no output"}
    except subprocess.TimeoutExpired:
        _cb.record_failure(tool_name)
        return {"error": "timeout"}
    except Exception as e:
        _cb.record_failure(tool_name)
        return {"error": str(e)[:200]}

def parallel_call_tools(calls, max_workers=4):
    """Run multiple independent tool calls concurrently.
    calls: list of (tool_name, *args) tuples
    Returns: dict mapping tool_name -> result
    """
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {}
        for i, (tool_name, *args) in enumerate(calls):
            future = pool.submit(call_tool, tool_name, *args)
            futures[future] = tool_name
        for future in as_completed(futures):
            tool_name = futures[future]
            try:
                results[tool_name] = future.result()
            except Exception as e:
                results[tool_name] = {"error": str(e)[:200], "parallel_failure": True}
    return results

def run_learn(*args):
    """Call learn.py with args, return parsed result."""
    if not os.path.exists(LEARN_PATH):
        return {}
    try:
        r = subprocess.run([sys.executable, LEARN_PATH] + list(args), capture_output=True, text=True, timeout=10)
        if r.stdout.strip():
            return json.loads(r.stdout.strip())
        return {}
    except:
        return {}

def load_registry():
    rp = os.path.join(TOOLS, "registry.json")
    return load_json(rp, {"tools": [], "total_tools": 0})

def dispatch(task_desc, phase=None, skip_tools=None):
    """Find tools whose trigger keywords match the task description.
    Returns list of {name, score, description, triggers} sorted by score descending.
    """
    reg = load_registry()
    matches = []
    task_lower = task_desc.lower()
    skip_tools = set(skip_tools or [])

    for tool in reg.get("tools", []):
        name = tool["name"]
        if name in skip_tools:
            continue
        triggers = tool.get("triggers", {})
        if phase and phase not in triggers.get("phases", []):
            continue
        keywords = triggers.get("keywords", [])
        score = sum(1 for kw in keywords if kw.lower() in task_lower)
        if score > 0:
            matches.append({
                "name": name,
                "score": score,
                "description": tool.get("description", ""),
                "triggers": triggers
            })

    matches.sort(key=lambda x: -x["score"])
    return matches

def dispatch_run(task_desc, phase=None, skip_tools=None, max_workers=4):
    """Find matching tools and run them in parallel.
    Uses dispatch_args from each tool's triggers to construct proper CLI args.
    """
    matches = dispatch(task_desc, phase, skip_tools)
    if not matches:
        return {}
    calls = []
    reg = load_registry()
    tool_map = {t["name"]: t for t in reg.get("tools", [])}
    for m in matches:
        if "auto" not in m["triggers"].get("modes", []):
            continue
        name = m["name"]
        triggers = tool_map.get(name, {}).get("triggers", {})
        da = triggers.get("dispatch_args", {})
        mode = da.get("mode")
        arg_map = da.get("map", {})
        args = [name]
        if mode:
            args.append(mode)
        # If map has "task" -> something, pass task_desc as that positional arg
        if "task" in arg_map:
            args.append(task_desc)
        elif not mode:
            args.append(task_desc)
        calls.append(tuple(args))
    if not calls:
        return {}
    return parallel_call_tools(calls, max_workers=max_workers)

def pre(task_desc, approach=None):
    self_data = load_json(SELF_PATH, {})
    warnings = []
    verdict = None
    confidence = None

    # Check learned preferences first
    prefs = run_learn("check", task_desc)
    pref_warnings = prefs.get("warnings", [])
    for pw in pref_warnings:
        warnings.append({
            "source": "preference",
            "rule": pw["rule"],
            "message": pw["message"],
            "check": pw.get("check", "")
        })

    fp_args = ["predict", task_desc]
    if approach:
        fp_args.append(approach)

    failure_query = call_tool("failure-query", task_desc)
    past_failures = failure_query.get("matches", []) if "error" not in failure_query else []

    # Run 4 independent tool calls in parallel
    par = parallel_call_tools([
        ("immune", "detect", task_desc),
        ("failure-predict", *fp_args),
        ("confidence", "score", task_desc),
        ("curriculum", "status")
    ])

    immune = par.get("immune", {})
    fp = par.get("failure-predict", {})
    conf = par.get("confidence", {})

    auto = immune.get("auto_deploy", [])
    suggest = immune.get("suggest", [])
    if auto:
        for m in auto:
            warnings.append({
                "source": "immune_auto",
                "id": m["id"],
                "message": m.get("countermeasure", {}).get("message", "")[:200],
                "strength": m["effective_strength"]
            })
    if suggest:
        for m in suggest:
            warnings.append({
                "source": "immune_suggest",
                "id": m["id"],
                "message": m.get("countermeasure", {}).get("message", "")[:200],
                "strength": m["effective_strength"]
            })

    verdict = fp.get("verdict", "UNKNOWN")
    fp_confidence = fp.get("confidence", 50)
    fp_factors = fp.get("factors", [])

    confidence = conf.get("score", 50)

    # Smooth confidence with EMA to reduce volatility
    prev_traj = self_data.get("confidence_trajectory", [])
    if confidence is not None and prev_traj and prev_traj[-1] is not None:
        alpha = 0.35
        confidence = round(alpha * confidence + (1 - alpha) * prev_traj[-1])

    # Curriculum-aware adjustments
    curriculum = par.get("curriculum", {})
    if curriculum and not curriculum.get("error"):
        if curriculum.get("locked", 0) > 0:
            warnings.append({
                "source": "curriculum",
                "message": f"{curriculum['locked']} skill(s) locked by prerequisites",
                "check": "review skill tree"
            })
        if curriculum.get("unused", 0) > 0:
            warnings.append({
                "source": "curriculum",
                "message": f"{curriculum['unused']} skill(s) never used — consider loading relevant skills",
                "check": "skill <name>"
            })
        overall = curriculum.get("overall_mastery", 100)
        if overall < 40:
            warnings.append({
                "source": "curriculum",
                "message": f"Overall mastery {overall}% — high risk on unfamiliar domains",
                "check": "curriculum status"
            })
            confidence = min(confidence, int(max(confidence * overall / 100, 20))) if confidence else int(overall)
        elif overall < 70:
            confidence = int(confidence * (0.8 + 0.2 * overall / 100))
    else:
        curriculum = None

    # Auto-dispatch pre-phase tools not already called
    auto_pre = dispatch_run(task_desc, "pre", skip_tools={"failure-query","immune","failure-predict","confidence","curriculum"})
    for tool_name, result in auto_pre.items():
        if "error" not in result:
            msg = f"{tool_name} auto-dispatched during pre: {str(result)[:120]}"
            warnings.append({"source": "dispatch", "tool": tool_name, "message": msg})

    session_id = self_data.get("session_id")
    mode_history = self_data.get("mode_history", [])
    mode_history.append("execution")
    if len(mode_history) > 20:
        mode_history = mode_history[-20:]
    goal_history = self_data.get("goal_history", [])
    old_goal = self_data.get("goal")
    if task_desc[:200] != old_goal:
        goal_history.append(task_desc[:200])
        if len(goal_history) > 10:
            goal_history = goal_history[-10:]
    conf_traj = self_data.get("confidence_trajectory", [])
    if confidence is not None:
        conf_traj.append(confidence)
        if len(conf_traj) > 20:
            conf_traj = conf_traj[-20:]
    self_data.update({
        "mode": "execution",
        "goal": task_desc[:200],
        "confidence": confidence,
        "confidence_trajectory": conf_traj,
        "active_warnings": warnings,
        "mode_history": mode_history,
        "goal_history": goal_history,
        "last_decision": None,
        "last_outcome": None,
        "reflection_pending": False
    })
    save_json(SELF_PATH, self_data)

    summary = {
        "session_id": session_id,
        "verdict": verdict,
        "confidence": confidence,
        "risk_level": fp_confidence,
        "warnings_count": len(warnings),
        "warnings": warnings[:3],
        "immune_matched": immune.get("total_matched", 0),
        "past_failure_count": len(past_failures),
        "failure_factors": fp_factors[:3],
        "recommendation": fp.get("recommendation", "")[:300],
        "curriculum": {
            "overall_mastery": curriculum.get("overall_mastery"),
            "unlocked": curriculum.get("unlocked"),
            "locked": curriculum.get("locked"),
            "unused": curriculum.get("unused"),
            "mastered": curriculum.get("mastered")
        } if curriculum else None
    }

    line = f"[BRIDGE] Verdict: {verdict} | Confidence: {confidence}% | Warnings: {len(warnings)}"
    print(line)
    print("---")
    print(json.dumps(summary, indent=2))
    return summary

def introspect():
    self_data = load_json(SELF_PATH, {})
    findings = []
    mode_history = self_data.get("mode_history", [])
    goal_history = self_data.get("goal_history", [])
    conf_traj = self_data.get("confidence_trajectory", [])
    decision_history = self_data.get("decision_history", [])
    mistakes = self_data.get("mistakes_this_session", 0)

    if len(mode_history) >= 4:
        recent = mode_history[-4:]
        if recent == ["execution", "reflection", "execution", "reflection"]:
            findings.append({"type": "oscillation", "message": "Mode oscillation detected: rapid execution↔reflection cycles", "severity": "info"})

    if len(goal_history) >= 3:
        findings.append({"type": "goal_churn", "message": f"Switched goals {len(goal_history)} times this session: {' → '.join(g[:30] for g in goal_history[-3:])}", "severity": "info"})

    if len(conf_traj) >= 3:
        recent_conf = conf_traj[-3:]
        if all(recent_conf[i] > recent_conf[i+1] for i in range(len(recent_conf)-1)):
            findings.append({"type": "confidence_drop", "message": f"Confidence declining: {recent_conf}", "severity": "warning"})

    if mistakes > 0 and decision_history:
        last_failure = None
        for d in reversed(decision_history):
            if d.get("outcome") == "failure":
                last_failure = d
                break
        if last_failure:
            findings.append({"type": "last_failure", "message": f"Last mistake: '{last_failure.get('action','')[:80]}'", "severity": "info"})

    if len(decision_history) >= 3:
        recent_decisions = decision_history[-3:]
        outcomes = [d.get("outcome") for d in recent_decisions]
        if outcomes.count("failure") >= 2:
            findings.append({"type": "failure_streak", "message": f"{outcomes.count('failure')}/3 last decisions failed", "severity": "warning"})

    # Check if a decision was made without alternatives
    for d in decision_history[-3:]:
        if not d.get("alternatives"):
            findings.append({"type": "no_alternatives", "message": f"Decision '{d.get('action','')[:50]}' had no alternatives recorded", "severity": "info"})

    if not findings:
        findings.append({"type": "stable", "message": "No concerning patterns detected", "severity": "ok"})

    return {"session_id": self_data.get("session_id"), "findings": findings, "mistakes": mistakes, "decisions": len(decision_history), "goals": len(goal_history), "mode_switches": len(mode_history)}

def check_repeated_failure(summary_text):
    """If this failure matches 2+ past lessons, run self-modify propose."""
    lessons_path = os.path.join(BASE, "lessons", "lessons.jsonl")
    if not os.path.exists(lessons_path):
        return None
    try:
        import re
        with open(lessons_path, encoding="utf-8") as f:
            past_lessons = [json.loads(l) for l in f if l.strip()]
        failures = [l for l in past_lessons if l.get("outcome") == "failure"]
        summary_lower = summary_text.lower()
        sw = {"the","a","an","is","are","was","were","be","been","have","has","had",
              "do","does","did","will","would","can","could","shall","should","may",
              "might","to","of","in","for","on","with","at","by","from","as","into",
              "through","during","before","after","above","below","between","out",
              "off","over","under","again","then","once","here","there","when",
              "where","why","how","all","each","every","both","few","more","most",
              "other","some","such","no","nor","not","only","own","same","so","than",
              "too","very","just","because","but","and","or","if","while","that",
              "this","it","its","what","which","who","whom","whose","get","make",
              "use","need","find","want"}
        query_tokens = set(re.findall(r'[a-zA-Z][a-zA-Z0-9_-]*', summary_lower)) - sw
        query_tokens = {t for t in query_tokens if len(t) > 2}
        similar = []
        for l in failures:
            text = (l.get("summary","") + " " + l.get("root_cause","")).lower()
            target_tokens = set(re.findall(r'[a-zA-Z][a-zA-Z0-9_-]*', text)) - sw
            target_tokens = {t for t in target_tokens if len(t) > 2}
            if not query_tokens or not target_tokens:
                continue
            overlap = query_tokens & target_tokens
            score = len(overlap) / max(len(query_tokens | target_tokens), 1)
            if score > 0.2:
                similar.append({"summary": l.get("summary","")[:100], "score": round(score, 3)})
        similar.sort(key=lambda x: -x["score"])
        if len(similar) >= 2:
            sm = call_tool("self-modify", "propose")
            if sm and sm.get("proposals"):
                return {
                    "repeated_failure_detected": True,
                    "similar_count": len(similar),
                    "similar_examples": similar[:3],
                    "proposal": sm["proposals"][0]
                }
    except Exception as e:
        return {"error": str(e)[:200]}
    return None

def decide(action, context, alternatives=None):
    """Record a conscious decision point in self.json."""
    self_data = load_json(SELF_PATH, {})
    decision_history = self_data.get("decision_history", [])
    entry = {
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "action": action[:200],
        "context": context[:300],
        "alternatives": (alternatives or [])[:5],
        "confidence_at_time": self_data.get("confidence"),
        "outcome": None
    }
    decision_history.append(entry)
    if len(decision_history) > 50:
        decision_history = decision_history[-50:]
    self_data["decision_history"] = decision_history
    self_data["last_decision"] = entry
    save_json(SELF_PATH, self_data)
    result = {"decision_recorded": True, "total_decisions": len(decision_history)}
    print(json.dumps(result))
    return result

def post(summary_text, outcome, session_id=None, skill_name=None):
    self_data = load_json(SELF_PATH, {})
    session_id = session_id or self_data.get("session_id")
    sid = str(session_id) if session_id else str(datetime.utcnow().strftime("%Y%m%d%H%M%S"))

    # Reset lesson-extractor CB if open (it was due to test non-JSON output bug, now fixed)
    _cb.reset("lesson-extractor")

    results = {}
    predicted = self_data.get("confidence", 50)
    actual = 100 if outcome == "success" else 0

    if skill_name:
        skill_calls = [("skill-tracker", "use", skill_name, outcome, "80")]
    else:
        # Auto-detect skill from summary_text by matching against known skill names
        detected_skill = None
        reg_path = os.path.join(BASE, "skills", "registry.json")
        if os.path.exists(reg_path):
            try:
                with open(reg_path, encoding="utf-8") as _f:
                    _reg = json.load(_f)
                _all = []
                for _sec in ("skills", "evolved_skills", "project_skills"):
                    _all.extend(s.get("name","") for s in _reg.get(_sec, []))
                _lower = summary_text.lower()
                for _sn in sorted(_all, key=lambda x: -len(x)):
                    if _sn and _sn.lower() in _lower:
                        detected_skill = _sn
                        break
            except:
                pass
        skill_calls = []
        if detected_skill:
            skill_calls = [("skill-tracker", "use", detected_skill, outcome, "80")]

    # Post-task: run consolidate + evolution diagnose + preference generalize
    consolidate_result = call_tool("consolidate", "scan")
    if "error" not in consolidate_result:
        if consolidate_result.get("proposals"):
            results["consolidate_proposals"] = len(consolidate_result["proposals"])

    evolve_engine = os.path.join(BASE, "..", "evolved", "evolution-loop", "engine.py")
    if os.path.exists(evolve_engine):
        try:
            ev_r = subprocess.run([sys.executable, evolve_engine, "diagnose"], capture_output=True, text=True, timeout=15)
            ev_out = ev_r.stdout.strip()
            if ev_out and "No patterns to analyze" not in ev_out:
                results["evolution"] = ev_out[:200]
        except:
            pass

    preference_gen = call_tool("preference", "generalize")
    if "error" not in preference_gen:
        results["preferences"] = preference_gen

    # Auto-dispatch post-phase tools not already called
    auto_post = dispatch_run(summary_text, "post", skip_tools={"lesson-extractor","plasticity","confidence","immune","skill-tracker","consolidate","preference"})
    for tool_name, result in auto_post.items():
        if "error" not in result:
            results[f"dispatch_{tool_name}"] = str(result)[:120]

    if outcome == "success":
        immune_deploys = []
        if self_data.get("active_warnings"):
            for w in self_data["active_warnings"]:
                if w.get("source") == "immune_auto":
                    immune_deploys.append(("immune", "deploy", w["id"], "success"))
        par = parallel_call_tools(
            [("lesson-extractor", summary_text, outcome, sid),
             ("plasticity", "strengthen-type", "task", "lesson", "produces"),
             ("confidence", "record", str(predicted), str(actual))] +
            skill_calls + immune_deploys
        )
        results["lesson"] = par.get("lesson-extractor", {}).get("lesson_id", par.get("lesson-extractor", {}).get("raw", "done"))
        results["plasticity"] = "strengthened"
        results["confidence_recorded"] = f"{predicted} -> {actual}"
        if skill_name and par.get("skill-tracker"):
            results["skill_track"] = par["skill-tracker"].get("raw", "done")
    else:
        par = parallel_call_tools(
            [("lesson-extractor", summary_text, outcome, sid),
             ("plasticity", "weaken-type", "task", "lesson", "produces"),
             ("immune", "learn", "failure", summary_text, json.dumps({"action": "review approach", "type": "guardrail"})),
             ("confidence", "record", str(predicted), str(actual))] +
            skill_calls
        )
        results["lesson"] = par.get("lesson-extractor", {}).get("lesson_id", par.get("lesson-extractor", {}).get("raw", "done"))
        results["immune"] = "learned from failure"
        results["plasticity"] = "weakened"
        results["confidence_recorded"] = f"{predicted} -> {actual}"
        if skill_name and par.get("skill-tracker"):
            results["skill_track"] = par["skill-tracker"].get("raw", "done")
        mistakes = self_data.get("mistakes_this_session", 0)
        self_data["mistakes_this_session"] = mistakes + 1
        repeated = check_repeated_failure(summary_text)
        if repeated and repeated.get("repeated_failure_detected"):
            results["repeated_failure"] = {
                "count": repeated["similar_count"],
                "examples": repeated["similar_examples"],
                "proposal": repeated["proposal"]["suggestion"][:200],
                "proposal_id": repeated["proposal"]["proposal_id"]
            }
            os.makedirs(RULES_DIR, exist_ok=True)
            auto_rules = load_json(AUTO_RULES_PATH, {"rules": []})
            auto_rules["rules"].append({
                "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "pattern": repeated["proposal"]["pattern"],
                "suggestion": repeated["proposal"]["suggestion"],
                "occurrences": repeated["similar_count"],
                "applied": False
            })
            save_json(AUTO_RULES_PATH, auto_rules)

    conf_traj = self_data.get("confidence_trajectory", [])
    conf_traj.append(actual)
    if len(conf_traj) > 20:
        conf_traj = conf_traj[-20:]

    mode_history = self_data.get("mode_history", [])
    mode_history.append("reflection")
    if len(mode_history) > 20:
        mode_history = mode_history[-20:]

    decision_history = self_data.get("decision_history", [])
    if decision_history:
        decision_history[-1]["outcome"] = outcome

    lsn = self_data.get("lessons_this_session", 0)
    self_data.update({
        "mode": "reflection",
        "confidence_trajectory": conf_traj,
        "mode_history": mode_history,
        "decision_history": decision_history,
        "last_outcome": outcome,
        "reflection_pending": False,
        "active_warnings": [],
        "lessons_this_session": lsn + 1
    })
    save_json(SELF_PATH, self_data)

    line = f"[BRIDGE] Post-task: outcome={outcome} | lesson saved | plasticity updated | confidence recorded"
    results["_summary"] = line
    print(line)
    print(json.dumps({k: v for k, v in results.items() if not k.startswith("_")}, indent=2))
    return results

def run_deep_learn(*args):
    if not os.path.exists(DEEP_LEARN_PATH):
        return {}
    try:
        r = subprocess.run([sys.executable, DEEP_LEARN_PATH] + list(args), capture_output=True, text=True, timeout=30)
        out = r.stdout.strip()
        if out:
            return out
        return {}
    except:
        return {}

def run_prm_scorer(*args):
    if not os.path.exists(PRM_SCORER_PATH):
        return {}
    try:
        r = subprocess.run([sys.executable, PRM_SCORER_PATH] + list(args), capture_output=True, text=True, timeout=30)
        out = r.stdout.strip()
        if out:
            return out
        return {}
    except:
        return {}

def run_skill_gen(*args):
    if not os.path.exists(SKILL_GEN_PATH):
        return {}
    try:
        r = subprocess.run([sys.executable, SKILL_GEN_PATH] + list(args), capture_output=True, text=True, timeout=30)
        out = r.stdout.strip()
        if out:
            return out
        return {}
    except:
        return {}

def main():
    if len(sys.argv) < 2:
        print("Usage: python bridge.py <pre|post|decide|dispatch|introspect|circuit|learn|deep-learn|prm|skillgen> [args]")
        print("  pre       \"<task_desc>\" [\"<approach>\"]")
        print("  post      \"<summary>\" <success|failure> [session_id] [skill_name]")
        print("  dispatch  \"<task_desc>\" [phase] [--run]")
        print("  circuit   [tool_name|--all|--reset|--reset-<tool>]")
        print("  deep-learn <analyze|synthesize|status>")
        print("  prm       <score|\"<query>\" \"<response>\">")
        print("  prm       revise \"<query>\" \"<response>\" [threshold]")
        print("  prm       status")
        print("  skillgen  <generate \"<summary>\" \"<cause>\" \"<fix>\">")
        print("  skillgen  auto")
        print("  skillgen  status")
        sys.exit(1)

    mode = sys.argv[1]
    if mode == "pre":
        task = sys.argv[2] if len(sys.argv) > 2 else ""
        approach = sys.argv[3] if len(sys.argv) > 3 else None
        pre(task, approach)
    elif mode == "post":
        summary = sys.argv[2] if len(sys.argv) > 2 else ""
        outcome = sys.argv[3] if len(sys.argv) > 3 else "success"
        session_id = sys.argv[4] if len(sys.argv) > 4 else None
        skill = sys.argv[5] if len(sys.argv) > 5 else None
        post(summary, outcome, session_id, skill)
    elif mode == "decide":
        action = sys.argv[2] if len(sys.argv) > 2 else ""
        context = sys.argv[3] if len(sys.argv) > 3 else ""
        alts = sys.argv[4].split("|") if len(sys.argv) > 4 else []
        decide(action, context, alts)
    elif mode == "introspect":
        result = introspect()
        print(json.dumps(result, indent=2))
    elif mode == "circuit":
        tool_name = sys.argv[2] if len(sys.argv) > 2 else None
        if tool_name == "--reset":
            _cb.reset()
            result = {"reset": True}
        elif tool_name and tool_name.startswith("--reset-"):
            target = tool_name.replace("--reset-", "")
            _cb.reset(target)
            result = {"reset": target}
        elif tool_name == "--all":
            result = _cb.get_status()
        else:
            result = _cb.get_status(tool_name)
        print(json.dumps(result, indent=2))
    elif mode == "learn":
        if len(sys.argv) > 2:
            result = run_learn(*sys.argv[2:])
        else:
            result = {"error": "learn needs args: observe|generalize|check|status"}
        print(json.dumps(result, indent=2))
    elif mode == "deep-learn":
        sub_mode = sys.argv[2] if len(sys.argv) > 2 else "synthesize"
        out = run_deep_learn(sub_mode)
        if isinstance(out, str):
            print(out)
        else:
            print(json.dumps(out, indent=2) if out else "{}")
    elif mode == "prm":
        sub = sys.argv[2] if len(sys.argv) > 2 else "status"
        if sub == "score":
            query = sys.argv[3] if len(sys.argv) > 3 else ""
            resp = sys.argv[4] if len(sys.argv) > 4 else ""
            out = run_prm_scorer("score", query, resp)
        elif sub == "revise":
            query = sys.argv[3] if len(sys.argv) > 3 else ""
            resp = sys.argv[4] if len(sys.argv) > 4 else ""
            threshold = sys.argv[5] if len(sys.argv) > 5 else "0.7"
            out = run_prm_scorer("revise", query, resp, threshold)
        elif sub == "status":
            out = run_prm_scorer("status")
        else:
            out = run_prm_scorer(*sys.argv[2:])
        if isinstance(out, str):
            print(out)
        else:
            print(json.dumps(out, indent=2) if out else "{}")
    elif mode == "skillgen":
        sub = sys.argv[2] if len(sys.argv) > 2 else "status"
        if sub == "generate":
            summary = sys.argv[3] if len(sys.argv) > 3 else ""
            cause = sys.argv[4] if len(sys.argv) > 4 else ""
            fix = sys.argv[5] if len(sys.argv) > 5 else ""
            out = run_skill_gen("generate", summary, cause, fix)
        elif sub == "auto":
            out = run_skill_gen("auto")
        elif sub == "status":
            out = run_skill_gen("status")
        else:
            out = run_skill_gen(*sys.argv[2:])
        if isinstance(out, str):
            print(out)
        else:
            print(json.dumps(out, indent=2) if out else "{}")
    elif mode == "dispatch":
        task = sys.argv[2] if len(sys.argv) > 2 else ""
        phase = None
        do_run = False
        remaining = sys.argv[3:]
        for i, arg in enumerate(remaining):
            if arg == "--run":
                do_run = True
            elif phase is None:
                phase = arg
        if do_run:
            skip = set()
            if phase == "pre":
                skip = {"failure-query","immune","failure-predict","confidence","curriculum"}
            elif phase == "post":
                skip = {"lesson-extractor","plasticity","confidence","immune","skill-tracker","consolidate","preference"}
            matches = dispatch(task, phase)
            results = dispatch_run(task, phase, skip_tools=skip)
            print(json.dumps({"matches": matches, "total": len(matches), "results": {k: str(v)[:200] for k, v in results.items()}}, indent=2))
        else:
            matches = dispatch(task, phase)
            print(json.dumps({"matches": matches, "total": len(matches)}, indent=2))
    else:
        print(f"Unknown mode: {mode}")

if __name__ == "__main__":
    main()
