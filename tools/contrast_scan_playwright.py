from playwright.sync_api import sync_playwright
import json, os

BASE = 'http://127.0.0.1:5000'
OUTDIR = 'visual_checks'
os.makedirs(OUTDIR, exist_ok=True)

pages = ['/login','/','/analytics','/goals','/badges','/profile']

js_script = r"""
() => {
  function luminance(r,g,b){
    const a=[r,g,b].map(function(v){
      v/=255;
      return v<=0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055,2.4);
    });
    return 0.2126*a[0]+0.7152*a[1]+0.0722*a[2];
  }
  function contrastRatio(fg, bg){
    const L1 = luminance(fg[0],fg[1],fg[2]);
    const L2 = luminance(bg[0],bg[1],bg[2]);
    const light = Math.max(L1,L2);
    const dark = Math.min(L1,L2);
    return (light+0.05)/(dark+0.05);
  }
  function parseRGB(str){
    if(!str) return [0,0,0];
    str = str.trim();
    // rgb/rgba
    const m = str.match(/rgba?\(([^)]+)\)/i);
    if(m){
      const parts = m[1].split(',').map(x=>parseFloat(x));
      return parts.slice(0,3);
    }
    // hex #rrggbb or #rgb
    const mh = str.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
    if(mh){
      const h = mh[1];
      if(h.length===3){
        return [parseInt(h[0]+h[0],16), parseInt(h[1]+h[1],16), parseInt(h[2]+h[2],16)];
      }
      return [parseInt(h.substr(0,2),16), parseInt(h.substr(2,2),16), parseInt(h.substr(4,2),16)];
    }
    // fallback try to extract numbers
    const nums = str.match(/(\d+),\s*(\d+),\s*(\d+)/);
    if(nums) return [parseInt(nums[1]), parseInt(nums[2]), parseInt(nums[3])];
    return [0,0,0];
  }
  function getEffectiveBackground(el){
    let node = el;
    while(node && node.nodeType===1){
      const bg = getComputedStyle(node).backgroundColor;
      if(bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') return bg;
      node = node.parentElement;
    }
    return 'rgb(11,11,12)'; // page default dark
  }
  function getSelector(el){
    if(el.id) return '#'+el.id;
    let sel = el.tagName.toLowerCase();
    if(el.classList && el.classList.length) sel += '.' + Array.from(el.classList).join('.');
    return sel;
  }
  const nodes = Array.from(document.querySelectorAll('body *'));
  const results = [];
  nodes.forEach(el => {
    const cs = getComputedStyle(el);
    if(!cs) return;
    const text = el.innerText || el.textContent || '';
    if(!text || text.trim().length===0) return;
    // skip invisible
    if(cs.visibility==='hidden' || cs.display==='none' || parseFloat(cs.opacity||1)===0) return;
    const fontSize = parseFloat(cs.fontSize||16);
    const isLarge = fontSize >= 18 || (fontSize>=14 && (cs.fontWeight==='700' || parseInt(cs.fontWeight||400)>=700));
    const fg = parseRGB(cs.color);
    const bgStr = getEffectiveBackground(el);
    const bg = parseRGB(bgStr);
    const ratio = contrastRatio(fg,bg);
    const passes = isLarge ? ratio>=3.0 : ratio>=4.5;
    if(!passes){
      results.push({
        selector: getSelector(el),
        text: text.trim().slice(0,80),
        fontSize: fontSize,
        ratio: Math.round(ratio*100)/100,
        recommendedColor: '#e8e8e8'
      });
    }
  });
  return results;
}
"""

with sync_playwright() as p:
    browser = None
    try:
        browser = p.chromium.launch(channel='chrome', headless=True)
    except Exception:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception:
            browser = p.firefox.launch(headless=True)

    context = browser.new_context(viewport={'width':1366,'height':900})
    page = context.new_page()

    all_reports = {}
    for path in pages:
        # Append timestamp to bust cache so CSS changes are picked up
        url = BASE + path + ('?_ts=' + str(int(os.times()[4])))
        print('Visiting', url)
        try:
            page.goto(url, wait_until='networkidle', timeout=15000)
        except Exception as e:
            print('Navigate warning', e)
        # attempt login if on login page
        if path=='/login':
            try:
                page.select_option('select[name="username"]', 'Akshit')
                page.click('button[type=submit]')
                page.wait_for_load_state('networkidle')
            except Exception as e:
                print('Login skipped or failed', e)
        try:
            res = page.evaluate(js_script)
            all_reports[path.strip('/') or 'index'] = res
            fname = os.path.join(OUTDIR, (path.strip('/') or 'index') + '.json')
            with open(fname,'w',encoding='utf-8') as f:
                json.dump(res,f,indent=2)
            print('Saved report', fname)
        except Exception as e:
            print('Eval error', e)

    browser.close()
    print('Contrast scans done')
