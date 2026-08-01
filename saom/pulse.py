import json, os
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).parent
SELF_PATH = BASE / "self.json"


def default_self():
    return {
        "mode": "idle",
        "goal": None,
        "confidence": 50,
        "session_count": 0,
        "decision_history": [],
        "mode_history": [],
        "confidence_trajectory": [],
        "created": datetime.utcnow().isoformat(),
    }


def read_self():
    if SELF_PATH.exists():
        try:
            with open(SELF_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return default_self()


def write_self(state):
    with open(SELF_PATH, "w") as f:
        json.dump(state, f, indent=2)


def pulse(mode):
    state = read_self()
    now = datetime.utcnow().isoformat()

    if mode == "start":
        state["session_count"] = state.get("session_count", 0) + 1
        state["mode"] = "active"
        state["goal"] = None
        state["started_at"] = now
        write_self(state)
        return {"session": state["session_count"], "status": "started"}

    elif mode == "end":
        state["mode"] = "ended"
        state["ended_at"] = now
        write_self(state)
        return {"session": state["session_count"], "status": "ended"}

    elif mode == "status":
        return {
            "mode": state.get("mode"),
            "session": state.get("session_count"),
            "confidence": state.get("confidence"),
            "warnings_count": len(state.get("warnings", [])),
        }

    return {"error": f"unknown mode: {mode}"}
