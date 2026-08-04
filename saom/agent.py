import json, os, subprocess, sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from saom.config import llm_config, get_memory_dir, ensure_memory


# ─── SAOMAgent: Self-Improving Agent with Meta-Cognitive Brain ────────────────

class SAOMAgent:
    """Self-improving agent with adaptive learning and meta-cognitive monitoring.

    Features:
        - Adaptive learning: Adjusts learning rate based on task domain
        - Meta-cognitive monitoring: Tracks thinking quality in real-time
        - Causal reasoning: Builds models of why things succeed/fail
        - Uncertainty quantification: Knows what it doesn't know

    Usage:
        agent = SAOMAgent()
        result = agent.pre("implement feature X")
        agent.post("implemented feature X", success=True)
    """

    def __init__(self, memory_dir: Optional[str] = None):
        if memory_dir is None:
            memory_dir = str(get_memory_dir())
        self.memory_dir = os.path.abspath(memory_dir)
        ensure_memory()

        self.state_path = os.path.join(self.memory_dir, "bridge", "self.json")
        self.state = self._load_state()

        from saom.core.agent import (
            AdaptiveLearningRate, MetaCognitiveMonitor,
            CausalReasoningEngine, UncertaintyQuantifier,
        )
        self._learning_rate = AdaptiveLearningRate(self.memory_dir)
        self._meta_cognitive = MetaCognitiveMonitor(self.memory_dir)
        self._causal_engine = CausalReasoningEngine(self.memory_dir)
        self._uncertainty = UncertaintyQuantifier(self.memory_dir)

    def _load_state(self) -> Dict[str, Any]:
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"mode": "idle", "confidence": 0.5, "goal": None, "warnings": [], "decision_history": []}

    def _save_state(self):
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2)
        os.replace(tmp, self.state_path)

    def pre(self, task_desc: str, approach: Optional[str] = None) -> Dict[str, Any]:
        meta = self._meta_cognitive.assess_task(task_desc)
        causal = self._causal_engine.predict(task_desc, approach)
        uncertainty = self._uncertainty.quantify(task_desc)
        learning_rate = self._learning_rate.get_rate(task_desc)
        verdict = self._combine_verdicts(meta, causal, uncertainty)

        result = {
            "verdict": verdict["verdict"], "confidence": verdict["confidence"],
            "reasoning": verdict["reasoning"], "warnings": verdict.get("warnings", []),
            "learning_rate": learning_rate, "uncertainty": uncertainty,
            "meta_assessment": meta, "causal_prediction": causal,
        }

        self.state["mode"] = "active"
        self.state["confidence"] = result["confidence"]
        self.state["goal"] = task_desc
        self.state["warnings"] = result["warnings"]
        self.state["decision_history"].append({
            "timestamp": datetime.utcnow().isoformat(),
            "task": task_desc[:200], "verdict": result["verdict"],
            "confidence": result["confidence"],
        })
        self._save_state()
        return result

    def post(self, summary: str, success: bool, session_id: Optional[int] = None) -> Dict[str, Any]:
        self._causal_engine.record_outcome(summary, success)
        self._learning_rate.update(success)
        reflection = self._meta_cognitive.reflect(summary, success)

        self.state["mode"] = "idle"
        self.state["confidence"] = 0.5
        self.state["goal"] = None
        self._save_state()

        return {
            "success": success, "learning_rate": self._learning_rate.current_rate,
            "reflection": reflection, "causal_edges_updated": self._causal_engine.edges_updated,
        }

    def _combine_verdicts(self, meta, causal, uncertainty):
        signals = []
        if meta.get("quality_score", 0.5) < 0.3: signals.append(("meta_low", 0.3))
        elif meta.get("quality_score", 0.5) > 0.7: signals.append(("meta_high", 0.7))
        if causal.get("predicted_success", 0.5) < 0.3: signals.append(("causal_low", 0.3))
        elif causal.get("predicted_success", 0.5) > 0.7: signals.append(("causal_high", 0.7))
        if uncertainty.get("gap_count", 0) > 3: signals.append(("uncertain", 0.3))

        if not signals:
            return {"verdict": "LOW_RISK", "confidence": 0.6, "reasoning": "No strong signals"}

        avg = sum(s[1] for s in signals) / len(signals)
        if avg < 0.3: v = "WILL_FAIL"
        elif avg < 0.5: v = "HIGH_RISK"
        elif avg < 0.7: v = "CAUTION"
        else: v = "LIKELY_SUCCEED"

        return {"verdict": v, "confidence": avg, "reasoning": "Signals: %s" % ", ".join(s[0] for s in signals)}


