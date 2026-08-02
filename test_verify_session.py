from playwright.sync_api import sync_playwright
import time, json

def safe_str(s):
    return s.encode('ascii', 'replace').decode('ascii').replace('\n', ' ')

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()

    print("=== 1. Loading Page ===")
    page.goto('https://saom-web.onrender.com/', timeout=60000)
    time.sleep(2)

    page.fill('#chat-input', 'what is 2 plus 2')
    page.press('#chat-input', 'Enter')
    time.sleep(25)

    ls = page.evaluate('localStorage.getItem("saom_session")')
    print("localStorage BEFORE reload:")
    if ls:
        data = json.loads(ls)
        print("  Session ID:", data.get("sessionId"))
        for idx, h in enumerate(data.get("history", [])):
            print("  History %d [%s]: '%s'" % (idx, h.get("role"), safe_str(h.get("content", ""))))

    print("\n=== 2. Reloading Page ===")
    page.reload(timeout=60000)
    time.sleep(3)

    msgs = page.query_selector_all('.msg')
    print("Reloaded messages count:", len(msgs))
    for i, m in enumerate(msgs):
        print("  Reloaded Msg %d inner_text: '%s'" % (i, safe_str(m.inner_text())))

    ls2 = page.evaluate('localStorage.getItem("saom_session")')
    print("\nlocalStorage AFTER reload:")
    if ls2:
        data2 = json.loads(ls2)
        print("  Session ID:", data2.get("sessionId"))
        for idx, h in enumerate(data2.get("history", [])):
            print("  History %d [%s]: '%s'" % (idx, h.get("role"), safe_str(h.get("content", ""))))

    # Check Copy button visibility and position
    copy_btns = page.query_selector_all('.copy-btn')
    print("\nCopy buttons found:", len(copy_btns))
    for i, btn in enumerate(copy_btns):
        print("  Copy button %d is_visible: %s" % (i, btn.is_visible()))

    page.screenshot(path=r'C:\Users\Rishav kumar\Documents\Codex\github_upload\test_verify_session.png')
    browser.close()
    print("\nDONE")