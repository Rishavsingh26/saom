import json
import sys
import os
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGISTRY_PATH = os.path.join(BASE, "skills", "registry.json")

def load_registry():
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        return json.load(f)

def save_registry(registry):
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)

def find_skill(registry, name):
    for section in ("skills", "evolved_skills", "project_skills"):
        for skill in registry.get(section, []):
            if skill.get("name") == name:
                return skill, section
    return None, None

def record_use(name, outcome, confidence=None):
    registry = load_registry()
    skill, section = find_skill(registry, name)
    if not skill:
        return {"error": f"Skill '{name}' not found in registry"}

    skill["use_count"] = skill.get("use_count", 0) + 1
    if outcome == "success":
        skill["success_count"] = skill.get("success_count", 0) + 1
    skill["last_used"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    if confidence is not None:
        prev = skill.get("avg_confidence")
        if prev is not None:
            n = skill["use_count"]
            skill["avg_confidence"] = round((prev * (n - 1) + confidence) / n, 1)
        else:
            skill["avg_confidence"] = round(confidence, 1)

    save_registry(registry)
    success_rate = round(skill["success_count"] / skill["use_count"] * 100, 1) if skill["use_count"] > 0 else 0
    return {
        "skill": name,
        "use_count": skill["use_count"],
        "success_count": skill["success_count"],
        "success_rate": success_rate,
        "avg_confidence": skill.get("avg_confidence"),
        "last_used": skill["last_used"]
    }

def prune_scan():
    registry = load_registry()
    flags = []
    for section in ("skills", "evolved_skills", "project_skills"):
        for skill in registry.get(section, []):
            uc = skill.get("use_count", 0)
            sc = skill.get("success_count", 0)
            if uc >= 5:
                rate = sc / uc
                if rate < 0.2:
                    flags.append({
                        "skill": skill["name"],
                        "section": section,
                        "use_count": uc,
                        "success_count": sc,
                        "success_rate": round(rate * 100, 1),
                        "action": "PRUNE (below 20% success)"
                    })
                elif rate < 0.4:
                    flags.append({
                        "skill": skill["name"],
                        "section": section,
                        "use_count": uc,
                        "success_count": sc,
                        "success_rate": round(rate * 100, 1),
                        "action": "REVIEW (below 40% success)"
                    })
    return {"flagged": flags, "total": len(flags)}

def prune_remove(name):
    registry = load_registry()
    skill, section = find_skill(registry, name)
    if not skill:
        return {"error": f"Skill '{name}' not found"}
    registry[section].remove(skill)
    save_registry(registry)
    return {"removed": name, "section": section}

def main():
    if len(sys.argv) < 2:
        result = prune_scan()
        print(json.dumps(result, indent=2))
        return
    mode = sys.argv[1]

    if mode == "use":
        if len(sys.argv) < 4:
            print("Usage: python tool.py use <skill_name> <success|failure> [confidence]")
            sys.exit(1)
        name = sys.argv[2]
        outcome = sys.argv[3].lower()
        confidence = float(sys.argv[4]) if len(sys.argv) > 4 else None
        result = record_use(name, outcome, confidence)
        print(json.dumps(result, indent=2))

    elif mode == "prune-scan":
        result = prune_scan()
        print(json.dumps(result, indent=2))

    elif mode == "prune-remove":
        if len(sys.argv) < 3:
            print("Usage: python tool.py prune-remove <skill_name>")
            sys.exit(1)
        result = prune_remove(sys.argv[2])
        print(json.dumps(result, indent=2))

    else:
        print(f"Unknown mode: {mode}")

if __name__ == "__main__":
    main()
