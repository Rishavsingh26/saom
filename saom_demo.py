"""
SAOM Demo - Complete example using all SAOM features
Run: python saom_demo.py
"""

from saom_lib import SAOM

saom = SAOM()

def safe_print(*args, **kwargs):
    """Print text safely, replacing non-ASCII characters."""
    text = " ".join(str(a) for a in args)
    print(text.encode('ascii', 'replace').decode(), **kwargs)

safe_print("=" * 60)
safe_print("SAOM Library Demo")
safe_print("=" * 60)

# 1. Chat
safe_print("\n[1] CHAT")
safe_print("-" * 40)
safe_print(saom.chat("What is the difference between a list and a tuple?"))

# 2. Write code
safe_print("\n[2] WRITE CODE")
safe_print("-" * 40)
safe_print(saom.write_code("write a function to check if a number is prime"))

# 3. Fix bug
safe_print("\n[3] FIX BUG")
safe_print("-" * 40)
buggy = """
def factorial(n):
    if n == 0:
        return 1
    return n * factorial(n)  # infinite recursion
"""
safe_print(saom.fix_bug(buggy))

# 4. Understand code
safe_print("\n[4] UNDERSTAND CODE")
safe_print("-" * 40)
safe_print(saom.understand("lambda x, y: x if x > y else y"))

# 5. Review code
safe_print("\n[5] REVIEW CODE")
safe_print("-" * 40)
code = """
def get_user(user_id):
    users = {"1": "Alice", "2": "Bob"}
    return users[user_id]
"""
safe_print(saom.review(code))

# 6. Model routing
safe_print("\n[6] MODEL ROUTING")
safe_print("-" * 40)
tasks = [
    "what is python",
    "write a function",
    "design a distributed system architecture"
]
for task in tasks:
    model = saom._route_model(task)
    safe_print(f"  Task: {task[:40]}")
    safe_print(f"  Model: {model}")

# 7. Tool chaining
safe_print("\n[7] TOOL CHAINING")
safe_print("-" * 40)
results = saom.chain([
    ("search", "Python async programming basics"),
])
safe_print(results[0][:300])

# 8. Run SAOM tools
safe_print("\n[8] SAOM TOOLS")
safe_print("-" * 40)
safe_print("Status:", saom.get_status().get("status", "unknown")[:200])

# 9. Graph query
safe_print("\n[9] GRAPH")
safe_print("-" * 40)
graph = saom.get_graph()
safe_print(f"Nodes: {len(graph.get('nodes', []))}")
safe_print(f"Edges: {len(graph.get('edges', []))}")

# 10. Lessons
safe_print("\n[10] LESSONS")
safe_print("-" * 40)
lessons = saom.get_lessons()
safe_print(f"Total lessons: {len(lessons)}")

# 11. Async demo (skip if aiohttp not installed)
safe_print("\n[11] ASYNC")
safe_print("-" * 40)
try:
    import asyncio
    async def async_demo():
        result = await saom.achat("What is 5 * 5?")
        safe_print("Async result: " + result[:100])
    asyncio.run(async_demo())
except ImportError:
    safe_print("Skipped - install aiohttp: pip install aiohttp")

# 12. Streaming demo
safe_print("\n[12] STREAMING")
safe_print("-" * 40)
safe_print("Response: ", end="")
for chunk in saom.stream("Write a one-line Python hello"):
    safe_print(chunk, end="", flush=True)
safe_print()

safe_print("\n" + "=" * 60)
safe_print("Demo complete!")
safe_print("=" * 60)
