---
name: cross-domain-synthesizer
description: Chains analogical-transfer, constraint-play, and debugging for novel problems
argument-hint: [problem-statement]
disable-model-invocation: true
allowed-tools: Read Write Edit Glob Grep Bash
context: fork
agent: general-purpose
shell: powershell
metadata:
  author: SAOM
  version: 2.0.0
  type: meta-skill
---

# Cross-Domain Synthesizer

Activated when: (a) task involves a novel/hard problem, (b) first approach fails, or (c) user says "think differently".

## Live Graph Context

Related skills and concepts:
```!
python "$SAOM_BASE/memory/tools/graph-query/tool.py" q2 "$DOMAIN"
```

## Pipeline

### Phase 1 — Problem Deconstruction
1. Strip domain-specific language from the problem
2. Extract the abstract structure: inputs, outputs, constraints, success criteria
3. Write the abstract form to `$SAOM_BASE/memory/working/abstract-problem.json`

### Phase 2 — Analogy Search
1. Query the SAOM graph for nodes in OTHER domains sharing structural features
2. For each candidate, ask: "Does the solution pattern from domain X apply here?"
3. Rank by structural similarity (not surface similarity)
4. Select the top candidate and load its skill
5. Present analogy:
   "[SAOM:Synthesis] Analogy: This <problem> is structurally like <past problem> from <domain>. Solution: <pattern>."

### Phase 3 — Constraint Play
1. List all explicit constraints
2. For each constraint, try:
   - Remove it: what breaks? What becomes possible?
   - Invert it: opposite constraint -> what solution emerges?
   - Exaggerate it: 10x the constraint -> what must change?
3. If a constraint-play variant works, adopt it
4. If not, restore original constraints

### Phase 4 — Multi-Path Execution
Run 2 solution paths in parallel:
- Path A: The current best approach (from Phase 2 or 3)
- Path B: The most DIFFERENT approach (opposite strategy)
Compare outputs at each step

### Phase 5 — Debug & Verify
1. If both paths agree: confidence high
2. If they diverge: isolate the divergence point
3. For each divergent step:
   - Hypothesis: "Path A is wrong because <reason>"
   - Test: verify with tool output
   - If confirmed: switch to Path B
   - If not: check assumptions, regenerate
4. Run final verification against success criteria

### Phase 6 — Cross-Domain Encoding
If the solution involved a transferable insight:
  1. Extract the general principle
  2. Write to `$SAOM_BASE/memory/working/cross-domain-insight.json`
  3. Propose adding it as a graph concept node

## Output Format
```
[SAOM:Synthesis] Problem: <abstract form>
[SAOM:Synthesis] Analogy: <from domain X>
[SAOM:Synthesis] Path A: <approach> | Path B: <opposite>
[SAOM:Synthesis] Verdict: <result> | Confidence: <high/medium/low>
[SAOM:Synthesis] Transferable: <insight if any>
```

## When NOT to use
- Routine tasks solvable by a single skill
- Tasks where domain-specific expertise > creative synthesis
- User says "just do it simply"

## Reference
See [reference.md](reference.md) for constraint play patterns and verification checklist.
