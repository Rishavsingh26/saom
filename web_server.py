import json, os, subprocess, sys, re, threading, time, platform, uuid, io
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, render_template, Response, stream_with_context, send_file

BASE_DIR = Path(__file__).parent
SAOM_DIR = BASE_DIR / "saom"
MEMORY_DIR = Path.home() / ".saom" / "memory"

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"), static_folder=str(BASE_DIR / "static"))
app.secret_key = os.urandom(24)

# ── Access control for dangerous endpoints ────────────────────────
# /api/run/* and /api/file/* execute arbitrary shell/python and read/write
# arbitrary files on this server. Previously nothing gated them at all — on
# a public deployment (see render.yaml) anyone who found the URL could run
# commands on the host. This key is opt-in (unset = old open behavior, so
# local/dev use is unaffected) but should be set in production.
_API_KEY = os.environ.get("SAOM_API_KEY", "")
_PROTECTED_PREFIXES = ("/api/run", "/api/file")

@app.before_request
def _guard_dangerous_routes():
    if _API_KEY and request.path.startswith(_PROTECTED_PREFIXES):
        supplied = request.headers.get("X-API-Key") or \
            request.headers.get("Authorization", "").replace("Bearer ", "", 1).strip()
        if supplied != _API_KEY:
            return jsonify({"error": "Unauthorized — set the X-API-Key header. "
                                      "(SAOM_API_KEY is configured on this server.)"}), 401

# ── Basic per-client rate limiting ────────────────────────────────
# Now that the server can genuinely run requests concurrently (see render.yaml),
# nothing stops one client from firing dozens of chat/upload requests at once
# and starving everyone else's share of the thread pool. Simple in-process
# sliding-window limiter — no external dependency, good enough for a single
# gunicorn process; would need a shared store (Redis) if this ever runs across
# multiple worker processes.
_RATE_LIMITED_PREFIXES = ("/api/chat", "/api/upload", "/api/web/", "/api/run", "/api/github")
_RATE_LIMIT_MAX = 20        # requests
_RATE_LIMIT_WINDOW = 60     # seconds
_rate_lock = threading.Lock()
_rate_buckets = {}          # client_key -> [timestamps]

def _rate_limit_key():
    # Prefer an explicit session id (works across proxies/shared IPs) if the
    # client sent one, otherwise fall back to remote address.
    sid = None
    if request.is_json:
        sid = (request.get_json(silent=True) or {}).get("session_id")
    return sid or request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")

@app.before_request
def _rate_limit():
    if not request.path.startswith(_RATE_LIMITED_PREFIXES):
        return
    key = _rate_limit_key()
    now = time.time()
    with _rate_lock:
        bucket = [t for t in _rate_buckets.get(key, []) if now - t < _RATE_LIMIT_WINDOW]
        if len(bucket) >= _RATE_LIMIT_MAX:
            _rate_buckets[key] = bucket
            return jsonify({"error": f"Rate limit: max {_RATE_LIMIT_MAX} requests per "
                                      f"{_RATE_LIMIT_WINDOW}s. Try again shortly."}), 429
        bucket.append(now)
        _rate_buckets[key] = bucket

# ── Health check (uptime monitors, Render health checks) ──────────
@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat(),
                     "active_sessions": len(conversations), "active_jobs": len(_jobs)})

# ── Conversation memory: bounded, token-aware, LRU-evicted ────────
# Previously: a plain dict that grew forever (every session_id ever seen stayed
# in memory for the life of the process — a real server-side memory leak), and
# history sent to the LLM was just "last 20 messages" with no regard for how
# large those messages actually were (a few big tool-result-era turns could
# blow well past a small/free model's context window).
from collections import OrderedDict

conversations = OrderedDict()   # sid -> {"messages": [...], "summary": "", "summarized_through": 0, "last_active": ts}
MAX_SESSIONS = 500              # hard cap on concurrent in-memory sessions
KEEP_RECENT = 8                 # most recent messages always sent verbatim
HISTORY_TOKEN_BUDGET = 3000     # soft budget (~tokens) for the verbatim tail
SESSION_TTL_SECONDS = 3600      # auto-purge a session after 1hr of inactivity

# Now that gunicorn actually runs multiple threads concurrently (see render.yaml),
# this dict gets touched from several requests at once — wrap all access in a
# lock. Python dicts are individually-atomic but our compound ops (check-then-
# create, move_to_end + popitem, append-while-another-thread-reads-for-
# summarization) are not, so without this a race could silently drop a message
# or corrupt the LRU ordering.
_conv_lock = threading.Lock()

