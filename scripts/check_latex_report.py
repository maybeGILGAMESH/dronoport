"""Validate the LaTeX edition, its numerical provenance and offline HTML."""
from pathlib import Path
import sys,json,re,hashlib,argparse
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from droneport.ingest import ROOT,checksum
from droneport.latex_content import FORMULAS,AXES
from droneport.event_validation import validate
from pypdf import PdfReader
import pandas as pd
from playwright.sync_api import sync_playwright

parser=argparse.ArgumentParser();parser.add_argument('--browsers',action='store_true');args=parser.parse_args()
out=ROOT/'reports/latex';m=json.loads((out/'build_manifest.json').read_text());tex=(out/'report.tex').read_text()
assert m['cached_only'],'Final build must use the offline TeX cache'
assert checksum(out/'report.pdf')==m['pdf_sha256'] and checksum(out/'report.tex')==m['tex_sha256']
assert m['source_article_sha256']==checksum(ROOT/'reports/article/article.json')
assert all(checksum(ROOT/k)==v for k,v in m['source_files'].items())
assert m['formulas']==len(FORMULAS)==14 and m['definitions']==75
assert len(re.findall(r'\\begin\{equation\}',tex))==14
assert tex.count(r'\textbf{Где:}')==14 and tex.count(r'\textbf{Как читать рисунок ')==m['graph_reading_guides']
assert len(re.findall(r'\\begin\{figure\}',tex))==m['figures']
assert len(set(re.findall(r'\\label\{eq:([^}]+)',tex)))==14
assert '\u2014' not in tex and '\u2014' not in (out/'article.md').read_text()
log=(out/'compile.log').read_text()
assert not re.search(r'Overfull|Missing character|already defined|^error:|downloading',log,re.M),log
reader=PdfReader(out/'report.pdf');texts=[p.extract_text() for p in reader.pages]
assert len(reader.pages)==m['pages'] and all(len(t)>70 for t in texts)
assert sum(int(p.get('/Rotate',0))%180!=0 for p in reader.pages)==25
assert '\u2014' not in ''.join(texts) and sum(t.count('Где:') for t in texts)==14
assert sum(t.count('Как читать рисунок') for t in texts)==m['graph_reading_guides']
audit=json.loads((ROOT/'reports/research_audit/validation.json').read_text());assert audit['valid']
for name,digest in {**audit['sources'],**audit['outputs']}.items():assert checksum(ROOT/name)==digest,name
catalog=pd.read_csv(ROOT/'reports/research_audit/result_catalog.csv');assert len(catalog)==540 and catalog.valid.all()
# Check every inventoried numerical artifact is still present and unchanged.
for row in pd.read_csv(ROOT/'reports/research_audit/file_inventory.csv').itertuples():assert (ROOT/row.path).stat().st_size==row.bytes and checksum(ROOT/row.path)==row.sha256,row.path
maps=json.loads((out/'map_validation.json').read_text());assert maps['valid'] and maps['views']==25 and maps['external_network_requests']==0
for name,digest in maps['tile_hashes'].items():assert checksum(out/'maps'/name)==digest,name
for name,digest in maps['map_hashes'].items():assert checksum(out/'maps'/name)==digest,name
sources=json.loads((out/'maps/source_manifest.json').read_text())
for name,digest in sources['sources'].items():assert checksum(ROOT/name)==digest,name
shots=json.loads((out/'screenshots_manifest.json').read_text());assert len(shots)==25
for s in shots:assert checksum(out/s['file'])==s['sha256'],s['id']
folder=ROOT/'runs/20261106_154352_regional';towns=pd.read_csv(folder/'towns_main.csv');plans=[]
for tag,sub in [('A','base'),('B','cp_ga/final_best'),('C','regional/final_best')]:
 r=json.loads((folder/sub/'result.json').read_text());cfg=json.loads((folder/sub/'config.json').read_text());check=validate(towns,r,cfg);assert check['valid'];plans.append(dict(variant=tag,**check))
requirements=pd.read_csv(folder/'requirements_matrix.csv');assert len(requirements)==28 and (requirements.status=='partial').sum()==3
original_article=json.loads((ROOT/'reports/article/article.json').read_text());matrix=next(b for b in original_article['blocks'] if b.get('title','').startswith('Таблица B1.'))
assert all(row[0] in (out/'article.md').read_text() for row in matrix['rows'])
browsers=[]
if args.browsers:
 with sync_playwright() as p:
  for name,engine,options in [('chromium',p.chromium,{'executable_path':'/usr/bin/google-chrome'}),('firefox',p.firefox,{})]:
   browser=engine.launch(headless=True,**options);context=browser.new_context(offline=True,viewport={'width':1440,'height':1000});page=context.new_page();remote=[];errors=[]
   page.on('request',lambda r:remote.append(r.url) if r.url.startswith(('http://','https://')) else None);page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto((out/'report.html').as_uri());page.locator('img').evaluate_all("els=>els.forEach(e=>e.loading='eager')");page.wait_for_function('Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)',timeout=60000)
   assert page.locator('figure').count()==m['figures'] and page.locator('.equation').count()==14 and page.locator('.definitions li').count()==75
   assert page.locator('merror').count()==0 and not remote and not errors
   page.locator('#eq-1').scroll_into_view_if_needed();page.screenshot(path=str(out/(name+'_mathml.png')))
   browsers.append(dict(browser=name,offline=True,figures=m['figures'],math_formulas=14,definitions=75,remote_requests=remote,js_errors=errors));browser.close()
result=dict(valid=True,pages=m['pages'],formulas=14,definitions=75,graph_guides=m['graph_reading_guides'],screenshots=25,figures=m['figures'],tiles=maps['tiles'],numerical_plans=plans,requirements=28,partial_requirements=requirements[requirements.status=='partial'].id.tolist(),cached_latex=True,typesetting_warnings=False,browsers=browsers,pdf_sha256=m['pdf_sha256'])
(out/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False,indent=2))
