"""
SAOM Library v2.0 - Complete SAOM as Python Library

All 51 SAOM tools, bridge lifecycle, model routing, semantic caching,
async support, streaming, and tool chaining.

Usage:
    from saom_lib import SAOM

    saom = SAOM()
    print(saom.chat("write a sorting function"))
    print(saom.search("python best practices"))
    print(saom.fix("my_code.py"))
    print(saom.understand("my_code.py"))

    # Bridge lifecycle
    saom.pre("build a web scraper")
    saom.post("completed web scraper", success=True)

    # Model routing
    saom.route_model("simple task")  # Uses ling-3.0-flash
    saom.route_model("complex reasoning")  # Uses mimo-v2.5

    # Tool chaining
    result = saom.chain([
        ("search", "Python async best practices"),
        ("fetch", "first result url"),
        ("understand", "the fetched content")
    ])

    # Streaming
    for chunk in saom.stream("explain async programming"):
        print(chunk, end="")
"""

import json, re, subprocess, sys, os, hashlib, time, sqlite3, threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import List, Tuple, Dict, Any, Generator, Optional, Callable
import asyncio

# ═══════════════════════════════════════════════════════════════════
# PATHS
# ═══════════════════════════════════════════════════════════════════
SAOM_BASE = Path(os.environ.get("SAOM_BASE_DIR",
    r"C:\Users\Rishav kumar\Documents\Codex\.opencode\skills\saom"))
BRIDGE_DIR = SAOM_BASE / "memory" / "bridge"
TOOLS_DIR = SAOM_BASE / "memory" / "tools"
REGISTRY_FILE = SAOM_BASE / "memory" / "tools" / "registry.json"
INIT_FILE = SAOM_BASE / "memory" / "init.json"
GRAPH_FILE = SAOM_BASE / "memory" / "graph" / "graph.json"
LESSONS_FILE = SAOM_BASE / "memory" / "lessons" / "lessons.jsonl"
SELF_FILE = BRIDGE_DIR / "self.json"
CACHE_DB = BRIDGE_DIR / "semantic_cache.db"

# ═══════════════════════════════════════════════════════════════════
# ZEN API
# ═══════════════════════════════════════════════════════════════════
ZEN_URL = "https://opencode.ai/zen/v1/chat/completions"

MODELS = {
    "mimo": "mimo-v2.5-free",
    "ling": "ling-3.0-flash-free",
    "north": "north-mini-code-free",
    "laguna": "laguna-s-2.1-free",
    "nemotron": "nemotron-3-ultra-free",
    "deepseek": "deepseek-v4-flash-free",
    "mimo-v2.5-free": "mimo-v2.5-free",
    "ling-3.0-flash-free": "ling-3.0-flash-free",
    "north-mini-code-free": "north-mini-code-free",
}

SIMPLE_TASKS = ["simple_qa", "classification", "extraction", "formatting", "greeting", "general_qa"]
CODE_TASKS = ["code_explanation", "simple_code", "code_review", "refactoring", "code_formatting"]
COMPLEX_TASKS = ["code_generation", "debugging", "architecture", "complex_reasoning", "math", "planning"]

SIMPLE_KEYWORDS = ["cache", "lookup", "format", "extract", "list", "count", "name", "what is", "hello", "hi"]
CODE_KEYWORDS = ["code", "function", "class", "def", "import", "python", "javascript", "bug", "error", "fix"]
COMPLEX_KEYWORDS = ["reason", "plan", "debug", "analyze", "predict", "architect", "design", "optimize", "research"]

SYSTEM_PROMPT = """You are SAOM, an advanced AI coding assistant built by Rishav Kumar. You help with:
- Writing, fixing, and understanding code
- Web research and analysis
- Complex reasoning and planning
- Code review and refactoring

You have tools available. Use them when needed.
Output tool calls as: [TOOL:name:argument]
Available tools: search, fetch, python, shell, read, write

Rules:
- Be concise
- For code: output only code unless asked
- For bugs: explain the fix then show corrected code
- For understanding: explain step by step"""


