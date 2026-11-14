"""Open file:// map with network disabled in two actual browser engines."""
from pathlib import Path
import argparse,json,hashlib
from playwright.sync_api import sync_playwright


def main():
    parser=argparse.ArgumentParser();parser.add_argument('map');parser.add_argument('--output',required=True);args=parser.parse_args()
    target=Path(args.map).resolve();out=Path(args.output);out.mkdir(parents=True,exist_ok=True);results=[]
    with sync_playwright() as p:
        for name,engine,options in [('chromium',p.chromium,{'executable_path':'/usr/bin/google-chrome'}),('firefox',p.firefox,{})]:
            browser=engine.launch(headless=True,**options); context=browser.new_context(offline=True,viewport={'width':1440,'height':1000})
            page=context.new_page();errors=[];remote=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda req:remote.append(req.url) if req.url.startswith(('https://','http://')) else None)
            page.goto(target.as_uri());page.wait_for_function('window.mapReady===true')
            for selector in ['#all','#y1','#y2']:page.locator(selector).check()
            page.evaluate('() => { window.projectMap.setZoom(8); }');page.wait_for_timeout(800)
            page.screenshot(path=str(out/(name+'.png')))
            result=dict(browser=name,offline=True,remote_requests=remote,js_errors=errors,canvas_count=page.locator('canvas').count(),ready=page.evaluate('window.mapReady'),html_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),asset_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (target.parent/'assets').iterdir() if p.is_file()})
            assert not remote and not errors and result['ready'] and result['canvas_count']>0,result
            results.append(result);browser.close()
    (out/'browser_checks.json').write_text(json.dumps(results,ensure_ascii=False,indent=2));print(json.dumps(results,ensure_ascii=False))

if __name__=='__main__':main()