def _approx_tokens(s):
    return max(1, len(s) // 4)  # ~4 chars/token for English — good enough for budgeting, no tokenizer dep

def _touch(sid):
    conversations[sid]["last_active"] = time.time()
    conversations.move_to_end(sid)
    while len(conversations) > MAX_SESSIONS:
        conversations.popitem(last=False)  # evict least-recently-used session

def get_history(sid):
    with _conv_lock:
        if sid not in conversations:
            conversations[sid] = {"messages": [], "summary": "", "summarized_through": 0, "last_active": time.time()}
        _touch(sid)
        return list(conversations[sid]["messages"])  # copy — caller shouldn't mutate live state

def add_to_history(sid, role, content):
    with _conv_lock:
        if sid not in conversations:
            conversations[sid] = {"messages": [], "summary": "", "summarized_through": 0, "last_active": time.time()}
        conversations[sid]["messages"].append({"role": role, "content": content})
        _touch(sid)

def purge_stale_sessions(ttl=SESSION_TTL_SECONDS):
    """Drop sessions idle longer than ttl seconds. Runs periodically in the
    background (see _session_janitor) in addition to the MAX_SESSIONS LRU cap
    — that cap only bites once memory is actually full; this keeps idle
    sessions from lingering at all."""
    cutoff = time.time() - ttl
    with _conv_lock:
        stale = [sid for sid, sess in conversations.items() if sess["last_active"] < cutoff]
        for sid in stale:
            del conversations[sid]
    return len(stale)

def seed_session_if_empty(sid, client_history):
    """Session state lives only in this process's memory — a server restart
    (Render free tier sleeps/restarts routinely), a deploy, or the TTL purge
    above all wipe it. When that happens the browser's own localStorage still
    shows the full chat, and the user has no way to know the backend forgot
    everything — they just see the model suddenly act like a stranger.
    If the client sends its own local history along and the backend has
    nothing for this session, rehydrate from it instead of silently starting
    fresh. This makes the browser's local copy the durable source of truth
    and the server dict just a cache/summarization aid on top of it."""
    if not client_history:
        return
    with _conv_lock:
        if sid in conversations and conversations[sid]["messages"]:
            return  # backend already has real state — don't clobber it with a possibly-stale client copy
        msgs = []
        for m in client_history[-40:]:
            role, content = m.get("role"), m.get("content")
            if role in ("user", "assistant") and isinstance(content, str) and content:
                msgs.append({"role": role, "content": content[:4000]})
        if msgs:
            conversations[sid] = {"messages": msgs, "summary": "", "summarized_through": 0, "last_active": time.time()}
            _touch(sid)

def _session_janitor():
    while True:
        time.sleep(300)  # every 5 minutes
        try:
            purge_stale_sessions()
            _purge_stale_jobs()
        except Exception:
            pass

threading.Thread(target=_session_janitor, daemon=True, name="saom-janitor").start()

def get_context_messages(sid):
    """Build what actually gets sent to the LLM: a compact running summary of
    anything older, plus the most recent turns verbatim, trimmed to a token
    budget. Replaces resending the full raw history every single turn."""
    with _conv_lock:
        sess = conversations.get(sid)
        if not sess:
            return []
        msgs = list(sess["messages"])
        summary = sess["summary"]
        summarized_through = sess["summarized_through"]
        _touch(sid)

    older = msgs[:-KEEP_RECENT] if len(msgs) > KEEP_RECENT else []
    recent = msgs[-KEEP_RECENT:] if len(msgs) > KEEP_RECENT else msgs

    # Fold any newly-aged-out turns into the running summary once (not every
    # turn) so older context is compacted rather than silently dropped.
    # The LLM call here happens OUTSIDE the lock — it can take seconds, and
    # holding a global lock during a network call would serialize every
    # concurrent user's requests behind it, reintroducing the exact
    # "everyone blocks on one slow request" problem this whole thing exists
    # to avoid.
    new_to_summarize = older[summarized_through:]
    if new_to_summarize:
        try:
            summary_prompt = [
                {"role": "system", "content": "Condense the following into a short factual summary "
                                               "(2-4 sentences) of what's been discussed, for use as "
                                               "background context. No preamble, just the summary."},
                {"role": "user", "content": (summary + "\n\n" if summary else "") +
                    "\n".join(f"{m['role']}: {m['content']}" for m in new_to_summarize)}
            ]
            new_summary = _call_llm(summary_prompt, max_tokens=150)
            if new_summary and not new_summary.startswith("[Error]"):
                summary = new_summary.strip()
                summarized_through = len(older)
                with _conv_lock:
                    if sid in conversations:  # session may have been purged while we were summarizing
                        conversations[sid]["summary"] = summary
                        conversations[sid]["summarized_through"] = summarized_through
        except Exception:
            pass  # summarization failing isn't fatal — recent turns still go through raw

    out = []
    if summary:
        out.append({"role": "system", "content": f"Earlier in this conversation: {summary}"})

    # Token-budget the verbatim tail too, in case any single message is huge
    budget = HISTORY_TOKEN_BUDGET
    trimmed = []
    for m in reversed(recent):
        t = _approx_tokens(m["content"])
        if trimmed and budget - t < 0:
            break
        budget -= t
        trimmed.append(m)
    out.extend(reversed(trimmed))
    return out

# ── System prompt (with auto tools) ──────────────────────────────
SYSTEM_PROMPT = """You are SAOM v12, AI assistant by Om. Be concise. Code only unless asked.

You have tools for anything you don't already know or that changes over time:
live scores, breaking/trending news, current events, prices, "latest"/"current"/
"today" questions, or any fact you're not confident is still true right now.
Never guess or make up numbers, scores, or dates for these — use a tool instead.
You also have a calculator and the current date/time — use them instead of doing
arithmetic or guessing "today's date" in your head.

To use a tool, reply with ONLY one tag, in exactly this format, and nothing else:
  [TOOL:search:your query here]   general web search — snippets + links
  [TOOL:news:your query here]     recent/trending news — dated articles, best for "what's happening with X"
  [TOOL:fetch:https://...]        full text of one specific URL — use when a snippet isn't enough detail
  [TOOL:calc:2 * (3.5 + 7) ** 2]  exact arithmetic — numbers and + - * / // % ** ( ) only
  [TOOL:datetime:]                current date/time in UTC — pass a timezone like [TOOL:datetime:Asia/Kolkata] for local time
  [TOOL:unit:10 km to miles]      unit conversion — length, mass, volume, temperature
  [TOOL:json:{"a": 1,}]           validate/pretty-print JSON and point out exactly what's wrong if it's invalid
  [TOOL:regex:PATTERN:::TEXT]     test a regex pattern against text, list matches/groups
  [TOOL:hash:sha256:::text]       md5/sha1/sha256/sha512 hex digest of text
  [TOOL:base64:encode:::text]     base64 encode/decode (use "encode" or "decode" before :::)
  [TOOL:pypi:requests]            look up a PyPI package's latest version, summary, license
  [TOOL:github:https://github.com/owner/repo]              list a repo's files
  [TOOL:github:https://github.com/owner/repo/blob/branch/path]  read one file's full content

When asked to review a GitHub repo or find bugs in it, first list the repo to
see what's there, then fetch the specific files that matter (entry points,
anything the user named) rather than guessing blindly.

Rules:
- Prefer search or news first. Only fetch a URL when you need more than the snippet gives you.
- Use as few tool calls as it takes — usually one is enough. Don't fetch every result.
- After you see tool results, answer the user directly and concisely, citing the source
  (e.g. "per ESPN Cricinfo" or "per Reuters").
- If results are empty, outdated, or unclear, say so honestly rather than guessing.
"""

MAX_TOOL_ROUNDS = 3  # cap on search->fetch->search style chains per turn

# ── Multi-provider LLM (v12) ───────────────────────────────────
import requests as _req

_GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
_GROQ_KEY = os.environ.get("GROQ_API_KEY", "")

_PROVIDER_CHAIN = [
    ("zen", "north-mini-code-free", "https://opencode.ai/zen/v1/chat/completions"),
    ("gemini", "gemini-3.5-flash", "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"),
    ("groq", "llama-3.3-70b-versatile", "https://api.groq.com/openai/v1/chat/completions"),
]

def _call_llm_stream(messages, max_tokens=500, temp=0.5):
    """Try providers in order: north (free) -> gemini -> groq. Yield chunks."""
    for prov_name, model, url in _PROVIDER_CHAIN:
        try:
            if prov_name == "gemini":
                if not _GEMINI_KEY:
                    continue
                contents = []
                for m in messages:
                    role = "user" if m["role"] in ("user",) else "model"
                    contents.append({"role": role, "parts": [{"text": m["content"]}]})
                r = _req.post(url.format(model=model, key=_GEMINI_KEY),
                    json={"contents": contents, "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temp}},
                    headers={"Content-Type": "application/json"}, timeout=60)
                if r.status_code != 200:
                    continue
                data = r.json()
                text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                if text:
                    yield {"provider": f"{prov_name}/{model}"}
                    yield text
                    return
            elif prov_name == "groq":
                if not _GROQ_KEY:
                    continue
                r = _req.post(url, json={"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temp},
                    headers={"Authorization": f"Bearer {_GROQ_KEY}", "Content-Type": "application/json"}, timeout=60)
                if r.status_code != 200:
                    continue
                text = r.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                if text:
                    yield {"provider": f"{prov_name}/{model}"}
                    yield text
                    return
            else:
                # Zen/north — free, no key needed
                r = _req.post(url, json={"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temp, "apiKey": "public", "stream": True},
                    headers={"Content-Type": "application/json", "User-Agent": "SAOM/12"}, stream=True, timeout=60)
                if r.status_code != 200:
                    continue
                yield {"provider": f"{prov_name}/{model}"}
                full = ""
                for line in r.iter_lines():
                    if not line:
                        continue
                    line = line.decode("utf-8", errors="replace")
                    if not line.startswith("data: "):
                        continue
                    payload_str = line[6:]
                    if payload_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload_str)
                        content = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if content:
                            full += content
                            yield content
                    except:
                        pass
                if full:
                    return
        except Exception:
            continue
    yield "[Error] All LLM providers failed. Set GEMINI_API_KEY or GROQ_API_KEY."

def _call_llm(messages, max_tokens=500, temp=0.5):
    """Non-streaming LLM call with fallback.

    Bug fix: this used to do `for chunk in _call_llm_stream(...): pass` and then
    return the loop variable `chunk`, which after the loop only holds the LAST
    item yielded. For streaming providers (e.g. the default free "zen" provider)
    the text arrives as many small chunks, so this silently returned just the
    final fragment of the reply and threw away everything before it. It also
    didn't skip the leading `{"provider": ...}` dict the generator yields first.
    Now we accumulate every text chunk and skip non-string metadata items.
    """
    full = ""
    for chunk in _call_llm_stream(messages, max_tokens, temp):
        if isinstance(chunk, dict):
            continue
        full += chunk
    return full if full else "[Error]"

# ── SAOM CLI helpers ─────────────────────────────────────────────
def _saom_cmd(*args):
    return [sys.executable, "-m", "saom"] + list(args)

def run_command(cmd_args, timeout=30):
    try:
        if platform.system() == "Windows":
            cmd_str = " ".join('"%s"' % a if " " in a else a for a in cmd_args)
            r = subprocess.run(cmd_str, capture_output=True, text=True, timeout=timeout,
                               cwd=str(BASE_DIR), shell=True)
        else:
            r = subprocess.run(cmd_args, capture_output=True, text=True, timeout=timeout,
                               cwd=str(BASE_DIR))
        return {"stdout": r.stdout.strip(), "stderr": r.stderr.strip(), "returncode": r.returncode}
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "Command timed out", "returncode": -1}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "returncode": -1}

# ── Response formatting ──────────────────────────────────────────
def format_status(data):
    if not isinstance(data, dict):
        return data
    lines = [
        f"Version: {data.get('version', '?')}",
        f"Mode: {data.get('current_mode', 'idle')} | Confidence: {data.get('current_confidence', 50)}%",
        f"Session: {data.get('current_session', 'none')}",
        f"Tools: {data.get('tools_used', 0)}/{data.get('tools_total', 0)} used",
        f"Graph: {data.get('graph_nodes', 0)} nodes, {data.get('graph_edges', 0)} edges",
        f"Lessons: {data.get('lessons_total', 0)} | Sessions: {data.get('sessions', 0)}",
    ]
    tools = data.get("tools", [])
    used_tools = [t["name"] for t in tools if t.get("used")]
    if used_tools:
        lines.append(f"Active: {', '.join(used_tools)}")
    return "\n".join(lines)

def format_response(raw, stderr="", returncode=0):
    if stderr and returncode != 0:
        return f"Error: {stderr}"
    if not raw:
        return "No output"
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            if "version" in data and "tools_total" in data:
                return format_status(data)
            if "error" in data and data["error"]:
                return f"Error: {data['error']}"
            if "result" in data:
                return format_response(data["result"], data.get("error", ""))
            if "response" in data:
                return data["response"]
            return "\n".join(f"{k}: {v}" for k, v in data.items())
        if isinstance(data, list):
            if data and isinstance(data[0], dict) and "name" in data[0]:
                return "\n".join(f"  - {t['name']}" + (" [used]" if t.get('used') else "") for t in data)
            return json.dumps(data, indent=2)
        return str(data)
    except (json.JSONDecodeError, ValueError):
        return raw

# ── Web search / news / fetch helpers (shared by routes + tool calls) ──
import html as _html_mod

def _ddgs_text(query, max_results=5):
    from ddgs import DDGS
    results = DDGS().text(query, max_results=max_results)
    return [f"{i}. {r.get('title', 'No title')}\n   {r.get('body', 'No description')}\n   {r.get('href', '')}"
            for i, r in enumerate(results, 1)]

def _ddgs_news(query, max_results=5):
    """Recent/trending news — better suited than plain text search for things
    like 'trending news', live scores, or anything time-sensitive, since
    results come back dated and sourced."""
    from ddgs import DDGS
    results = DDGS().news(query, max_results=max_results)
    out = []
    for i, r in enumerate(results, 1):
        out.append(f"{i}. {r.get('title', '')} ({r.get('date', '')})\n"
                    f"   {r.get('body', '')}\n"
                    f"   Source: {r.get('source', '')} \u2014 {r.get('url', '')}")
    return out

def _web_fetch(url, max_chars=5000):
    try:
        r = _req.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; SAOM/1.0)"},
                      timeout=15, allow_redirects=True)
        text = r.text
        # Bug fix: previously only tags were stripped, so a <script>...</script> or
        # <style>...</style> block's raw JS/CSS *content* survived into the "readable"
        # text and got fed straight to the LLM/summary, degrading quality badly on
        # most real news/sports sites. Strip those blocks (tag + content) first.
        text = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = _html_mod.unescape(text)  # &amp; &#39; &quot; etc. were left as-is before
        text = re.sub(r'\s+', ' ', text).strip()
        return {"content": text[:max_chars], "status": r.status_code, "url": url} if text else \
               {"content": "", "status": r.status_code, "url": url, "error": "Empty page."}
    except Exception as e:
        return {"content": "", "status": None, "url": url, "error": str(e)}

