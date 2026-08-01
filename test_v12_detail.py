from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()

    page.goto('https://saom-web.onrender.com/', timeout=60000)
    time.sleep(2)

    # Send a message
    page.fill('#chat-input', 'hello')
    page.press('#chat-input', 'Enter')
    time.sleep(15)

    # Check DOM structure of last assistant message
    last_msg = page.query_selector_all('.msg')[-1]
    html = last_msg.inner_html()
    print('Last msg HTML snippet:')
    print(html[:500])
    print()

    # Check copy buttons
    copy_btns = page.query_selector_all('.copy-btn')
    print('Copy buttons in DOM:', len(copy_btns))
    for i, btn in enumerate(copy_btns):
        print('  Copy btn %d: visible=%s' % (i, btn.is_visible()))

    # Check localStorage
    ls = page.evaluate('localStorage.getItem("saom_session")')
    print('localStorage session:', ls[:100] if ls else 'NONE')

    # Check msg-body text
    msg_bodies = page.query_selector_all('.msg-body')
    print('msg-body elements:', len(msg_bodies))
    for i, mb in enumerate(msg_bodies):
        print('  msg-body %d:', mb.text_content()[:60])

    page.screenshot(path=r'C:\Users\Rishav kumar\Documents\Codex\github_upload\test_v12_detail.png')
    browser.close()
    print('DONE')