# ═══════════════════════════════════════════════════════════════════
# TOOL DEFINITIONS (All 51 SAOM Tools)
# ═══════════════════════════════════════════════════════════════════
TOOLS = {
    # Core
    "chat": {"desc": "Chat with SAOM", "args": "message"},
    "search": {"desc": "Web search", "args": "query"},
    "fetch": {"desc": "Fetch webpage", "args": "url"},
    "python": {"desc": "Run Python code", "args": "code"},
    "shell": {"desc": "Run shell command", "args": "command"},
    "read": {"desc": "Read file", "args": "path"},
    "write": {"desc": "Write file", "args": "path,content"},
    # Code
    "write_code": {"desc": "Write code from description", "args": "description"},
    "fix_bug": {"desc": "Fix bugs in code", "args": "code,error"},
    "understand": {"desc": "Explain what code does", "args": "code_or_path"},
    "review": {"desc": "Review code for issues", "args": "code_or_path"},
    "refactor": {"desc": "Refactor code", "args": "code_or_path"},
    "explain": {"desc": "Explain code simply", "args": "code_or_path"},
    # Bridge
    "pre": {"desc": "Pre-task analysis", "args": "task"},
    "post": {"desc": "Post-task recording", "args": "summary,success"},
    "pulse": {"desc": "Session lifecycle", "args": "mode"},
    "status": {"desc": "System status", "args": ""},
    "init": {"desc": "Initialize memory", "args": ""},
    # SAOM Tools
    "confidence": {"desc": "Get confidence score", "args": "task"},
    "failure-predict": {"desc": "Predict failure risk", "args": "task"},
    "immune": {"desc": "Immune system detect", "args": "task"},
    "lesson-extractor": {"desc": "Extract lessons", "args": "outcome"},
    "graph-query": {"desc": "Query knowledge graph", "args": "query"},
    "skill-tracker": {"desc": "Track skill usage", "args": "skill"},
    "plasticity": {"desc": "Update edge weights", "args": "edge,strength"},
    "curriculum": {"desc": "Check curriculum", "args": "topic"},
    "self-modify": {"desc": "Self-modify system", "args": "pattern"},
    "task-decomposer": {"desc": "Decompose task", "args": "goal"},
    "file-map": {"desc": "Map files", "args": "mode"},
    "vault": {"desc": "Secure vault", "args": "operation"},
    "hypothesis-test": {"desc": "Test hypothesis", "args": "hypothesis"},
    "playbook-synth": {"desc": "Create playbook", "args": "task"},
    "counterfactual": {"desc": "What-if analysis", "args": "scenario"},
    "metacognitive-reflector": {"desc": "Reflect on outcome", "args": "outcome"},
    "experience-abstraction": {"desc": "Extract mechanisms", "args": "experience"},
    "trajectory-rectifier": {"desc": "Detect dead-ends", "args": "trajectory"},
    "math-solver": {"desc": "Solve math", "args": "problem"},
    "coding-decoder": {"desc": "Coding-decoding", "args": "problem"},
    "blood-relations": {"desc": "Blood relations", "args": "problem"},
    "syllogisms": {"desc": "Syllogism solver", "args": "problem"},
    "data-sufficiency": {"desc": "Data sufficiency", "args": "problem"},
    "web-forager": {"desc": "Discover skills", "args": "query"},
    "composer": {"desc": "Compose tools", "args": "task"},
    "consolidate": {"desc": "Consolidate lessons", "args": "mode"},
    "saom-health": {"desc": "Health check", "args": ""},
    "skill-crystallizer": {"desc": "Crystallize skills", "args": "pattern"},
    "tool-weaver": {"desc": "Create tools", "args": "spec"},
    "session-files": {"desc": "Track files", "args": "mode"},
    "self-improve": {"desc": "Self-improve", "args": "mode"},
    "reasoning-mcts": {"desc": "MCTS reasoning", "args": "problem"},
    "preference": {"desc": "Check preferences", "args": "task"},
    "job-tracker": {"desc": "Job tracker", "args": "operation"},
    # Meta
    "chain": {"desc": "Chain multiple tools", "args": "steps"},
    "batch": {"desc": "Batch execute", "args": "operations"},
}


