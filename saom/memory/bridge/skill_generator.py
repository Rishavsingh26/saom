"""Autonomous Skill Generator.
Reads failure patterns from lessons or direct params and writes new SKILL.md
files to .opencode/skills/<name>/. Registers in registry.json and init.json.

Uses a separate LLM call (not the main assistant). Token-limited: keeps
input prompts under 250 tokens, output under 500 tokens.

Usage:
  python skill_generator.py generate "<summary>" "<root_cause>" "<fix>"
  python skill_generator.py auto  -- scans lessons.jsonl for failures to fix
  python skill_generator.py status
"""
import json, os, re, sys, urllib.request
from datetime import datetime, timezone

BRIDGE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(BRIDGE)  # memory/
SKILLS_BASE = os.path.dirname(BASE)   # saom/
PROJECT_SKILLS = os.path.abspath(os.path.join(BRIDGE, "..", "..", "..", "..", ".."))  # Codex/
REGISTRY_PATH = os.path.join(BASE, "skills", "registry.json")
INIT_PATH = os.path.join(BASE, "init.json")
LESSONS_PATH = os.path.join(BASE, "lessons", "lessons.jsonl")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
MODEL = "openai/gpt-oss-20b"
UA = "Mozilla/5.0 (compatible; SAOM-bot/1.0)"


def _llm(prompt):
    if not GROQ_KEY:
        return "ERROR: no GROQ_API_KEY"
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 600, "temperature": 0.3
    }).encode()
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json", "User-Agent": UA},
        method="POST"
    )
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
        return resp['choices'][0]['message']['content'].strip()
    except Exception as e:
        return f"ERROR: {e}"


def load_json(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return default if default is not None else {}


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _safe_filename(name):
    return re.sub(r'[^a-z0-9_-]', '', name.lower().replace(' ', '-'))[:40]


def existing_skill_names():
    """Return set of existing skill names from registry."""
    reg = load_json(REGISTRY_PATH, {})
    skills = reg.get("skills", [])
    # Also check init.json
    init = load_json(INIT_PATH, {})
    loaded = init.get("loaded_skills", [])
    names = set()
    for s in skills:
        if isinstance(s, dict):
            names.add(s.get("name", ""))
        elif isinstance(s, str):
            names.add(s)
    for s in loaded:
        if isinstance(s, dict):
            names.add(s.get("name", ""))
        elif isinstance(s, str):
            names.add(s)
    # Also scan filesystem
    sk_dir = os.path.join(PROJECT_SKILLS, ".opencode", "skills")
    if os.path.isdir(sk_dir):
        for d in os.listdir(sk_dir):
            names.add(d)
    return names


def generate(summary, root_cause, fix):
    """Generate a SKILL.md from failure pattern. Returns path or error."""
    existing = existing_skill_names()

    prompt = (
        f"Failure: {summary[:150]}\n"
        f"Cause: {root_cause[:150]}\n"
        f"Fix: {fix[:200]}\n\n"
        "Create a concise SKILL.md that prevents this. "
        "Output ONLY:\n"
        "---\n"
        "name: <short-name>\n"
        "description: <1 sentence, max 200 chars>\n"
        "---\n"
        "<3-5 bullet instructions>"
    )

    raw = _llm(prompt)
    if raw.startswith("ERROR"):
        return {"error": raw}

    # Validate and parse frontmatter
    fmm = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)', raw, re.DOTALL)
    if not fmm:
        # Try to construct basic frontmatter
        name = _safe_filename(summary.split()[0] if summary.split() else "new-skill")
        desc = summary[:150]
        body = raw[:600]
        skill_name = name
        content = f"---\nname: {name}\ndescription: {desc}\n---\n\n{body}"
    else:
        meta = fmm.group(1)
        body = fmm.group(2).strip()
        m_name = re.search(r'name:\s*(\S+)', meta)
        m_desc = re.search(r'description:\s*(.+)', meta)
        skill_name = m_name.group(1) if m_name else _safe_filename(summary.split()[0] if summary.split() else "new-skill")
        desc = m_desc.group(1).strip() if m_desc else summary[:150]
        content = f"---\nname: {skill_name}\ndescription: {desc}\n---\n\n{body[:600]}"

    # Check for conflicts
    if skill_name in existing:
        skill_name = f"{skill_name}-v2"
        content = content.replace(
            f"name: {_safe_filename(skill_name.replace('-v2',''))}",
            f"name: {skill_name}",
            1
        )

    # Write SKILL.md to project .opencode/skills/
    skill_dir = os.path.join(PROJECT_SKILLS, ".opencode", "skills", skill_name)
    os.makedirs(skill_dir, exist_ok=True)
    skill_path = os.path.join(skill_dir, "SKILL.md")
    with open(skill_path, "w", encoding="utf-8") as f:
        f.write(content)

    # Register in registry.json
    reg = load_json(REGISTRY_PATH, {"skills": []})
    reg["skills"].append({
        "name": skill_name,
        "path": f".opencode/skills/{skill_name}/SKILL.md",
        "origin": "auto-generated",
        "quality_score": None,
        "use_count": 0,
        "success_count": 0,
        "last_used": None,
        "avg_confidence": None
    })
    save_json(REGISTRY_PATH, reg)

    # Register in init.json loaded_skills
    init = load_json(INIT_PATH, {"loaded_skills": [], "tools": []})
    init["loaded_skills"].append(skill_name)
    save_json(INIT_PATH, init)

    result = {
        "skill_name": skill_name,
        "path": skill_path,
        "description": desc,
        "registered": True
    }
    print(json.dumps(result, indent=2))
    return result


