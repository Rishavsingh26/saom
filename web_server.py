import json, os, subprocess, sys, re, threading, time, platform
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, render_template, Response, stream_with_context

BASE_DIR = Path(__file__).parent
SAOM_DIR = BASE_DIR / "saom"
MEMORY_DIR = Path.home() / ".saom" / "memory"

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"), static_folder=str(BASE_DIR / "static"))
app.secret_key = os.urandom(24)

# ── Conversation memory ──────────────────────────────────────────
conversations = {}
MAX_HISTORY = 20

def get_history(sid):
    if sid not in conversations:
        conversations[sid] = []
    return conversations[sid]

def add_to_history(sid, role, content):
    h = get_history(sid)
    h.append({"role": role, "content": content})
    if len(h) > MAX_HISTORY:
        conversations[sid] = h[-MAX_HISTORY:]

# ── System prompt (with auto tools) ──────────────────────────────
SYSTEM_PROMPT = """You are SAOM v12, AI assistant by Om. Be concise. Code only unless asked."""

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
    """Non-streaming LLM call with fallback."""
    for chunk in _call_llm_stream(messages, max_tokens, temp):
        pass
    return chunk if chunk else "[Error]"

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

# ── Web search (DuckDuckGo, free) ────────────────────────────────
@app.route("/api/web/search", methods=["POST"])
def api_web_search():
    data = request.get_json() or {}
    query = data.get("query", "")
    max_results = data.get("max_results", 5)
    if not query:
        return jsonify({"error": "No query"}), 400
    try:
        from ddgs import DDGS
        results = DDGS().text(query, max_results=max_results)
        formatted = []
        for i, r in enumerate(results, 1):
            formatted.append(f"{i}. {r.get('title', 'No title')}\n   {r.get('body', 'No description')}\n   {r.get('href', '')}")
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
    try:
        import requests as req_lib
        headers = {"User-Agent": "Mozilla/5.0 (compatible; SAOM/1.0)"}
        r = req_lib.get(url, headers=headers, timeout=15, allow_redirects=True)
        content = r.text[:max_chars]
        # Simple HTML tag removal
        clean = re.sub(r'<[^>]+>', ' ', content)
        clean = re.sub(r'\s+', ' ', clean).strip()
        return jsonify({"content": clean[:max_chars], "status": r.status_code, "url": url})
    except Exception as e:
        return jsonify({"error": str(e)})

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

# ── Detect tool calls in message ─────────────────────────────────
def detect_tool_call(message):
    msg = message.strip()
    if msg.lower().startswith("search "):
        return ("search", msg[7:].strip())
    if msg.lower().startswith("fetch "):
        return ("fetch", msg[6:].strip())
    return None

def execute_tool(tool_name, arg):
    if tool_name == "search":
        try:
            from ddgs import DDGS
            results = DDGS().text(arg, max_results=5)
            formatted = []
            for i, r in enumerate(results, 1):
                formatted.append(f"{i}. {r.get('title', '')}\n   {r.get('body', '')}\n   {r.get('href', '')}")
            return "\n\n".join(formatted) if formatted else "No results found."
        except Exception as e:
            return f"Search error: {e}"
    if tool_name == "fetch":
        try:
            import requests as req_lib
            r = req_lib.get(arg, headers={"User-Agent": "SAOM/1.0"}, timeout=15)
            content = re.sub(r'<[^>]+>', ' ', r.text)
            content = re.sub(r'\s+', ' ', content).strip()
            return content[:5000] if content else "Empty page."
        except Exception as e:
            return f"Fetch error: {e}"
    return "Unknown tool."

# ── Detect tool calls in LLM response ────────────────────────────
import re

def find_tool_calls(text):
    """Find [TOOL:name:arg] patterns in text."""
    pattern = r'\[TOOL:(\w+):([^\]]+)\]'
    return re.findall(pattern, text)