class SAOM:
    """SAOM AI assistant as a Python library - All 51 tools included."""

    def __init__(self, model: str = None, api_key: str = "public",
                 auto_route: bool = True, cache_enabled: bool = True):
        self.model = model or "mimo-v2.5-free"
        self.api_key = api_key
        self.auto_route = auto_route
        self.cache_enabled = cache_enabled
        self.history: List[Dict] = []
        self.session_id = f"lib_{int(time.time())}"
        self._cache = {}
        self._cache_ttl = {}
        self._executor = ThreadPoolExecutor(max_workers=4)

    # ═══════════════════════════════════════════════════════════════
    # CORE LLM
    # ═══════════════════════════════════════════════════════════════
    def _call_llm(self, messages: List[Dict], model: str = None,
                  max_tokens: int = 2000, temperature: float = 0.3) -> str:
        """Call Zen API with automatic model routing."""
        import requests
        m = model or self.model
        resp = requests.post(
            ZEN_URL,
            json={"model": m, "messages": messages, "max_tokens": max_tokens,
                  "temperature": temperature, "apiKey": self.api_key},
            headers={"Content-Type": "application/json", "User-Agent": "SAOM-Lib/2.0"},
            timeout=60
        )
        result = resp.json()
        if "error" in result:
            return f"Error: {result['error']}"
        return result["choices"][0]["message"]["content"]

    def _route_model(self, task: str) -> str:
        """Route to best model based on task complexity."""
        task_lower = task.lower()
        if any(k in task_lower for k in COMPLEX_KEYWORDS):
            return "mimo-v2.5-free"
        elif any(k in task_lower for k in CODE_KEYWORDS):
            return "north-mini-code-free"
        else:
            return "ling-3.0-flash-free"

    # ═══════════════════════════════════════════════════════════════
    # CHAT
    # ═══════════════════════════════════════════════════════════════
    def chat(self, message: str, context: str = None,
             model: str = None, max_tokens: int = 2000) -> str:
        """Chat with SAOM."""
        m = self._route_model(message) if self.auto_route else (model or self.model)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if context:
            messages.append({"role": "system", "content": f"Context: {context}"})
        for h in self.history[-10:]:
            messages.append(h)
        messages.append({"role": "user", "content": message})
        reply = self._call_llm(messages, model=m, max_tokens=max_tokens)
        self.history.append({"role": "user", "content": message})
        self.history.append({"role": "assistant", "content": reply})
        return reply

    def stream(self, message: str, model: str = None,
               max_tokens: int = 2000) -> Generator[str, None, None]:
        """Stream response token by token."""
        import requests
        m = self._route_model(message) if self.auto_route else (model or self.model)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for h in self.history[-10:]:
            messages.append(h)
        messages.append({"role": "user", "content": message})
        resp = requests.post(
            ZEN_URL,
            json={"model": m, "messages": messages, "max_tokens": max_tokens,
                  "temperature": 0.3, "apiKey": self.api_key, "stream": True},
            headers={"Content-Type": "application/json", "User-Agent": "SAOM-Lib/2.0"},
            stream=True, timeout=60
        )
        full = ""
        for line in resp.iter_lines():
            if line:
                line = line.decode("utf-8", errors="replace")
                if line.startswith("data: ") and line != "data: [DONE]":
                    try:
                        chunk = json.loads(line[6:])
                        token = chunk["choices"][0]["delta"].get("content", "")
                        if token:
                            full += token
                            yield token
                    except:
                        pass
        self.history.append({"role": "user", "content": message})
        self.history.append({"role": "assistant", "content": full})

    # ═══════════════════════════════════════════════════════════════
    # WEB TOOLS
    # ═══════════════════════════════════════════════════════════════
    def search(self, query: str, max_results: int = 5) -> str:
        """Web search using DuckDuckGo."""
        try:
            from ddgs import DDGS
            results = DDGS().text(query, max_results=max_results)
            formatted = []
            for r in results:
                formatted.append(f"{r.get('title', '')}\n{r.get('body', '')}\n{r.get('href', '')}")
            return "\n\n".join(formatted)
        except Exception as e:
            return f"Search error: {e}"

    def fetch(self, url: str, max_chars: int = 5000) -> str:
        """Fetch and read a webpage."""
        import requests
        r = requests.get(url, headers={"User-Agent": "SAOM/2.0"}, timeout=15)
        content = re.sub(r'<[^>]+>', ' ', r.text)
        content = re.sub(r'\s+', ' ', content).strip()
        return content[:max_chars]

    # ═══════════════════════════════════════════════════════════════
    # CODE EXECUTION
    # ═══════════════════════════════════════════════════════════════
    def python(self, code: str, timeout: int = 30) -> str:
        """Run Python code."""
        r = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=timeout
        )
        return r.stdout or r.stderr

    def shell(self, command: str, timeout: int = 30) -> str:
        """Run shell command."""
        r = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.stdout or r.stderr

    # ═══════════════════════════════════════════════════════════════
    # FILE OPERATIONS
    # ═══════════════════════════════════════════════════════════════
    def read_file(self, path: str) -> str:
        """Read a file."""
        return Path(path).read_text(encoding="utf-8", errors="replace")

    def write_file(self, path: str, content: str) -> str:
        """Write to a file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Written {len(content)} bytes to {path}"

    # ═══════════════════════════════════════════════════════════════
    # CODE INTELLIGENCE
    # ═══════════════════════════════════════════════════════════════
    def write_code(self, description: str) -> str:
        """Write code from description."""
        return self.chat(f"Write Python code for: {description}\n\nOutput only the code.")

    def fix_bug(self, code_or_path: str, error_msg: str = None) -> str:
        """Fix bugs in code."""
        code = self._load_code(code_or_path)
        prompt = f"Fix the bugs in this code:\n\n{code}"
        if error_msg:
            prompt += f"\n\nError: {error_msg}"
        return self.chat(prompt)

    def understand(self, code_or_path: str) -> str:
        """Understand what code does."""
        code = self._load_code(code_or_path)
        return self.chat(f"Explain this code step by step:\n\n{code}")

    def review(self, code_or_path: str) -> str:
        """Review code for issues."""
        code = self._load_code(code_or_path)
        return self.chat(f"Review this code for bugs, performance, and improvements:\n\n{code}")

    def refactor(self, code_or_path: str) -> str:
        """Refactor code."""
        code = self._load_code(code_or_path)
        return self.chat(f"Refactor this code to be cleaner:\n\n{code}")

    def explain(self, code_or_path: str) -> str:
        """Explain code simply."""
        code = self._load_code(code_or_path)
        return self.chat(f"Explain this code simply:\n\n{code}")

    def _load_code(self, code_or_path: str) -> str:
        """Load code from file or use as-is."""
        if Path(code_or_path).exists():
            return self.read_file(code_or_path)
        return code_or_path

    # ═══════════════════════════════════════════════════════════════
    # BRIDGE LIFECYCLE (pre/post/pulse)
    # ═══════════════════════════════════════════════════════════════
    def pre(self, task: str) -> Dict:
        """Pre-task analysis pipeline."""
        return self._run_bridge("pre", task)

    def post(self, summary: str, success: bool = True) -> Dict:
        """Post-task recording pipeline."""
        return self._run_bridge("post", summary, "success" if success else "failure")

    def pulse(self, mode: str = "status", summary: str = "") -> Dict:
        """Session lifecycle management."""
        return self._run_bridge("pulse", mode, summary)

    def decide(self, decision: str, alternatives: List[str] = None) -> Dict:
        """Record a decision."""
        return self._run_bridge("decide", decision, json.dumps(alternatives or []))

    def _run_bridge(self, command: str, *args) -> Dict:
        """Run bridge script."""
        bridge_py = BRIDGE_DIR / "bridge.py"
        pulse_py = BRIDGE_DIR / "pulse.py"
        if command == "pulse":
            cmd = [sys.executable, str(pulse_py)] + list(args)
        else:
            cmd = [sys.executable, str(bridge_py), command] + list(args)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        try:
            return json.loads(r.stdout)
        except:
            return {"raw": r.stdout, "error": r.stderr}

    # ═══════════════════════════════════════════════════════════════
    # SAOM TOOLS (All 51)
    # ═══════════════════════════════════════════════════════════════
    def run_tool(self, tool_name: str, *args) -> str:
        """Run any SAOM tool by name."""
        tool_map = {
            "chat": lambda *a: self.chat(*a),
            "search": lambda *a: self.search(*a),
            "fetch": lambda *a: self.fetch(*a),
            "python": lambda *a: self.python(*a),
            "shell": lambda *a: self.shell(*a),
            "read": lambda *a: self.read_file(*a),
            "write": lambda *a: self.write_file(*a),
            "write_code": lambda *a: self.write_code(*a),
            "fix_bug": lambda *a: self.fix_bug(*a),
            "understand": lambda *a: self.understand(*a),
            "review": lambda *a: self.review(*a),
            "refactor": lambda *a: self.refactor(*a),
            "explain": lambda *a: self.explain(*a),
            "pre": lambda *a: self.pre(*a),
            "post": lambda *a: self.post(*a),
            "pulse": lambda *a: self.pulse(*a),
            "status": lambda *a: self.get_status(),
            "init": lambda *a: self._run_bridge("init"),
            "confidence": lambda *a: self._tool_confidence(*a),
            "failure-predict": lambda *a: self._tool_failure_predict(*a),
            "immune": lambda *a: self._tool_immune(*a),
            "lesson-extractor": lambda *a: self._tool_lesson_extractor(*a),
            "graph-query": lambda *a: self._tool_graph_query(*a),
            "skill-tracker": lambda *a: self._tool_skill_tracker(*a),
            "plasticity": lambda *a: self._tool_plasticity(*a),
            "curriculum": lambda *a: self._tool_curriculum(*a),
            "self-modify": lambda *a: self._tool_self_modify(*a),
            "task-decomposer": lambda *a: self._tool_task_decomposer(*a),
            "file-map": lambda *a: self._tool_file_map(*a),
            "vault": lambda *a: self._tool_vault(*a),
            "hypothesis-test": lambda *a: self._tool_hypothesis_test(*a),
            "playbook-synth": lambda *a: self._tool_playbook_synth(*a),
            "counterfactual": lambda *a: self._tool_counterfactual(*a),
            "metacognitive-reflector": lambda *a: self._tool_metacognitive_reflector(*a),
            "experience-abstraction": lambda *a: self._tool_experience_abstraction(*a),
            "trajectory-rectifier": lambda *a: self._tool_trajectory_rectifier(*a),
            "math-solver": lambda *a: self._tool_math_solver(*a),
            "coding-decoder": lambda *a: self._tool_coding_decoder(*a),
            "blood-relations": lambda *a: self._tool_blood_relations(*a),
            "syllogisms": lambda *a: self._tool_syllogisms(*a),
            "data-sufficiency": lambda *a: self._tool_data_sufficiency(*a),
            "web-forager": lambda *a: self._tool_web_forager(*a),
            "composer": lambda *a: self._tool_composer(*a),
            "consolidate": lambda *a: self._tool_consolidate(*a),
            "saom-health": lambda *a: self._tool_saom_health(),
            "skill-crystallizer": lambda *a: self._tool_skill_crystallizer(*a),
            "tool-weaver": lambda *a: self._tool_tool_weaver(*a),
            "session-files": lambda *a: self._tool_session_files(*a),
            "self-improve": lambda *a: self._tool_self_improve(*a),
            "reasoning-mcts": lambda *a: self._tool_reasoning_mcts(*a),
            "preference": lambda *a: self._tool_preference(*a),
            "job-tracker": lambda *a: self._tool_job_tracker(*a),
        }
        if tool_name in tool_map:
            return tool_map[tool_name](*args)
        return self._run_tool_script(tool_name, *args)

    def _run_tool_script(self, tool_name: str, *args) -> str:
        """Run tool from registry."""
        tool_dir = TOOLS_DIR / tool_name
        tool_py = tool_dir / "tool.py"
        if tool_py.exists():
            cmd = [sys.executable, str(tool_py)] + list(args)
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            return r.stdout or r.stderr
        return f"Tool {tool_name} not found"

    def _tool_confidence(self, task: str = "") -> str:
        return self._run_tool_script("confidence", task)

    def _tool_failure_predict(self, task: str = "") -> str:
        return self._run_tool_script("failure-predict", task)

    def _tool_immune(self, task: str = "") -> str:
        return self._run_tool_script("immune", "detect", task)

    def _tool_lesson_extractor(self, outcome: str = "") -> str:
        return self._run_tool_script("lesson-extractor", "extract", outcome)

    def _tool_graph_query(self, query: str = "") -> str:
        return self._run_tool_script("graph-query", query)

    def _tool_skill_tracker(self, skill: str = "") -> str:
        return self._run_tool_script("skill-tracker", "record", skill)

    def _tool_plasticity(self, edge: str = "", strength: str = "") -> str:
        return self._run_tool_script("plasticity", "strengthen-type", edge)

    def _tool_curriculum(self, topic: str = "") -> str:
        return self._run_tool_script("curriculum", "status")

    def _tool_self_modify(self, pattern: str = "") -> str:
        return self._run_tool_script("self-modify", "scan")

    def _tool_task_decomposer(self, goal: str = "") -> str:
        return self._run_tool_script("task-decomposer", "decompose", goal)

    def _tool_file_map(self, mode: str = "build") -> str:
        return self._run_tool_script("file-map", mode)

    def _tool_vault(self, operation: str = "list") -> str:
        return self._run_tool_script("vault", operation)

    def _tool_hypothesis_test(self, hypothesis: str = "") -> str:
        return self._run_tool_script("hypothesis-test", "test", hypothesis)

    def _tool_playbook_synth(self, task: str = "") -> str:
        return self._run_tool_script("playbook-synth", "create", task)

    def _tool_counterfactual(self, scenario: str = "") -> str:
        return self._run_tool_script("counterfactual", "explore", scenario)

    def _tool_metacognitive_reflector(self, outcome: str = "") -> str:
        return self._run_tool_script("metacognitive-reflector", "reflect", outcome)

    def _tool_experience_abstraction(self, experience: str = "") -> str:
        return self._run_tool_script("experience-abstraction", "extract", experience)

    def _tool_trajectory_rectifier(self, trajectory: str = "") -> str:
        return self._run_tool_script("trajectory-rectifier", "detect", trajectory)

    def _tool_math_solver(self, problem: str = "") -> str:
        return self._run_tool_script("math-solver", "solve", problem)

    def _tool_coding_decoder(self, problem: str = "") -> str:
        return self._run_tool_script("coding-decoder", "decode", problem)

    def _tool_blood_relations(self, problem: str = "") -> str:
        return self._run_tool_script("blood-relations", "build", problem)

    def _tool_syllogisms(self, problem: str = "") -> str:
        return self._run_tool_script("syllogisms", "check", problem)

    def _tool_data_sufficiency(self, problem: str = "") -> str:
        return self._run_tool_script("data-sufficiency", "evaluate", problem)

    def _tool_web_forager(self, query: str = "") -> str:
        return self._run_tool_script("web-forager", "search", query)

    def _tool_composer(self, task: str = "") -> str:
        return self._run_tool_script("composer", "find", task)

    def _tool_consolidate(self, mode: str = "scan") -> str:
        return self._run_tool_script("consolidate", mode)

    def _tool_saom_health(self) -> str:
        return self._run_tool_script("saom-health")

    def _tool_skill_crystallizer(self, pattern: str = "") -> str:
        return self._run_tool_script("skill-crystallizer", "crystallize", pattern)

    def _tool_tool_weaver(self, spec: str = "") -> str:
        return self._run_tool_script("tool-weaver", "weave", spec)

    def _tool_session_files(self, mode: str = "summary") -> str:
        return self._run_tool_script("session-files", mode)

    def _tool_self_improve(self, mode: str = "health") -> str:
        return self._run_tool_script("self-improve", mode)

    def _tool_reasoning_mcts(self, problem: str = "") -> str:
        return self._run_tool_script("reasoning-mcts", "solve", problem)

    def _tool_preference(self, task: str = "") -> str:
        return self._run_tool_script("preference", "check", task)

    def _tool_job_tracker(self, operation: str = "status") -> str:
        return self._run_tool_script("job-tracker", operation)

    # ═══════════════════════════════════════════════════════════════
    # TOOL CHAINING
    # ═══════════════════════════════════════════════════════════════
    def chain(self, steps: List[Tuple[str, str]]) -> List[str]:
        """Chain multiple tools sequentially. Each step gets previous result."""
        results = []
        prev_result = ""
        for tool_name, arg in steps:
            if arg == "{prev}":
                arg = prev_result
            result = self.run_tool(tool_name, arg)
            results.append(result)
            prev_result = result
        return results

    def parallel(self, operations: List[Tuple[str, str]]) -> List[str]:
        """Run multiple tools in parallel."""
        futures = []
        for tool_name, arg in operations:
            futures.append(self._executor.submit(self.run_tool, tool_name, arg))
        return [f.result() for f in futures]

    # ═══════════════════════════════════════════════════════════════
    # SEMANTIC CACHE
    # ═══════════════════════════════════════════════════════════════
    def cache_get(self, prompt: str) -> Optional[str]:
        """Get from cache."""
        if not self.cache_enabled:
            return None
        key = hashlib.sha256(prompt.encode()).hexdigest()[:32]
        if key in self._cache:
            if time.time() - self._cache_ttl[key] < 3600:
                return self._cache[key]
            del self._cache[key]
        return None

    def cache_set(self, prompt: str, response: str):
        """Set cache."""
        if not self.cache_enabled:
            return
        key = hashlib.sha256(prompt.encode()).hexdigest()[:32]
        self._cache[key] = response
        self._cache_ttl[key] = time.time()

    # ═══════════════════════════════════════════════════════════════
    # GRAPH QUERIES
    # ═══════════════════════════════════════════════════════════════
    def get_graph(self) -> Dict:
        """Get knowledge graph."""
        if GRAPH_FILE.exists():
            return json.loads(GRAPH_FILE.read_text())
        return {"nodes": [], "edges": []}

    def get_lessons(self) -> List[Dict]:
        """Get all lessons."""
        lessons = []
        if LESSONS_FILE.exists():
            for line in LESSONS_FILE.read_text().split("\n"):
                if line.strip():
                    try:
                        lessons.append(json.loads(line))
                    except:
                        pass
        return lessons

    def get_registry(self) -> Dict:
        """Get tool registry."""
        if REGISTRY_FILE.exists():
            return json.loads(REGISTRY_FILE.read_text())
        return {}

    def get_status(self) -> Dict:
        """Get system status."""
        return self._run_bridge("pulse", "status")

    # ═══════════════════════════════════════════════════════════════
    # ASYNC SUPPORT
    # ═══════════════════════════════════════════════════════════════
    async def achat(self, message: str, model: str = None) -> str:
        """Async chat."""
        import aiohttp
        m = self._route_model(message) if self.auto_route else (model or self.model)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for h in self.history[-10:]:
            messages.append(h)
        messages.append({"role": "user", "content": message})
        async with aiohttp.ClientSession() as session:
            async with session.post(
                ZEN_URL,
                json={"model": m, "messages": messages, "max_tokens": 2000,
                      "temperature": 0.3, "apiKey": self.api_key},
                headers={"Content-Type": "application/json", "User-Agent": "SAOM-Lib/2.0"}
            ) as resp:
                result = await resp.json()
                reply = result["choices"][0]["message"]["content"]
                self.history.append({"role": "user", "content": message})
                self.history.append({"role": "assistant", "content": reply})
                return reply

    async def asearch(self, query: str) -> str:
        """Async search."""
        import aiohttp
        try:
            from ddgs import DDGS
            results = DDGS().text(query, max_results=5)
            return "\n\n".join([f"{r.get('title','')}\n{r.get('body','')}" for r in results])
        except Exception as e:
            return f"Search error: {e}"

    async def afetch(self, url: str) -> str:
        """Async fetch."""
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers={"User-Agent": "SAOM/2.0"}) as resp:
                text = await resp.text()
                content = re.sub(r'<[^>]+>', ' ', text)
                return re.sub(r'\s+', ' ', content).strip()[:5000]


# ═══════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════
def chat(message: str, **kwargs) -> str:
    return SAOM(**kwargs).chat(message)

def search(query: str, **kwargs) -> str:
    return SAOM(**kwargs).search(query)

def fix(code_or_path: str, error: str = None, **kwargs) -> str:
    return SAOM(**kwargs).fix_bug(code_or_path, error)

def understand(code_or_path: str, **kwargs) -> str:
    return SAOM(**kwargs).understand(code_or_path)

def write_code(description: str, **kwargs) -> str:
    return SAOM(**kwargs).write_code(description)

def review(code_or_path: str, **kwargs) -> str:
    return SAOM(**kwargs).review(code_or_path)
