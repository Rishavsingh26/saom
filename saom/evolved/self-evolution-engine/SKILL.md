---
name: self-evolution-engine
description: Continuous SAOM self-improvement loop with user approval gates
disable-model-invocation: true
argument-hint: [task-outcome] [domain]
allowed-tools: Read Write Edit Glob Grep Bash
context: fork
agent: Plan
shell: powershell
metadata:
  author: SAOM
  version: 2.0.0
  type: meta-skill
---

# Self-Evolution Engine

Triggered automatically after any task completes or fails.

## Live Graph State

Recent failure patterns:
```!
python "$SAOM_BASE/memory/tools/graph-query/tool.py" q3
```

Skill gaps in this domain:
```!
python "$SAOM_BASE/memory/tools/graph-query/tool.py" q5
```

## Pipeline

### Stage 1 — Outcome Analysis
- Read the task result: success or failure
- If failure: extract root cause, tool used, error message
- If success with difficulty > 2 attempts: note the bottleneck
- Write to `$SAOM_BASE/memory/working/last-step.json`

### Stage 2 — Pattern Matching via Graph
- Query `$SAOM_BASE/memory/graph/nodes.json` for nodes matching the task domain
- Query `$SAOM_BASE/memory/graph/edges.json` for edges of type "caused" or "failure"
- Check: does this exact failure pattern exist in the graph?
- If yes: severity++ (escalate — same failure repeated)
- If no: add new failure node

### Stage 3 — Proposal Generation
IF (severity >= 2) OR (task failed AND same domain failed before):
  1. Identify which skill would have prevented this
  2. Propose a patch to that skill OR a new skill
  3. Format proposal:
     ```
     [SAOM:Evolution] Proposal: <name>
     Problem: <what went wrong>
     Fix: <proposed change to skill or new skill>
     Impact: <low/medium/high>
     [y/N]:
     ```
  4. Wait for user input
  5. If approved: implement the change
     - For skill patches: edit the SKILL.md
     - For new skills: create `$SAOM_BASE/evolved/<name>/SKILL.md`
     - Add graph node for the new/patch skill
     - Add edge: new-skill -> failure-node (type: fixes)
  6. If rejected: add note to the failure node as "user_declined"

### Stage 4 — Lesson Recording
  1. Run lesson-extractor tool:
     ```!
     python "$SAOM_BASE/memory/tools/lesson-extractor/tool.py" "<task_summary>" <outcome> <session_id>
     ```
  2. Add lesson node to graph
  3. Link lesson -> session and lesson -> task

### Stage 5 — Dashboard Update Check
- If lesson count % 5 == 0: suggest dashboard regeneration
  "Lessons recorded: <N>. Regenerate dashboard to visualize patterns?"

## Reference
See [reference.md](reference.md) for detailed graph schema and mutation patterns.

## Safety
- Never auto-apply skill patches — always ask user
- Never delete existing skill content — only append
- If proposal would change more than 1 file, list all files before asking
