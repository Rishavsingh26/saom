"""
SAOM Library v12.0 - Python import for SAOM agent.

3-model routing: north-mini-code (free) -> gemini -> groq fallback.

Usage:
    from saom_lib import SAOM

    saom = SAOM()
    print(saom.chat("write a sorting function"))
    print(saom.fix("my_code.py"))
    print(saom.understand("my_code.py"))

    # Streaming
    for chunk in saom.stream("explain async programming"):
        print(chunk, end="")
"""

import json, re, subprocess, sys, os, hashlib, time
from pathlib import Path
from typing import List, Tuple, Dict, Any, Generator, Optional

VERSION = "12.0.0"

# ═══════════════════════════════════════════════════════════════════
# 3 PROVIDERS: north (free) -> gemini -> groq
# ═══════════════════════════════════════════════════════════════════
PROVIDERS = {
    "north": {
        "url": "https://opencode.ai/zen/v1/chat/completions",
        "format": "openai",
        "auth": "body_key",
        "model": "north-mini-code-free",
    },
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
        "format": "gemini",
        "auth": "api_key",
        "model": "gemini-3.5-flash",
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "format": "openai",
        "auth": "bearer",
        "model": "llama-3.3-70b-versatile",
    },
}

ROUTING = ["north", "gemini", "groq"]

SYSTEM_PROMPT = """You are SAOM, an AI coding assistant by Om.
- Write, fix, understand code
- Web search and analysis
- Complex reasoning and planning
Output tool calls as: [TOOL:name:argument]
Available: search, fetch, python, shell, read, write
Rules: Be concise. Code only unless asked otherwise."""

# ═══════════════════════════════════════════════════════════════════
# PATHS (cross-platform, auto-detect)
# ═══════════════════════════════════════════════════════════════════
def _find_saom_base():
    """Find SAOM base directory cross-platform."""
    env = os.environ.get("SAOM_BASE_DIR")
    if env and Path(env).exists():
        return Path(env)
    candidates = [
        Path.home() / ".saom",
        Path.cwd() / "saom_memory",
    ]
    for c in candidates:
        if c.exists():
            return c
    return Path.home() / ".saom"

SAOM_BASE = _find_saom_base()
BRIDGE_DIR = SAOM_BASE / "memory" / "bridge"
TOOLS_DIR = SAOM_BASE / "memory" / "tools"


