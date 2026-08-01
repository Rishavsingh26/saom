"""
Evolution Loop Engine — Autonomous Self-Improvement for SAOM

Usage:
    python engine.py diagnose          # Analyze failure patterns
    python engine.py propose --task T  # Generate upgrade proposal
    python engine.py evolve --prop P   # Apply approved proposal
    python engine.py status            # Show evolution state
"""
import json, os, sys, re, datetime
from pathlib import Path

SAOM_BASE = Path(os.environ.get("SAOM_BASE", str(Path(__file__).resolve().parent.parent.parent)))

def load_json(path):
    if not path.exists():
        return {} if path.suffix == ".json" else []
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {} if path.suffix == ".json" else []

def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def load_lessons():
    path = SAOM_BASE / "memory" / "lessons" / "lessons.jsonl"
    lessons = []
    if path.exists():
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        lessons.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return lessons

def load_graph():
    nodes = load_json(SAOM_BASE / "memory" / "graph" / "nodes.json")
    edges = load_json(SAOM_BASE / "memory" / "graph" / "edges.json")
    if isinstance(nodes, dict):
        nodes = nodes.get("nodes", [])
    if isinstance(edges, dict):
        edges = edges.get("edges", [])
    return nodes, edges

def load_last_task():
    path = SAOM_BASE / "memory" / "working" / "last-step.json"
    return load_json(path)

# ─── Diagnose ──────────────────────────────────────────────────────

def diagnose():
    lessons = load_lessons()
    nodes, edges = load_graph()
    last = load_last_task()

    print(f"=== Evolution Loop: Diagnose ===")
    print(f"Lessons recorded: {len(lessons)}")
    print(f"Graph nodes: {len(nodes)}, edges: {len(edges)}")

    if not lessons:
        print("No lessons yet. Run a task first.")
        return {"severity": 0, "patterns": []}

    # Analyze recent lessons (last 10)
    recent = lessons[-10:]
    domains = {}
    errors = {}
    tools = {}

    for l in recent:
        domain = l.get("domain", "unknown")
        error = l.get("error", "").split("\n")[0][:100]
        tool = l.get("tool", "unknown")
        domains[domain] = domains.get(domain, 0) + 1
        errors[error] = errors.get(error, 0) + 1
        tools[tool] = tools.get(tool, 0) + 1

    print(f"\n=== Failure Patterns ===")
    print(f"Domains: {domains}")
    print(f"Top errors: {dict(sorted(errors.items(), key=lambda x: -x[1])[:5])}")
    print(f"Tools used: {tools}")

    # Check for repeat errors (same error appeared 2+ times)
    repeats = {e: c for e, c in errors.items() if c >= 2}
    domain_weakness = {d: c for d, c in domains.items() if c >= 3}

    severity = 0
    patterns = []

    if repeats:
        severity += len(repeats)
        for e, c in repeats.items():
            patterns.append({"type": "repeat_error", "detail": e, "count": c})
            print(f"  !!! REPEAT ERROR ({c}x): {e[:80]}")

    if domain_weakness:
        severity += len(domain_weakness)
        for d, c in domain_weakness.items():
            patterns.append({"type": "domain_weakness", "detail": d, "count": c})
            print(f"  !!! DOMAIN WEAKNESS ({c}x): {d}")

    # Check if last task was a repeat
    if last and last.get("status") == "failure":
        last_error = str(last.get("error", ""))[:100]
        if last_error in errors:
            severity += 1
            print(f"  !!! LAST TASK is a repeat failure")

    print(f"\nSeverity: {severity}/5")
    result = {"severity": min(severity, 5), "patterns": patterns, "timestamp": datetime.datetime.now().isoformat()}
    save_json(SAOM_BASE / "evolved" / "evolution-loop" / "state.json", result)
    return result

# ─── Propose ───────────────────────────────────────────────────────