# ── Safe calculator (AST-restricted — NOT eval()) ─────────────────
import ast, operator as _op

_SAFE_MATH_OPS = {
    ast.Add: _op.add, ast.Sub: _op.sub, ast.Mult: _op.mul, ast.Div: _op.truediv,
    ast.FloorDiv: _op.floordiv, ast.Mod: _op.mod, ast.Pow: _op.pow,
    ast.USub: _op.neg, ast.UAdd: _op.pos,
}

def _safe_eval_math(expr):
    """Evaluate a pure arithmetic expression safely. Only numbers and
    + - * / // % ** () are allowed — no names, no calls, no attribute access,
    no imports. This is the standard 'don't use eval() on user/LLM input'
    pattern: walk a parsed AST and only permit a small allowlist of nodes."""
    def _walk(node):
        if isinstance(node, ast.Expression):
            return _walk(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                return node.value
            raise ValueError("only numbers are allowed")
        if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_MATH_OPS:
            return _SAFE_MATH_OPS[type(node.op)](_walk(node.left), _walk(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_MATH_OPS:
            return _SAFE_MATH_OPS[type(node.op)](_walk(node.operand))
        raise ValueError("unsupported expression")
    return _walk(ast.parse(expr, mode="eval"))

# ── Date/time (LLMs often don't reliably know "today") ────────────
def _tool_datetime(tz_name=""):
    tz_name = (tz_name or "").strip()
    try:
        if tz_name and tz_name.lower() not in ("utc", "local"):
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo(tz_name))
            return now.strftime(f"%Y-%m-%d %H:%M:%S {tz_name} (%A)")
        from datetime import timezone
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m-%d %H:%M:%S UTC (%A)")
    except Exception as e:
        return f"Datetime error: {e} (use an IANA name like 'Asia/Kolkata' or 'America/New_York', or 'UTC')"

# ── Unit conversion (chat-user staple: "10 km to miles", "98.6 F to C") ──
_UNIT_ALIASES = {
    "km": "kilometer", "kilometers": "kilometer", "kilometre": "kilometer", "kilometres": "kilometer",
    "m": "meter", "meters": "meter", "metre": "meter", "metres": "meter",
    "cm": "centimeter", "centimeters": "centimeter",
    "mm": "millimeter", "millimeters": "millimeter",
    "mi": "mile", "miles": "mile",
    "yd": "yard", "yards": "yard",
    "ft": "foot", "feet": "foot",
    "in": "inch", "inches": "inch",
    "kg": "kilogram", "kilograms": "kilogram", "kgs": "kilogram",
    "g": "gram", "grams": "gram",
    "lb": "pound", "lbs": "pound", "pounds": "pound",
    "oz": "ounce", "ounces": "ounce",
    "l": "liter", "liters": "liter", "litre": "liter", "litres": "liter",
    "ml": "milliliter", "milliliters": "milliliter",
    "gal": "gallon", "gallons": "gallon",
    "cup": "cup", "cups": "cup",
    "c": "celsius", "celsius": "celsius", "\u00b0c": "celsius",
    "f": "fahrenheit", "fahrenheit": "fahrenheit", "\u00b0f": "fahrenheit",
    "k": "kelvin", "kelvin": "kelvin",
}
# Everything expressed in a base unit per category (meters, kilograms, liters)
_UNIT_TO_BASE = {
    "kilometer": 1000.0, "meter": 1.0, "centimeter": 0.01, "millimeter": 0.001,
    "mile": 1609.344, "yard": 0.9144, "foot": 0.3048, "inch": 0.0254,
    "kilogram": 1000.0, "gram": 1.0, "pound": 453.59237, "ounce": 28.349523125,
    "liter": 1.0, "milliliter": 0.001, "gallon": 3.785411784, "cup": 0.2365882365,
}
_UNIT_CATEGORY = {
    "kilometer": "length", "meter": "length", "centimeter": "length", "millimeter": "length",
    "mile": "length", "yard": "length", "foot": "length", "inch": "length",
    "kilogram": "mass", "gram": "mass", "pound": "mass", "ounce": "mass",
    "liter": "volume", "milliliter": "volume", "gallon": "volume", "cup": "volume",
    "celsius": "temperature", "fahrenheit": "temperature", "kelvin": "temperature",
}

def _to_celsius(v, unit):
    return v if unit == "celsius" else (v - 32) * 5 / 9 if unit == "fahrenheit" else v - 273.15

def _from_celsius(v, unit):
    return v if unit == "celsius" else v * 9 / 5 + 32 if unit == "fahrenheit" else v + 273.15

def _tool_unit_convert(arg):
    """Parses free-form 'VALUE UNIT to UNIT', e.g. '10 km to miles' or '98.6 f to c'."""
    m = re.match(r'^\s*([\-\d.]+)\s*([a-zA-Z\u00b0]+)\s*(?:to|in|->|as)\s*([a-zA-Z\u00b0]+)\s*$',
                 arg.strip(), re.IGNORECASE)
    if not m:
        return "Couldn't parse that — use 'VALUE UNIT to UNIT', e.g. '10 km to miles' or '98.6 F to C'."
    value, from_u, to_u = m.groups()
    from_key = _UNIT_ALIASES.get(from_u.lower())
    to_key = _UNIT_ALIASES.get(to_u.lower())
    if not from_key or not to_key:
        unknown = from_u if not from_key else to_u
        return f"Unknown unit '{unknown}'. Supported: length (km/m/cm/mm/mile/yard/foot/inch), " \
               f"mass (kg/g/lb/oz), volume (l/ml/gallon/cup), temperature (C/F/K)."
    if _UNIT_CATEGORY[from_key] != _UNIT_CATEGORY[to_key]:
        return f"Can't convert {_UNIT_CATEGORY[from_key]} ({from_key}) to {_UNIT_CATEGORY[to_key]} ({to_key})."
    value = float(value)
    if _UNIT_CATEGORY[from_key] == "temperature":
        result = _from_celsius(_to_celsius(value, from_key), to_key)
    else:
        result = value * _UNIT_TO_BASE[from_key] / _UNIT_TO_BASE[to_key]
    result = round(result, 6)
    if result == int(result):
        result = int(result)
    return f"{value} {from_key} = {result} {to_key}"

# ── JSON validate/pretty-print (programmer staple) ─────────────────
def _tool_json(arg):
    try:
        parsed = json.loads(arg)
        return json.dumps(parsed, indent=2, ensure_ascii=False)
    except json.JSONDecodeError as e:
        return f"Invalid JSON: {e.msg} at line {e.lineno}, column {e.colno}"

# ── Regex tester (programmer staple) ────────────────────────────────
def _tool_regex(arg):
    """Format: pattern:::text  (::: chosen since it won't collide with typical regex/text)"""
    if ":::" not in arg:
        return "Format: [TOOL:regex:PATTERN:::TEXT]"
    pattern, text = arg.split(":::", 1)
    try:
        matches = list(re.finditer(pattern, text))
        if not matches:
            return "No matches."
        lines = []
        for i, m in enumerate(matches[:20], 1):
            groups = f" groups={m.groups()}" if m.groups() else ""
            lines.append(f"{i}. '{m.group(0)}' at [{m.start()}:{m.end()}]{groups}")
        more = f"\n... and {len(matches) - 20} more" if len(matches) > 20 else ""
        return "\n".join(lines) + more
    except re.error as e:
        return f"Invalid regex: {e}"

# ── Hashing (programmer staple) ─────────────────────────────────────
def _tool_hash(arg):
    """Format: algorithm:::text, e.g. sha256:::hello world"""
    import hashlib
    if ":::" not in arg:
        return "Format: [TOOL:hash:ALGORITHM:::TEXT] (md5, sha1, sha256, sha512)"
    algo, text = arg.split(":::", 1)
    algo = algo.strip().lower()
    if algo not in ("md5", "sha1", "sha256", "sha512"):
        return f"Unsupported algorithm '{algo}'. Use md5, sha1, sha256, or sha512."
    return hashlib.new(algo, text.encode("utf-8")).hexdigest()

# ── Base64 encode/decode (programmer staple) ────────────────────────
def _tool_base64(arg):
    """Format: encode:::text or decode:::text"""
    import base64 as _b64
    if ":::" not in arg:
        return "Format: [TOOL:base64:encode:::TEXT] or [TOOL:base64:decode:::TEXT]"
    mode, text = arg.split(":::", 1)
    mode = mode.strip().lower()
    try:
        if mode == "encode":
            return _b64.b64encode(text.encode("utf-8")).decode("ascii")
        if mode == "decode":
            return _b64.b64decode(text.encode("ascii")).decode("utf-8", errors="replace")
        return "Mode must be 'encode' or 'decode'."
    except Exception as e:
        return f"Base64 error: {e}"

# ── GitHub link reading (repo trees + individual files) ─────────────
_GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

def _gh_headers():
    h = {"Accept": "application/vnd.github+json"}
    if _GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {_GITHUB_TOKEN}"
    return h

def _gh_rate_limited(r):
    return r.status_code == 403 and r.headers.get("X-RateLimit-Remaining") == "0"

def _parse_github_url(url):
    url = url.strip()
    m = re.match(r'^https?://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)$', url)
    if m:
        owner, repo, branch, path = m.groups()
        return ("blob", owner, repo.removesuffix(".git"), branch, path)
    m = re.match(r'^https?://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+)$', url)
    if m:
        owner, repo, branch, path = m.groups()
        return ("blob", owner, repo, branch, path)
    m = re.match(r'^https?://github\.com/([^/]+)/([^/]+)/tree/([^/]+)/?(.*)$', url)
    if m:
        owner, repo, branch, path = m.groups()
        return ("tree", owner, repo.removesuffix(".git"), branch, path)
    m = re.match(r'^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$', url)
    if m:
        owner, repo = m.groups()
        return ("repo", owner, repo, None, "")
    return None

_CODE_EXTENSIONS = ('.py', '.php', '.js', '.jsx', '.ts', '.tsx', '.html', '.css', '.java',
                     '.go', '.rb', '.c', '.cpp', '.h', '.cs', '.sql', '.sh', '.json', '.yml', '.yaml')

def _tool_github(url):
    parsed = _parse_github_url(url)
    if not parsed:
        return ("Not a recognized GitHub URL. Use a repo URL (https://github.com/owner/repo) "
                 "or a file URL (.../blob/branch/path/to/file).")
    kind, owner, repo, branch, path = parsed
    try:
        if kind == "blob":
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
            r = _req.get(raw_url, timeout=15)
            if r.status_code != 200:
                return f"Couldn't fetch {path} from {owner}/{repo}@{branch} (HTTP {r.status_code})."
            content = r.text
            body = content[:8000] + ("\n... (truncated)" if len(content) > 8000 else "")
            return f"File: {path} ({len(content)} chars)\n\n{body}"

        # repo or tree — list files so the model (or user) can pick specific ones
        if not branch:
            r = _req.get(f"https://api.github.com/repos/{owner}/{repo}", timeout=15, headers=_gh_headers())
            if _gh_rate_limited(r):
                return ("GitHub API rate limit hit (60/hr unauthenticated, shared across all users of this "
                        "server). Set a GITHUB_TOKEN env var to raise it to 5000/hr. Reading individual "
                        "files by URL still works, since that doesn't use the rate-limited API.")
            if r.status_code != 200:
                return f"Couldn't find repo {owner}/{repo} (HTTP {r.status_code})."
            branch = r.json().get("default_branch", "main")

        r = _req.get(f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1",
                      timeout=15, headers=_gh_headers())
        if _gh_rate_limited(r):
            return ("GitHub API rate limit hit (60/hr unauthenticated, shared across all users of this "
                    "server). Set a GITHUB_TOKEN env var to raise it to 5000/hr. Reading individual "
                    "files by URL still works, since that doesn't use the rate-limited API.")
        if r.status_code != 200:
            return f"Couldn't list {owner}/{repo}@{branch} (HTTP {r.status_code})."
        tree = r.json().get("tree", [])
        files = [t["path"] for t in tree if t.get("type") == "blob"]
        if path:
            files = [f for f in files if f.startswith(path)]
        code_files = [f for f in files if f.lower().endswith(_CODE_EXTENSIONS)]
        shown = code_files or files
        listing = "\n".join(shown[:60])
        more = f"\n... and {len(shown) - 60} more" if len(shown) > 60 else ""
        return (f"{owner}/{repo}@{branch} \u2014 {len(files)} files total"
                f"{' under ' + path if path else ''}.\n\n{listing}{more}\n\n"
                f"To read a specific file: [TOOL:github:https://github.com/{owner}/{repo}/blob/{branch}/PATH]")
    except Exception as e:
        return f"GitHub error: {e}"
def _tool_pypi(arg):
    pkg = arg.strip()
    if not pkg:
        return "Give a package name, e.g. [TOOL:pypi:requests]"
    try:
        r = _req.get(f"https://pypi.org/pypi/{pkg}/json", timeout=10)
        if r.status_code == 404:
            return f"No PyPI package named '{pkg}'."
        r.raise_for_status()
        info = r.json().get("info", {})
        return (f"{info.get('name')} {info.get('version')}\n"
                f"{(info.get('summary') or '').strip()}\n"
                f"License: {info.get('license') or 'unknown'}\n"
                f"Homepage: {info.get('home_page') or info.get('project_url') or ''}\n"
                f"Install: pip install {info.get('name')}")
    except Exception as e:
        return f"PyPI lookup error: {e}"

# ── Web search (DuckDuckGo, free) ────────────────────────────────
@app.route("/api/web/search", methods=["POST"])
def api_web_search():
    data = request.get_json() or {}
    query = data.get("query", "")
    max_results = data.get("max_results", 5)
    if not query:
        return jsonify({"error": "No query"}), 400
    try:
        formatted = _ddgs_text(query, max_results)
        return jsonify({"results": formatted, "count": len(formatted), "query": query})
    except Exception as e:
        return jsonify({"error": str(e)})

# ── Trending / recent news (DuckDuckGo, free) ────────────────────
@app.route("/api/web/news", methods=["POST"])
def api_web_news():
    data = request.get_json() or {}
    query = data.get("query", "")
    max_results = data.get("max_results", 5)
    if not query:
        return jsonify({"error": "No query"}), 400
    try:
        formatted = _ddgs_news(query, max_results)
        return jsonify({"results": formatted, "count": len(formatted), "query": query})
    except Exception as e:
        return jsonify({"error": str(e)})

# ── Web fetch (read URL) ─────────────────────────────────────────
@app.route("/api/web/fetch", methods=["POST"])
def api_web_fetch():
    data = request.get_json() or {}
    url = data.get("url", "")
    max_chars = data.get("max_chars", 5000)
    if not url:
        return jsonify({"error": "No URL"}), 400
    result = _web_fetch(url, max_chars)
    return jsonify(result)

# ── Upload -> background bug analysis -> downloadable fixed file ────
# Runs as a background thread rather than blocking the request: a real review
# (static check + an LLM call asking for a full corrected file) can take well
# over gunicorn's request timeout on a slow provider, so the upload endpoint
# hands back a job_id immediately and the client polls /api/analyze/<id>.
_JOBS_LOCK = threading.Lock()
_jobs = {}  # job_id -> {status, filename, ext, language, code, bugs_report, fixed_code, error, created, updated}

MAX_UPLOAD_BYTES = 300_000  # 300KB is generous for one source file and keeps LLM context sane
JOB_TTL_SECONDS = 7200      # keep a finished job's result downloadable for 2hrs, then purge

ALLOWED_UPLOAD_EXTENSIONS = {
    ".py": "Python", ".php": "PHP", ".html": "HTML", ".htm": "HTML", ".js": "JavaScript",
    ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript", ".java": "Java",
    ".go": "Go", ".rb": "Ruby", ".c": "C", ".cpp": "C++", ".h": "C/C++ header",
    ".cs": "C#", ".css": "CSS", ".sql": "SQL", ".sh": "Shell", ".json": "JSON",
}

def _purge_stale_jobs():
    cutoff = time.time() - JOB_TTL_SECONDS
    with _JOBS_LOCK:
        stale = [jid for jid, j in _jobs.items() if j["updated"] < cutoff]
        for jid in stale:
            del _jobs[jid]
    return len(stale)

def _static_lint(code, ext):
    """Best-effort deterministic check before handing off to the LLM. Catches
    hard syntax errors reliably instead of hoping the model notices them."""
    if ext == ".py":
        try:
            ast.parse(code)
            return "No syntax errors (ast.parse)."
        except SyntaxError as e:
            return f"SyntaxError: {e.msg} at line {e.lineno}, column {e.offset}"
    if ext == ".php":
        try:
            r = subprocess.run(["php", "-l"], input=code, capture_output=True, text=True, timeout=15)
            return (r.stdout or r.stderr).strip() or "No output from php -l."
        except FileNotFoundError:
            return "(php CLI not installed on this server \u2014 skipping lint, LLM review only)"
        except Exception as e:
            return f"(php lint error: {e})"
    if ext == ".json":
        try:
            json.loads(code)
            return "Valid JSON."
        except json.JSONDecodeError as e:
            return f"Invalid JSON: {e.msg} at line {e.lineno}, column {e.colno}"
    return "(no static linter for this file type \u2014 LLM review only)"

def _run_analysis_job(job_id):
    with _JOBS_LOCK:
        job = _jobs.get(job_id)
        if not job:
            return
        job["status"] = "running"
        job["updated"] = time.time()
        code, ext, filename, sid = job["code"], job["ext"], job["filename"], job["session_id"]

    lint_result = _static_lint(code, ext)
    prompt = [
        {"role": "system", "content":
            "You are a careful code reviewer. You'll be given a source file and a static-analysis "
            "result. Find real bugs (logic errors, security issues, off-by-ones, unhandled errors, "
            "resource leaks) \u2014 don't invent issues that aren't there. Respond in EXACTLY this format:\n\n"
            "## Bugs found\n"
            "(numbered list, one line each: what's wrong and why, cite line numbers where you can. "
            "If there are genuinely no bugs, say so plainly instead of inventing some.)\n\n"
            "## Fixed code\n"
            "```\n(the complete corrected file \u2014 not a diff or snippet, the whole file)\n```"},
        {"role": "user", "content": f"File: {filename}\nStatic check result: {lint_result}\n\n```\n{code}\n```"}
    ]
    try:
        reply = _call_llm(prompt, max_tokens=4000)
        # Bug fix: _call_llm returns "[Error] All LLM providers failed..." as a normal
        # string on total provider failure — it doesn't raise. The old code treated that
        # string as if it were a real review: no fenced block matched, so fixed_code fell
        # back to `code` (the untouched original) and the whole error text became the
        # "bugs report" — reported as status="done" with a "Download fixed file" button
        # that silently handed back the unmodified original file. Catch that explicitly.
        if reply.strip().startswith("[Error]"):
            with _JOBS_LOCK:
                job = _jobs.get(job_id)
                if job:
                    job.update(status="error", error=reply.strip(), lint_result=lint_result, updated=time.time())
            return
        blocks = re.findall(r'```[a-zA-Z0-9_+-]*\n(.*?)```', reply, re.DOTALL)
        fixed_code = blocks[-1].rstrip("\n") if blocks else code
        bugs_section = reply.split("## Fixed code")[0].strip() if "## Fixed code" in reply else reply
        with _JOBS_LOCK:
            job = _jobs.get(job_id)
            if job:
                job.update(status="done", bugs_report=bugs_section, fixed_code=fixed_code,
                           lint_result=lint_result, updated=time.time())

        # Bug fix: upload/analyze ran entirely outside the chat's real memory — a
        # follow-up like "fix this code" had nothing to refer to, since the backend
        # session never saw the file, only a client-side cosmetic "Uploaded X" bubble.
        # Inject the actual code (capped) and the review into real session history so
        # follow-up messages in the same session can reference it naturally.
        code_excerpt = code if len(code) <= 4000 else code[:4000] + "\n... (truncated)"
        add_to_history(sid, "user", f"[Uploaded {filename} for review]\n```{ext.lstrip('.')}\n{code_excerpt}\n```")
        add_to_history(sid, "assistant", bugs_section)
    except Exception as e:
        with _JOBS_LOCK:
            job = _jobs.get(job_id)
            if job:
                job.update(status="error", error=str(e), updated=time.time())

@app.route("/api/upload", methods=["POST"])
def api_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "No file uploaded"}), 400
    sid = request.form.get("session_id", "default")
    ext = Path(f.filename).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return jsonify({"error": f"Unsupported file type '{ext}'. Allowed: "
                                  f"{', '.join(sorted(ALLOWED_UPLOAD_EXTENSIONS))}"}), 400
    raw = f.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        return jsonify({"error": f"File too large ({len(raw):,} bytes, max {MAX_UPLOAD_BYTES:,})"}), 400
    try:
        code = raw.decode("utf-8")
    except UnicodeDecodeError:
        return jsonify({"error": "File isn't valid UTF-8 text"}), 400

    job_id = uuid.uuid4().hex
    now = time.time()
    with _JOBS_LOCK:
        _jobs[job_id] = {"status": "queued", "filename": f.filename, "ext": ext, "session_id": sid,
                          "language": ALLOWED_UPLOAD_EXTENSIONS[ext], "code": code,
                          "bugs_report": "", "fixed_code": "", "lint_result": "", "error": "",
                          "created": now, "updated": now}
    threading.Thread(target=_run_analysis_job, args=(job_id,), daemon=True, name=f"analyze-{job_id[:8]}").start()
    return jsonify({"job_id": job_id, "filename": f.filename,
                     "language": ALLOWED_UPLOAD_EXTENSIONS[ext], "size": len(raw)})