class SAOM:
    """SAOM AI assistant - 3-model routing, streaming, tool chaining."""

    def __init__(self, model: str = None, api_key: str = "public",
                 gemini_key: str = None, groq_key: str = None,
                 auto_route: bool = True, cache_enabled: bool = True):
        self.model = model or "north-mini-code-free"
        self.api_key = api_key
        self.gemini_key = gemini_key or os.environ.get("GEMINI_API_KEY", "")
        self.groq_key = groq_key or os.environ.get("GROQ_API_KEY", "")
        self.auto_route = auto_route
        self.cache_enabled = cache_enabled
        self.history: List[Dict] = []
        self.session_id = f"lib_{int(time.time())}"
        self._cache: Dict[str, str] = {}
        self._cache_ttl: Dict[str, float] = {}
        self._failed: set = set()

    # ═══════════════════════════════════════════════════════════════
    # LLM CALLS
    # ═══════════════════════════════════════════════════════════════
    def _call_gemini(self, messages, model, api_key, max_tokens=2000):
        import requests
        url = PROVIDERS["gemini"]["url"].format(model=model, key=api_key)
        contents = []
        for m in messages:
            role = "user" if m["role"] in ("user",) else "model"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})
        r = requests.post(url, json={
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.3}
        }, headers={"Content-Type": "application/json"}, timeout=60)
        if r.status_code != 200:
            raise Exception(f"Gemini {r.status_code}")
        data = r.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()

    def _call_openai_compat(self, messages, model, api_key, url, auth_type, max_tokens=2000):
        import requests
        headers = {"Content-Type": "application/json"}
        body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.3}
        if auth_type == "bearer":
            headers["Authorization"] = f"Bearer {api_key}"
        elif auth_type == "body_key":
            body["apiKey"] = api_key or "public"
        r = requests.post(url, json=body, headers=headers, timeout=60)
        if r.status_code != 200:
            raise Exception(f"HTTP {r.status_code}")
        return r.json()["choices"][0]["message"]["content"].strip()

    def _call_llm(self, messages, max_tokens=2000, _depth=0):
        """Call LLM with north -> gemini -> groq fallback."""
        if _depth > 2:
            return "[Error] All providers failed"

        for prov_name in ROUTING:
            if prov_name in self._failed:
                continue
            prov = PROVIDERS[prov_name]
            # Check if key is needed
            if prov["auth"] == "api_key":
                key = self.gemini_key
                if not key:
                    continue
            elif prov["auth"] == "bearer":
                key = self.groq_key
                if not key:
                    continue
            else:
                key = self.api_key

            try:
                if prov["format"] == "gemini":
                    return self._call_gemini(messages, prov["model"], key, max_tokens)
                else:
                    return self._call_openai_compat(
                        messages, prov["model"], key, prov["url"], prov["auth"], max_tokens)
            except Exception as e:
                self._failed.add(prov_name)
                continue

        return "[Error] No providers available. Set GEMINI_API_KEY or GROQ_API_KEY."

    def _route_model(self, task):
        """Route by keyword (unused when auto_route uses _call_llm fallback)."""
        return task  # routing handled by _call_llm fallback chain

    # ═══════════════════════════════════════════════════════════════
    # CHAT
    # ═══════════════════════════════════════════════════════════════
    def chat(self, message: str, context: str = None,
             max_tokens: int = 2000) -> str:
        """Chat with SAOM."""
        # Check cache
        cached = self._cache_get(message)
        if cached:
            return cached

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if context:
            messages.append({"role": "system", "content": f"Context: {context}"})
        for h in self.history[-10:]:
            messages.append(h)
        messages.append({"role": "user", "content": message})

        reply = self._call_llm(messages, max_tokens)
        self.history.append({"role": "user", "content": message})
        self.history.append({"role": "assistant", "content": reply})
        self._cache_set(message, reply)
        return reply

    def stream(self, message: str, max_tokens: int = 2000) -> Generator[str, None, None]:
        """Stream response token by token."""
        import requests
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for h in self.history[-10:]:
            messages.append(h)
        messages.append({"role": "user", "content": message})

        # Try north first (free, streaming)
        for prov_name in ROUTING:
            if prov_name in self._failed:
                continue
            prov = PROVIDERS[prov_name]
            if prov["auth"] == "api_key" and not self.gemini_key:
                continue
            if prov["auth"] == "bearer" and not self.groq_key:
                continue
            key = self.api_key if prov["auth"] == "body_key" else (self.gemini_key if prov_name == "gemini" else self.groq_key)
            try:
                if prov["format"] == "gemini":
                    # Gemini doesn't stream well, fall through
                    continue
                body = {"model": prov["model"], "messages": messages, "max_tokens": max_tokens,
                        "temperature": 0.3, "apiKey": key, "stream": True}
                headers = {"Content-Type": "application/json", "User-Agent": "SAOM-Lib/12"}
                resp = requests.post(prov["url"], json=body, headers=headers, stream=True, timeout=60)
                if resp.status_code != 200:
                    continue
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
                return
            except:
                self._failed.add(prov_name)
                continue

        # Fallback: non-streaming
        yield self.chat(message, max_tokens=max_tokens)

    # ═══════════════════════════════════════════════════════════════
    # WEB TOOLS
    # ═══════════════════════════════════════════════════════════════
    def search(self, query: str, max_results: int = 5) -> str:
        """Web search using DuckDuckGo."""
        try:
            from ddgs import DDGS
            results = DDGS().text(query, max_results=max_results)
            return "\n\n".join(
                f"{r.get('title', '')}\n{r.get('body', '')}\n{r.get('href', '')}"
                for r in results
            )
        except Exception as e:
            return f"Search error: {e}"

    def fetch(self, url: str, max_chars: int = 5000) -> str:
        """Fetch and read a webpage."""
        import requests
        r = requests.get(url, headers={"User-Agent": "SAOM/12"}, timeout=15)
        content = re.sub(r'<[^>]+>', ' ', r.text)
        return re.sub(r'\s+', ' ', content).strip()[:max_chars]

    # ═══════════════════════════════════════════════════════════════
    # CODE EXECUTION
    # ═══════════════════════════════════════════════════════════════
    def python(self, code: str, timeout: int = 30) -> str:
        """Run Python code."""
        r = subprocess.run([sys.executable, "-c", code],
                          capture_output=True, text=True, timeout=timeout)
        return r.stdout or r.stderr

    def shell(self, command: str, timeout: int = 30) -> str:
        """Run shell command."""
        r = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout or r.stderr

    # ═══════════════════════════════════════════════════════════════
    # FILE OPERATIONS
    # ═══════════════════════════════════════════════════════════════
    def read_file(self, path: str) -> str:
        return Path(path).read_text(encoding="utf-8", errors="replace")

    def write_file(self, path: str, content: str) -> str:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Written {len(content)} bytes to {path}"

    # ═══════════════════════════════════════════════════════════════
    # CODE INTELLIGENCE
    # ═══════════════════════════════════════════════════════════════
    def _load_code(self, code_or_path: str) -> str:
        if Path(code_or_path).exists():
            return self.read_file(code_or_path)
        return code_or_path

    def write_code(self, description: str) -> str:
        return self.chat(f"Write Python code for: {description}\n\nOutput only the code.")

    def fix(self, code_or_path: str, error: str = None) -> str:
        code = self._load_code(code_or_path)
        prompt = f"Fix the bugs in this code:\n\n{code}"
        if error:
            prompt += f"\n\nError: {error}"
        return self.chat(prompt)

    def understand(self, code_or_path: str) -> str:
        return self.chat(f"Explain this code step by step:\n\n{self._load_code(code_or_path)}")

    def review(self, code_or_path: str) -> str:
        return self.chat(f"Review this code for bugs, performance, and improvements:\n\n{self._load_code(code_or_path)}")

    def refactor(self, code_or_path: str) -> str:
        return self.chat(f"Refactor this code to be cleaner:\n\n{self._load_code(code_or_path)}")

    # ═══════════════════════════════════════════════════════════════
    # TOOL CHAINING
    # ═══════════════════════════════════════════════════════════════
    def chain(self, steps: List[Tuple[str, str]]) -> List[str]:
        """Chain tools. Each step gets previous result with {prev}."""
        results = []
        prev = ""
        for tool, arg in steps:
            if arg == "{prev}":
                arg = prev
            fn = getattr(self, tool, None)
            result = fn(arg) if fn else f"Unknown tool: {tool}"
            results.append(result)
            prev = result
        return results

    # ═══════════════════════════════════════════════════════════════
    # CACHE
    # ═══════════════════════════════════════════════════════════════
    def _cache_get(self, prompt):
        if not self.cache_enabled:
            return None
        key = hashlib.sha256(prompt.encode()).hexdigest()[:32]
        if key in self._cache:
            if time.time() - self._cache_ttl.get(key, 0) < 3600:
                return self._cache[key]
            del self._cache[key]
        return None

    def _cache_set(self, prompt, response):
        if not self.cache_enabled:
            return
        key = hashlib.sha256(prompt.encode()).hexdigest()[:32]
        self._cache[key] = response
        self._cache_ttl[key] = time.time()

    # ═══════════════════════════════════════════════════════════════
    # CONVENIENCE
    # ═══════════════════════════════════════════════════════════════
    def get_status(self) -> Dict:
        return {"version": VERSION, "session": self.session_id,
                "history_len": len(self.history), "failed": list(self._failed)}


# ═══════════════════════════════════════════════════════════════════
# MODULE-LEVEL CONVENIENCE
# ═══════════════════════════════════════════════════════════════════
def chat(message, **kw):
    return SAOM(**kw).chat(message)

def search(query, **kw):
    return SAOM(**kw).search(query)

def fix(code_or_path, error=None, **kw):
    return SAOM(**kw).fix(code_or_path, error)

def understand(code_or_path, **kw):
    return SAOM(**kw).understand(code_or_path)

def write_code(desc, **kw):
    return SAOM(**kw).write_code(desc)

def review(code_or_path, **kw):
    return SAOM(**kw).review(code_or_path)
