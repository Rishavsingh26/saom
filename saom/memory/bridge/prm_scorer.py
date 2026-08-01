"""PRM (Process Reward Model) Scorer.
Step-level scoring of assistant responses using a separate LLM call.
Scores each reasoning step 0.0-1.0, catching wrong steps even when
final answer is accidentally correct.

Usage:
  python prm_scorer.py score "<query>" "<response>" -- scores one response
  python prm_scorer.py batch <file.jsonl> -- scores multiple from file
  python prm_scorer.py status -- shows recent scores
"""
import json, os, re, sys, urllib.request
from datetime import datetime, timezone

BRIDGE = os.path.dirname(os.path.abspath(__file__))
SCORES_PATH = os.path.join(BRIDGE, "prm_scores.jsonl")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
MODEL = "openai/gpt-oss-20b"
UA = "Mozilla/5.0 (compatible; SAOM-bot/1.0)"

# Token limit constraints: keep prompts under 300 tokens
MAX_QUERY_CHARS = 200
MAX_STEP_CHARS = 200
MAX_STEPS = 8


def _llm(prompt):
    if not GROQ_KEY:
        return "ERROR: no GROQ_API_KEY"
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 512, "temperature": 0.2
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


def split_steps(response):
    """Split response into reasoning steps. Client-side, no LLM.
    Handles newline-separated steps and inline 'Step N:' patterns.
    """
    if not response or not response.strip():
        return [{"step": 1, "text": "(empty)"}]
    text = response.strip()

    # Split on "Step N:" or heading markers only (inline or newline-separated)
    inline_pattern = re.compile(r'(?:^|\s)(?:Step\s+\d+[\.\:\)]?\s*|##?\s+)', re.IGNORECASE | re.MULTILINE)
    raw_steps = re.split(inline_pattern, text)

    if len(raw_steps) <= 1:
        # Fallback: split by paragraph breaks
        raw_steps = [p.strip() for p in text.split("\n\n") if p.strip()]
        if len(raw_steps) <= 1:
            raw_steps = [text]

    steps = [s.strip() for s in raw_steps if s.strip()]

    result = []
    for i, text in enumerate(steps[:MAX_STEPS]):
        truncated = text[:MAX_STEP_CHARS]
        result.append({"step": i + 1, "text": truncated})
    return result


def _sympy_eval(query, steps_text):
    """Check math steps with sympy. Returns (score_penalty:float, details:list)."""
    try:
        import sympy as sp
    except ImportError:
        return 0.0, []
    # Only attempt if query looks mathy
    import re
    math_keywords = {"percent", "calculate", "solve", "sum", "difference",
                     "product", "ratio", "integral", "derivative", "equation"}
    if not any(k in query.lower() for k in math_keywords):
        return 0.0, []

    details = []
    penalty = 0.0

    # Extract final answer: last number after "=", "answer", "result", "is"
    final_ans = None
    m = re.search(r'(?:=|answer|result|is)\s*(\d+[\.\d]*)', query + " " + steps_text, re.IGNORECASE)
    if not m:
        m = re.search(r'(\d+[\.\d]*)', steps_text.split(".")[-1] if "." in steps_text else steps_text)
    if m:
        final_ans = m.group(1)

    # Try to evaluate the query as a math problem
    query_clean = re.sub(r'[^\d\.\+\-\*\/\%\(\)\s]', ' ', query).strip()
    # Replace "X% of Y" with "(X/100)*Y"
    percent_m = re.search(r'(\d+[\.\d]*)\s*%\s*of\s*(\d+)', query, re.IGNORECASE)
    if percent_m:
        pct = float(percent_m.group(1))
        val = float(percent_m.group(2))
        expected = (pct / 100) * val
        if final_ans:
            got = float(final_ans)
            if abs(got - expected) > 0.01:
                details.append(f"expected {expected}, got {got}")
                penalty += 0.5
    return penalty, details