@app.route("/api/analyze/<job_id>")
def api_analyze_status(job_id):
    with _JOBS_LOCK:
        job = _jobs.get(job_id)
        if not job:
            return jsonify({"error": "Unknown job_id (expired or never existed)"}), 404
        return jsonify({"status": job["status"], "filename": job["filename"], "language": job["language"],
                         "bugs_report": job.get("bugs_report", ""), "error": job.get("error", ""),
                         "lint_result": job.get("lint_result", ""), "has_fixed_code": bool(job.get("fixed_code"))})

@app.route("/api/download/<job_id>")
def api_download(job_id):
    with _JOBS_LOCK:
        job = _jobs.get(job_id)
        if not job or job["status"] != "done" or not job.get("fixed_code"):
            return jsonify({"error": "Not ready, failed, or job not found"}), 404
        fixed_code, filename = job["fixed_code"], job["filename"]
    stem, ext = Path(filename).stem, Path(filename).suffix
    buf = io.BytesIO(fixed_code.encode("utf-8"))
    buf.seek(0)
    return send_file(buf, mimetype="text/plain", as_attachment=True, download_name=f"{stem}_fixed{ext}")

# ── File operations ──────────────────────────────────────────────
@app.route("/api/file/read", methods=["POST"])
def api_file_read():
    data = request.get_json() or {}
    path = data.get("path", "")
    if not path:
        return jsonify({"error": "No path"}), 400
    try:
        p = Path(path).resolve()
        if not p.exists():
            return jsonify({"error": f"Not found: {path}"})
        if p.stat().st_size > 1_000_000:
            return jsonify({"error": "Too large (>1MB)"})
        content = p.read_text(encoding="utf-8", errors="replace")
        return jsonify({"content": content, "lines": content.count("\n") + 1, "size": p.stat().st_size})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/api/file/write", methods=["POST"])
