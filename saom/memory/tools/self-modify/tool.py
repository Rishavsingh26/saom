import json
import sys
import os
import shutil
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAOM_DIR = os.path.dirname(BASE)
LESSONS_PATH = os.path.join(BASE, "lessons", "lessons.jsonl")
REGISTRY_PATH = os.path.join(BASE, "tools", "registry.json")
SKILL_TRACKER_PATH = os.path.join(BASE, "skills", "registry.json")
DESIGNS_DIR = os.path.join(BASE, "designs")
ARCHIVE_DIR = os.path.join(DESIGNS_DIR, "self-modify-archive")
HISTORY_PATH = os.path.join(ARCHIVE_DIR, "history.json")

def ensure_dirs():
    os.makedirs(ARCHIVE_DIR, exist_ok=True)

def load_history():
    ensure_dirs()
    if os.path.exists(HISTORY_PATH):
        with open(HISTORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"modifications": []}

def save_history(history):
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)

def load_lessons():
    if not os.path.exists(LESSONS_PATH):
        return []
    lessons = []
    with open(LESSONS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                lessons.append(json.loads(line))
    return lessons

def load_skill_registry():
    with open(SKILL_TRACKER_PATH, encoding="utf-8") as f:
        return json.load(f)

def find_behavioral_gaps():
    lessons = load_lessons()
    failures = [l for l in lessons if l.get("outcome") == "failure"]
    if len(failures) < 2:
        return []

    patterns = {}
    keywords = ["rate limit", "timeout", "auth", "download", "password", "install", "windows",
                "node", "wsl", "env var", "environment variable", "registry", "scope", "api_key",
                "groq", "tested wrong", "untested", "didn't test", "401", "unauthorized",
                "keyword", "not found", "no module", "import error", "syntax error",
                "empty", "null", "none", "missing", "not set", "api"]
    keywords.sort(key=len, reverse=True)
    for l in failures:
        summary = l.get("summary", "").lower()
        root_cause = l.get("root_cause", "").lower()
        combined = summary + " " + root_cause
        for kw in keywords:
            if kw in combined:
                patterns.setdefault(kw, []).append(l)
    return [{"pattern": k, "lessons": v} for k, v in patterns.items() if len(v) >= 2]

def find_target_file(pattern):
    mapping = {
        "rate limit": "sub-skills/loops.md",
        "timeout": "sub-skills/loops.md",
        "auth": "SKILL.md",
        "download": "sub-skills/loops.md",
        "api": "SKILL.md",
        "install": "SKILL.md",
        "windows": "SKILL.md",
        "wsl": "SKILL.md",
        "env var": "SKILL.md",
        "environment variable": "SKILL.md",
        "registry": "SKILL.md",
        "scope": "SKILL.md",
        "api_key": "SKILL.md",
        "groq": "SKILL.md",
        "tested wrong": "SKILL.md",
        "untested": "SKILL.md",
        "401": "SKILL.md",
        "unauthorized": "SKILL.md",
        "missing": "SKILL.md",
        "not set": "SKILL.md",
    }
    relative = mapping.get(pattern, "SKILL.md")
    target = os.path.join(SAOM_DIR, relative)
    if os.path.exists(target):
        return target, relative
    return None, None

def generate_suggestion(pattern, lessons):
    root_causes = set()
    for l in lessons:
        rc = l.get("root_cause", "")
        if rc and rc != "N/A":
            root_causes.add(rc[:120])
    summaries = [l.get("summary", "")[:80] for l in lessons]

    suggestions = {
        "rate limit": "Add a retry-with-backoff utility before any network call. Check if the target has rate limiting and implement exponential backoff (1s, 2s, 4s...) up to 3 retries.",
        "timeout": "Set explicit timeouts on all network calls. Default: 30s for API calls, 120s for downloads. Log and retry once on timeout.",
        "auth": "Before any auth-dependent task, verify the auth method is available (cookie file, logged-in browser, API key). If not available, abort early instead of failing mid-task.",
        "download": "Before downloading, check: (1) is the file local already? (2) is the tool installed? (3) is there enough disk space? Use aria2c or yt-dlp, not requests, for large files.",
        "api": "Before calling any external API, verify: endpoint is reachable, API key is set, rate limit not hit. Log the request URL and response code for debugging.",
        "install": "Before suggesting any install, use `tool-forager` to check if the tool exists. Verify platform compatibility (Windows/Linux). Never suggest Windows feature installs (WSL, Hyper-V).",
        "wsl": "NEVER suggest WSL or Hyper-V installation. These modify core OS components and can break PowerShell/console input. Use portable Python scripts instead.",
        "env var": "When setting env vars on Windows: (1) set BOTH Process scope ($env:VAR) and User scope ([Environment]::SetEnvironmentVariable). (2) Always verify with `python -c \"import os; print(os.environ.get('VAR', 'MISSING'))\"`. (3) Add registry fallback in the consuming script.",
        "environment variable": "When setting env vars on Windows: (1) set BOTH Process scope ($env:VAR) and User scope ([Environment]::SetEnvironmentVariable). (2) Always verify with `python -c \"import os; print(os.environ.get('VAR', 'MISSING'))\"`. (3) Add registry fallback in the consuming script.",
        "scope": "When setting env vars on Windows: (1) set BOTH Process scope ($env:VAR) and User scope ([Environment]::SetEnvironmentVariable). (2) Always verify with `python -c \"import os; print(os.environ.get('VAR', 'MISSING'))\"`.",
        "api_key": "Before using any API key: (1) verify it's set by reading env var, not hardcoding. (2) Test the env var path, not the literal key. (3) Add fallback for registry/file if Windows env var might not be in current process.",
        "groq": "Before using any API key: (1) verify it's set by reading env var, not hardcoding. (2) Test the env var path, not the literal key. (3) Add fallback for registry/file if Windows env var might not be in current process.",
        "401": "Before using any API key: (1) verify it's set by reading env var, not hardcoding. (2) Test the env var path, not the literal key. (3) Add fallback for registry/file if Windows env var might not be in current process.",
        "unauthorized": "Before using any API key: (1) verify it's set by reading env var, not hardcoding. (2) Test the env var path, not the literal key. (3) Add fallback for registry/file if Windows env var might not be in current process.",
        "untested": "Before presenting any code or fix: (1) run `python _failures.py <topic>` to check past failures. (2) Run the actual script (not just syntax check). (3) Test the env/path the script will use, not a hardcoded value.",
        "tested wrong": "Before presenting any code or fix: (1) run `python _failures.py <topic>` to check past failures. (2) Run the actual script (not just syntax check). (3) Test the env/path the script will use, not a hardcoded value.",
        "missing": "Before reporting something as missing, verify: (1) it's not in a different path. (2) the env var isn't set in a different scope. (3) the tool isn't installed under a different name.",
        "not set": "Before reporting something as not set, verify: (1) check both Process and User env var scopes on Windows. (2) check registry fallback. (3) check config files.",
    }

    # Use the pattern's suggestion or a generic one
    suggestion = suggestions.get(pattern, "Add a guardrail check before attempting this type of operation again.")

    return {
        "pattern": pattern,
        "occurrences": len(lessons),
        "evidence": summaries,
        "root_causes": list(root_causes)[:3],
        "suggestion": suggestion,
        "confidence": min(len(lessons) * 20, 90)
    }

def propose():
    gaps = find_behavioral_gaps()
    if not gaps:
        for entry in load_skill_registry().get("skills", []):
            uc = entry.get("use_count", 0)
            sc = entry.get("success_count", 0)
            if uc >= 3 and sc / uc < 0.3:
                gaps.append({"pattern": f"skill:{entry['name']}", "lessons": []})

    if not gaps:
        return {"proposals": [], "message": "No recurring failure patterns found. Need 2+ similar failures to propose a fix."}

    proposals = []
    for idx, gap in enumerate(gaps, 1):
        target_path, relative = find_target_file(gap["pattern"]) if gap["pattern"] != "skill:" else (None, None)
        suggestion_data = generate_suggestion(gap["pattern"], gap["lessons"])
        proposals.append({
            "proposal_id": idx,
            "target_file": relative or "SKILL.md",
            "target_path": target_path,
            "pattern": suggestion_data["pattern"],
            "occurrences": suggestion_data["occurrences"],
            "evidence": suggestion_data["evidence"][:5],
            "root_causes": suggestion_data["root_causes"],
            "suggestion": suggestion_data["suggestion"],
            "confidence": suggestion_data["confidence"]
        })
    return {"proposals": proposals, "message": f"Found {len(proposals)} improvement suggestion(s)"}

def archive_file(filepath):
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    basename = os.path.basename(filepath)
    rel = os.path.relpath(filepath, SAOM_DIR).replace(os.sep, "_")
    archive_name = f"{rel}_{ts}"
    archive_path = os.path.join(ARCHIVE_DIR, archive_name)
    shutil.copy2(filepath, archive_path)
    return archive_path

def apply_modification(proposal_id):
    proposals_data = propose()
    proposals = proposals_data.get("proposals", [])
    if proposal_id < 1 or proposal_id > len(proposals):
        return {"error": f"Invalid proposal_id {proposal_id}. Valid: 1-{len(proposals)}"}
    prop = proposals[proposal_id - 1]

    target_path = prop.get("target_path")
    if not target_path or not os.path.exists(target_path):
        return {"error": f"Target file not found: {target_path}"}

    # Archive original
    archive_path = archive_file(target_path)
    with open(target_path, encoding="utf-8") as f:
        original_content = f.read()

    # Build patch: add a safety comment before the first code block or after mode table
    suggestion = prop["suggestion"]
    pattern = prop["pattern"]

    # Insert as a safety rule comment
    if "## Safety Rules" in original_content:
        parts = original_content.split("## Safety Rules")
        new_rule = f"- {suggestion} (auto-added by self-modify based on {pattern} failure pattern)"
        modified = parts[0] + "## Safety Rules\n\n" + new_rule + "\n" + parts[1]
    else:
        # Append to end
        modified = original_content + f"\n# Auto-added safety rule\n# {suggestion}\n"

    with open(target_path, "w", encoding="utf-8") as f:
        f.write(modified)

    history = load_history()
    history["modifications"].append({
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "proposal_id": proposal_id,
        "target_file": prop["target_file"],
        "archive_path": archive_path,
        "pattern": pattern,
        "suggestion": suggestion
    })
    save_history(history)

    return {
        "applied": True,
        "target_file": prop["target_file"],
        "archive_path": archive_path,
        "suggestion": suggestion,
        "modification_count": len(history["modifications"])
    }

def rollback(target_file=None):
    history = load_history()
    mods = history["modifications"]

    if not target_file:
        return {"modifications": mods[-5:] if mods else [], "total": len(mods)}

    # Find latest modification for this file
    relevant = [m for m in mods if m["target_file"] == target_file]
    if not relevant:
        return {"error": f"No modifications found for {target_file}"}

    last = relevant[-1]
    archive_path = last["archive_path"]
    target_full = os.path.join(SAOM_DIR, target_file)
    if not os.path.exists(archive_path):
        return {"error": f"Archive not found: {archive_path}"}

    shutil.copy2(archive_path, target_full)
    return {"rolled_back": True, "file": target_file, "from_archive": archive_path}

def history():
    history_data = load_history()
    mods = history_data.get("modifications", [])
    return {
        "modifications": [
            {
                "id": i + 1,
                "timestamp": m["timestamp"],
                "target_file": m["target_file"],
                "pattern": m.get("pattern", "N/A"),
                "suggestion": m.get("suggestion", "")[:100]
            }
            for i, m in enumerate(mods)
        ],
        "total": len(mods)
    }

def main():
    if len(sys.argv) < 2:
        result = propose()
        print(json.dumps(result, indent=2))
        return
    mode = sys.argv[1]

    if mode == "propose":
        result = propose()
        print(json.dumps(result, indent=2))

    elif mode == "apply":
        if len(sys.argv) < 3:
            print("Usage: python tool.py apply <proposal_id>")
            sys.exit(1)
        result = apply_modification(int(sys.argv[2]))
        print(json.dumps(result, indent=2))

    elif mode == "rollback":
        target = sys.argv[2] if len(sys.argv) > 2 else None
        result = rollback(target)
        print(json.dumps(result, indent=2))

    elif mode == "history":
        result = history()
        print(json.dumps(result, indent=2))

    else:
        print(f"Unknown mode: {mode}")

if __name__ == "__main__":
    main()
