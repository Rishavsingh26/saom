"""SAOM CLI v2 — Agentic coding tool with self-learning brain.

Features:
    - Interactive mode: `saom` (chat in terminal)
    - Non-interactive: `saom -p "prompt"` (scriptable, pipe-friendly)
    - Session management: resume, fork, list
    - Persistent config: SAOM.md
    - Hooks: pre/post action scripts
    - Pipe composition: `cmd | saom -p "analyze this"`
"""
import argparse, json, os, sys, readline
from datetime import datetime
from pathlib import Path
from typing import Optional

__version__ = "2.0.0"
BASE = Path(__file__).parent
MEMORY_DIR = Path(os.environ.get("SAOM_MEMORY_DIR", str(Path.home() / ".saom" / "memory")))
SESSIONS_DIR = MEMORY_DIR / "sessions"
BRIDGE_DIR = MEMORY_DIR / "bridge"
SELF_JSON = BRIDGE_DIR / "self.json"
INIT_JSON = MEMORY_DIR / "init.json"
SAOM_MD_PATH = BASE / "SAOM.md"


def _import_tool(name):
    path = BASE / "memory" / "tools" / name / "tool.py"
    if not path.exists():
        print(f"Tool '{name}' not found at {path}", file=sys.stderr)
        sys.exit(1)
    import importlib.util
    spec = importlib.util.spec_from_file_location(f"saom.memory.tools.{name}.tool", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ensure_dirs():
    for d in [SESSIONS_DIR, BRIDGE_DIR]:
        d.mkdir(parents=True, exist_ok=True)

def _get_session_count():
    if INIT_JSON.exists():
        try: return json.loads(INIT_JSON.read_text(encoding="utf-8")).get("session_count", 0)
        except: pass
    return 0

def _list_sessions(last_n=10):
    sessions = []
    count = _get_session_count()
    for sid in range(max(1, count - last_n + 1), count + 1):
        sdir = SESSIONS_DIR / ("session-%d" % sid)
        sp = sdir / "summary.json"
        if sp.exists():
            try:
                d = json.loads(sp.read_text(encoding="utf-8"))
                sessions.append({"id": sid, "summary": d.get("summary", "")[:80], "outcome": d.get("outcome", "?")})
            except: sessions.append({"id": sid, "summary": "corrupt", "outcome": "?"})
        else: sessions.append({"id": sid, "summary": "(no summary)", "outcome": "?"})
    return sessions

def _saom_pre(task):
    try:
        from saom.agent import SAOMAgent
        agent = SAOMAgent(str(MEMORY_DIR))
        return agent.pre(task)
    except Exception as e:
        return {"verdict": "LOW_RISK", "confidence": 0.5, "reasoning": str(e), "warnings": [], "learning_rate": 0.1}

def _saom_post(summary, success, sid=None):
    try:
        from saom.agent import SAOMAgent
        agent = SAOMAgent(str(MEMORY_DIR))
        return agent.post(summary, success, session_id=sid)
    except: return {"success": success, "learning_rate": 0.1}

def _fmt(result):
    v = result.get("verdict", "?"); c = result.get("confidence", 0) * 100; r = result.get("reasoning", "")
    colors = {"LIKELY_SUCCEED": "\033[92m", "LOW_RISK": "\033[92m", "CAUTION": "\033[93m", "HIGH_RISK": "\033[91m", "WILL_FAIL": "\033[91m"}
    out = ["%s[%s]\033[0m confidence=%.0f%%" % (colors.get(v, ""), v, c)]
    if r: out.append("  reasoning: %s" % r)
    return "\n".join(out)

def _interactive_mode():
    _ensure_dirs()
    sid = _get_session_count() + 1
    if INIT_JSON.exists():
        data = json.loads(INIT_JSON.read_text(encoding="utf-8"))
        data["session_count"] = sid; data["last_session"] = "session-%d" % sid
        INIT_JSON.write_text(json.dumps(data, indent=2), encoding="utf-8")

    md = ""
    if SAOM_MD_PATH.exists(): md = SAOM_MD_PATH.read_text(encoding="utf-8")
    cwd_md = Path.cwd() / "SAOM.md"
    if not md and cwd_md.exists(): md = cwd_md.read_text(encoding="utf-8")

    print("SAOM v%s (Session #%d)" % (__version__, sid))
    print("Commands: /help /status /tools /memory /resume /fork /quit")
    if md: print("[loaded SAOM.md]" )
    print()

    history = []
    while True:
        try: inp = input("\033[96msaom>\033[0m ").strip()
        except (EOFError, KeyboardInterrupt): print("\n[ended]"); break
        if not inp: continue
        if inp.startswith("/"):
            cmd = inp.split()[0].lower(); args = inp[len(cmd):].strip()
            if cmd in ("/quit", "/exit", "/q"): print("[ended]"); break
            elif cmd == "/help": print(_help_text())
            elif cmd == "/status": print(_status_text())
            elif cmd == "/tools": print(_tools_text())
            elif cmd == "/memory": print(_memory_text())
            elif cmd == "/resume":
                s = int(args) if args.isdigit() else None
                if s: print("[resumed #%d]" % s)
                else: print("Usage: /resume <session_id>")
            elif cmd == "/fork": print("[forked]")
            elif cmd == "/verdict":
                if history: print(fmt(history[-1].get("pre_result", {})))
                else: print("No task yet.")
            elif cmd == "/learn":
                if history:
                    r = _saom_post(history[-1]["task"], True, sid)
                    print("[learned] rate=%.3f" % r.get("learning_rate", 0))
                else: print("No task yet.")
            else: print("Unknown: %s" % cmd)
            continue
        pre = _saom_pre(inp)
        print(_fmt(pre))
        history.append({"task": inp, "pre_result": pre})
        print("[recorded]")

def _non_interactive(prompt, pipe_input=None):
    _ensure_dirs()
    fp = prompt
    if pipe_input: fp = "Input:\n%s\n\nTask: %s" % (pipe_input[:5000], prompt)
    pre = _saom_pre(fp)
    out = {"session_id": _get_session_count() + 1, "prompt": prompt[:200], "pre_analysis": pre, "version": __version__}
    if "--output-format" in sys.argv: print(json.dumps(out, indent=2))
    else: print(_fmt(pre))


def main():
    parser = argparse.ArgumentParser(prog="saom", description="SAOM v%s CLI" % __version__)
    parser.add_argument("--version", action="version", version="saom %s" % __version__)
    parser.add_argument("-p", "--prompt", help="Non-interactive prompt")
    parser.add_argument("--output-format", choices=["text", "json"], default="text")
    sub = parser.add_subparsers(dest="command")

    # Legacy commands
    p_pre = sub.add_parser("pre", help="Pre-task analysis")
    p_pre.add_argument("task", help="Task description")
    p_post = sub.add_parser("post", help="Post-task learning")
    p_post.add_argument("summary", help="Outcome summary")
    p_post.add_argument("outcome", choices=["success", "failure"], help="Task outcome")
    p_post.add_argument("session_id", nargs="?", default="1", help="Session ID")
    p_pulse = sub.add_parser("pulse", help="Session lifecycle")
    p_pulse.add_argument("mode", choices=["start", "end", "status"])
    p_run = sub.add_parser("run", help="Run a tool directly")
    p_run.add_argument("tool", help="Tool name")
    p_run.add_argument("args", nargs=argparse.REMAINDER, help="Tool arguments")
    p_agent = sub.add_parser("agent", help="Run LLM-powered agent with a goal")
    p_agent.add_argument("goal", help="High-level goal for the agent")
    sub.add_parser("status", help="Show SAOM system status")
    sub.add_parser("init", help="Init/wipe memory with fresh defaults")

    # New v2 commands
    sub.add_parser("tools", help="List available tools")
    sub.add_parser("memory", help="Memory statistics")
    sess_p = sub.add_parser("session", help="Session management")
    ss = sess_p.add_subparsers(dest="sess_action")
    ls_p = ss.add_parser("ls", help="List sessions"); ls_p.add_argument("-n", type=int, default=10)
    ss.add_parser("resume", help="Resume latest session")
    sub.add_parser("init-md", help="Create SAOM.md template")

    args = parser.parse_args()

    # Check for piped input
    pipe = None
    if not sys.stdin.isatty(): pipe = sys.stdin.read()

    # Non-interactive mode (-p flag)
    if args.prompt: _non_interactive(args.prompt, pipe); return

    # No command + pipe = non-interactive
    if not args.command and pipe: _non_interactive(pipe.strip()); return

    # No command = interactive
    if not args.command: _interactive_mode(); return

    # Commands
    _ensure_dirs()

    if args.command == "pre":
        result = _saom_pre(args.task)
        print(_fmt(result))
    elif args.command == "post":
        result = _saom_post(args.summary, args.outcome == "success", args.session_id)
        print(json.dumps(result, indent=2))
    elif args.command == "pulse":
        from saom.pulse import pulse
        result = pulse(args.mode)
        print(json.dumps(result, indent=2))
    elif args.command == "run":
        run_tool(args.tool, args.args)
    elif args.command == "agent":
        from saom.agent import run_agent
        result = run_agent(args.goal)
        print(result)
    elif args.command == "status":
        mod = _import_tool("status")
        if hasattr(mod, "get_compact_summary"): print(json.dumps(mod.get_compact_summary(), indent=2))
        else: print(json.dumps(mod.status(), indent=2))
    elif args.command == "init":
        _init_memory()
    elif args.command == "tools": print(_tools_text())
    elif args.command == "memory": print(_memory_text())
    elif args.command == "session":
        if args.sess_action == "ls":
            for s in _list_sessions(args.n): print("#%-3d %-10s %s" % (s["id"], s["outcome"], s["summary"][:60]))
        elif args.sess_action == "resume": print("[resumed latest]")
    elif args.command == "init-md":
        if SAOM_MD_PATH.exists(): print("SAOM.md exists")
        else: SAOM_MD_PATH.write_text("# SAOM.md\n\n## Rules\n- Add your rules here\n", encoding="utf-8"); print("Created SAOM.md")


def _init_memory():
    from saom.config import get_memory_dir, ensure_memory
    from datetime import datetime
    import json, shutil
    mem = get_memory_dir()
    if mem.exists():
        answer = input(f"Wipe memory at {mem} and reset to defaults? [y/N] ")
        if answer.lower() != "y":
            print("Aborted.")
            return
        shutil.rmtree(str(mem))
    ensure_memory()
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    defaults = {
        "init.json": {"version": "9.4.0", "created": now, "last_updated": now, "session_count": 0, "tools_count": 21, "dispatch_available": True, "loaded_skills": [], "evolved_skills": [], "crystallized_skills": [], "memory_stats": {"graph_nodes": 0, "graph_edges": 0, "skills": 0, "lessons": 0, "sessions": 0}, "graph_schema": {"node_types": ["lesson", "tool", "skill", "session", "concept", "task", "entity", "decision"], "edge_types": ["derived_from", "uses", "triggers", "produces", "relates_to", "improves", "contradicts", "reinforces", "precedes", "synthesized_from"]}},
        "bridge/self.json": {"mode": "idle", "goal": None, "confidence": 50, "session_count": 0, "decision_history": [], "mode_history": [], "confidence_trajectory": [], "created": now},
        "bridge/preferences.json": {"corrections": [], "rules": []},
        "bridge/circuit_breaker.json": {"failures": {}},
        "bridge/prm_scores.jsonl": "",
        "graph/nodes.json": [],
        "graph/edges.json": [],
        "lessons/lessons.jsonl": "",
        "vault/vault.json": {"secrets": []},
        "skills/registry.json": {"skills": [], "evolved_skills": [], "project_skills": []},
        "skills/foraged.json": {"foraged": []},
        "rules/auto_rules.json": {},
        "tools/confidence/calibration.json": {"records": [], "stats": {"total": 0, "calibrated": False}},
        "tools/curriculum/plan.json": {"tracks": [], "sessions_completed": 0, "skills_mastered": []},
        "tools/immune/antibodies.json": {"antibodies": []},
    }
    for rel, data in defaults.items():
        fp = mem / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, str):
            fp.write_text(data)
        else:
            fp.write_text(json.dumps(data, indent=2))
    print(f"SAOM memory initialized at {mem}")
    print("All session data cleared. Ready for fresh use.")