def api_file_write():
    data = request.get_json() or {}
    path = data.get("path", "")
    content = data.get("content", "")
    if not path:
        return jsonify({"error": "No path"}), 400
    try:
        p = Path(path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return jsonify({"success": True, "path": str(p), "size": len(content)})
    except Exception as e:
        return jsonify({"error": str(e)})

# ── Tool/Skill operations ────────────────────────────────────────
@app.route("/api/tools")
def api_tools():
    try:
        r = run_command(_saom_cmd("status"), timeout=10)
        data = json.loads(r["stdout"])
        return jsonify({"tools": data.get("tools", []), "total": len(data.get("tools", []))})
    except:
        return jsonify({"tools": [], "total": 0})

@app.route("/api/skills")
def api_skills():
    skills_dir = Path.cwd() / ".opencode" / "skills"
    if not skills_dir.exists():
        skills_dir = BASE_DIR.parent / ".opencode" / "skills"
    skills = []
    if skills_dir.exists():
        for d in sorted(skills_dir.iterdir()):
            if d.is_dir() and not d.name.startswith("."):
                skills.append({"name": d.name})
    return jsonify({"skills": skills, "total": len(skills)})

# ── Code runners ─────────────────────────────────────────────────
@app.route("/api/run/python", methods=["POST"])
def api_run_python():
    data = request.get_json() or {}
    code = data.get("code", "")
    if not code:
        return jsonify({"error": "No code"}), 400
    try:
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30, cwd=str(BASE_DIR))
        output = r.stdout or r.stderr
        if len(output) > 5000:
            output = output[:5000] + "\n... (truncated)"
        return jsonify({"output": output, "returncode": r.returncode})
    except subprocess.TimeoutExpired:
        return jsonify({"output": "Timed out (30s)", "returncode": -1})
    except Exception as e:
        return jsonify({"output": str(e), "returncode": -1})