def auto():
    """Scan lessons for unaddressed failures, generate skills for them."""
    if not os.path.exists(LESSONS_PATH):
        print(json.dumps({"error": "No lessons file found", "generated": 0}))
        return

    lessons = []
    with open(LESSONS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    lessons.append(json.loads(line))
                except:
                    pass

    failures = [l for l in lessons if l.get("outcome") == "failure" and l.get("severity") in ("warning", "critical", "key")]
    if not failures:
        print(json.dumps({"message": "No unaddressed failures found", "generated": 0}))
        return

    generated = []
    existing = existing_skill_names()
    for f in failures[:5]:
        summary = f.get("summary", "")[:150]
        rc = f.get("root_cause", "")[:150]
        fix = f.get("fix", "")[:200]
        if not summary or not rc:
            continue
        # Check if a skill already covers this
        if any(summary[:30].lower() in (s.lower() for s in existing) for s in [summary]):
            continue
        try:
            r = generate(summary, rc, fix)
            if r.get("skill_name"):
                generated.append(r["skill_name"])
        except Exception as e:
            pass

    result = {"generated": len(generated), "skills": generated, "source_failures": len(failures)}
    print(json.dumps(result, indent=2))
    return result


def status():
    reg = load_json(REGISTRY_PATH, {})
    skills = reg.get("skills", [])
    auto_skills = [s for s in skills if isinstance(s, dict) and s.get("origin") == "auto-generated"]
    result = {
        "total_skills": len(skills),
        "auto_generated": len(auto_skills),
        "auto_skills": [s.get("name", "?") for s in auto_skills]
    }
    print(json.dumps(result, indent=2))
    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: python skill_generator.py <generate|auto|status> [args]")
        sys.exit(1)
    mode = sys.argv[1]
    if mode == "generate":
        summary = sys.argv[2] if len(sys.argv) > 2 else ""
        root_cause = sys.argv[3] if len(sys.argv) > 3 else ""
        fix = sys.argv[4] if len(sys.argv) > 4 else ""
        generate(summary, root_cause, fix)
    elif mode == "auto":
        auto()
    elif mode == "status":
        status()
    else:
        print(f"Unknown mode: {mode}")


if __name__ == "__main__":
    main()
