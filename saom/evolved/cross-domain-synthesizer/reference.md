# Cross-Domain Synthesizer Reference

## Constraint Play Patterns

| Pattern | Operation | Example |
|---------|-----------|---------|
| Remove | Delete the constraint entirely | "No authentication" -> public endpoint |
| Invert | Flip to opposite | "Must be fast" -> "Can be slow" |
| Exaggerate | 10x or 0.1x | "Handle 100 users" -> "Handle 100,000" |
| Substitute | Replace with different constraint | "Must use SQL" -> "Must use filesystem" |
| Merge | Combine with another constraint | "Fast + Secure" -> "Fast AND Secure (how?)" |

## Verification Checklist

- [ ] Both paths agree on output?
- [ ] Output satisfies all original constraints?
- [ ] Edge cases handled?
- [ ] No regressions in existing behavior?
- [ ] Solution is explainable in plain language?

## Common Cross-Domain Analogies

| Domain A | Domain B | Structure |
|----------|----------|-----------|
| Web auth | Physical access control | Authenticate -> authorize -> audit |
| Database indexing | Library catalog | Organize -> search -> retrieve |
| Rate limiting | Traffic management | Detect congestion -> throttle -> recover |
| State machine | Workflow pipeline | State -> transition -> action |
| Caching | Human memory | Store -> recall -> invalidate |
