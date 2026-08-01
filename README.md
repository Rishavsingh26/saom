# SAOM — Super Agent Ouroboros Manager

A self-improving cognitive architecture for LLM agents. SAOM gives AI agents structured memory, tool dispatch, confidence calibration, failure prediction, immune system (recurring failure detection), skill crystallization, session continuity, and autonomous self-modification.

## Quick Start

```bash
pip install -r requirements.txt
set LLM_API_KEY=sk-...   # or set OPENAI_API_KEY
set LLM_MODEL=gpt-4o     # default; any OpenAI-compatible model
set LLM_BASE_URL=https://api.openai.com/v1  # default
python -m saom init      # create fresh memory directory
python -m saom status    # verify it works
```

## Usage

### System status
```bash
python -m saom status
```

### Initialize memory (wipes all runtime data — privacy-safe)
```bash
python -m saom init
```
Creates fresh memory directory at `~/.saom/memory/`. Prompts before wiping existing data. No session history, preferences, or learned patterns are ever committed to Git.

### Session lifecycle
```bash
python -m saom pulse start
python -m saom pulse status
python -m saom pulse end "Session summary"
```

### Pre-task checks (immune + failure prediction + preference)
```bash
python -m saom pre "Implement user authentication"
```

### Post-task processing (lesson extraction + plasticity update)
```bash
python -m saom post "Added login endpoint" success
python -m saom post "Auth failed" failure
```

### Run a tool directly
```bash
python -m saom run status
python -m saom run task-decomposer decompose "Build a recommendation system"
python -m saom run vault list
python -m saom run skill-crystallizer list
```

### LLM-powered agent (autonomous tool orchestration)
```bash
python -m saom agent "Analyze the codebase and suggest improvements"
```

## Architecture

```
saom/
├── cli.py              # CLI entry point
├── agent.py            # LLM-powered tool orchestrator
├── bridge.py           # Pre/post task processing
├── pulse.py            # Session lifecycle management
├── config.py           # Env-var-based configuration
├── memory/             # Persistent state (tools + data)
│   ├── tools/          # 21 tool modules
│   │   ├── confidence/
│   │   ├── consolidate/
│   │   ├── continuity/
│   │   ├── curriculum/
│   │   ├── failure-predict/
│   │   ├── failure-query/
│   │   ├── graph-query/
│   │   ├── immune/
│   │   ├── lesson-extractor/
│   │   ├── plasticity/
│   │   ├── preference/
│   │   ├── saom-health/
│   │   ├── self-modify/
│   │   ├── session-files/
│   │   ├── skill-crystallizer/
│   │   ├── skill-tracker/
│   │   ├── status/
│   │   ├── task-decomposer/
│   │   ├── tool-weaver/
│   │   ├── vault/
│   │   └── web-forager/
│   ├── bridge/         # Runtime data (self.json, preferences.json)
│   ├── graph/          # Graph memory database
│   ├── lessons/        # Lesson database
│   ├── skills/         # Crystallized skills
│   ├── sessions/       # Session archives
│   ├── vault/          # Masked secret storage
│   └── ...
└── evolved/            # Self-evolution components
    ├── evolution-loop/
    ├── cross-domain-synthesizer/
    └── self-evolution-engine/
```

## Configuration (Environment Variables)

| Variable | Default | Description |
|---|---|---|
| `LLM_API_KEY` | — | API key (falls back to `OPENAI_API_KEY`) |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible API base |
| `LLM_MODEL` | `gpt-4o` | Model name |
| `SAOM_MEMORY_DIR` | `~/.saom/memory` | Custom memory directory |

## Tools Overview

| Tool | Description |
|---|---|
| `confidence` | Scores predictions 0-100% with calibration |
| `consolidate` | Consolidates short-term memory to long-term |
| `continuity` | Cross-session context injection |
| `curriculum` | Structured skill tree with prerequisites |
| `failure-predict` | Meta-predictor combining 5 risk signals |
| `failure-query` | Query past failures by pattern |
| `graph-query` | Multi-dimensional graph queries |
| `immune` | Adaptive failure pattern detection |
| `lesson-extractor` | Structured lesson extraction from outcomes |
| `plasticity` | Dynamic edge weight adjustment |
| `preference` | Observes corrections, generalizes rules |
| `saom-health` | Contrarian memory health checker |
| `self-modify` | Proposes patches to own behavior |
| `session-files` | Per-session file change tracking |
| `skill-crystallizer` | Creates reusable skills from protocols |
| `skill-tracker` | Usage/success tracking with prune logic |
| `status` | One-shot system summary |
| `task-decomposer` | Splits goals into sub-task DAGs |
| `tool-weaver` | Chains tools into pipelines |
| `vault` | Masked secret storage |
| `web-forager` | Autonomous web skill discovery |

## Privacy & Data Safety

SAOM stores session history, extracted lessons, preference rules, and graph embeddings in `~/.saom/memory/`. This directory is excluded from the repository via `.gitignore` — **no runtime data leaks into Git**.

The repository ships with **empty memory defaults** (no session history, no preferences, no API keys). All 21 tool source files are safe to commit.

**Before sharing or publishing your SAOM instance:**
1. Run `python -m saom init` to wipe all learned patterns and session data
2. Check `~/.saom/memory/vault/` for any stored secrets
3. Verify no `.env` files are present

## License

MIT
