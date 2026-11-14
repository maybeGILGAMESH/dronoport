"""Generate and compile the LaTeX edition from preserved numerical results."""
from pathlib import Path
import sys,argparse,subprocess,os,json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from droneport.ingest import ROOT,checksum
from droneport.latex_article import build
parser=argparse.ArgumentParser();parser.add_argument('--online',action='store_true');parser.add_argument('--generate-only',action='store_true');args=parser.parse_args()
out=ROOT/'reports/latex';manifest=build(out)
if not args.generate_only:
    command=[str(ROOT/'.tools/tectonic'),'-b','http://127.0.0.1:18766/tex.tar','--keep-logs','--keep-intermediates']
    if not args.online:command.append('--only-cached')
    command.append('report.tex')
    with (out/'compile.log').open('w') as f:subprocess.run(command,cwd=out,env={**os.environ,'XDG_CACHE_HOME':str(ROOT/'.tools/tex-cache')},stdout=f,stderr=subprocess.STDOUT,check=True)
    from pypdf import PdfReader
    manifest.update(pages=len(PdfReader(out/'report.pdf').pages),pdf_sha256=checksum(out/'report.pdf'),engine='Tectonic 0.17.0 (XeTeX/LaTeX)',cached_only=not args.online)
    (out/'build_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    print('LaTeX PDF:',manifest['pages'],'pages;',manifest['figures'],'figures',flush=True)