@app.route("/api/run/shell", methods=["POST"])
def api_run_shell():
    data = request.get_json() or {}
    cmd = data.get("command", "")
    if not cmd:
        return jsonify({"error": "No command"}), 400
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30, cwd=str(BASE_DIR))
        output = r.stdout or r.stderr
        if len(output) > 5000:
            output = output[:5000] + "\n... (truncated)"
        return jsonify({"output": output, "returncode": r.returncode})
    except subprocess.TimeoutExpired:
        return jsonify({"output": "Timed out (30s)", "returncode": -1})
    except Exception as e:
        return jsonify({"output": str(e), "returncode": -1})

# ── Detect tool calls in message (explicit "search "/"news "/"fetch " commands) ──
def detect_tool_call(message):
    msg = message.strip()
    if msg.lower().startswith("search "):
        return ("search", msg[7:].strip())
    if msg.lower().startswith("news "):
        return ("news", msg[5:].strip())
    if msg.lower().startswith("fetch "):
        return ("fetch", msg[6:].strip())
    if msg.lower().startswith("calc "):
        return ("calc", msg[5:].strip())
    if msg.lower() in ("datetime", "time", "date") or msg.lower().startswith("datetime "):
        return ("datetime", msg[9:].strip() if msg.lower().startswith("datetime ") else "")
    if msg.lower().startswith("convert "):
        return ("unit", msg[8:].strip())
    if msg.lower().startswith("json "):
        return ("json", msg[5:].strip())
    if msg.lower().startswith("regex "):
        return ("regex", msg[6:].strip())
    if msg.lower().startswith("hash "):
        return ("hash", msg[5:].strip())
    if msg.lower().startswith("base64 "):
        return ("base64", msg[7:].strip())
    if msg.lower().startswith("pypi "):
        return ("pypi", msg[5:].strip())
    if msg.lower().startswith("github "):
        return ("github", msg[7:].strip())
    if re.match(r'^https?://(github\.com|raw\.githubusercontent\.com)/', msg, re.IGNORECASE):
        return ("github", msg)
    return None

