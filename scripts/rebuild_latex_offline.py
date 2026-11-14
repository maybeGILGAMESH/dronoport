"""One sequential entrypoint: local OSM maps, screenshots, LaTeX, validation."""
from pathlib import Path
import sys,subprocess,argparse,time,json,os,hashlib,shutil,socket
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--offline',action='store_true',help='Use only the already prepared local tiles and TeX cache');parser.add_argument('--network-namespace',action='store_true',help='Record that the caller has disabled networking using unshare -Urn');parser.add_argument('--reuse-maps',action='store_true',help='Reuse previously verified screenshots and tiles; all hashes are checked again');args=parser.parse_args()
out=ROOT/'reports/latex';out.mkdir(exist_ok=True);records=[]
interfaces=sorted(name for _,name in socket.if_nameindex())
if args.network_namespace:assert interfaces==['lo'],interfaces
steps=[]
if not args.offline:steps.append(('Extract local cartography',['scripts/extract_cartography.py']))
steps += [('Audit saved calculations',['scripts/audit_research.py']),('Prepare map layers',['scripts/build_detailed_maps.py']),('Capture all network views',['scripts/capture_network_maps.py']+(['--offline-only'] if args.offline else [])),('Compile LaTeX',['scripts/build_latex_report.py']),('Validate PDF, formulas and HTML',['scripts/check_latex_report.py','--browsers'])]
if args.reuse_maps:
 assert args.offline and (out/'map_validation.json').exists() and (out/'screenshots_manifest.json').exists()
 steps=[(title,cmd) for title,cmd in steps if title not in ('Prepare map layers','Capture all network views')]
if args.offline and (out/'map_validation.json').exists() and not (out/'map_local_server_validation.json').exists():
 shutil.copy2(out/'map_validation.json',out/'map_local_server_validation.json')
for title,arguments in steps:
 print(title,flush=True);started=time.monotonic();subprocess.run([sys.executable,*arguments],cwd=ROOT,check=True)
 records.append(dict(step=title,command=arguments,seconds=time.monotonic()-started))
report=dict(valid=True,offline=args.offline,network_namespace=args.network_namespace,network_interfaces=interfaces,steps=records,pdf_sha256=hashlib.sha256((out/'report.pdf').read_bytes()).hexdigest(),optimizers_rerun=False,reused_verified_maps=args.reuse_maps)
if args.network_namespace:assert report['network_interfaces']==['lo'],report['network_interfaces']
(out/'pipeline_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print('Sequential build complete',flush=True)
