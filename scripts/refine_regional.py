"""Resume a regional run after construction; preserve the earlier solver attempt."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ[k]='1'
from pathlib import Path
import sys,json,shutil,time
from copy import deepcopy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import pandas as pd
from droneport.ingest import ROOT
from droneport.event_model import EventInstance
from droneport.event_cpsat import solve_isolated
from droneport.regional_search import region_metrics
from droneport.pipeline_v2 import export,save,metrics,stress

folder=Path((ROOT/'.cache/regional_run.txt').read_text());out=folder/'regional'
cfg=json.loads((out/'config.json').read_text());inst=EventInstance(pd.read_csv(folder/'towns_main.csv'),cfg)
best=json.loads((out/'final_best/result.json').read_text())
reports=json.loads((out/'cp_reports.json').read_text())
result,report=solve_isolated(inst,best['plan'],best,seconds=180,workers=8,memory_gib=20)
reports.append(report);save(out/'cp_reports.json',reports)
print('CP',report,flush=True)
if result and result['completed_trips']>=best['completed_trips']:best=result
export(inst,best,out/'cp_refined')
polished=deepcopy(best);trips=[]
for y in (1,2,3):
    fs=[f for f in polished['flights'] if f['year']==y]
    for f in fs:f['passengers']=0;f['empty']=True
    ts,_=inst.allocate(fs,y);trips+=ts
polished['itineraries']=trips;polished['annual_completed']=[sum(t['year']==y for t in trips)*cfg['operating_days'] for y in (1,2,3)]
polished['completed_trips']=sum(polished['annual_completed'])
if polished['completed_trips']>=best['completed_trips']:best=polished
export(inst,best,out/'final_best');pd.DataFrame(region_metrics(inst,best)).to_csv(out/'region_service.csv',index=False)
comp=pd.read_csv(out/'comparison.csv');comp=comp[comp.method!='regional_service']
pd.concat([comp,pd.DataFrame([metrics(inst,best,method='regional_service')])],ignore_index=True).to_csv(out/'comparison.csv',index=False)
inst.cache[(inst.key(best['plan']),1.,None,None)]=deepcopy(best)
scenarios=[]
for name,result in stress(inst,best['plan']):
    export(inst,result,out/'scenarios'/name);scenarios.append(metrics(inst,result,scenario=name));print(name,result['completed_trips'],flush=True)
pd.DataFrame(scenarios).to_csv(out/'scenarios.csv',index=False)
manifest=json.loads((out/'manifest.json').read_text());manifest['cp_attempts']=len(reports);manifest['refinement_seconds']=report.get('process_wall_seconds');save(out/'manifest.json',manifest)
print('DONE',best['completed_trips'],flush=True)
