"""Additional full-grid CP-SAT with eight search workers, preserved separately."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import json,shutil,time,argparse
import pandas as pd
from droneport.ingest import ROOT,checksum
from droneport.event_model import EventInstance
from droneport.event_cpsat import solve_isolated
from droneport.pipeline_v2 import export,save

parser=argparse.ArgumentParser();parser.add_argument('--run-dir');args=parser.parse_args()
folder=Path(args.run_dir or (ROOT/'.cache/cp_ga_run.txt' if (ROOT/'.cache/cp_ga_run.txt').exists() else ROOT/'results_v2/current_run.txt').read_text().strip());out=folder/'cp_ga/portfolio_30'
if out.exists():raise FileExistsError(out)
for d in ('src','scripts','config','tests'):shutil.copytree(ROOT/d,out/'source_snapshot'/d,ignore=shutil.ignore_patterns('__pycache__'))
inst=EventInstance(pd.read_csv(folder/'towns_main.csv'),json.loads((folder/'config.json').read_text()))
source=folder/'cp_ga/fixed/main_30/result.json';warm=json.loads(source.read_text())
result,report=solve_isolated(inst,warm['plan'],warm,seconds=180,workers=8)
export(inst,result,out);report['source_sha256']=checksum(source);save(out/'solver_report.json',report)
print(report,flush=True)
