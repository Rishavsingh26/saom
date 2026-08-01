# Self-Evolution Engine Reference

## Graph Schema

Node types: session, task, skill, lesson, failure, tool, concept
Edge types: uses, caused, related_to, followed_by, similar_to, employs, produces, discovered_from

## Graph File Locations

- Nodes: `$SAOM_BASE/memory/graph/nodes.json`
- Edges: `$SAOM_BASE/memory/graph/edges.json`

## Node Template

```json
{
  "id": "<type>:<unique-name>",
  "type": "<node-type>",
  "label": "Human-readable name",
  "summary": "Brief description",
  "timestamp": "<ISO-timestamp>",
  "session_id": <N>,
  "metadata": {}
}
```

## Edge Template

```json
{
  "source_id": "<source-node-id>",
  "target_id": "<target-node-id>",
  "type": "<edge-type>",
  "weight": 1.0,
  "timestamp": "<ISO-timestamp>"
}
```

## Severity Levels

| Severity | Condition | Action |
|----------|-----------|--------|
| info | First occurrence or success | Log only |
| warning | 2nd same-domain failure | Propose patch |
| critical | 3+ same-pattern failures | Propose new skill |
