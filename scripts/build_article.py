"""Rebuild the comparative paper from saved data without running optimizers."""
from pathlib import Path
import sys,argparse,shutil
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from droneport.ingest import ROOT
from droneport.article_figures import build
from droneport.article_document import render

parser=argparse.ArgumentParser();parser.add_argument('--run-dir');parser.add_argument('--output',default='reports/article');parser.add_argument('--text-only',action='store_true');args=parser.parse_args()
folder=Path(args.run_dir or (ROOT/'results_v2/current_run.txt').read_text().strip()).resolve();out=Path(args.output).resolve()
if not folder.exists() and not args.run_dir:
    folder=ROOT/'runs'/folder.name
if not args.text_only:build(folder,out)
render(folder,out)
shutil.copytree(folder/'report/maps',out/'maps',dirs_exist_ok=True)
