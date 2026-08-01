import subprocess, sys, time, json, urllib.request

BASE = "C:\\Users\\Rishav kumar\\Documents\\Codex\\github_upload"
proc = subprocess.Popen(
    [sys.executable, "web_server.py"],
    cwd=BASE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)
time.sleep(2)

base_url = "http://localhost:5000"

print("Testing SAOM Dashboard API...")

# Test 1: Index page
try:
    r = urllib.request.urlopen(base_url + "/", timeout=5)
    html = r.read().decode()
    print("1. GET / -> OK (status %d, len=%d)" % (r.status, len(html)))
except Exception as e:
    print("1. GET / -> ERROR:", e)

# Test 2: Status endpoint
try:
    r = urllib.request.urlopen(base_url + "/api/status", timeout=5)
    data = json.loads(r.read().decode())
    print("2. GET /api/status -> OK, version:", data.get("version"))
except Exception as e:
    print("2. GET /api/status -> ERROR:", e)

# Test 3: Chat endpoint
try:
    body = json.dumps({"message": "status"}).encode("utf-8")
    req = urllib.request.Request(base_url + "/api/chat", data=body, headers={"Content-Type": "application/json"})
    r = urllib.request.urlopen(req, timeout=5)
    data = json.loads(r.read().decode())
    print("3. POST /api/chat -> OK, has_response:", "response" in data)
    resp_text = data.get("response", "")[:100]
    print("   Response preview:", resp_text)
except Exception as e:
    print("3. POST /api/chat -> ERROR:", e)

# Test 4: Init endpoint
try:
    req = urllib.request.Request(base_url + "/api/init", data=b"{}", headers={"Content-Type": "application/json"})
    r = urllib.request.urlopen(req, timeout=5)
    data = json.loads(r.read().decode())
    print("4. POST /api/init -> OK:", data.get("result", "no result")[:100])
except Exception as e:
    print("4. POST /api/init -> ERROR:", e)

proc.terminate()
try:
    proc.wait(timeout=3)
except:
    proc.kill()
print("\nAll tests complete.")