def score(query, response):
    """Score a single response: split into steps, call LLM, store result."""
    steps = split_steps(response)
    if not steps:
        return {"error": "no steps", "scores": [], "overall": None}

    steps_text = "\n".join(
        f"{s['step']}. {s['text']}" for s in steps
    )

    # Sympy pre-check for math answers
    math_penalty, math_details = _sympy_eval(query, steps_text)

    prompt = (
        f"Query: {query[:MAX_QUERY_CHARS]}\n\n"
        f"Response steps:\n{steps_text}\n\n"
        "Score each step 0.0-1.0 for correctness. "
        "Return ONLY JSON array: "
        '[{"step":N,"score":0.0-1.0,"reason":"short"}]. '
        "Overall is last entry with step=0."
    )

    raw = _llm(prompt)
    scores = []

    if raw.startswith("ERROR"):
        return {"error": raw, "scores": [], "overall": None}

    try:
        m = re.search(r'\[.*\]', raw, re.DOTALL)
        if m:
            parsed = json.loads(m.group(0))
            for entry in parsed:
                step = entry.get("step", 0)
                score_val = max(0.0, min(1.0, float(entry.get("score", 0.5))))
                reason = entry.get("reason", "")[:60]
                if step == 0:
                    overall = score_val
                else:
                    # Apply sympy penalty
                    if math_penalty > 0:
                        score_val = max(0.0, score_val - math_penalty)
                    scores.append({"step": step, "score": score_val, "reason": reason})
    except Exception:
        return {"error": "parse_failed", "raw": raw[:200], "scores": [], "overall": None}

    overall = overall if scores else None
    if overall is None and scores:
        overall = round(sum(s["score"] for s in scores) / len(scores), 2)

    record = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "query": query[:100],
        "step_count": len(scores),
        "overall": overall,
        "scores": scores,
        "flagged": [s for s in scores if s["score"] < 0.5]
    }

    os.makedirs(BRIDGE, exist_ok=True)
    with open(SCORES_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    result = {"overall": overall, "step_count": len(scores), "scores": scores}
    if record["flagged"]:
        result["flagged_steps"] = record["flagged"]
    print(json.dumps(result, indent=2))
    return result


def batch(filepath):
    """Score multiple responses from a JSONL file.
    Each line: {"query": "...", "response": "..."}
    """
    if not os.path.exists(filepath):
        print(json.dumps({"error": f"File not found: {filepath}"}))
        return
    results = []
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entry = json.loads(line)
                    r = score(entry.get("query", ""), entry.get("response", ""))
                    results.append(r)
                except Exception as e:
                    results.append({"error": str(e)[:100]})
    summary = {
        "total": len(results),
        "avg_overall": round(sum(r.get("overall", 0) or 0 for r in results) / max(len(results), 1), 2),
        "flagged": sum(1 for r in results if r.get("flagged_steps"))
    }
    print(json.dumps(summary, indent=2))
    return summary


def status():
    if not os.path.exists(SCORES_PATH):
        print(json.dumps({"total": 0, "recent": []}))
        return
    records = []
    with open(SCORES_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except:
                    pass
    recent = records[-10:] if records else []
    avg = round(sum(r.get("overall", 0) or 0 for r in records) / max(len(records), 1), 2) if records else None
    flagged = [r for r in records if r.get("flagged")]
    result = {
        "total_scored": len(records),
        "average_overall": avg,
        "total_flagged": len(flagged),
        "recent": [{"ts": r["timestamp"][:19], "overall": r["overall"], "steps": r["step_count"]} for r in recent]
    }
    print(json.dumps(result, indent=2))
    return result


def _apply_sympy_to_scores(query, scores, steps):
    """Apply sympy penalty to scores list. Returns list of (step_index, score_before, score_after)."""
    try:
        import sympy as sp
    except ImportError:
        return []
    import re
    ql = query.lower()
    math_keywords = {"percent", "calculate", "solve", "sum", "difference",
                     "product", "ratio", "integral", "derivative", "equation"}
    has_keyword = any(k in ql for k in math_keywords) or "%" in ql
    if not has_keyword:
        return []
    steps_text = "\n".join(f"{s['step']}. {s['text']}" for s in steps)

    final_ans = None
    m = re.search(r'(?:=|answer|result|is)\s*(\d+[\.\d]*)', query + " " + steps_text, re.IGNORECASE)
    if m:
        final_ans = m.group(1)

    percent_m = re.search(r'(\d+[\.\d]*)\s*%\s*of\s*(\d+)', query, re.IGNORECASE)
    if not percent_m:
        return []

    pct = float(percent_m.group(1))
    val = float(percent_m.group(2))
    expected = (pct / 100) * val
    if final_ans:
        got = float(final_ans)
        if abs(got - expected) > 0.01:
            adjustments = []
            for sc in scores:
                idx = sc["step"] - 1
                if 0 <= idx < len(steps):
                    old = sc["score"]
                    new_val = max(0.0, old - 0.5)
                    sc["score"] = new_val
                    adjustments.append({"step": sc["step"], "from": old, "to": new_val, "reason": f"expected {expected}, got {got}"})
            return adjustments
    return []


def revise(query, response, threshold=0.7):
    """Score and auto-revise flagged steps.
    For each step scoring below threshold, calls separate LLM to produce
    a corrected version. Re-scores the final revised response.
    """
    import copy
    # First score the current response
    steps = split_steps(response)
    steps_text = "\n".join(f"{s['step']}. {s['text']}" for s in steps)
    score_prompt = (
        f"Query: {query[:MAX_QUERY_CHARS]}\n\n"
        f"Response steps:\n{steps_text}\n\n"
        "Score each step 0.0-1.0 for correctness. "
        "Return ONLY JSON array: "
        '[{"step":N,"score":0.0-1.0,"reason":"short"}]. '
        "Overall is last entry with step=0."
    )
    raw = _llm(score_prompt)
    if raw.startswith("ERROR"):
        print(json.dumps({"error": raw}))
        return
    try:
        m = re.search(r'\[.*\]', raw, re.DOTALL)
        if not m:
            print(json.dumps({"error": "no json from scorer", "raw": raw[:200]}))
            return
        parsed = json.loads(m.group(0))
    except Exception as e:
        print(json.dumps({"error": f"parse: {e}", "raw": raw[:200]}))
        return

    scores = []
    for entry in parsed:
        step_num = entry.get("step", 0)
        if step_num == 0:
            continue
        scores.append({
            "step": step_num,
            "score": max(0.0, min(1.0, float(entry.get("score", 0.5)))),
            "text": steps[step_num - 1]["text"] if step_num - 1 < len(steps) else ""
        })

    # Apply sympy adjustments to scores
    sympy_adj = _apply_sympy_to_scores(query, scores, steps)

    flagged = [s for s in scores if s["score"] < threshold]
    if not flagged:
        result = {"overall": None, "step_count": len(scores), "scores": scores, "revised": False, "message": "no flagged steps", "sympy_adjustments": sympy_adj if sympy_adj else None}
        print(json.dumps(result, indent=2))
        return result

    revised_steps = copy.deepcopy(steps)
    revisions_made = []
    for s in flagged:
        idx = s["step"] - 1
        step_text = s.get("text", "")
        revise_prompt = (
            f"Query: {query[:MAX_QUERY_CHARS]}\n"
            f"Flawed step ({s['score']:.1f}): {step_text[:MAX_STEP_CHARS]}\n\n"
            "Write a corrected version of this step. "
            "Keep it short and precise. Output ONLY the corrected text."
        )
        revised = _llm(revise_prompt)
        if not revised.startswith("ERROR"):
            revised_steps[idx]["text"] = revised[:MAX_STEP_CHARS]
            revisions_made.append({"step": s["step"], "from": step_text[:100], "to": revised[:100]})

    new_response = "\n".join(s["text"] for s in revised_steps)

    print(json.dumps({
        "revised": True,
        "flagged_count": len(flagged),
        "sympy_adjustments": sympy_adj if sympy_adj else None,
        "revisions": [{"step": r["step"]} for r in revisions_made],
        "revised_response": new_response
    }, indent=2))

    # Auto-re-score the revised response
    print("\n--- Re-scoring revised response ---")
    score(query, new_response)

def main():
    if len(sys.argv) < 2:
        print("Usage: python prm_scorer.py <score|batch|revise|status> [args]")
        print("  score   \"<query>\" \"<response>\"")
        print("  batch   <file.jsonl>")
        print("  revise  \"<query>\" \"<response>\" [threshold=0.7]")
        print("  status")
        sys.exit(1)
    mode = sys.argv[1]
    if mode == "score":
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        response = sys.argv[3] if len(sys.argv) > 3 else ""
        score(query, response)
    elif mode == "batch":
        filepath = sys.argv[2] if len(sys.argv) > 2 else ""
        batch(filepath)
    elif mode == "revise":
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        response = sys.argv[3] if len(sys.argv) > 3 else ""
        threshold = float(sys.argv[4]) if len(sys.argv) > 4 else 0.7
        revise(query, response, threshold)
    elif mode == "status":
        status()
    else:
        print(f"Unknown mode: {mode}")


if __name__ == "__main__":
    main()
