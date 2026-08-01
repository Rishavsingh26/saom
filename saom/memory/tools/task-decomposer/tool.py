import json, os, re, sys

TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY_PATH = os.path.join(TOOLS_DIR, "registry.json")

PHASES = ["research", "plan", "build", "test", "document", "deploy", "reflect", "monitor"]

PHASE_GUIDE = {
    "research":    "Gather information, understand context, explore unknowns",
    "plan":        "Define approach, break into steps, identify risks",
    "build":       "Implement, code, configure, construct",
    "test":        "Verify correctness, find bugs, validate output",
    "document":    "Record decisions, write specs, update logs",
    "deploy":      "Ship, release, publish, distribute",
    "reflect":     "Review outcome, extract lessons, update memory",
    "monitor":     "Track metrics, alert on anomalies, observe behavior"
}

PHASE_PREV = {
    "research":    [],
    "plan":        ["research"],
    "build":       ["plan", "research"],
    "test":        ["build"],
    "document":    ["build", "test"],
    "deploy":      ["test"],
    "reflect":     ["deploy", "test", "build"],
    "monitor":     ["deploy"]
}

PHASE_VERBS = {
    "research":    ["find", "search", "lookup", "gather", "research", "investigate", "explore", "study", "learn", "read", "survey", "review"],
    "plan":        ["plan", "design", "outline", "strategy", "architect", "decide", "choose", "select"],
    "build":       ["build", "create", "implement", "code", "write", "develop", "generate", "construct", "make", "produce", "author", "scaffold"],
    "test":        ["test", "verify", "validate", "check", "audit", "benchmark", "evaluate", "debug", "assert", "prove"],
    "document":    ["document", "record", "log", "note", "summarize", "explain", "annotate", "write about"],
    "deploy":      ["deploy", "ship", "release", "publish", "distribute", "install", "launch"],
    "reflect":     ["reflect", "review", "learn", "extract", "analyze", "improve", "optimize"],
    "monitor":     ["monitor", "track", "watch", "observe", "alert", "report"]
}

CONNECTOR_PAT = re.compile(r'\s+(?:and then|then|after that|followed by|next|finally|also|in order to)\s+', re.IGNORECASE)
AND_PAT = re.compile(r'\s+and\s+', re.IGNORECASE)

