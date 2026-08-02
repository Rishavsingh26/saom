from playwright.sync_api import sync_playwright
import time, json

def safe_str(s):
    return s.encode('ascii', 'replace').decode('ascii').replace('\n', ' ')

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()

    print("=== Loading Page ===")
    page.goto('https://saom-web.onrender.com/', timeout=60000)
    time.sleep(2)

    page.fill('#chat-input', 'tell me a 3 word joke')
    page.press('#chat-input', 'Enter')
    time.sleep(25)

    ls = page.evaluate('localStorage.getItem("saom_session")')
    print("Full localStorage string:")
    print(safe_str(ls if ls else "NONE"))

    print("\n=== Reloading Page ===")
    page.reload(timeout=60000)
    time.sleep(3)

    msgs = page.query_selector_all('.msg')
    print("Reloaded messages count:", len(msgs))
    for i, m in enumerate(msgs):
        body = m.query_selector('.msg-body')
        btext = body.inner_text() if body else "NO BODY"
        print(f"  Reloaded Msg {i} body text: '{safe_str(btext)}'")

    browser.close()
    print("DONE")