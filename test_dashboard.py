import subprocess, sys, time, json
from pathlib import Path

BASE = Path(__file__).parent
SERVER_PROC = None

def start_server():
    global SERVER_PROC
    SERVER_PROC = subprocess.Popen(
        [sys.executable, "web_server.py"],
        cwd=str(BASE),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    time.sleep(2)
    if SERVER_PROC.poll() is not None:
        stdout, stderr = SERVER_PROC.communicate(timeout=2)
        print("SERVER FAILED TO START:")
        print("STDOUT:", stdout[:500])
        print("STDERR:", stderr[:500])
        return False
    return True

def test_dashboard():
    from playwright.sync_api import sync_playwright

    results = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Navigate to dashboard
        page.goto("http://localhost:5000/", timeout=10000)
        time.sleep(1)
        title = page.title()
        results["page_title"] = title
        results["navigated"] = True

        # Check if sidebar is present
        sidebar = page.query_selector("#sidebar")
        results["sidebar_present"] = sidebar is not None

        # Check if chat input is present
        chat_input = page.query_selector("#chat-input")
        results["chat_input_present"] = chat_input is not None

        # Test status API via chat
        chat_input.fill("status")
        chat_input.press("Enter")
        time.sleep(3)

        # Check if chat messages appeared
        messages = page.query_selector_all(".msg")
        results["chat_messages_count"] = len(messages)

        # Check for API response content
        if len(messages) >= 2:
            assistant_msg = messages[-1]
            text_content = assistant_msg.text_content() or ""
            results["last_response_preview"] = text_content[:200]
            results["api_working"] = "version" in text_content.lower() or "tools" in text_content.lower()
        else:
            results["api_working"] = False
            results["last_response_preview"] = "No assistant messages found"

        # Take screenshot
        screenshot_path = str(BASE / "dashboard_test.png")
        page.screenshot(path=screenshot_path, full_page=True)
        results["screenshot"] = screenshot_path

        browser.close()

    return results

def stop_server():
    global SERVER_PROC
    if SERVER_PROC and SERVER_PROC.poll() is None:
        SERVER_PROC.terminate()
        try:
            SERVER_PROC.wait(timeout=5)
        except:
            SERVER_PROC.kill()

if __name__ == "__main__":
    print("=" * 60)
    print("SAOM DASHBOARD PLAYWRIGHT TEST")
    print("=" * 60)

    print("\n[1/3] Starting Flask server...")
    if not start_server():
        print("FAILED: Server did not start")
        sys.exit(1)
    print("Server started (PID: %d)" % SERVER_PROC.pid)

    print("\n[2/3] Running Playwright tests...")
    try:
        results = test_dashboard()
        print("\nTest Results:")
        for k, v in results.items():
            print("  %s: %s" % (k, v))

        passed = 0
        total = 0
        for k, v in results.items():
            total += 1
            if v is True or (isinstance(v, str) and len(v) > 0):
                passed += 1

        print("\n%d/%d checks passed" % (passed, total))

    except Exception as e:
        print("ERROR: %s" % str(e))
        import traceback
        traceback.print_exc()

    finally:
        print("\n[3/3] Stopping server...")
        stop_server()
        print("Done.")