def load_json(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return default if default is not None else {}

def load_registry():
    return load_json(REGISTRY_PATH, {"tools": []})

def keyword_score(text, keywords):
    t = text.lower()
    return sum(1 for kw in keywords if kw.lower() in t)

def classify_segment(segment):
    seg_lower = segment.lower()
    score_map = {}
    for phase, verbs in PHASE_VERBS.items():
        score = sum(2 for v in verbs if re.search(r'\b' + re.escape(v) + r'\b', seg_lower))
        guide_tokens = PHASE_GUIDE[phase].lower().split(",")
        score += sum(1 for g in guide_tokens if g.strip() in seg_lower)
        if score > 0:
            score_map[phase] = score
    if score_map:
        return max(score_map, key=score_map.get)
    for phase, verbs in PHASE_VERBS.items():
        score = sum(1 for v in verbs if v in seg_lower)
        if score > 0:
            return phase
    return "plan"

def match_tools(segment, registry, phase):
    matched = []
    seg_lower = segment.lower()
    for tool in registry.get("tools", []):
        triggers = tool.get("triggers", {})
        phases = triggers.get("phases", ["pre", "post"])
        if phase not in phases and "pre" not in phases and "post" not in phases:
            continue
        keywords = triggers.get("keywords", [])
        score = keyword_score(seg_lower, keywords)
        if score > 0:
            matched.append({
                "name": tool["name"],
                "score": score,
                "description": tool.get("description", "")[:100],
                "mode": triggers.get("modes", ["manual"])[0]
            })
    matched.sort(key=lambda x: -x["score"])
    return matched[:3]

CONNECTOR_WORDS = {"then", "finally", "next", "also", "and", "to", "for", "in order to", "after that", "followed by"}

def split_goal(goal):
    goal = re.sub(r'[,;]+', ' ', goal).strip()
    segments = CONNECTOR_PAT.split(goal)
    segments = [s.strip().rstrip(".,;!?") for s in segments if s.strip()]
    segments = [s for s in segments if len(s) > 5]
    if len(segments) == 1:
        sentences = re.split(r'[.!?]\s+', goal)
        segments = [s.strip().rstrip(".,;!?") for s in sentences if len(s.strip()) > 10]
    if not segments:
        segments = [goal[:200].strip()]
    expanded = []
    for seg in segments:
        parts = AND_PAT.split(seg)
        parts = [p.strip() for p in parts if len(p.strip()) > 12]
        if len(parts) > 1:
            expanded.extend(parts)
        else:
            expanded.append(seg)
    return expanded

def decompose_goal(goal):
    registry = load_registry()
    segments = split_goal(goal)
    subtasks = []
    for i, seg in enumerate(segments):
        phase = classify_segment(seg)
        tools = match_tools(seg, registry, phase)
        tid = f"subtask-{i+1:02d}"
        deps = []
        for prev_phase in PHASE_PREV.get(phase, []):
            for j in range(i - 1, -1, -1):
                if j < len(subtasks) and subtasks[j].get("phase") == prev_phase:
                    deps.append(subtasks[j]["id"])
                    break
        subtasks.append({
            "id": tid,
            "description": seg[:150],
            "phase": phase,
            "phase_guide": PHASE_GUIDE.get(phase, ""),
            "matched_tools": tools,
            "depends_on": deps,
            "order": i + 1
        })
    return subtasks

def build_dag(subtasks):
    plan_lines = []
    plan_lines.append("## Execution Plan (DAG)")
    plan_lines.append("")
    for st in subtasks:
        deps_str = ", ".join(st["depends_on"]) if st["depends_on"] else "none"
        tools_str = ", ".join(t["name"] for t in st["matched_tools"]) if st["matched_tools"] else "no matching tool"
        plan_lines.append(f"  {st['id']}: [{st['phase']}] {st['description'][:80]}")
        plan_lines.append(f"       tools -> {tools_str}")
        plan_lines.append(f"       waits  -> {deps_str}")
        plan_lines.append("")

    deps = {st["id"]: set(st["depends_on"]) for st in subtasks}
    order = {}
    for i, st in enumerate(subtasks):
        order[st["id"]] = st["order"]

    exec_order = []
    remaining = set(st["id"] for st in subtasks)
    while remaining:
        ready = [tid for tid in remaining if not deps[tid]]
        if not ready:
            ready = list(remaining)
        ready.sort(key=lambda x: order.get(x, 0))
        current = ready[0]
        exec_order.append(current)
        remaining.remove(current)
        for tid in remaining:
            deps[tid].discard(current)

    plan_lines.append("### Execution Order")
    for i, tid in enumerate(exec_order, 1):
        st = next(s for s in subtasks if s["id"] == tid)
        plan_lines.append(f"  {i}. {tid} [{st['phase']}] {st['description'][:80]}")

    return "\n".join(plan_lines), exec_order

def trace_decomposition(goal):
    lines = []
    lines.append(f"INPUT: {goal}")
    lines.append("")
    lines.append("Step 1: Split goal into segments")
    segments = split_goal(goal)
    for i, seg in enumerate(segments):
        lines.append(f"  Segment {i+1}: \"{seg[:100]}\"")
    lines.append("")
    lines.append("Step 2: Classify each segment + match tools")
    registry = load_registry()
    for i, seg in enumerate(segments):
        phase = classify_segment(seg)
        lines.append(f"  Segment {i+1} -> [{phase}] ({PHASE_GUIDE.get(phase, '')})")
        tools = match_tools(seg, registry, phase)
        for t in tools:
            lines.append(f"       tool: {t['name']} (score={t['score']}, mode={t['mode']})")
        if not tools:
            lines.append("       tool: none")
    lines.append("")
    lines.append("Step 3: Build dependency DAG")
    subtasks = decompose_goal(goal)
    dag, exec_order = build_dag(subtasks)
    lines.append(dag)
    return "\n".join(lines)

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"help": "Task decomposer tool — splits high-level goals into sub-tasks with phase classification and tool dispatch matching", "modes": ["decompose <goal>", "plan <goal>", "trace <goal>"], "usage": "python tool.py <decompose|plan|trace> <goal>", "default": "Showing help (no default mode)"}, indent=2))
        return
    mode = sys.argv[1]
    goal = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
    if not goal:
        print(json.dumps({"error": "Goal is required"}))
        sys.exit(1)

    if mode == "trace":
        print(trace_decomposition(goal))
        return

    subtasks = decompose_goal(goal)
    if not subtasks:
        print(json.dumps({"error": "Could not decompose goal into sub-tasks"}))
        sys.exit(1)

    dag, exec_order = build_dag(subtasks)

    if mode == "plan":
        output = {
            "goal": goal[:200],
            "subtasks": subtasks,
            "total_subtasks": len(subtasks),
            "execution_order": exec_order,
            "dag_plan": dag
        }
    else:
        output = {
            "goal": goal[:200],
            "subtasks": [{k: v for k, v in st.items() if k != "phase_guide"} for st in subtasks],
            "total_subtasks": len(subtasks),
            "execution_order": exec_order
        }

    print(json.dumps(output, indent=2))

if __name__ == "__main__":
    main()
