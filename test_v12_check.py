from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()

    # Test 1: Page loads
    page.goto('https://saom-web.onrender.com/', timeout=60000)
    time.sleep(2)
    body = page.inner_text('body')
    print('=== Load Test ===')
    print('v12:', 'v12' in body)
    print('I can removed:', 'I can:' not in body)
    print('LLM shown:', 'north' in body.lower())

    # Test 2: User message + AI response
    page.fill('#chat-input', 'hello')
    page.press('#chat-input', 'Enter')
    time.sleep(15)

    msgs = page.query_selector_all('.msg')
    print()
    print('=== Messages Test ===')
    print('Total messages:', len(msgs))
    for i, m in enumerate(msgs):
        text = m.inner_text()[:60]
        print('  Msg %d: %s' % (i, text))

    has_user = any('You' in m.inner_text() for m in msgs)
    has_bot = any('SAOM' in m.inner_text() for m in msgs)
    print('Has user msg:', has_user)
    print('Has bot msg:', has_bot)

    # Test 3: Copy button visible
    print()
    print('=== Copy Button Test ===')
    copy_btns = page.query_selector_all('.copy-btn')
    print('Copy buttons found:', len(copy_btns))

    # Test 4: Check localStorage persistence
    print()
    print('=== Session Persistence Test ===')
    has_storage = page.evaluate('localStorage.getItem("saom_session") !== null')
    print('localStorage has session:', has_storage)

    # Test 5: Mobile layout
    page.set_viewport_size({'width': 375, 'height': 812})
    time.sleep(1)
    mobile_msgs = page.query_selector_all('.msg')
    print('Mobile messages:', len(mobile_msgs))

    page.screenshot(path=r'C:\Users\Rishav kumar\Documents\Codex\github_upload\test_v12_final2.png')

    browser.close()
    print()
    print('DONE')