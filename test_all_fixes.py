from playwright.sync_api import sync_playwright
import time

def safe_str(s):
    return s.encode('ascii', 'replace').decode('ascii').replace('\n', ' ')

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()

    print("=== 1. Loading Page ===")
    page.goto('https://saom-web.onrender.com/', timeout=60000)
    time.sleep(2)
    
    initial_msgs = page.query_selector_all('.msg')
    print("Initial message count:", len(initial_msgs))
    if initial_msgs:
        print("Initial msg 0 text:", safe_str(initial_msgs[0].inner_text()))

    print("\n=== 2. Sending User Message ===")
    page.fill('#chat-input', 'hello SAOM persistence test')
    page.press('#chat-input', 'Enter')
    
    # Wait for response stream to complete
    time.sleep(25)
    
    msgs = page.query_selector_all('.msg')
    print("Messages after exchange:", len(msgs))
    for i, m in enumerate(msgs):
        print("  Msg %d text: %s" % (i, safe_str(m.inner_text())[:100]))
    
    # Check Copy Buttons
    copy_btns = page.query_selector_all('.copy-btn')
    print("\n=== 3. Copy Button Test ===")
    print("Copy buttons found:", len(copy_btns))
    for i, btn in enumerate(copy_btns):
        print("  Copy btn %d visible: %s" % (i, btn.is_visible()))

    # Check localStorage session data
    ls = page.evaluate('localStorage.getItem("saom_session")')
    print("\n=== 4. localStorage Check ===")
    print("localStorage session before reload:", safe_str(ls[:150]) if ls else "NONE")

    print("\n=== 5. Reloading Page to Test Session Persistence ===")
    page.reload(timeout=60000)
    time.sleep(3)
    
    msgs_reloaded = page.query_selector_all('.msg')
    print("Messages after reload:", len(msgs_reloaded))
    for i, m in enumerate(msgs_reloaded):
        print("  Reloaded Msg %d text: %s" % (i, safe_str(m.inner_text())[:100]))

    ls_reloaded = page.evaluate('localStorage.getItem("saom_session")')
    print("localStorage session after reload:", safe_str(ls_reloaded[:150]) if ls_reloaded else "NONE")

    page.screenshot(path=r'C:\Users\Rishav kumar\Documents\Codex\github_upload\test_all_fixes.png')
    browser.close()
    print("\n=== TEST COMPLETE ===")