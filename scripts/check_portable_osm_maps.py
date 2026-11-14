"""Check standalone maps after relocation/renaming in two network-disabled browsers."""
from pathlib import Path
import tempfile,shutil,json,hashlib,sys,argparse
from playwright.sync_api import sync_playwright
parser=argparse.ArgumentParser();parser.add_argument('--browser',choices=['chromium','firefox']);args=parser.parse_args()
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'artifacts/maps';manifest=json.loads((OUT/'manifest.json').read_text());checks=[]
previous=OUT/'validation.json'
if args.browser and previous.exists():
 old=json.loads(previous.read_text())
 if old.get('files')=={x['file']:x['sha256'] for x in manifest['files']}:checks=[r for r in old['checks'] if r['browser']!=args.browser]
(OUT/'previews').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='droneport portable maps ') as temp:
 root=Path(temp)
 # Different folders with a single renamed HTML in each: no neighboring assets available.
 for item in manifest['files']:
  folder=root/('Карта '+item['variant']);folder.mkdir();shutil.copy2(OUT/item['file'],folder/'любой файл.html')
 with sync_playwright() as p:
  for name,engine,options in [('chromium',p.chromium,{'executable_path':'/usr/bin/google-chrome'}),('firefox',p.firefox,{})]:
   if args.browser and args.browser!=name:continue
   for item in manifest['files']:
    browser=engine.launch(headless=True,**options)
    context=browser.new_context(offline=True,viewport={'width':1440,'height':960})
    page=context.new_page();errors=[];remote=[];local=[]
    page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:remote.append(r.url) if r.url.startswith(('http://','https://')) else local.append(r.url) if r.url.startswith('file:') else None)
    url=(root/('Карта '+item['variant'])/'любой файл.html').as_uri()
    for year in (1,2,3):
     page.goto(url+'?year='+str(year),wait_until='load',timeout=120000)
     page.wait_for_function('window.captureReady===true && !tile.isLoading()',timeout=60000)
     assert page.evaluate('window.mapState.variant')==item['variant']
     assert page.evaluate('window.mapState.year')==year
     assert not page.evaluate('window.tileErrors') and not errors and not remote,(item,errors,remote)
     assert all(x.split('?')[0]==url for x in local),local
     visible=page.locator('canvas[data-osm]').count();assert visible>=4,(item,visible)
     # Confirm there are actual painted map features, not a uniform background image.
     varied=page.evaluate("""Array.from(document.querySelectorAll('canvas[data-osm]')).some(c=>{let a=c.getContext('2d').getImageData(0,0,512,512).data;let n=0;for(let i=0;i<a.length;i+=64){if(a[i]!=250||a[i+1]!=251||a[i+2]!=249)n++}return n>100})""")
     assert varied,(item,'No cartographic features')
     checks.append(dict(browser=name,variant=item['variant'],year=year,view='network',embedded_canvases=visible,offline=True,relocated_and_renamed=True))
     if year==3:page.screenshot(path=str(OUT/'previews'/f'{item["variant"]}_{name}.png'))
    # Test native detail and ancestor fallback at a location without detailed tiles.
    for label,lat,lon,z in [('port_detail',55.993,37.482,13),('regional_overview',56.2,35.4,7),('remote_overzoom',57.8,33.8,14)]:
     page.evaluate('([lat,lon,z])=>map.setView([lat,lon],z)',[lat,lon,z]);page.wait_for_function('!tile.isLoading()',timeout=60000);page.wait_for_timeout(100)
     assert page.locator('canvas[data-osm]').count()>=4 and not page.evaluate('window.tileErrors') and not errors and not remote
     checks.append(dict(browser=name,variant=item['variant'],view=label,zoom=z,offline=True,relocated_and_renamed=True))
    page.close();browser.close();print(name,item['variant'],'all checks passed',flush=True)
assert len({(r['browser'],r['variant'],r['view'],r.get('year')) for r in checks})==len(checks)
report=dict(valid=len(checks)==36,checks=checks,browsers=sorted({r['browser'] for r in checks}),network_disabled=True,external_requests=0,relative_asset_requests=0,html_files=3,files={x['file']:hashlib.sha256((OUT/x['file']).read_bytes()).hexdigest() for x in manifest['files']})
assert all(report['files'][x['file']]==x['sha256'] for x in manifest['files'])
(OUT/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print('Passed',len(checks),'map checks',flush=True)
