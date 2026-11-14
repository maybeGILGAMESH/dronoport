"""Improve the final sequential stage's start, keeping years 1 and 2 fixed."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import json,time,shutil
import pandas as pd
from droneport.ingest import ROOT,checksum
from droneport.event_model import EventInstance
from droneport.event_warmstart import extend_year
from droneport.event_mip import solve
from droneport.pipeline_v2 import export,save,metrics


def main():
    folder=Path((ROOT/'results_v2/current_run.txt').read_text().strip());out=folder/'sequential_mip/8';cfg=json.loads((folder/'config.json').read_text());inst=EventInstance(pd.read_csv(folder/'towns_main.csv').head(8),cfg)
    previous=json.loads((out/'year_2/result.json').read_text());old=json.loads((out/'year_3/result.json').read_text());begin=time.perf_counter();warm=extend_year(inst,previous,3);warm_seconds=time.perf_counter()-begin
    export(inst,warm,out/'constructed_year_3_start');print('Constructed year 3 start:',warm['annual_completed'],flush=True)
    if warm['annual_completed'][2]<=old['annual_completed'][2]:return
    backup=out/'year_3_without_constructive_start'
    if backup.exists():raise FileExistsError(backup)
    shutil.copytree(out/'year_3',backup)
    snapshot=out/'constructive_start_source_snapshot'
    for d in ('src','scripts','config'):shutil.copytree(ROOT/d,snapshot/d,ignore=shutil.ignore_patterns('__pycache__'))
    result,report=solve(inst,600,objective_years=[3],fixed=previous,warm_result=warm)
    report['constructive_start_seconds']=warm_seconds;report['comparison_budget']='600 seconds final stage, plus explicitly reported construction time'
    export(inst,result,out/'year_3');save(out/'year_3/solver_report.json',report);export(inst,result,out)
    reports=json.loads((out/'solver_reports.json').read_text());reports[2]=report;save(out/'solver_reports.json',reports)
    methods=pd.read_csv(folder/'method_comparison.csv');methods=methods[~((methods.instance==8)&(methods.method=='sequential_mip'))]
    row=metrics(inst,result,instance=8,method='sequential_mip',wall_seconds=sum(r['wall_seconds'] for r in reports)+warm_seconds,gap=report['gap'],status=report['status'])
    pd.concat([methods,pd.DataFrame([row])],ignore_index=True).to_csv(folder/'method_comparison.csv',index=False)
    save(out/'constructive_start_revision.json',dict(previous_attempt='year_3_without_constructive_start',source_sha256=checksum(Path(__file__)),fixed_years=[1,2],warm_start_seconds=warm_seconds,annual_completed=result['annual_completed']))
    print('Sequential final stage complete:',result['annual_completed'],flush=True)

if __name__=='__main__':main()