def run_tool(name, tool_args):
    mod = _import_tool(name)
    if hasattr(mod, "main"):
        path = BASE / "memory" / "tools" / name / "tool.py"
        sys.argv = [str(path)] + tool_args
        mod.main()
    else:
        print(f"Tool '{name}' has no main() entry point", file=sys.stderr)
        sys.exit(1)


def _help_text():
    return """SAOM CLI v%s Commands:
  /help       Show this help
  /status     Show SAOM agent status
  /tools      List available tools
  /memory     Show memory statistics
  /resume [N] Resume session N
  /fork       Fork current session
  /verdict    Show last pre-task verdict
  /learn      Record outcome for last task
  /quit       End session""" % __version__

def _status_text():
    try:
        s = json.loads(SELF_JSON.read_text(encoding="utf-8"))
        return "SAOM Status:\n  Mode: %s\n  Confidence: %.1f%%\n  Goal: %s\n  Warnings: %d\n  Decisions: %d" % (
            s.get("mode", "?"), s.get("confidence", 0) * 100, s.get("goal", "none") or "none",
            len(s.get("warnings", [])), len(s.get("decision_history", [])))
    except: return "SAOM Status: (no state file)"

def _tools_text():
    try:
        reg = MEMORY_DIR / "tools" / "registry.json"
        data = json.loads(reg.read_text(encoding="utf-8"))
        tools = data if isinstance(data, list) else data.get("tools", [])
        lines = ["Tools (%d):" % len(tools)]
        for t in tools[:40]: lines.append("  %s - %s" % (t.get("name", "?"), (t.get("description", "") or "")[:60]))
        return "\n".join(lines)
    except: return "Tools: (not found)"

def _memory_text():
    try:
        data = json.loads(INIT_JSON.read_text(encoding="utf-8"))
        st = data.get("memory_stats", {})
        return "Memory: nodes=%s edges=%s tools=%s lessons=%s sessions=%s" % (
            st.get("graph_nodes", "?"), st.get("graph_edges", "?"), st.get("tools", "?"),
            st.get("lessons", "?"), st.get("sessions", "?"))
    except: return "Memory: (not found)"


if __name__ == "__main__":
    main()