def propose(task_path=None):
    state = load_json(SAOM_BASE / "evolved" / "evolution-loop" / "state.json")
    tasks = load_json(Path(task_path)) if task_path and Path(task_path).exists() else load_last_task()

    print(f"=== Evolution Loop: Propose ===")
    severity = state.get("severity", 0)

    if severity < 2:
        print("Severity < 2. No proposal needed. Lesson logged.")
        return {"proposal": None, "reason": "low_severity"}

    lessons = load_lessons()
    if not lessons:
        print("No lessons to learn from.")
        return {"proposal": None, "reason": "no_lessons"}

    # Analyze which skill could have helped
    error_keywords = set()
    for l in lessons[-5:]:
        error = l.get("error", "").lower()
        if "chrome" in error or "dpapi" in error:
            error_keywords.add("cookie_extraction")
        if "mega" in error or "rate limit" in error or "etoomany" in error:
            error_keywords.add("mega_download")
        if "yt-dlp" in error or "youtube" in error:
            error_keywords.add("youtube_auth")
        if "age" in error or "login_required" in error:
            error_keywords.add("youtube_age_bypass")
        if "403" in error or "401" in error:
            error_keywords.add("auth_bypass")
        if "timeout" in error:
            error_keywords.add("network_timeout")
        if "not found" in error or "no such" in error:
            error_keywords.add("tool_install")

    # Map keywords to skill proposals
    skill_map = {
        "cookie_extraction": {
            "name": "auth-bypass",
            "type": "load",
            "reason": "Chrome DPAPI encryption blocks cookie extraction. Firefox SQLite read works."
        },
        "mega_download": {
            "name": "tool-forager",
            "type": "run",
            "reason": "MEGAcmd handles rate limits. Install it instead of hacking around MEGA."
        },
        "youtube_auth": {
            "name": "auth-bypass",
            "type": "load",
            "reason": "YouTube requires cookies from authenticated browser. Firefox + --cookies-from-browser."
        },
        "youtube_age_bypass": {
            "name": "auth-bypass",
            "type": "load",
            "reason": "Age-restricted videos need auth cookies. Firefox private window export works."
        },
        "auth_bypass": {
            "name": "auth-bypass",
            "type": "load",
            "reason": "Token replay pattern would have solved this."
        },
        "tool_install": {
            "name": "tool-forager",
            "type": "load",
            "reason": "Systematic search + install would have found the right tool."
        },
        "network_timeout": {
            "name": "tool-forager",
            "type": "run",
            "reason": "aria2c or wget with retry flags would handle timeouts."
        },
    }

    proposals = []
    for kw in error_keywords:
        if kw in skill_map:
            proposals.append(skill_map[kw])

    # Deduplicate
    seen = set()
    unique_proposals = []
    for p in proposals:
        key = p["name"]
        if key not in seen:
            seen.add(key)
            unique_proposals.append(p)

    if unique_proposals:
        print(f"\n=== Proposed Upgrades ===")
        for p in unique_proposals:
            print(f"  Load skill: {p['name']}")
            print(f"  Reason: {p['reason']}")
        proposal = {
            "timestamp": datetime.datetime.now().isoformat(),
            "severity": severity,
            "patterns": state.get("patterns", []),
            "proposals": unique_proposals,
            "message": f"Found {len(unique_proposals)} skill gap(s). Run `evolution-loop evolve` to apply."
        }
    else:
        proposal = {
            "timestamp": datetime.datetime.now().isoformat(),
            "severity": severity,
            "patterns": state.get("patterns", []),
            "proposals": [],
            "message": "No matching skill gap found. Manual analysis needed."
        }
        print("\nNo matching skill proposal. Error pattern unknown.")

    save_json(SAOM_BASE / "evolved" / "evolution-loop" / "proposal.json", proposal)
    return proposal

# ─── Evolve ────────────────────────────────────────────────────────

def evolve(proposal_path=None):
    prop = load_json(Path(proposal_path)) if proposal_path else \
           load_json(SAOM_BASE / "evolved" / "evolution-loop" / "proposal.json")

    print(f"=== Evolution Loop: Evolve ===")

    if not prop.get("proposals"):
        print("No proposals to evolve.")
        return

    for p in prop["proposals"]:
        name = p["name"]
        action = p.get("type", "load")
        print(f"\n  Evolving: {name} ({action})")

        # Register as evolved in skills registry
        registry_path = SAOM_BASE / "memory" / "skills" / "registry.json"
        reg = load_json(registry_path)
        evolved = reg.get("evolved", [])

        entry = {
            "name": name,
            "action": action,
            "proposed_at": prop["timestamp"],
            "reason": p["reason"],
            "domain": prop.get("patterns", [{}])[0].get("detail", "unknown") if prop.get("patterns") else "unknown"
        }

        if entry not in evolved:
            evolved.append(entry)
            reg["evolved"] = evolved
            save_json(registry_path, reg)
            print(f"    Registered in skills registry.")

    # Update the init.json
    init_path = SAOM_BASE / "memory" / "init.json"
    init = load_json(init_path)
    init["last_evolution"] = prop["timestamp"]
    init["evolution_count"] = init.get("evolution_count", 0) + len(prop["proposals"])
    save_json(init_path, init)

    print(f"\n  Evolution complete. {len(prop['proposals'])} upgrade(s) registered.")
    print(f"  Next step: User loads the proposed skill with `skill` tool.")

    return prop

# ─── Status ────────────────────────────────────────────────────────

def status():
    state = load_json(SAOM_BASE / "evolved" / "evolution-loop" / "state.json")
    prop = load_json(SAOM_BASE / "evolved" / "evolution-loop" / "proposal.json")
    init = load_json(SAOM_BASE / "memory" / "init.json")
    lessons = load_lessons()

    print(f"=== Evolution Loop: Status ===")
    print(f"Total lessons: {len(lessons)}")
    print(f"Session count: {init.get('session_count', 0)}")
    print(f"Last evolution: {init.get('last_evolution', 'never')}")
    print(f"Evolution count: {init.get('evolution_count', 0)}")
    print(f"Current severity: {state.get('severity', 0)}/5")
    if prop.get("proposals"):
        print(f"Pending proposals: {len(prop['proposals'])}")
        for p in prop["proposals"]:
            print(f"  - {p['name']}: {p['reason']}")
    else:
        print("No pending proposals.")

# ─── CLI ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: engine.py [diagnose|propose|evolve|status]")
        sys.exit(1)

    command = sys.argv[1]
    if command == "diagnose":
        diagnose()
    elif command == "propose":
        task_path = None
        if "--task" in sys.argv:
            idx = sys.argv.index("--task")
            if idx + 1 < len(sys.argv):
                task_path = sys.argv[idx + 1]
        propose(task_path)
    elif command == "evolve":
        prop_path = None
        if "--prop" in sys.argv:
            idx = sys.argv.index("--prop")
            if idx + 1 < len(sys.argv):
                prop_path = sys.argv[idx + 1]
        evolve(prop_path)
    elif command == "status":
        status()
    else:
        print(f"Unknown command: {command}")
        print("Usage: engine.py [diagnose|propose|evolve|status]")