def execute_tool_call(tool_name, arg):
    """Execute a tool call and return result."""
    if tool_name == "search":
        try:
            from ddgs import DDGS
            results = DDGS().text(arg, max_results=5)
            formatted = []
            for i, r in enumerate(results, 1):
                formatted.append(f"{i}. {r.get('title', '')}\n   {r.get('body', '')}\n   {r.get('href', '')}")
            return "\n\n".join(formatted) if formatted else "No results found."
        except Exception as e:
            return f"Search error: {e}"
    if tool_name == "fetch":
        try:
            import requests as req_lib
            r = req_lib.get(arg, headers={"User-Agent": "SAOM/1.0"}, timeout=15)
            content = re.sub(r'<[^>]+>', ' ', r.text)
            content = re.sub(r'\s+', ' ', content).strip()
            return content[:5000] if content else "Empty page."
        except Exception as e:
            return f"Fetch error: {e}"
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
        add_to_history(sid, "user", message)
        history = get_history(sid)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for m in history:
            messages.append({"role": m["role"], "content": m["content"]})

        try:
            full = ""
            for chunk in _call_llm_stream(messages):
                if isinstance(chunk, dict):
                    # Provider info — send to client
                    yield f"data: {json.dumps({'provider': chunk.get('provider', '')})}\n\n"
                    continue
                if "<tool_call>" in chunk or "function_call" in chunk:
                    continue
                full += chunk
                yield f"data: {json.dumps({'chunk': chunk, 'done': False})}\n\n"

            # Check for tool calls in response
            tool_calls = find_tool_calls(full)
            if tool_calls:
                yield f"data: {json.dumps({'chunk': '', 'done': False, 'tool': True})}\n\n"
                # Execute each tool call
                tool_results = []
                for tool_name, tool_arg in tool_calls:
                    yield f"data: {json.dumps({'chunk': '', 'done': False, 'tool_status': f'Running {tool_name}...', 'tool_name': tool_name})}\n\n"
                    result = execute_tool_call(tool_name, tool_arg)
                    tool_results.append(f"[{tool_name} result]: {result}")
                    yield f"data: {json.dumps({'chunk': '', 'done': False, 'tool_status': f'{tool_name} done', 'tool_name': tool_name})}\n\n"

                # Feed results back to LLM for summary
                add_to_history(sid, "assistant", full)
                add_to_history(sid, "user", "Tool results:\n" + "\n".join(tool_results))
                messages2 = [{"role": "system", "content": "Summarize these tool results concisely for the user."}]
                for m in get_history(sid)[-8:]:
                    messages2.append({"role": m["role"], "content": m["content"]})
                try:
                    full2 = ""
                    for chunk in _call_llm_stream(messages2):
                        full2 += chunk
                        yield f"data: {json.dumps({'chunk': chunk, 'done': False})}\n\n"
                    if full2:
                        add_to_history(sid, "assistant", full2)
                    yield f"data: {json.dumps({'chunk': '', 'done': True, 'full': full2})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'chunk': '', 'done': True, 'full': full})}\n\n"
            else:
                if full:
                    add_to_history(sid, "assistant", full)
                yield f"data: {json.dumps({'chunk': '', 'done': True, 'full': full})}\n\n"
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
    add_to_history(sid, "user", message)
    history = get_history(sid)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})

    try:
        reply = _call_llm(messages)
        reply = reply.encode("ascii", "replace").decode("ascii")

        # Check for tool calls
        tool_calls = find_tool_calls(reply)
        if tool_calls:
            tool_results = []
            for tool_name, tool_arg in tool_calls:
                result = execute_tool_call(tool_name, tool_arg)
                tool_results.append(f"[{tool_name} result]: {result}")
            # Feed results back to LLM
            add_to_history(sid, "assistant", reply)
            add_to_history(sid, "user", "Tool results:\n" + "\n".join(tool_results))
            messages2 = [{"role": "system", "content": "Summarize these tool results concisely."}]
            for m in get_history(sid)[-8:]:
                messages2.append({"role": m["role"], "content": m["content"]})
            reply2 = _call_llm(messages2)
            reply2 = reply2.encode("ascii", "replace").decode("ascii")
            add_to_history(sid, "assistant", reply2)
            return jsonify({"response": reply2})

        add_to_history(sid, "assistant", reply)
        return jsonify({"response": reply})
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
