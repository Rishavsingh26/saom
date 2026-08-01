import json, os, sys, re
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SESSIONS_DIR = os.path.join(BASE, "sessions")

def get_session_path(session_id):
    return os.path.join(SESSIONS_DIR, "session-%d.json" % session_id)

def load_json(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return default if default is not None else {}

def save_json_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)

def record(session_id, action, filepath):
    path = get_session_path(session_id)
    data = load_json(path, {"session_id": session_id, "files_created": [], "files_deleted": []})
    if "files_created" not in data:
        data["files_created"] = []
    if "files_deleted" not in data:
        data["files_deleted"] = []
    entry = {"path": filepath, "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if action == "create":
        data["files_created"].append(entry)
    elif action == "delete":
        data["files_deleted"].append(entry)
    else:
        return {"error": "action must be 'create' or 'delete'"}
    save_json_atomic(path, data)
    return {"recorded": True, "session_id": session_id, "action": action, "filepath": filepath}

def summary(session_id=None):
    files = []
    if session_id:
        paths = [get_session_path(session_id)]
    else:
        paths = [os.path.join(SESSIONS_DIR, f) for f in os.listdir(SESSIONS_DIR) if f.startswith("session-") and f.endswith(".json") and f != "last.json"]
    for p in sorted(paths):
        if not os.path.exists(p):
            continue
        data = load_json(p)
        sid = data.get("session_id", "?")
        created = len(data.get("files_created", []))
        deleted = len(data.get("files_deleted", []))
        files.append({"session_id": sid, "files_created": created, "files_deleted": deleted})
    return {"file_activity": files, "total_sessions": len(files)}

def main():
    args = sys.argv[1:]
    if not args:
        print(json.dumps(summary(), indent=2))
    elif args[0] == "record" and len(args) >= 3:
        print(json.dumps(record(int(args[1]), args[2], args[3] if len(args) > 3 else ""), indent=2))
    elif args[0] == "summary":
        sid = int(args[1]) if len(args) > 1 else None
        print(json.dumps(summary(sid), indent=2))
    else:
        print("Usage: session-files.py [record <session_id> create|delete <filepath> | summary [session_id]]")

if __name__ == "__main__":
    main()