def execute_tool_call(tool_name, arg):
    """Execute a tool call (from a user command or an LLM [TOOL:...] tag) and
    return a plain-text result. search/news/fetch share the same underlying
    helpers as the /api/web/* routes so there's one place that owns quality
    (e.g. the fetch HTML-cleaning logic) instead of three copies drifting apart."""
    if tool_name == "search":
        try:
            formatted = _ddgs_text(arg, max_results=5)
            return "\n\n".join(formatted) if formatted else "No results found."
        except Exception as e:
            return f"Search error: {e}"
    if tool_name == "news":
        try:
            formatted = _ddgs_news(arg, max_results=5)
            return "\n\n".join(formatted) if formatted else "No news results found."
        except Exception as e:
            return f"News search error: {e}"
    if tool_name == "fetch":
        result = _web_fetch(arg)
        if result.get("error") and not result.get("content"):
            return f"Fetch error: {result['error']}"
        return result["content"]
    if tool_name == "calc":
        try:
            result = _safe_eval_math(arg)
            return str(result)
        except Exception as e:
            return f"Calc error: invalid expression ({e})"
    if tool_name == "datetime":
        return _tool_datetime(arg)
    if tool_name == "unit":
        return _tool_unit_convert(arg)
    if tool_name == "json":
        return _tool_json(arg)
    if tool_name == "regex":
        return _tool_regex(arg)
    if tool_name == "hash":
        return _tool_hash(arg)
    if tool_name == "base64":
        return _tool_base64(arg)
    if tool_name == "pypi":
        return _tool_pypi(arg)
    if tool_name == "github":
        return _tool_github(arg)
    if tool_name == "python":
        try:
            r = subprocess.run([sys.executable, "-c", arg], capture_output=True, text=True, timeout=30)
            return r.stdout or r.stderr or "No output."
        except Exception as e:
            return f"Python error: {e}"
    if tool_name == "shell":
        try:
            r = subprocess.run(arg, shell=True, capture_output=True, text=True, timeout=30)
            return r.stdout or r.stderr or "No output."
        except Exception as e:
            return f"Shell error: {e}"
    if tool_name == "read":
        try:
            content = Path(arg).read_text(encoding="utf-8", errors="replace")
            return content[:5000]
        except Exception as e:
            return f"Read error: {e}"
    return f"Unknown tool: {tool_name}"

# execute_tool (explicit user "search "/"news "/"fetch " commands) is the same
# execution path as LLM-triggered [TOOL:...] tags.
execute_tool = execute_tool_call

# ── Detect tool calls in LLM response ────────────────────────────
def find_tool_calls(text):
    """Find [TOOL:name:arg] patterns in text. Arg may be empty (e.g. [TOOL:datetime:])."""
    pattern = r'\[TOOL:(\w+):([^\]]*)\]'
    return re.findall(pattern, text)

# ── Streaming chat with auto tools ───────────────────────────────
@app.route("/api/chat/stream", methods=["POST"])
def api_chat_stream():
    data = request.get_json() or {}
    message = data.get("message", "")
    sid = data.get("session_id", "default")
    if not message:
        return jsonify({"error": "No message"}), 400

    def generate():
        import requests as req_lib
        msg_lower = message.lower().strip()

        # Built-in commands (instant)
        if msg_lower in ("status", "saom status"):
            r = run_command(_saom_cmd("status"), timeout=10)
            yield f"data: {json.dumps({'chunk': format_response(r['stdout']), 'done': True})}\n\n"
            return
        if msg_lower in ("init", "saom init"):
            r = run_command(_saom_cmd("init"), timeout=10)
            yield f"data: {json.dumps({'chunk': r['stdout'] or 'Memory initialized.', 'done': True})}\n\n"
            return
        if msg_lower.startswith("pulse start"):
            r = run_command(_saom_cmd("pulse", "start"), timeout=10)
            yield f"data: {json.dumps({'chunk': format_response(r['stdout']), 'done': True})}\n\n"
            return
        if msg_lower.startswith("pulse end"):
            r = run_command(_saom_cmd("pulse", "end"), timeout=10)
            yield f"data: {json.dumps({'chunk': format_response(r['stdout']), 'done': True})}\n\n"
            return
        if msg_lower.startswith("pulse status") or msg_lower == "pulse":
            r = run_command(_saom_cmd("pulse", "status"), timeout=10)
            yield f"data: {json.dumps({'chunk': format_response(r['stdout']), 'done': True})}\n\n"
            return
        if msg_lower.startswith("pre "):
            task = message.split(" ", 1)[1].strip()
            r = run_command(_saom_cmd("pre", task), timeout=15)
            yield f"data: {json.dumps({'chunk': format_response(r['stdout'], r['stderr']), 'done': True})}\n\n"
            return
        if msg_lower.startswith("post "):
            parts = message.split(" ", 2)
            summary = parts[1] if len(parts) > 1 else ""
            outcome = parts[2] if len(parts) > 2 and parts[2] in ("success", "failure") else "success"
            r = run_command(_saom_cmd("post", summary, outcome), timeout=15)
            yield f"data: {json.dumps({'chunk': format_response(r['stdout'], r['stderr']), 'done': True})}\n\n"
            return

        # Regular LLM chat with auto tool execution
        seed_session_if_empty(sid, data.get("history"))
        add_to_history(sid, "user", message)
        round_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + get_context_messages(sid)

        try:
            final_full = None
            for round_num in range(MAX_TOOL_ROUNDS):
                full = ""
                buf = ""              # holds text until we know if it's a [TOOL:...] tag
                suppressed = None      # None=undecided, True=hide (tool tag), False=stream live
                for chunk in _call_llm_stream(round_messages):
                    if isinstance(chunk, dict):
                        yield f"data: {json.dumps({'provider': chunk.get('provider', '')})}\n\n"
                        continue
                    full += chunk
                    if suppressed is True:
                        continue  # accumulating a tool tag silently, nothing to show yet
                    if suppressed is False:
                        yield f"data: {json.dumps({'chunk': chunk, 'done': False})}\n\n"
                        continue
                    # Undecided: buffer a few chars to see if this looks like [TOOL:...
                    buf += chunk
                    if buf.lstrip().startswith("[TOOL:"):
                        suppressed = True
                    elif len(buf) >= 8 or "\n" in buf:
                        suppressed = False
                        yield f"data: {json.dumps({'chunk': buf, 'done': False})}\n\n"
                        buf = ""
                if suppressed is None and buf:
                    # Reply ended before we hit the decision threshold — flush it.
                    yield f"data: {json.dumps({'chunk': buf, 'done': False})}\n\n"

                tool_calls = find_tool_calls(full)
                if not tool_calls:
                    final_full = full
                    break

                yield f"data: {json.dumps({'chunk': '', 'done': False, 'tool': True})}\n\n"
                tool_results = []
                for tool_name, tool_arg in tool_calls:
                    yield f"data: {json.dumps({'chunk': '', 'done': False, 'tool_status': f'Running {tool_name}...', 'tool_name': tool_name})}\n\n"
                    result = execute_tool_call(tool_name, tool_arg)
                    tool_results.append(f"[{tool_name} result]: {result}")
                    yield f"data: {json.dumps({'chunk': '', 'done': False, 'tool_status': f'{tool_name} done', 'tool_name': tool_name})}\n\n"

                # Extend this turn's scratch context only — tool-result blobs
                # aren't persisted into long-term session history, so a chatty
                # search->fetch chain doesn't bloat every future turn's context.
                round_messages = round_messages + [
                    {"role": "assistant", "content": full},
                    {"role": "user", "content": "Tool results:\n" + "\n\n".join(tool_results) +
                        "\n\nAnswer the user now using these results. Only emit another "
                        "[TOOL:...] tag if you genuinely still need more information."}
                ]
            else:
                final_full = "I couldn't finish gathering results for that — try narrowing the question."
                yield f"data: {json.dumps({'chunk': final_full, 'done': False})}\n\n"

            if final_full:
                add_to_history(sid, "assistant", final_full)
            yield f"data: {json.dumps({'chunk': '', 'done': True, 'full': final_full or ''})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'chunk': f'Error: {e}', 'done': True})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ── Regular chat with memory + tools ─────────────────────────────
