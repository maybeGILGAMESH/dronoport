"""Sequential online-local and network-disabled screenshots of every saved view."""
from pathlib import Path
import argparse,json,subprocess,sys,time,socket,urllib.request,hashlib,os
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright
from PIL import Image,ImageChops
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--offline-only',action='store_true');args=parser.parse_args()
out=ROOT/'reports/latex';maps=out/'maps';shots=out/'screenshots';shots.mkdir(exist_ok=True)
views=json.loads((maps/'views.json').read_text());process=None;checks=[]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
try:
    if not args.offline_only:
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        log=open(ROOT/'.cache/local_osm_server.log','w')
        process=subprocess.Popen([sys.executable,str(ROOT/'scripts/serve_local_osm.py'),'--port',str(port)],stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'})
        start=time.monotonic()
        while True:
            if process.poll() is not None:raise RuntimeError('Local OSM server exited; see .cache/local_osm_server.log')
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/health',timeout=1) as r:
                    if json.load(r)['ready']:break
            except OSError:pass
            if time.monotonic()-start>120:raise TimeoutError('OSM startup')
            time.sleep(.5)
    with sync_playwright() as p:
        configurations=[]
        if not args.offline_only:configurations.append(('chromium_local',p.chromium,False,{'executable_path':'/usr/bin/google-chrome'}))
        configurations += [('chromium_offline',p.chromium,True,{'executable_path':'/usr/bin/google-chrome'}),('firefox_offline',p.firefox,True,{})]
        for label,engine,offline,options in configurations:
            if offline and process is not None:
                process.terminate();process.wait(timeout=20);process=None;log.close()
                print('Local server stopped; proceeding without network',flush=True)
            browser=engine.launch(headless=True,**options)
            context=browser.new_context(offline=offline,viewport={'width':1440,'height':960},device_scale_factor=2)
            for v in views:
                page=context.new_page();errors=[];requests=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('request',lambda r:requests.append(r.url) if r.url.startswith(('http://','https://')) else None)
                query=urlencode(dict(variant=v['variant'],year=v['year'],view=v['view'],capture='1'))
                base=(maps/'index.html').as_uri() if offline else f'http://127.0.0.1:{port}/index.html'
                page.goto(base+'?'+query,wait_until='load',timeout=120000)
                page.wait_for_function('window.captureReady===true',timeout=120000)
                page.wait_for_timeout(250)
                tile_errors=page.evaluate('window.tileErrors');assert not tile_errors,(v['id'],tile_errors)
                assert not errors,(v['id'],errors)
                assert all(r.startswith(f'http://127.0.0.1:{port}/') for r in requests) if not offline else not requests
                directory=shots/label;directory.mkdir(exist_ok=True);target=directory/(v['id']+'.png')
                page.screenshot(path=str(target))
                row=dict(**v,browser=label,offline=offline,remote_requests=len([r for r in requests if not r.startswith('http://127.0.0.1:')]),http_requests=len(requests),tile_errors=tile_errors,js_errors=errors,state=page.evaluate('window.mapState'),file=str(target.relative_to(out)),sha256=sha(target))
                if label=='chromium_offline' and not args.offline_only:
                    a=Image.open(shots/'chromium_local'/(v['id']+'.png')).convert('RGB');b=Image.open(target).convert('RGB')
                    same=ImageChops.difference(a,b).getbbox() is None;row['identical_to_local_server']=same
                    assert same,('Online/offline pixels differ',v['id'])
                checks.append(row);print(label,v['id'],'OK',flush=True);page.close()
            browser.close()
    records=[r for r in checks if r['browser']=='chromium_offline']
    (out/'screenshots_manifest.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))
    tile_files=sorted((maps/'tiles').rglob('*.png'))
    report=dict(valid=True,views=len(views),checks=checks,tiles=len(tile_files),tile_bytes=sum(t.stat().st_size for t in tile_files),tile_hashes={str(t.relative_to(maps)):sha(t) for t in tile_files},map_hashes={str(t.relative_to(maps)):sha(t) for t in [maps/'index.html',maps/'network_data.js',maps/'views.json']},external_network_requests=0,server_stopped_before_offline=True)
    (out/'map_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('All map captures passed:',len(checks),'checks;',len(tile_files),'local tiles',flush=True)
finally:
    if process is not None:process.terminate();process.wait(timeout=20)
