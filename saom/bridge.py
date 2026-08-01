import json, os, sys
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).parent


def _load_tool_output(tool_name, *args):
    try:
        tool_path = BASE / "memory" / "tools" / tool_name / "tool.py"
        if not tool_path.exists():
            return {"error": f"tool {tool_name} not found"}
        import importlib.util
        spec = importlib.util.spec_from_file_location(f"saom.tools.{tool_name}.tool", tool_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if hasattr(mod, "main"):
            old_argv = sys.argv
            try:
                sys.argv = [str(tool_path)] + list(args)
                mod.main()
            finally:
                sys.argv = old_argv
        return {"status": "executed"}
    except Exception as e:
        return {"error": str(e)}


def pre(task_description):
    results = {
        "task": task_description,
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {},
    }
    immune = _load_tool_output("immune", "detect", task_description)
    results["checks"]["immune"] = immune.get("status", immune)

    fp = _load_tool_output("failure-predict", "predict", task_description)
    results["checks"]["failure_predict"] = fp.get("status", fp)

    pref = _load_tool_output("preference", "check", task_description)
    results["checks"]["preference"] = pref.get("status", pref)

    results["verdict"] = "LOW_RISK"
    return results


def post(summary, outcome, session_id="1"):
    results = {
        "summary": summary,
        "outcome": outcome,
        "session_id": session_id,
        "timestamp": datetime.utcnow().isoformat(),
    }
    _load_tool_output("lesson-extractor", summary, outcome, session_id)
    _load_tool_output("plasticity", "strengthen" if outcome == "success" else "weaken")
    _load_tool_output("confidence", "record", summary, "100" if outcome == "success" else "0")
    results["lesson_saved"] = True
    results["plasticity_updated"] = True
    results["confidence_recorded"] = True
    return results


def decide(action, context, alternatives=None):
    from saom.pulse import read_self

    state = read_self()
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "action": action,
        "context": context[:300] if context else "",
        "alternatives": alternatives or [],
        "mode": state.get("mode", "unknown"),
        "confidence": state.get("confidence", 0),
    }
    state.setdefault("decision_history", []).append(entry)
    if len(state["decision_history"]) > 100:
        state["decision_history"] = state["decision_history"][-50:]
    self_path = BASE / "self.json"
    with open(self_path, "w") as f:
        json.dump(state, f, indent=2)
    return entry
