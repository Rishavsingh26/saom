import argparse, importlib, json, sys
from pathlib import Path

BASE = Path(__file__).parent


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


def main():
    parser = argparse.ArgumentParser(prog="saom", description="Super Agent Ouroboros Manager")
    sub = parser.add_subparsers(dest="command")

    p_pre = sub.add_parser("pre", help="Run bridge pre-task checks")
    p_pre.add_argument("task", help="Task description")

    p_post = sub.add_parser("post", help="Run bridge post-task processing")
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

    p_status = sub.add_parser("status", help="Show SAOM system status")
    p_init = sub.add_parser("init", help="Init/wipe memory with fresh defaults (privacy-safe)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "pre":
        from saom.bridge import pre as bridge_pre
        result = bridge_pre(args.task)
        print(json.dumps(result, indent=2))

    elif args.command == "post":
        from saom.bridge import post as bridge_post
        result = bridge_post(args.summary, args.outcome, args.session_id)
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
        if hasattr(mod, "get_compact_summary"):
            print(json.dumps(mod.get_compact_summary(), indent=2))
        else:
            print(json.dumps(mod.status(), indent=2))

    elif args.command == "init":
        _init_memory()


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


if __name__ == "__main__":
    main()
