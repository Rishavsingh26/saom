import json
import os
import subprocess
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(BASE, "tools")
BRIDGE = os.path.dirname(os.path.abspath(__file__))
SELF_PATH = os.path.join(BRIDGE, "self.json")
INIT_PATH = os.path.join(BASE, "init.json")

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

# Import call_tool (with circuit breaker) from bridge
import importlib.util as _util
_spec = _util.spec_from_file_location("bridge_mod", os.path.join(BRIDGE, "bridge.py"))
_bridge_mod = _util.module_from_spec(_spec)
_spec.loader.exec_module(_bridge_mod)
call_tool = _bridge_mod.call_tool

def start():
    init = load_json(INIT_PATH, {})
    current_count = init.get("session_count", 0)
    session_id = current_count + 1

    continuity = call_tool("continuity", "start")
    context = {}
    if "error" not in continuity:
        context = continuity

    self_data = {
        "session_id": session_id,
        "mode": "idle",
        "goal": None,
        "confidence": None,
        "active_warnings": [],
        "last_decision": None,
        "last_outcome": None,
        "reflection_pending": False,
        "started_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    }
    save_json(SELF_PATH, self_data)

    init["session_count"] = session_id
    save_json(INIT_PATH, init)

    prev_sessions = context.get("prev_sessions", [])
    recent_lessons = context.get("recent_lessons", [])
    underperforming = context.get("underperforming_skills", [])
    pending_writes = context.get("pending_writes", 0)

    print(f"[PULSE] Session {session_id} started")
    if prev_sessions:
        print(f"  Previous sessions: {len(prev_sessions)}")
    if recent_lessons:
        print(f"  Recent lessons: {len(recent_lessons)}")
        for l in recent_lessons[-2:]:
            print(f"    - {l.get('summary', '')[:80]}")
    if underperforming:
        print(f"  Underperforming skills: {[u['skill'] for u in underperforming]}")
    if pending_writes:
        print(f"  Pending graph writes: {pending_writes}")

    return {"session_id": session_id, "prev_sessions": prev_sessions, "recent_lessons": recent_lessons}

def end(summary="Session completed", tasks=None, issues=None):
    self_data = load_json(SELF_PATH, {})
    session_id = self_data.get("session_id")

    call_tool("plasticity", "decay")
    call_tool("immune", "forget")

    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    session_payload = json.dumps({
        "session_id": session_id,
        "summary": summary[:500],
        "tasks": tasks or [],
        "issues": issues or [],
        "lessons_extracted": [],
        "skills_used": [],
        "notes": ""
    })
    continuity = call_tool("continuity", "end", session_payload)

    init = load_json(INIT_PATH, {})
    save_json(INIT_PATH, init)

    self_data["mode"] = "ended"
    save_json(SELF_PATH, self_data)

    flushed = 0
    if "error" not in continuity:
        flushed = continuity.get("graph_nodes_flushed", 0)

    print(f"[PULSE] Session {session_id} ended. Graph writes flushed: {flushed}")
    return {"session_id": session_id, "flushed": flushed}

def status():
    self_data = load_json(SELF_PATH, {})
    init = load_json(INIT_PATH, {})
    print(f"[PULSE] Session {self_data.get('session_id')} | Mode: {self_data.get('mode')} | Goal: {str(self_data.get('goal', ''))[:60]}")
    print(f"  Confidence: {self_data.get('confidence')}% | Warnings: {len(self_data.get('active_warnings', []))}")
    print(f"  SAOM v{init.get('version')} | Graph: {init.get('memory_stats', {}).get('graph_nodes', '?')} nodes")
    health = call_tool("saom-health")
    if "error" not in health:
        if not health.get("healthy", False):
            surprises = health.get("surprises_found", 0)
            print(f"  Health: {surprises} surprise(s) found")
            for c in health.get("checks", [])[:3]:
                if c.get("severity") in ("error", "warning"):
                    print(f"    {c['severity'][0].upper()}: {c['message'][:100]}")
        else:
            print(f"  Health: OK")
    return self_data

def introspect():
    bridge_py = os.path.join(BRIDGE, "bridge.py")
    r = subprocess.run([sys.executable, bridge_py, "introspect"], capture_output=True, text=True, timeout=10)
    out = r.stdout.strip()
    try:
        data = json.loads(out)
    except:
        data = {"raw": out[:300]}
    msg = data.get('findings', [{}])[0].get('message', 'N/A')
    print(f"[PULSE] Introspection: {msg.encode('ascii', errors='replace').decode()}")
    for f in data.get("findings", []):
        tag = {"ok": "+", "info": "~", "warning": "!"}.get(f.get("severity"), "?")
        fmsg = f['message'].encode('ascii', errors='replace').decode()
        print(f"  {tag} {fmsg}")
    print(f"  Decisions: {data.get('decisions', 0)} | Mistakes: {data.get('mistakes', 0)} | Goals: {data.get('goals', 0)}")
    return data

def main():
    if len(sys.argv) < 2:
        print("Usage: python pulse.py <start|end|status|introspect> [args]")
        sys.exit(1)
    mode = sys.argv[1]
    if mode == "start":
        start()
    elif mode == "end":
        summary = sys.argv[2] if len(sys.argv) > 2 else "Session completed"
        end(summary)
    elif mode == "status":
        status()
    elif mode == "introspect":
        introspect()
    else:
        print(f"Unknown mode: {mode}")

if __name__ == "__main__":
    main()
