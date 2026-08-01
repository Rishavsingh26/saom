import json, os, sys
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).parent


def _load_tool_output(tool_name, *args):
    """Run a tool's main() in-process and return what it actually reported.

    Bug fix: every tool's `main()` communicates its result by *printing* JSON
    to stdout (see e.g. memory/tools/immune/tool.py or failure-predict/tool.py).
    This function used to call `mod.main()` and then unconditionally return
    the placeholder `{"status": "executed"}`, discarding whatever the tool
    printed. That meant callers (like `pre()` below) never saw the immune
    system's match decision, the failure-predictor's verdict, or the
    preference tool's check result -- they only ever saw "executed". We now
    capture stdout, parse it as JSON, and hand back the real result.
    """
    try:
        tool_path = BASE / "memory" / "tools" / tool_name / "tool.py"
        if not tool_path.exists():
            return {"error": f"tool {tool_name} not found"}
        import importlib.util, io, contextlib
        spec = importlib.util.spec_from_file_location(f"saom.tools.{tool_name}.tool", tool_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if hasattr(mod, "main"):
            old_argv = sys.argv
            captured = io.StringIO()
            try:
                sys.argv = [str(tool_path)] + list(args)
                with contextlib.redirect_stdout(captured):
                    mod.main()
            finally:
                sys.argv = old_argv
            printed = captured.getvalue().strip()
            if printed:
                try:
                    return json.loads(printed)
                except json.JSONDecodeError:
                    return {"raw_output": printed}
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
    results["checks"]["immune"] = immune

    fp = _load_tool_output("failure-predict", "predict", task_description)
    results["checks"]["failure_predict"] = fp

    pref = _load_tool_output("preference", "check", task_description)
    results["checks"]["preference"] = pref

    # Bug fix: verdict used to be hardcoded to "LOW_RISK" no matter what the
    # checks above found, which made the entire pre-task risk assessment a
    # no-op -- immune could flag an auto-deploy antibody or failure-predict
    # could return WILL_FAIL and the caller would still be told "LOW_RISK".
    # failure-predict already synthesizes the immune system, past failures,
    # environment, and complexity signals into a single verdict, so prefer
    # that; fall back to the immune system's own decision if failure-predict
    # didn't return one.
    verdict = fp.get("verdict") if isinstance(fp, dict) else None
    if not verdict:
        decision = immune.get("decision") if isinstance(immune, dict) else None
        verdict = {"auto_deploy": "HIGH_RISK", "suggest": "LOW_RISK"}.get(decision, "LOW_RISK")
    results["verdict"] = verdict
    if isinstance(fp, dict) and fp.get("recommendation"):
        results["recommendation"] = fp["recommendation"]
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
