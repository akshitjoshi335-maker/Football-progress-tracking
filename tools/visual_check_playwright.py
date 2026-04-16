from playwright.sync_api import sync_playwright
import os, time

BASE = 'http://127.0.0.1:5000'
OUTDIR = 'visual_checks/screenshots'

os.makedirs(OUTDIR, exist_ok=True)

with sync_playwright() as p:
    # Try Chromium first; on some Windows installs chromium headless may fail,
    # fall back to Firefox if needed.
    browser = None
    # Prefer to use a locally installed Chrome (channel) if available
    try:
        browser = p.chromium.launch(channel="chrome", headless=True)
        print('Launched Chromium via local channel')
    except Exception as e:
        print('Could not launch chromium via channel:', e)
        try:
            browser = p.chromium.launch(headless=True)
            print('Launched downloaded Chromium')
        except Exception as e2:
            print('Chromium launch failed, trying Firefox:', e2)
            try:
                browser = p.firefox.launch(headless=True)
                print('Launched Firefox')
            except Exception as e3:
                print('All browser launch attempts failed:', e3)
                raise
    context = browser.new_context(viewport={'width':1366,'height':900})
    page = context.new_page()

    # Login as Akshit via select + submit
    print('Opening login page...')
    page.goto(f'{BASE}/login', wait_until='networkidle')
    try:
        page.select_option('select[name="username"]', 'Akshit')
        page.click('button[type=submit]')
        page.wait_for_load_state('networkidle')
        print('Logged in as Akshit')
    except Exception as e:
        print('Login step error (may be already logged in):', e)

    targets = {
        'login': '/login',
        'dashboard': '/',
        'analytics': '/analytics',
        'goals': '/goals',
        'badges': '/badges',
        'profile': '/profile'
    }

    for name, path in targets.items():
        url = BASE + path
        print('Visiting', url)
        try:
            page.goto(url, wait_until='networkidle', timeout=15000)
            time.sleep(0.6)
            out = os.path.join(OUTDIR, f'{name}.png')
            page.screenshot(path=out, full_page=True)
            print('Saved', out)
        except Exception as e:
            print('Failed to capture', url, '->', e)
            # try a shorter navigation without waiting for networkidle
            try:
                page.goto(url, timeout=8000)
                time.sleep(0.5)
                out = os.path.join(OUTDIR, f'{name}.png')
                page.screenshot(path=out, full_page=True)
                print('Saved (fallback)', out)
            except Exception as e2:
                print('Fallback failed for', url, '->', e2)

    browser.close()
    print('Done.')
