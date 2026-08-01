import json
import sys
import os
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NODES_PATH = os.path.join(BASE, "graph", "nodes.json")
EDGES_PATH = os.path.join(BASE, "graph", "edges.json")
INIT_PATH = os.path.join(BASE, "init.json")

STRENGTHEN_RATE = 0.1
WEAKEN_RATE = 0.2
DECAY_RATE = 0.05
DECAY_THRESHOLD_DAYS = 14
MAX_WEIGHT = 1.0
MIN_WEIGHT = 0.0

def load_json(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def load_edges():
    return load_json(EDGES_PATH) or []

def save_edges(edges):
    save_json(EDGES_PATH, edges)

def find_edge(edges, source_id, target_id, edge_type=None):
    matches = []
    for e in edges:
        if e.get("source_id") == source_id and e.get("target_id") == target_id:
            if edge_type is None or e.get("type") == edge_type:
                matches.append(e)
    return matches

def strengthen(source_id, target_id, edge_type=None):
    edges = load_edges()
    from_ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    updated = 0

    for e in edges:
        if e.get("source_id") == source_id and e.get("target_id") == target_id:
            if edge_type is None or e.get("type") == edge_type:
                old = e.get("weight", 0.5)
                e["weight"] = round(min(MAX_WEIGHT, old + STRENGTHEN_RATE), 3)
                e["last_strengthened"] = from_ts
                updated += 1

    if updated:
        save_edges(edges)
    return {"updated": updated, "action": "strengthen", "rate": STRENGTHEN_RATE}

def weaken(source_id, target_id, edge_type=None):
    edges = load_edges()
    from_ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    updated = 0

    for e in edges:
        if e.get("source_id") == source_id and e.get("target_id") == target_id:
            if edge_type is None or e.get("type") == edge_type:
                old = e.get("weight", 0.5)
                e["weight"] = round(max(MIN_WEIGHT, old - WEAKEN_RATE), 3)
                e["last_weakened"] = from_ts
                updated += 1

    if updated:
        save_edges(edges)
    return {"updated": updated, "action": "weaken", "rate": WEAKEN_RATE}

def strengthen_by_type(source_type, target_type, edge_type=None, amount=STRENGTHEN_RATE):
    edges = load_edges()
    nodes = load_json(NODES_PATH) or []
    node_map = {n["id"]: n.get("type") for n in nodes}
    from_ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    updated = 0

    for e in edges:
        src_type = node_map.get(e.get("source_id"))
        tgt_type = node_map.get(e.get("target_id"))
        if src_type == source_type and tgt_type == target_type:
            if edge_type is None or e.get("type") == edge_type:
                old = e.get("weight", 0.5)
                e["weight"] = round(min(MAX_WEIGHT, old + amount), 3)
                e["last_strengthened"] = from_ts
                updated += 1

    if updated:
        save_edges(edges)
    return {"updated": updated, "action": "strengthen_by_type", "source_type": source_type, "target_type": target_type}

def weaken_by_type(source_type, target_type, edge_type=None, amount=WEAKEN_RATE):
    edges = load_edges()
    nodes = load_json(NODES_PATH) or []
    node_map = {n["id"]: n.get("type") for n in nodes}
    from_ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    updated = 0

    for e in edges:
        src_type = node_map.get(e.get("source_id"))
        tgt_type = node_map.get(e.get("target_id"))
        if src_type == source_type and tgt_type == target_type:
            if edge_type is None or e.get("type") == edge_type:
                old = e.get("weight", 0.5)
                e["weight"] = round(max(MIN_WEIGHT, old - amount), 3)
                e["last_weakened"] = from_ts
                updated += 1

    if updated:
        save_edges(edges)
    return {"updated": updated, "action": "weaken_by_type", "source_type": source_type, "target_type": target_type}

def decay():
    edges = load_edges()
    now = datetime.utcnow()
    decayed = 0

    for e in edges:
        last_strongthened = e.get("last_strengthened")
        last_weakened = e.get("last_weakened")
        if not last_strongthened and not last_weakened:
            continue
        last_ts = last_strongthened or last_weakened
        try:
            last = datetime.strptime(last_ts, "%Y-%m-%dT%H:%M:%SZ")
        except:
            continue
        days_since = (now - last).days
        if days_since >= DECAY_THRESHOLD_DAYS:
            cycles = days_since / DECAY_THRESHOLD_DAYS
            old = e.get("weight", 0.5)
            decay_factor = (1 - DECAY_RATE) ** cycles
            new_weight = round(max(MIN_WEIGHT, old * decay_factor), 3)
            if new_weight < old:
                e["weight"] = new_weight
                e["last_decayed"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                decayed += 1

    if decayed:
        save_edges(edges)

        init = load_json(INIT_PATH)
        if init:
            init["memory_stats"]["last_decay"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            save_json(INIT_PATH, init)

    return {"decayed_edges": decayed, "threshold_days": DECAY_THRESHOLD_DAYS, "decay_rate": DECAY_RATE}

def status():
    edges = load_edges()
    nodes = load_json(NODES_PATH) or []
    node_map = {n["id"]: n for n in nodes}

    weights = [e.get("weight", 0.5) for e in edges]

    by_type = {}
    for e in edges:
        et = e.get("type", "unknown")
        by_type.setdefault(et, []).append(e.get("weight", 0.5))

    type_summary = {}
    for et, wlist in by_type.items():
        type_summary[et] = {
            "count": len(wlist),
            "avg_weight": round(sum(wlist) / len(wlist), 3),
            "min": round(min(wlist), 3),
            "max": round(max(wlist), 3)
        }

    weakest = sorted(edges, key=lambda e: e.get("weight", 0.5))[:5]
    strongest = sorted(edges, key=lambda e: -e.get("weight", 0.5))[:5]

    def edge_summary(e):
        src = node_map.get(e.get("source_id"), {})
        tgt = node_map.get(e.get("target_id"), {})
        return {
            "source": f"{src.get('type','?')}:{e.get('source_id','?')[:30]}",
            "target": f"{tgt.get('type','?')}:{e.get('target_id','?')[:30]}",
            "type": e.get("type"),
            "weight": e.get("weight", 0.5),
            "last_strengthened": e.get("last_strengthened"),
            "last_weakened": e.get("last_weakened")
        }

    return {
        "total_edges": len(edges),
        "weight_distribution": {
            "avg_weight": round(sum(weights) / max(len(weights), 1), 3),
            "min_weight": round(min(weights), 3) if weights else 0,
            "max_weight": round(max(weights), 3) if weights else 0,
            "strong_edges": sum(1 for w in weights if w >= 0.8),
            "medium_edges": sum(1 for w in weights if 0.4 <= w < 0.8),
            "weak_edges": sum(1 for w in weights if w < 0.4)
        },
        "by_edge_type": type_summary,
        "weakest": [edge_summary(e) for e in weakest],
        "strongest": [edge_summary(e) for e in strongest]
    }

def main():
    if len(sys.argv) < 2:
        result = status()
        print(json.dumps(result, indent=2))
        return
    mode = sys.argv[1]

    if mode == "strengthen":
        if len(sys.argv) < 4:
            print("Usage: python tool.py strengthen <source_id> <target_id> [edge_type]")
            sys.exit(1)
        edge_type = sys.argv[4] if len(sys.argv) > 4 else None
        result = strengthen(sys.argv[2], sys.argv[3], edge_type)
        print(json.dumps(result, indent=2))

    elif mode == "weaken":
        if len(sys.argv) < 4:
            print("Usage: python tool.py weaken <source_id> <target_id> [edge_type]")
            sys.exit(1)
        edge_type = sys.argv[4] if len(sys.argv) > 4 else None
        result = weaken(sys.argv[2], sys.argv[3], edge_type)
        print(json.dumps(result, indent=2))

    elif mode == "strengthen-type":
        if len(sys.argv) < 4:
            print("Usage: python tool.py strengthen-type <source_type> <target_type> [edge_type] [amount]")
            sys.exit(1)
        edge_type = sys.argv[4] if len(sys.argv) > 4 else None
        amount = float(sys.argv[5]) if len(sys.argv) > 5 else STRENGTHEN_RATE
        result = strengthen_by_type(sys.argv[2], sys.argv[3], edge_type, amount)
        print(json.dumps(result, indent=2))

    elif mode == "weaken-type":
        if len(sys.argv) < 4:
            print("Usage: python tool.py weaken-type <source_type> <target_type> [edge_type] [amount]")
            sys.exit(1)
        edge_type = sys.argv[4] if len(sys.argv) > 4 else None
        amount = float(sys.argv[5]) if len(sys.argv) > 5 else WEAKEN_RATE
        result = weaken_by_type(sys.argv[2], sys.argv[3], edge_type, amount)
        print(json.dumps(result, indent=2))

    elif mode == "decay":
        result = decay()
        print(json.dumps(result, indent=2))

    elif mode == "status":
        result = status()
        print(json.dumps(result, indent=2))

    else:
        print(f"Unknown mode: {mode}")

if __name__ == "__main__":
    main()
    try:
        import subprocess
        record_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_record_usage.py")
        subprocess.run([sys.executable, record_path, "plasticity"], capture_output=True, timeout=5)
    except:
        pass