@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json() or {}
    message = data.get("message", "")
    sid = data.get("session_id", "default")
    if not message:
        return jsonify({"error": "No message"}), 400
    msg = message.lower().strip()

    # Built-in commands
    if msg in ("status", "saom status"):
        r = run_command(_saom_cmd("status"), timeout=10)
        return jsonify({"response": format_response(r["stdout"], r["stderr"], r["returncode"])})
    if msg in ("init", "saom init"):
        r = run_command(_saom_cmd("init"), timeout=10)
        return jsonify({"response": r["stdout"] or "Memory initialized."})
    if msg.startswith("pulse start"):
        r = run_command(_saom_cmd("pulse", "start"), timeout=10)
        return jsonify({"response": format_response(r["stdout"], r["stderr"])})
    if msg.startswith("pulse end"):
        r = run_command(_saom_cmd("pulse", "end"), timeout=10)
        return jsonify({"response": format_response(r["stdout"], r["stderr"])})
    if msg.startswith("pulse status") or msg == "pulse":
        r = run_command(_saom_cmd("pulse", "status"), timeout=10)
        return jsonify({"response": format_response(r["stdout"], r["stderr"])})
    if msg.startswith("pre "):
        task = message.split(" ", 1)[1].strip()
        r = run_command(_saom_cmd("pre", task), timeout=15)
        return jsonify({"response": format_response(r["stdout"], r["stderr"], r["returncode"])})
    if msg.startswith("post "):
        parts = message.split(" ", 2)
        summary = parts[1] if len(parts) > 1 else ""
        outcome = parts[2] if len(parts) > 2 and parts[2] in ("success", "failure") else "success"
        r = run_command(_saom_cmd("post", summary, outcome), timeout=15)
        return jsonify({"response": format_response(r["stdout"], r["stderr"], r["returncode"])})

    # Tool calls
    tool = detect_tool_call(message)
    if tool:
        result = execute_tool(tool[0], tool[1])
        add_to_history(sid, "user", message)
        add_to_history(sid, "assistant", result)
        return jsonify({"response": result})

    # LLM with memory + auto tools
    seed_session_if_empty(sid, data.get("history"))
    add_to_history(sid, "user", message)
    round_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + get_context_messages(sid)

    try:
        final_reply = None
        for round_num in range(MAX_TOOL_ROUNDS):
            reply = _call_llm(round_messages)
            reply = reply.encode("ascii", "replace").decode("ascii")

            tool_calls = find_tool_calls(reply)
            if not tool_calls:
                final_reply = reply
                break

            tool_results = []
            for tool_name, tool_arg in tool_calls:
                result = execute_tool_call(tool_name, tool_arg)
                tool_results.append(f"[{tool_name} result]: {result}")

            round_messages = round_messages + [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": "Tool results:\n" + "\n\n".join(tool_results) +
                    "\n\nAnswer the user now using these results. Only emit another "
                    "[TOOL:...] tag if you genuinely still need more information."}
            ]
        else:
            final_reply = "I couldn't finish gathering results for that — try narrowing the question."

        add_to_history(sid, "assistant", final_reply)
        return jsonify({"response": final_reply})
    except Exception as e:
        return jsonify({"response": f"Error: {e}"})

# ── Other routes ─────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/status")
def api_status():
    r = run_command(_saom_cmd("status"))
    try:
        return jsonify(json.loads(r["stdout"]))
    except:
        return jsonify({"error": r["stderr"]})

@app.route("/api/init", methods=["POST"])
def api_init():
    r = run_command(_saom_cmd("init"))
    return jsonify({"response": r["stdout"] or "Memory initialized.", "error": r["stderr"]})

@app.route("/api/pre", methods=["POST"])
def api_pre():
    data = request.get_json() or {}
    task = data.get("task", "")
    if not task:
        return jsonify({"error": "No task"}), 400
    r = run_command(_saom_cmd("pre", task), timeout=15)
    return jsonify({"response": format_response(r["stdout"], r["stderr"], r["returncode"])})

@app.route("/api/post", methods=["POST"])
def api_post():
    data = request.get_json() or {}
    summary = data.get("summary", "")
    outcome = data.get("outcome", "success")
    if not summary:
        return jsonify({"error": "No summary"}), 400
    r = run_command(_saom_cmd("post", summary, outcome), timeout=15)
    return jsonify({"response": format_response(r["stdout"], r["stderr"], r["returncode"])})

@app.route("/api/pulse/<mode>", methods=["POST"])
def api_pulse(mode):
    if mode == "start":
        r = run_command(_saom_cmd("pulse", "start"), timeout=10)
    elif mode == "end":
        r = run_command(_saom_cmd("pulse", "end"), timeout=10)
    elif mode == "status":
        r = run_command(_saom_cmd("pulse", "status"), timeout=10)
    else:
        return jsonify({"error": f"Unknown mode: {mode}"}), 400
    return jsonify({"response": format_response(r["stdout"], r["stderr"], r["returncode"])})

@app.route("/api/run", methods=["POST"])
def api_run():
    data = request.get_json() or {}
    tool = data.get("tool", "")
    args = data.get("args", [])
    if not tool:
        return jsonify({"error": "No tool"}), 400
    r = run_command(_saom_cmd("run", tool, *args), timeout=15)
    return jsonify({"response": format_response(r["stdout"], r["stderr"], r["returncode"])})

if __name__ == "__main__":
    print(f"[WEB] SAOM Dashboard starting on http://localhost:5000")
    print(f"[WEB] Memory directory: {MEMORY_DIR}")
    app.run(host="0.0.0.0", port=5000, debug=False)
