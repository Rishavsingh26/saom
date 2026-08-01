import json, os, sys
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VAULT_PATH = os.path.join(BASE, "vault", "vault.json")

def load_vault():
    if os.path.exists(VAULT_PATH):
        try:
            with open(VAULT_PATH, encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"secrets": []}

def save_vault(data):
    tmp = VAULT_PATH + ".tmp"
    os.makedirs(os.path.dirname(VAULT_PATH), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, VAULT_PATH)

def mask_value(value):
    if not value:
        return ""
    if len(value) <= 8:
        return value[:2] + "..." + value[-1] if len(value) > 2 else "***"
    return value[:4] + "..." + value[-4:]

def vault_set(name, value, category="secret", description=""):
    data = load_vault()
    for item in data["secrets"]:
        if item["name"] == name:
            item["value"] = value
            item["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            item["description"] = description or item.get("description", "")
            item["category"] = category or item.get("category", "secret")
            save_vault(data)
            return {"status": "updated", "name": name}
    data["secrets"].append({
        "name": name,
        "value": value,
        "category": category or "secret",
        "description": description or "",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    })
    save_vault(data)
    return {"status": "created", "name": name}

def vault_get(name):
    data = load_vault()
    for item in data["secrets"]:
        if item["name"] == name:
            return {"name": name, "value": mask_value(item["value"]), "category": item.get("category", "secret"), "description": item.get("description", "")}
    return {"error": "not found", "name": name}

def vault_list(category=None):
    data = load_vault()
    items = []
    for item in data["secrets"]:
        if category and item.get("category") != category:
            continue
        items.append({
            "name": item["name"],
            "category": item.get("category", "secret"),
            "value": mask_value(item.get("value", "")),
            "description": item.get("description", ""),
            "updated_at": item.get("updated_at", "")
        })
    return {"items": items, "count": len(items)}

def vault_delete(name):
    data = load_vault()
    before = len(data["secrets"])
    data["secrets"] = [item for item in data["secrets"] if item["name"] != name]
    if len(data["secrets"]) < before:
        save_vault(data)
        return {"status": "deleted", "name": name}
    return {"error": "not found", "name": name}

def main():
    args = sys.argv[1:]
    if not args:
        print(json.dumps(vault_list(), indent=2))
    elif args[0] == "set" and len(args) >= 3:
        cat = args[3] if len(args) > 3 else "secret"
        desc = " ".join(args[4:]) if len(args) > 4 else ""
        print(json.dumps(vault_set(args[1], args[2], cat, desc), indent=2))
    elif args[0] == "get" and len(args) >= 2:
        print(json.dumps(vault_get(args[1]), indent=2))
    elif args[0] == "list":
        cat = args[1] if len(args) > 1 else None
        print(json.dumps(vault_list(cat), indent=2))
    elif args[0] == "delete" and len(args) >= 2:
        print(json.dumps(vault_delete(args[1]), indent=2))
    else:
        print("Usage: vault.py [set <name> <value> [category] [desc] | get <name> | list [category] | delete <name>]")

if __name__ == "__main__":
    main()
