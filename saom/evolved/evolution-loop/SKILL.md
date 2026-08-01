---
name: evolution-loop
description: Autonomous SAOM self-improvement: extract lessons, audit failures, propose upgrades
allowed-tools: Read Write Edit Glob Grep Bash
context: fork
agent: Plan
shell: powershell
metadata:
  author: SAOM
  version: 1.0.0
  type: meta-skill
  evolution-cycle: continuous
---

# Evolution Loop — Autonomous Self-Improvement Pipeline

Inspired by Evolve Loop (github.com/mickeyyaya/evolve-loop) and BerriAI Self-Improving Agent — adapted for Python-only environments.

## Architecture

```
Task Complete
    │
    ▼
┌─────────────────┐
│ Phase 1         │  Extract outcome + error + context
│ Harvest          │  Write to memory/working/last-task.json
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Phase 2         │  Query graph for failure pattern match
│ Diagnose         │  Check lessons.jsonl for repeats
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Phase 3         │  Generate proposal if:
│ Propose          │    severity >= 2 OR
│                  │    same-domain failure repeat
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Phase 4         │  If approved → write skill patch
│ Evolve           │  Update graph + registry
└─────────────────┘
```

## Phase 1 — Harvest (run after every task)

```powershell
python "$SAOM_BASE/memory/tools/lesson-extractor/tool.py" --auto
```

This extracts: outcome, error message, domain, tool used, attempt count.

## Phase 2 — Diagnose (run after harvest)

```powershell
python "$SAOM_BASE/evolved/evolution-loop/engine.py" diagnose
```

Queries the graph for:
- Same error pattern in past 10 lessons
- Same domain with multiple failures
- Tool-specific failure clusters

Output: severity score (0-5) + matched patterns

## Phase 3 — Propose (run if severity >= 2)

```powershell
python "$SAOM_BASE/evolved/evolution-loop/engine.py" propose --task <last-task.json>
```

Generates a structured proposal:

```
Proposal: [Skill name or patch]
Problem: [Root cause]
Evidence: [Matched failure patterns]
Solution: [New skill content or patch diff]
Confidence: [High/Medium/Low]
```

The proposal is shown to the user for approval.

## Phase 4 — Evolve (run on approval)

```powershell
python "$SAOM_BASE/evolved/evolution-loop/engine.py" evolve --proposal <proposal.json>
```

- Creates new skill SKILL.md or patches existing one
- Adds graph node for new skill
- Links skill to the lessons that prompted it
- Updates skills/registry.json

## Preference Integration (NEW)

The evolution loop now integrates with the preference-learning system:

- **Observe**: After each user correction about format/style/conciseness, run `python memory/tools/preference/tool.py observe "<input>" "<output>" "<correction>"`
- **Generalize**: After 2+ similar corrections, run `python memory/tools/preference/tool.py generalize` which generates rules automatically
- **Check**: Before any task, `bridge.py pre` auto-runs `preference check` — warnings show alongside immune/failure-predict warnings
- **Evolution**: When running `engine.py propose`, query preferences.json for active rules and consider if a skill upgrade could encode the preference permanently (e.g., "always concise" → update SKILL.md core instructions)

## Trigger Conditions

The evolution loop activates automatically when:
1. A task fails with the same error as a past lesson (repeat failure)
2. 3+ tasks in the same domain have failed (domain weakness)
3. A tool-specific error occurs 2+ times (tool needs upgrade)
4. 2+ similar user corrections about format/style/output (preference learning trigger)
5. User explicitly runs: `evolution-loop run`

## Safety Gates

| Gate | Behavior |
|------|----------|
| Severity < 2 | Log lesson only, no proposal |
| Proposal confidence Low | Ask user for guidance |
| Skill patch affects active skill | Require explicit user approval |
| New tool installation | Run tool-forager first, then propose |
