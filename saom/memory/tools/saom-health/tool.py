#!/usr/bin/env python3
"""saom-health: contrarian memory health-check for SAOM.

Designed to find things that are WRONG even when they look right.
Cross-references directories, finds semantic contradictions, detects
orphan data, and questions assumptions about what "healthy" means.
"""

import json
import os
import re
import sys
import datetime


MEMORY_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return {"_error": str(e), "_path": path}


def _looks_like_iso_date(s):
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}", s))


def _parse_iso(s):
    s = s.replace("Z", "+00:00")
    if re.match(r".*[+-]\d{4}$", s):
        s = s[:-2] + ":" + s[-2:]
    dt = datetime.datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


###############################################################################
# C1: Tool registry vs actual directories
###############################################################################
def check_tool_registry_consistency(registry, tools_dir):
    results = []
    registry_names = set()
    if "tools" in registry:
        for t in registry["tools"]:
            name = t.get("name")
            entrypoint = t.get("entrypoint", "")
            registry_names.add(name)
            expected_dir = os.path.join(tools_dir, name)
            if not os.path.isdir(expected_dir):
                results.append({
                    "check": "missing-tool-directory",
                    "severity": "error",
                    "message": "Tool '%s' registered but no directory at tools/%s/" % (name, name)
                })
            else:
                ep_name = os.path.basename(entrypoint) if entrypoint else "tool.py"
                ep_path = os.path.join(tools_dir, name, ep_name)
                if not os.path.isfile(ep_path):
                    results.append({
                        "check": "missing-entrypoint",
                        "severity": "warning",
                        "message": "Tool '%s' entrypoint '%s' not found" % (name, ep_path)
                    })

    if os.path.isdir(tools_dir):
        for d in sorted(os.listdir(tools_dir)):
            dpath = os.path.join(tools_dir, d)
            if os.path.isdir(dpath) and d not in registry_names:
                results.append({
                    "check": "unregistered-tool-directory",
                    "severity": "warning",
                    "message": "Directory tools/%s/ exists but not in registry" % d
                })
    return results


###############################################################################
# C2: Date sanity — future / ancient / unparseable timestamps
###############################################################################
def check_date_sanity(obj, path_context="", results=None):
    if results is None:
        results = []
    now = datetime.datetime.now(datetime.timezone.utc)
    future_grace = datetime.timedelta(days=1)
    ancient_threshold = datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc)

    if isinstance(obj, dict):
        for k, v in obj.items():
            ctx = "%s.%s" % (path_context, k) if path_context else k
            if isinstance(v, str) and _looks_like_iso_date(v):
                try:
                    dt = _parse_iso(v)
                    if dt > now + future_grace:
                        results.append({
                            "check": "future-timestamp",
                            "severity": "error",
                            "message": "Future timestamp at %s: %s" % (ctx, v)
                        })
                    elif dt < ancient_threshold:
                        results.append({
                            "check": "ancient-timestamp",
                            "severity": "warning",
                            "message": "Timestamp before 2000 at %s: %s" % (ctx, v)
                        })
                except (ValueError, OverflowError):
                    results.append({
                        "check": "unparseable-timestamp",
                        "severity": "warning",
                        "message": "Cannot parse date at %s: %s" % (ctx, v)
                    })
            else:
                check_date_sanity(v, ctx, results)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            ctx = "%s[%d]" % (path_context, i)
            check_date_sanity(item, ctx, results)
    return results


###############################################################################
# C3: Duplicate node IDs
###############################################################################
def check_duplicate_nodes(nodes):
    results = []
    seen = {}
    for i, node in enumerate(nodes):
        nid = node.get("id")
        if not nid:
            results.append({
                "check": "node-missing-id",
                "severity": "error",
                "message": "Node at index %d has no 'id'" % i
            })
            continue
        if nid in seen:
            results.append({
                "check": "duplicate-node-id",
                "severity": "error",
                "message": "Duplicate node id '%s' at index %d (first at %d)" % (nid, i, seen[nid])
            })
        else:
            seen[nid] = i
    return results


