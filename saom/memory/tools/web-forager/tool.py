import json, sys, os, re, urllib.request, urllib.parse, urllib.error, html, time
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NODES_PATH = os.path.join(BASE, "graph", "nodes.json")
EDGES_PATH = os.path.join(BASE, "graph", "edges.json")
KNOWLEDGE_DIR = os.path.join(BASE, "knowledge")

DDG_URL = "https://lite.duckduckgo.com/lite/"

def load_json(path):
    if not os.path.exists(path):
        return [] if path.endswith(".json") else {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError, OSError):
        return [] if path.endswith(".json") else {}

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

def formulate_queries(query, domain):
    return [
        f"{query} {domain} 2026",
        f"{query} tool github python",
        f"{query} approach technique guide 2025 2026"
    ]

def search_ddg(query):
    data = urllib.parse.urlencode({"q": query}).encode()
    req = urllib.request.Request(DDG_URL, data=data, method="POST")
    req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return {"success": False, "error": str(e)}

    results = []
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', body, re.DOTALL)
    for row in rows:
        a_match = re.search(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', row, re.DOTALL)
        snippet_match = re.search(r'<td[^>]*class="result-snippet"[^>]*>(.*?)</td>', row, re.DOTALL)
        if a_match:
            url = html.unescape(a_match.group(1))
            title = html.unescape(re.sub(r'<[^>]+>', '', a_match.group(2)).strip())
            snippet = ""
            if snippet_match:
                snippet = html.unescape(re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip())
            if title and url:
                results.append({"title": title[:200], "url": url[:500], "snippet": snippet[:300]})
    return {"success": True, "results": results[:15], "total": len(results)}

def evaluate_result(result, query_tokens):
    title_lower = result["title"].lower()
    snippet_lower = result["snippet"].lower()
    combined = title_lower + " " + snippet_lower
    match_count = sum(1 for t in query_tokens if t in combined)
    relevance = round(match_count / max(len(query_tokens), 1), 2)

    url = result["url"].lower()
    authority = 0.0
    if "github.com" in url: authority = 0.9
    elif ".edu" in url: authority = 0.8
    elif "arxiv.org" in url: authority = 0.85
    elif "reddit.com" in url: authority = 0.5
    elif "medium.com" in url: authority = 0.4
    else: authority = 0.3

    freshness = 0.5
    year_match = re.findall(r'(202[456])', combined)
    if "2026" in year_match: freshness = 0.9
    elif "2025" in year_match: freshness = 0.7
    elif "2024" in year_match: freshness = 0.5

    score = round(0.5 * relevance + 0.3 * authority + 0.2 * freshness, 2)
    return {"relevance": relevance, "authority": authority, "freshness": freshness, "score": score}

def tokenize(text):
    return set(re.findall(r'[a-zA-Z][a-zA-Z0-9_-]{2,}', text.lower()))

def create_knowledge_note(query, domain, results, findings):
    os.makedirs(KNOWLEDGE_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    safe_name = re.sub(r'[^a-z0-9]+', '_', query.lower()[:40])
    path = os.path.join(KNOWLEDGE_DIR, f"{safe_name}_{int(time.time())}.json")
    note = {
        "query": query,
        "domain": domain,
        "timestamp": timestamp,
        "results_count": len(results),
        "top_results": results[:5],
        "findings": findings,
        "source": "web-forager",
        "status": "new"
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(note, f, indent=2, ensure_ascii=False)
    return path

def add_graph_node(query, domain, findings):
    nodes = load_json(NODES_PATH)
    edges = load_json(EDGES_PATH)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    node_id = "finding:" + re.sub(r'[^a-z0-9]+', '-', query.lower()[:30])

    existing = [n for n in nodes if n["id"] == node_id]
    if existing:
        existing[0]["summary"] = findings[:300]
        existing[0]["timestamp"] = timestamp
        save_json(NODES_PATH, nodes)
        return node_id

    new_node = {
        "id": node_id,
        "type": "finding",
        "label": query[:80],
        "summary": findings[:300],
        "domain": domain,
        "timestamp": timestamp,
        "quality_score": None,
        "embedding_keywords": list(tokenize(query + " " + domain)),
        "metadata": {}
    }
    nodes.append(new_node)

    domain_node_id = "concept:" + re.sub(r'[^a-z0-9]+', '-', domain.lower()[:20])
    domain_exists = any(n["id"] == domain_node_id for n in nodes)
    if not domain_exists:
        domain_node = {
            "id": domain_node_id,
            "type": "concept",
            "label": domain,
            "summary": f"Domain: {domain}",
            "domain": domain,
            "timestamp": timestamp,
            "quality_score": None,
            "embedding_keywords": [domain.lower()],
            "metadata": {}
        }
        nodes.append(domain_node)

    edges.append({
        "source_id": node_id,
        "target_id": domain_node_id,
        "type": "related_to",
        "weight": 1.0,
        "timestamp": timestamp,
        "last_strengthened": timestamp
    })

    save_json(NODES_PATH, nodes)
    save_json(EDGES_PATH, edges)
    return node_id

def discover(query, domain):
    queries = formulate_queries(query, domain)
    all_results = []

    for q in queries:
        resp = search_ddg(q)
        if resp["success"]:
            all_results.extend(resp["results"])
            time.sleep(0.5)

    if not all_results:
        plan = "SEARCH_PLAN\n"
        plan += f"Web search unavailable. Use the assistant's websearch tool with these queries:\n"
        for q in queries:
            plan += f"  - {q}\n"
        plan += f"Then feed results back via mode=ingest.\n\n"
        plan += f"For quick reference, check:\n"
        plan += f"  - GitHub: https://github.com/search?q={urllib.parse.quote(query)}+{urllib.parse.quote(domain)}\n"
        plan += f"  - Reddit: https://www.reddit.com/search/?q={urllib.parse.quote(query)}"
        return {
            "success": True,
            "search_plan": plan,
            "queries": queries,
            "message": "No search results. Use search-plan to guide manual search."
        }

    query_tokens = tokenize(query + " " + domain)
    scored = []
    seen_urls = set()
    for r in all_results:
        url_key = r["url"][:100]
        if url_key in seen_urls:
            continue
        seen_urls.add(url_key)
        score = evaluate_result(r, query_tokens)
        scored.append({**r, "score": score})

    scored.sort(key=lambda x: -x["score"]["score"])
    top_results = scored[:10]

    findings_parts = []
    findings_parts.append(f"Web forager discovered {len(scored)} unique results for '{query}' in domain '{domain}'.")
    top_keywords = set()
    for r in top_results[:3]:
        words = tokenize(r["title"] + " " + r["snippet"])
        top_keywords.update(words)
    if top_keywords:
        findings_parts.append(f"Key concepts: {', '.join(list(top_keywords)[:8])}.")
    findings_parts.append(f"Top result: {top_results[0]['title']} ({top_results[0]['url']}) with score {top_results[0]['score']['score']}.")

    findings = " ".join(findings_parts)

    note_path = create_knowledge_note(query, domain, top_results, findings)
    graph_id = add_graph_node(query, domain, findings)

    return {
        "success": True,
        "note_path": note_path,
        "graph_node_id": graph_id,
        "queries_used": queries,
        "total_results": len(scored),
        "top_results": top_results[:5],
        "findings": findings
    }

def ingest(query, domain, results):
    if not results:
        return {"success": False, "error": "No results provided for ingestion"}

    query_tokens = tokenize(query + " " + domain)
    scored = []
    seen = set()
    for r in results:
        url_key = r.get("url", "")[:100]
        if url_key in seen:
            continue
        seen.add(url_key)
        score = evaluate_result(r, query_tokens)
        scored.append({**r, "score": score})

    scored.sort(key=lambda x: -x["score"]["score"])
    top_results = scored[:10]

    findings_parts = []
    findings_parts.append(f"Web forager ingested {len(scored)} results for '{query}'.")
    findings_parts.append(f"Top result: {top_results[0]['title']} ({top_results[0]['url']})" if top_results else "No results scored.")
    findings = " ".join(findings_parts)

    note_path = create_knowledge_note(query, domain, top_results, findings)
    graph_id = add_graph_node(query, domain, findings)

    return {
        "success": True,
        "note_path": note_path,
        "graph_node_id": graph_id,
        "total_results": len(scored),
        "top_results": top_results[:5],
        "findings": findings
    }

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"help": "Web forager tool — searches DuckDuckGo, scores results, stores findings to knowledge base and graph", "modes": ["discover <query> [domain]", "search-plan <query> [domain]", "ingest <query> <domain> <results_json>"], "usage": "python tool.py <discover|search-plan|ingest> <query> [domain] [results_json]", "examples": ['python tool.py discover "self-improving agents" "agent-research"', 'python tool.py ingest "query" "domain" \'[{"title":"...","url":"...","snippet":"..."}]\''], "default": "Showing help (no default mode)"}, indent=2))
        return
    if len(sys.argv) < 3:
        print("Usage: python tool.py <mode> <query> [domain] [results_json]")
        print("  Modes: discover, search-plan, ingest")
        sys.exit(1)

    mode = sys.argv[1]
    query = sys.argv[2]
    domain = sys.argv[3] if len(sys.argv) > 3 else "general"

    if mode == "discover":
        result = discover(query, domain)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif mode == "search-plan":
        queries = formulate_queries(query, domain)
        plan = {
            "mode": "search-plan",
            "query": query,
            "domain": domain,
            "queries": queries,
            "instructions": "Use assistant's websearch tool with each query. Collect results (title + url + snippet). Feed back via mode=ingest."
        }
        print(json.dumps(plan, indent=2, ensure_ascii=False))
    elif mode == "ingest":
        if len(sys.argv) < 4:
            print("Usage: python web-forager/tool.py ingest <query> <domain> '<results_json>'")
            sys.exit(1)
        results = json.loads(sys.argv[3])
        result = ingest(query, domain, results)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)

if __name__ == "__main__":
    main()
