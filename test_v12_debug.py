from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()

    page.goto('https://saom-web.onrender.com/', timeout=60000)
    time.sleep(2)

    # Send a message
    page.fill('#chat-input', 'hi')
    page.press('#chat-input', 'Enter')
    time.sleep(15)

    # Check all msg-text elements
    msg_texts = page.query_selector_all('.msg-text')
    print('Number of msg-text elements:', len(msg_texts))
    for i, mt in enumerate(msg_texts):
        inner = mt.inner_html()
        print('msg-text %d innerHTML:' % i, inner[:300])
        print('msg-text %d textContent:' % i, mt.text_content()[:100])

    # Check localStorage
    ls = page.evaluate('localStorage.getItem("saom_session")')
    print('localStorage session:', ls[:150] if ls else 'NONE')

    # Check all copy buttons
    copy_btns = page.query_selector_all('.copy-btn')
    print('Copy buttons:', len(copy_btns))

    # Check all msg-stream spans
    streams = page.query_selector_all('.msg-stream')
    print('msg-stream spans:', len(streams))
    for i, s in enumerate(streams):
        print('  msg-stream %d text:', s.text_content()[:60])

    page.screenshot(path=r'C:\Users\Rishav kumar\Documents\Codex\github_upload\test_v12_debug.png')
    browser.close()
    print('DONE')