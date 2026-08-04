"""Core SAOM subsystems: adaptive learning, meta-cognition, causal reasoning, uncertainty."""

import json
import os
from datetime import datetime
from typing import Optional, Dict, Any, List


class AdaptiveLearningRate:
    """Adjusts learning rate based on task domain and success history."""

    def __init__(self, memory_dir: str):
        self.memory_dir = memory_dir
        self.current_rate = 0.1
        self.domain_rates = {}
        self._load()

    def _load(self):
        path = os.path.join(self.memory_dir, "bridge", "learning_rates.json")
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                    self.current_rate = data.get("current_rate", 0.1)
                    self.domain_rates = data.get("domain_rates", {})
            except Exception:
                pass

    def _save(self):
        path = os.path.join(self.memory_dir, "bridge", "learning_rates.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"current_rate": self.current_rate, "domain_rates": self.domain_rates}, f, indent=2)

    def get_rate(self, task_desc: str) -> float:
        domain = self._classify_domain(task_desc)
        return self.domain_rates.get(domain, self.current_rate)

    def update(self, success: bool):
        if success:
            self.current_rate = min(0.5, self.current_rate * 1.1)
        else:
            self.current_rate = max(0.01, self.current_rate * 0.9)
        self._save()

    def _classify_domain(self, task_desc: str) -> str:
        task_lower = task_desc.lower()
        if any(w in task_lower for w in ["bug", "fix", "error", "crash"]):
            return "debugging"
        elif any(w in task_lower for w in ["feature", "add", "create", "build"]):
            return "development"
        elif any(w in task_lower for w in ["test", "verify", "validate"]):
            return "testing"
        elif any(w in task_lower for w in ["refactor", "optimize", "clean"]):
            return "maintenance"
        return "general"


class MetaCognitiveMonitor:
    """Monitors thinking quality in real-time."""

    def __init__(self, memory_dir: str):
        self.memory_dir = memory_dir
        self.assessments = []

    def assess_task(self, task_desc: str) -> Dict[str, Any]:
        words = len(task_desc.split())
        specificity = len(set(task_desc.lower().split())) / max(words, 1)
        quality_score = min(1.0, (words / 20) * 0.5 + specificity * 0.5)
        return {"quality_score": quality_score, "word_count": words, "specificity": specificity}

    def reflect(self, summary: str, success: bool) -> Dict[str, Any]:
        return {"success": success, "summary_length": len(summary.split()), "timestamp": datetime.utcnow().isoformat()}


class CausalReasoningEngine:
    """Builds causal models of why things succeed or fail."""

    def __init__(self, memory_dir: str):
        self.memory_dir = memory_dir
        self.edges_updated = 0
        self.graph = self._load_graph()

    def _load_graph(self) -> Dict:
        path = os.path.join(self.memory_dir, "bridge", "causal", "causal_graph.json")
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"nodes": [], "edges": [], "confidence": {}}

    def _save_graph(self):
        path = os.path.join(self.memory_dir, "bridge", "causal", "causal_graph.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.graph, f, indent=2)

    def predict(self, task_desc: str, approach: Optional[str] = None) -> Dict[str, Any]:
        positive = sum(1 for e in self.graph.get("edges", []) if e.get("weight", 0) > 0)
        negative = sum(1 for e in self.graph.get("edges", []) if e.get("weight", 0) < 0)
        total = positive + negative
        predicted_success = positive / total if total > 0 else 0.5
        return {"predicted_success": predicted_success, "positive_edges": positive, "negative_edges": negative}

    def record_outcome(self, summary: str, success: bool):
        edge = {
            "source": "task", "target": "outcome",
            "weight": 1.0 if success else -1.0,
            "timestamp": datetime.utcnow().isoformat(),
            "summary": summary[:200],
        }
        self.graph.setdefault("edges", []).append(edge)
        self.edges_updated += 1
        if len(self.graph["edges"]) > 100:
            self.graph["edges"] = self.graph["edges"][-100:]
        self._save_graph()


class UncertaintyQuantifier:
    """Knows what it doesn't know."""

    def __init__(self, memory_dir: str):
        self.memory_dir = memory_dir
        self.knowledge_gaps = self._load_gaps()

    def _load_gaps(self) -> List[Dict]:
        path = os.path.join(self.memory_dir, "bridge", "curiosity", "gaps.json")
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list): return data
                    elif isinstance(data, dict) and "gaps" in data: return data["gaps"]
            except Exception:
                pass
        return []

    def quantify(self, task_desc: str) -> Dict[str, Any]:
        task_words = set(task_desc.lower().split())
        related_gaps = []
        for gap in self.knowledge_gaps:
            gap_words = set(gap.get("description", "").lower().split())
            if len(task_words & gap_words) >= 2:
                related_gaps.append(gap)
        return {
            "gap_count": len(related_gaps), "gaps": related_gaps[:5],
            "confidence_penalty": min(0.3, len(related_gaps) * 0.05),
        }