# ─── Legacy: LLM-powered agent with tool calling ─────────────────────────────

def _discover_tools(base):
    tools_dir = base / "memory" / "tools"
    registry = tools_dir / "registry.json"
    if registry.exists():
        with open(registry) as f:
            data = json.load(f)
            return data if isinstance(data, list) else data.get("tools", [])
    discovered = []
    for d in sorted(tools_dir.iterdir()):
        if d.is_dir() and (d / "tool.py").exists():
            tj = d / "tool.json"
            if tj.exists():
                with open(tj) as f:
                    info = json.load(f)
                    discovered.append(info)
            else:
                discovered.append({"name": d.name, "description": d.name})
    return discovered


def _build_tool_schemas(tools):
    schemas = []
    for t in tools:
        name = t.get("name", "unknown")
        desc = t.get("description", "")
        trigger = t.get("trigger", {})
        keywords = trigger.get("keywords", [name])
        schemas.append({
            "type": "function",
            "function": {
                "name": f"tool_{name}",
                "description": f"{desc} [triggers: {', '.join(keywords[:5])}]",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": t.get("modes", ["status"]),
                            "description": f"Tool mode. Available: {', '.join(t.get('modes', ['status']))}",
                        },
                        "args": {
                            "type": "string",
                            "description": "Additional arguments as space-separated string",
                        },
                    },
                    "required": ["mode"],
                },
            },
        })
    return schemas


def run_agent(goal):
    cfg = llm_config()
    if not cfg["api_key"]:
        return "ERROR: LLM_API_KEY or OPENAI_API_KEY not set"

    base = Path(__file__).parent
    tools = _discover_tools(base)
    tool_schemas = _build_tool_schemas(tools)

    from openai import OpenAI
    client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])

    messages = [
        {
            "role": "system",
            "content": (
                "You are SAOM, a self-improving agent architecture. "
                "You have access to tools for memory, confidence, failure prediction, "
                "skill tracking, immune system, graph queries, and more. "
                "Analyze the user's goal and use the appropriate tools to accomplish it. "
                "When you use a tool, call it via function calling, then interpret the result."
            ),
        },
        {"role": "user", "content": goal},
    ]

    result_text = ""
    for _ in range(10):
        resp = client.chat.completions.create(
            model=cfg["model"],
            messages=messages,
            tools=tool_schemas if tool_schemas else None,
            tool_choice="auto" if tool_schemas else None,
        )
        msg = resp.choices[0].message

        if not msg.tool_calls:
            result_text = msg.content or ""
            break

        messages.append(msg)
        for tc in msg.tool_calls:
            fn = tc.function
            try:
                params = json.loads(fn.arguments)
                mode = params.get("mode", "")
                args = params.get("args", "").split()
                tool_name = fn.name.replace("tool_", "")
                result = _execute_tool(base, tool_name, mode, args)
            except Exception as e:
                result = {"error": str(e)}
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result),
            })

    else:
        result_text = "Agent reached maximum iteration limit."

    return result_text


def _execute_tool(base, tool_name, mode, args):
    tool_path = base / "memory" / "tools" / tool_name / "tool.py"
    if not tool_path.exists():
        return {"error": f"Tool '{tool_name}' not found"}
    cmd = [sys.executable, str(tool_path), mode] + args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        out = r.stdout.strip()
        try:
            return json.loads(out) if out else {"exit": r.returncode}
        except json.JSONDecodeError:
            return {"output": out[:2000], "exit": r.returncode}
    except subprocess.TimeoutExpired:
        return {"error": "tool timed out"}
    except Exception as e:
        return {"error": str(e)}
