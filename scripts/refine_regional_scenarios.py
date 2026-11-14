"""CP recourse for the regional assets; retain all earlier feasible schedules."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ[k]='1'
from pathlib import Path
import sys,json,shutil
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import pandas as pd
from droneport.ingest import ROOT
from droneport.event_model import EventInstance
from droneport.event_cpsat import solve_isolated
from droneport.pipeline_v2 import export,save,metrics

folder=Path((ROOT/'.cache/regional_run.txt').read_text());out=folder/'regional'
shutil.copytree(out/'scenarios',out/'scenarios_before_cp')
towns=pd.read_csv(folder/'towns_main.csv');cfg=json.loads((out/'config.json').read_text());records=[]
names=list(pd.read_csv(out/'scenarios.csv').scenario)
def run(name):
    inst=EventInstance(towns,cfg);path=out/'scenarios'/name;warm=json.loads((path/'result.json').read_text())
    if name=='base':return metrics(inst,warm,scenario=name)
    result,report=solve_isolated(inst,warm['plan'],warm,scenario=warm['scenario'],mode='pool',seconds=15,workers=4,memory_gib=9)
    if result is None:result=warm
    export(inst,result,path);save(path/'cp_report.json',report)
    print(name,report['status'],warm['completed_trips'],'->',result['completed_trips'],flush=True)
    return metrics(inst,result,scenario=name)
with ThreadPoolExecutor(max_workers=2) as pool:records=list(pool.map(run,names))
# Give the weakest two failures the full time-grid model.
for row in sorted((r for r in records if r['scenario'].startswith('failed_')),key=lambda r:r['completed_trips'])[:2]:
    name=row['scenario'];path=out/'scenarios'/name;inst=EventInstance(towns,cfg);warm=json.loads((path/'result.json').read_text())
    result,report=solve_isolated(inst,warm['plan'],warm,scenario=warm['scenario'],seconds=60,workers=8,memory_gib=20)
    if result is None:result=warm
    export(inst,result,path);save(path/'full_cp_report.json',report)
    row.update(metrics(inst,result));print('FULL',name,report['status'],result['completed_trips'],flush=True)
pd.DataFrame(records).to_csv(out/'scenarios.csv',index=False)
save(out/'scenario_cp_manifest.json',dict(status='complete',pool_seconds=15,pool_workers=4,parallel_processes=2,per_process_memory_gib=9,full_seconds=60,full_workers=8,full_cases=2,full_memory_gib=20))
print('DONE',flush=True)
