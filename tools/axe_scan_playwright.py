from playwright.sync_api import sync_playwright
import json, os

BASE = 'http://127.0.0.1:5000'
OUTDIR = 'visual_checks/axe_reports'
os.makedirs(OUTDIR, exist_ok=True)

pages = ['/login','/','/analytics','/goals','/badges','/profile']

with sync_playwright() as p:
    browser = None
    try:
        browser = p.chromium.launch(channel='chrome', headless=True)
    except Exception:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception:
            browser = p.firefox.launch(headless=True)

    context = browser.new_context()
    page = context.new_page()

    for path in pages:
        url = BASE + path
        print('Visiting', url)
        try:
            page.goto(url, wait_until='networkidle', timeout=15000)
        except Exception as e:
            print('Navigation warning', e)
        # try to log in if on login page
        if path == '/login':
            try:
                page.select_option('select[name="username"]', 'Akshit')
                page.click('button[type=submit]')
                page.wait_for_load_state('networkidle')
            except Exception as e:
                print('Login attempt failed or not needed:', e)
        # inject axe
        try:
            page.add_script_tag(url='https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.7.3/axe.min.js')
            result = page.evaluate('''async () => await axe.run(document, {runOnly: {type: 'rule', values: ['color-contrast']}})''')
            fname = os.path.join(OUTDIR, path.strip('/').replace('/','_') or 'index') + '.json'
            with open(fname, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2)
            print('Saved axe report to', fname)
        except Exception as e:
            print('Axe failed on', url, e)

    browser.close()
    print('Axe scans complete.')