###############################################################################
# C4: Orphan sessions — files in sessions/ not referenced in graph
###############################################################################
def check_orphan_sessions(sessions_dir, nodes):
    results = []
    node_ids = {n.get("id") for n in nodes if n.get("id")}
    node_session_ids = set()
    for n in nodes:
        sid = n.get("session_id")
        if sid is not None:
            node_session_ids.add(sid)

    if not os.path.isdir(sessions_dir):
        return results

    for fname in sorted(os.listdir(sessions_dir)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(sessions_dir, fname)
        fdata = load_json(fpath)
        if "_error" in fdata:
            results.append({
                "check": "corrupt-session-file",
                "severity": "error",
                "message": "Session file '%s' is corrupt: %s" % (fname, fdata["_error"])
            })
            continue

        fsid = fdata.get("session_id")
        maybe_node_id = fname.replace(".json", "")
        has_graph_node = maybe_node_id in node_ids

        if fsid is not None and fsid not in node_session_ids and not has_graph_node:
            results.append({
                "check": "orphan-session-no-graph-node",
                "severity": "warning",
                "message": "Session file '%s' (id=%s) has no graph node" % (fname, fsid)
            })

        if not has_graph_node and fsid is None:
            results.append({
                "check": "unlinked-session-file",
                "severity": "info",
                "message": "Session file '%s' has no graph node and no session_id" % fname
            })
    return results


###############################################################################
# C5: Circular references in edges (DFS)
###############################################################################
def check_circular_edges(edges):
    results = []
    adjacency = {}
    for i, edge in enumerate(edges):
        src = edge.get("source_id")
        tgt = edge.get("target_id")
        if not src or not tgt:
            results.append({
                "check": "edge-missing-ids",
                "severity": "error",
                "message": "Edge %d missing source_id or target_id" % i
            })
            continue
        adjacency.setdefault(src, []).append(tgt)
        if src == tgt:
            results.append({
                "check": "self-loop-edge",
                "severity": "error",
                "message": "Self-loop edge %d: %s -> itself" % (i, src)
            })

    visited = set()
    rec_stack = set()
    cycle_paths = []

    def dfs(node, path):
        visited.add(node)
        rec_stack.add(node)
        for neighbor in adjacency.get(node, []):
            if neighbor not in visited:
                if dfs(neighbor, path + [neighbor]):
                    return True
            elif neighbor in rec_stack:
                cycle_paths.append(path + [neighbor])
                return True
        rec_stack.discard(node)
        return False

    for node in adjacency:
        if node not in visited:
            dfs(node, [node])

    if cycle_paths:
        paths_str = "; ".join(" -> ".join(p) for p in cycle_paths[:5])
        results.append({
            "check": "circular-edge-reference",
            "severity": "error",
            "message": "%d circular reference(s): %s" % (len(cycle_paths), paths_str)
        })
    return results


###############################################################################
# C6: Dangling edge references
###############################################################################
def check_dangling_edges(edges, nodes):
    results = []
    node_ids = {n.get("id") for n in nodes if n.get("id")}
    for i, edge in enumerate(edges):
        src = edge.get("source_id")
        tgt = edge.get("target_id")
        if src and src not in node_ids:
            results.append({
                "check": "dangling-edge-source",
                "severity": "error",
                "message": "Edge %d source '%s' has no node" % (i, src)
            })
        if tgt and tgt not in node_ids:
            results.append({
                "check": "dangling-edge-target",
                "severity": "error",
                "message": "Edge %d target '%s' has no node" % (i, tgt)
            })
    return results


###############################################################################
# C7: init.json stats vs actual
###############################################################################
def check_init_stats_accuracy(init, nodes, edges, tool_dirs):
    results = []
    stats = init.get("memory_stats", {})

    expected_nodes = stats.get("graph_nodes")
    expected_edges = stats.get("graph_edges")
    expected_tools = init.get("tools_count")

    if expected_nodes is not None and expected_nodes != len(nodes):
        results.append({
            "check": "stat-nodes-mismatch",
            "severity": "error",
            "message": "init.json claims %d nodes, actual %d" % (expected_nodes, len(nodes))
        })
    if expected_edges is not None and expected_edges != len(edges):
        results.append({
            "check": "stat-edges-mismatch",
            "severity": "error",
            "message": "init.json claims %d edges, actual %d" % (expected_edges, len(edges))
        })
    if expected_tools is not None and expected_tools != len(tool_dirs):
        results.append({
            "check": "stat-tools-mismatch",
            "severity": "warning",
            "message": "init.json claims %d tools, actual %d tool dirs" % (expected_tools, len(tool_dirs))
        })

    last_session = init.get("last_session", "")
    if last_session:
        sf = os.path.join(MEMORY_ROOT, "sessions", "%s.json" % last_session)
        if not os.path.isfile(sf):
            results.append({
                "check": "last-session-file-missing",
                "severity": "warning",
                "message": "init.json last_session='%s' has no file" % last_session
            })
    return results


###############################################################################
# C8: Lesson consistency
###############################################################################
def check_lesson_consistency(nodes):
    results = []
    for i, node in enumerate(nodes):
        if node.get("type") != "lesson":
            continue
        nid = node.get("id", "index-%d" % i)
        summary = node.get("summary", "")
        root_cause = node.get("root_cause", "")
        fix = node.get("fix", "")

        if summary.endswith("...") or summary.rstrip().endswith("before "):
            results.append({
                "check": "lesson-truncated-summary",
                "severity": "warning",
                "message": "Lesson '%s' summary appears truncated" % nid,
            })
        if summary and root_cause and summary.strip() == root_cause.strip():
            results.append({
                "check": "lesson-summary-equals-root-cause",
                "severity": "warning",
                "message": "Lesson '%s' summary == root_cause (template residue)" % nid,
            })
        if "confidence" not in node:
            results.append({
                "check": "lesson-missing-confidence",
                "severity": "info",
                "message": "Lesson '%s' has no confidence field" % nid,
            })
        if "TODO" in fix.upper():
            results.append({
                "check": "lesson-unresolved-fix",
                "severity": "warning",
                "message": "Lesson '%s' fix is still TODO" % nid,
            })
    return results


###############################################################################
# C9: Edge types vs schema
###############################################################################
def check_edge_types_against_schema(edges, init):
    results = []
    valid_types = set(init.get("graph_schema", {}).get("edge_types", []))
    if not valid_types:
        return results
    for i, edge in enumerate(edges):
        etype = edge.get("type")
        if etype and etype not in valid_types:
            results.append({
                "check": "unsupported-edge-type",
                "severity": "warning",
                "message": "Edge %d type '%s' not in schema" % (i, etype)
            })
    return results


###############################################################################
# C10: Node types vs schema
###############################################################################
def check_node_types_against_schema(nodes, init):
    results = []
    valid_types = set(init.get("graph_schema", {}).get("node_types", []))
    if not valid_types:
        return results
    for i, node in enumerate(nodes):
        ntype = node.get("type")
        if ntype and ntype not in valid_types:
            results.append({
                "check": "unsupported-node-type",
                "severity": "warning",
                "message": "Node '%s' type '%s' not in schema" % (node.get("id", "?"), ntype)
            })
    return results


###############################################################################
# C11: Registry last_tool_created stale
###############################################################################
def check_registry_last_tool_created(registry):
    results = []
    claimed = registry.get("last_tool_created")
    if not claimed:
        return results
    try:
        claimed_dt = _parse_iso(claimed)
    except (ValueError, OverflowError, OSError):
        return results

    max_created = None
    for t in registry.get("tools", []):
        c = t.get("created_at")
        if c:
            try:
                cd = _parse_iso(c)
                if max_created is None or cd > max_created:
                    max_created = cd
            except (ValueError, OverflowError):
                pass

    if max_created and max_created > claimed_dt:
        results.append({
            "check": "last-tool-created-stale",
            "severity": "warning",
            "message": "last_tool_created='%s' but newer tool created at '%s'" % (
                claimed, max_created.isoformat())
        })
    return results


###############################################################################
# C12: Session graph stats stale
###############################################################################
def check_session_graph_stats(sessions_dir, nodes, edges):
    results = []
    if not os.path.isdir(sessions_dir):
        return results
    for fname in sorted(os.listdir(sessions_dir)):
        if not fname.endswith(".json"):
            continue
        fdata = load_json(os.path.join(sessions_dir, fname))
        if "_error" in fdata:
            continue
        gs = fdata.get("graph_stats")
        if not gs:
            continue
        cn = gs.get("graph_nodes")
        ce = gs.get("graph_edges")
        if cn is not None and cn != len(nodes):
            results.append({
                "check": "stale-graph-stats-nodes",
                "severity": "info",
                "message": "'%s' claims %d nodes, actual %d" % (fname, cn, len(nodes))
            })
        if ce is not None and ce != len(edges):
            results.append({
                "check": "stale-graph-stats-edges",
                "severity": "info",
                "message": "'%s' claims %d edges, actual %d" % (fname, ce, len(edges))
            })
    return results


###############################################################################
# C13: Session lesson refs missing
###############################################################################
def check_session_lesson_refs(sessions_dir, nodes):
    results = []
    actual_lesson_ids = set()
    for n in nodes:
        if n.get("type") == "lesson":
            nid = n.get("id")
            if nid:
                actual_lesson_ids.add(nid)

    if not os.path.isdir(sessions_dir):
        return results

    for fname in sorted(os.listdir(sessions_dir)):
        if not fname.endswith(".json"):
            continue
        fdata = load_json(os.path.join(sessions_dir, fname))
        if "_error" in fdata:
            continue
        for ref in fdata.get("lessons_extracted", []):
            if ref not in actual_lesson_ids:
                results.append({
                    "check": "session-lesson-ref-missing",
                    "severity": "warning",
                    "message": "'%s' references lesson '%s' not in graph" % (fname, ref)
                })
    return results


###############################################################################
# C14: Skill registry consistency
###############################################################################
def check_skill_registry_consistency(init, skills_registry):
    results = []
    loaded = set(init.get("loaded_skills", []))
    evolved = set(init.get("evolved_skills", []))

    for es in evolved:
        if es not in loaded:
            results.append({
                "check": "evolved-skill-not-in-loaded",
                "severity": "info",
                "message": "Evolved skill '%s' not in loaded_skills" % es
            })

    if "skills" in skills_registry:
        names = []
        for s in skills_registry["skills"]:
            n = s.get("name")
            if n:
                names.append(n)
        seen = set()
        for n in names:
            if n in seen:
                results.append({
                    "check": "duplicate-skill-entry",
                    "severity": "warning",
                    "message": "Skill '%s' appears >1 in skills/registry.json" % n
                })
            seen.add(n)
    return results


###############################################################################
# Main
###############################################################################
def run_health_check():
    result = {"healthy": True, "checks": [], "surprises_found": 0, "summary": ""}

    init = load_json(os.path.join(MEMORY_ROOT, "init.json"))
    if "_error" in init:
        result["checks"].append({
            "check": "init-json-corrupt", "severity": "error",
            "message": "Cannot load init.json: %s" % init["_error"]
        })
        result["healthy"] = False
        result["summary"] = "FATAL: init.json unreadable"
        return result

    tools_registry = load_json(os.path.join(MEMORY_ROOT, "tools", "registry.json"))
    nodes = load_json(os.path.join(MEMORY_ROOT, "graph", "nodes.json"))
    edges = load_json(os.path.join(MEMORY_ROOT, "graph", "edges.json"))
    skills_registry = load_json(os.path.join(MEMORY_ROOT, "skills", "registry.json"))

    if isinstance(nodes, dict) and "_error" not in nodes:
        nodes = nodes.get("nodes", nodes.get("data", list(nodes.values())))
    if isinstance(edges, dict) and "_error" not in edges:
        edges = edges.get("edges", edges.get("data", list(edges.values())))
    if isinstance(nodes, dict):
        nodes = list(nodes.values())
    if isinstance(edges, dict):
        edges = list(edges.values())

    tools_dir = os.path.join(MEMORY_ROOT, "tools")
    sessions_dir = os.path.join(MEMORY_ROOT, "sessions")

    actual_tool_dirs = []
    if os.path.isdir(tools_dir):
        for d in os.listdir(tools_dir):
            if os.path.isdir(os.path.join(tools_dir, d)):
                actual_tool_dirs.append(d)

    all_results = []
    all_results.extend(check_tool_registry_consistency(tools_registry, tools_dir))
    all_results.extend(check_date_sanity(nodes, "nodes"))
    all_results.extend(check_date_sanity(edges, "edges"))
    all_results.extend(check_date_sanity(init, "init"))
    all_results.extend(check_date_sanity(tools_registry, "tools/registry"))
    if isinstance(nodes, list):
        all_results.extend(check_duplicate_nodes(nodes))
    all_results.extend(check_orphan_sessions(sessions_dir, nodes if isinstance(nodes, list) else []))
    if isinstance(edges, list):
        all_results.extend(check_circular_edges(edges))
    if isinstance(edges, list) and isinstance(nodes, list):
        all_results.extend(check_dangling_edges(edges, nodes))
    if isinstance(nodes, list) and isinstance(edges, list):
        all_results.extend(check_init_stats_accuracy(init, nodes, edges, actual_tool_dirs))
    if isinstance(nodes, list):
        all_results.extend(check_lesson_consistency(nodes))
    if isinstance(edges, list):
        all_results.extend(check_edge_types_against_schema(edges, init))
    all_results.extend(check_registry_last_tool_created(tools_registry))
    if isinstance(nodes, list):
        all_results.extend(check_node_types_against_schema(nodes, init))
    if isinstance(nodes, list) and isinstance(edges, list):
        all_results.extend(check_session_graph_stats(sessions_dir, nodes, edges))
    if isinstance(nodes, list):
        all_results.extend(check_session_lesson_refs(sessions_dir, nodes))
    all_results.extend(check_skill_registry_consistency(init, skills_registry))

    errors = [r for r in all_results if r.get("severity") == "error"]
    warnings = [r for r in all_results if r.get("severity") == "warning"]
    infos = [r for r in all_results if r.get("severity") == "info"]

    result["surprises_found"] = len(errors) + len(warnings)
    result["healthy"] = len(errors) == 0
    result["checks"] = all_results

    parts = []
    if errors:
        parts.append("%d error(s)" % len(errors))
    if warnings:
        parts.append("%d warning(s)" % len(warnings))
    if infos:
        parts.append("%d info(s)" % len(infos))
    part_str = ", ".join(parts) if parts else "all clean"

    top = (errors + warnings)[:3]
    extras = ""
    if top:
        bits = []
        for s in top:
            m = s["message"]
            if len(m) > 80:
                m = m[:77] + "..."
            bits.append(m)
        extras = "; " + "; ".join(bits)
        stash = len(errors) + len(warnings) - len(top)
        if stash > 0:
            extras += " (+%d more)" % stash

    result["summary"] = ("%s | %s | %d nodes, %d edges, %d tools | %d surprise(s)%s" % (
        "HEALTHY" if result["healthy"] else "UNHEALTHY",
        part_str,
        len(nodes) if isinstance(nodes, list) else 0,
        len(edges) if isinstance(edges, list) else 0,
        len(actual_tool_dirs),
        result["surprises_found"],
        extras
    ))

    return result


def main():
    result = run_health_check()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["healthy"] else 1)

if __name__ == "__main__":
    main()
