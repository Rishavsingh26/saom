import json
import sys
import os
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLAN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plan.json")
REGISTRY_PATH = os.path.join(BASE, "skills", "registry.json")
TOOLS_REGISTRY_PATH = os.path.join(BASE, "tools", "registry.json")
SKILL_DIR = os.path.join(os.path.dirname(os.path.dirname(BASE)), "skills")
NODES_PATH = os.path.join(BASE, "graph", "nodes.json")
EDGES_PATH = os.path.join(BASE, "graph", "edges.json")

def load_json(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None

def load_plan():
    return load_json(PLAN_PATH) or {"tracks": [], "version": "1.0"}

def load_skill_registry():
    return load_json(REGISTRY_PATH) or {"skills": []}

def load_tool_registry():
    return load_json(TOOLS_REGISTRY_PATH) or {"tools": []}

def build_skill_map():
    plan = load_plan()
    registry = load_skill_registry()
    tool_reg = load_tool_registry()
    reg_map = {s["name"]: s for s in registry.get("skills", [])}
    tool_map = {t["name"]: t for t in tool_reg.get("tools", [])}

    skill_map = {}
    for track in plan.get("tracks", []):
        for s in track.get("skills", []):
            name = s["name"]
            reg = reg_map.get(name, {})
            tool = tool_map.get(name, {})
            is_tool = bool(tool)
            if is_tool:
                uc = (tool.get("success_count", 0) + tool.get("failure_count", 0)) if name in tool_map else 0
                sc = tool.get("success_count", 0)
                lu = tool.get("last_used")
            else:
                uc = reg.get("use_count", 0)
                sc = reg.get("success_count", 0)
                lu = reg.get("last_used")
            skill_map[name] = {
                "name": name,
                "difficulty": s["difficulty"],
                "prerequisites": s.get("prerequisites", []),
                "track": track["name"],
                "track_label": track.get("label", track["name"]),
                "use_count": uc,
                "success_count": sc,
                "avg_confidence": reg.get("avg_confidence"),
                "last_used": lu,
                "is_tool": is_tool
            }
    return skill_map

def compute_mastery(skill_info):
    uc = skill_info.get("use_count", 0)
    sc = skill_info.get("success_count", 0)
    if uc == 0:
        return {"level": "unused", "mastery": 0.0, "uses": 0}
    success_rate = sc / uc if uc > 0 else 0
    plan = load_plan()
    mc = plan.get("mastery_config", {})
    target_uses = mc.get("uses_for_mastery", 5)
    target_rate = mc.get("min_success_rate", 0.7)

    uses_factor = min(1.0, uc / target_uses)
    rate_factor = min(1.0, success_rate / target_rate) if target_rate > 0 else 0
    mastery = round((uses_factor * 0.4 + rate_factor * 0.6) * 100)

    if mastery >= 90:
        level = "mastered"
    elif mastery >= 60:
        level = "proficient"
    elif mastery >= 30:
        level = "learning"
    elif mastery > 0:
        level = "novice"
    else:
        level = "unused"

    return {"level": level, "mastery": mastery, "uses": uc, "success_rate": round(success_rate * 100)}

def path_to_skill(target_skill):
    skill_map = build_skill_map()
    if target_skill not in skill_map:
        return {"error": f"Skill '{target_skill}' not found in curriculum", "available": sorted(skill_map.keys())}

    target = skill_map[target_skill]
    visited = set()
    def resolve_prereqs(name, depth=0):
        if name not in skill_map or depth > 10:
            return []
        info = skill_map[name]
        prereqs = []
        for p in info["prerequisites"]:
            if p in visited:
                continue
            visited.add(p)
            prereqs.extend(resolve_prereqs(p, depth + 1))
            prereqs.append(p)
        return prereqs

    all_prereqs = resolve_prereqs(target_skill)
    path = []
    seen = set()
    for p in all_prereqs:
        if p not in seen:
            seen.add(p)
            info = skill_map[p]
            path.append({
                "skill": p,
                "track": info["track_label"],
                "difficulty": info["difficulty"],
                "mastery": compute_mastery(info)
            })

    path.append({
        "skill": target_skill,
        "track": target["track_label"],
        "difficulty": target["difficulty"],
        "mastery": compute_mastery(target)
    })

    return {
        "target": target_skill,
        "path_length": len(path),
        "avg_difficulty": round(sum(s["difficulty"] for s in path) / len(path), 1),
        "path": path
    }

def check_unlock(skill_name):
    skill_map = build_skill_map()
    if skill_name not in skill_map:
        return {"error": f"Skill '{skill_name}' not found in curriculum", "unlocked": False}

    info = skill_map[skill_name]
    prereqs = info["prerequisites"]
    if not prereqs:
        return {"skill": skill_name, "unlocked": True, "missing": []}

    missing = []
    for p in prereqs:
        if p in skill_map:
            mastery = compute_mastery(skill_map[p])
            if mastery["mastery"] < 30:
                missing.append({"skill": p, "mastery": mastery})
        else:
            missing.append({"skill": p, "mastery": {"level": "unknown", "mastery": 0}})

    unlocked = len(missing) == 0
    return {"skill": skill_name, "unlocked": unlocked, "missing": missing}

def progress():
    skill_map = build_skill_map()
    tracks = {}
    for name, info in skill_map.items():
        t = info["track_label"]
        tracks.setdefault(t, {"skills": []})
        tracks[t]["skills"].append({
            "name": name,
            "difficulty": info["difficulty"],
            "prerequisites": info["prerequisites"],
            "mastery": compute_mastery(info)
        })

    track_summary = []
    for tname, tdata in tracks.items():
        skills = tdata["skills"]
        avg_mastery = round(sum(s["mastery"]["mastery"] for s in skills) / max(len(skills), 1), 1)
        mastered = sum(1 for s in skills if s["mastery"]["level"] == "mastered")
        unused = sum(1 for s in skills if s["mastery"]["level"] == "unused")
        track_summary.append({
            "track": tname,
            "skills": skills,
            "avg_mastery": avg_mastery,
            "mastered": mastered,
            "unused": unused,
            "total": len(skills)
        })

    all_masteries = [s["mastery"]["mastery"] for t in track_summary for s in t["skills"]]
    overall = round(sum(all_masteries) / max(len(all_masteries), 1), 1) if all_masteries else 0

    return {
        "overall_mastery": overall,
        "total_skills": len(skill_map),
        "mastered": sum(1 for s in skill_map.values() if compute_mastery(s)["level"] == "mastered"),
        "unused": sum(1 for s in skill_map.values() if compute_mastery(s)["level"] == "unused"),
        "tracks": track_summary
    }

def status():
    skill_map = build_skill_map()

    unlocked = 0
    locked = 0
    for name in skill_map:
        result = check_unlock(name)
        if result.get("unlocked"):
            unlocked += 1
        else:
            locked += 1

    prog = progress()

    if not skill_map:
        return {
            "error": "No skills defined in curriculum plan",
            "total_skills": 0,
            "unlocked": 0,
            "locked": 0,
            "mastered": 0,
            "unused": 0,
            "difficulty_range": {},
            "tracks": []
        }

    return {
        "overall_mastery": prog["overall_mastery"],
        "total_skills": prog["total_skills"],
        "unlocked": unlocked,
        "locked": locked,
        "mastered": prog["mastered"],
        "unused": prog["unused"],
        "difficulty_range": {
            "min": min(s["difficulty"] for s in skill_map.values()),
            "max": max(s["difficulty"] for s in skill_map.values()),
            "avg": round(sum(s["difficulty"] for s in skill_map.values()) / max(len(skill_map), 1), 1)
        },
        "tracks": prog["tracks"]
    }

def tree():
    plan = load_plan()
    skill_map = build_skill_map()
    lines = []

    for track in plan.get("tracks", []):
        lines.append(f"\n{'='*60}")
        lines.append(f"  {track['label']}  ({track['description']})")
        lines.append(f"{'='*60}")

        track_skills = track.get("skills", [])
        for s in sorted(track_skills, key=lambda x: x["difficulty"]):
            name = s["name"]
            info = skill_map.get(name, {})
            mastery = compute_mastery(info)
            unlock = check_unlock(name)

            depth_mark = "  " * s["difficulty"]
            prereq_str = f"  <-  {', '.join(s['prerequisites'])}" if s["prerequisites"] else ""
            lock_str = "  [LOCKED]" if not unlock.get("unlocked") else ""
            mastery_str = f"  [{mastery['level']} {mastery['mastery']}%]"

            line = f"  Lvl {s['difficulty']}: {name}{mastery_str}{lock_str}{prereq_str}"
            lines.append(line)

    return {"tree": "\n".join(lines)}

def main():
    if len(sys.argv) < 2:
        result = status()
        print(json.dumps(result, indent=2))
        return
    mode = sys.argv[1]

    if mode == "path":
        if len(sys.argv) < 3:
            print("Usage: python tool.py path <skill_name>")
            sys.exit(1)
        result = path_to_skill(sys.argv[2])
        print(json.dumps(result, indent=2))

    elif mode == "unlock":
        if len(sys.argv) < 3:
            print("Usage: python tool.py unlock <skill_name>")
            sys.exit(1)
        result = check_unlock(sys.argv[2])
        print(json.dumps(result, indent=2))

    elif mode == "progress":
        result = progress()
        print(json.dumps(result, indent=2))

    elif mode == "status":
        result = status()
        print(json.dumps(result, indent=2))

    elif mode == "tree":
        result = tree()
        print(result["tree"])

    else:
        print(f"Unknown mode: {mode}")

if __name__ == "__main__":
    main()
    try:
        import subprocess
        record_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_record_usage.py")
        subprocess.run([sys.executable, record_path, "curriculum"], capture_output=True, timeout=5)
    except:
        pass
