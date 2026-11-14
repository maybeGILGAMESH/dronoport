"""New fixed-investment scheduling experiment; never edits baseline artifacts."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import argparse,json,time,concurrent.futures,shutil
import pandas as pd
from droneport.event_model import EventInstance
from droneport.event_cpsat import solve_isolated
from droneport.pipeline_v2 import save,export,metrics
from droneport.ingest import ROOT,checksum

def task(spec):
    folder,name,source,n,seconds=spec;folder=Path(folder);out=folder/'cp_ga/fixed'/name
    if (out/'solver_report.json').exists():return name
    inst=EventInstance(pd.read_csv(folder/'towns_main.csv').head(n),json.loads((folder/source/'config.json').read_text()))
    warm=json.loads((folder/source/'result.json').read_text())
    result,report=solve_isolated(inst,warm['plan'],warm,seconds=seconds,scenario=warm.get('scenario',{}),memory_gib=20)
    if result is None:raise RuntimeError(report)
    assert result['plan']==warm['plan']
    export(inst,result,out);report.update(source=source,source_sha256=checksum(folder/source/'result.json'),before=warm['completed_trips'])
    save(out/'solver_report.json',report)
    print(name,report['status'],warm['completed_trips'],'->',result['completed_trips'],flush=True)
    return name

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir');args=parser.parse_args()
    folder=Path(args.run_dir or (ROOT/'.cache/cp_ga_run.txt' if (ROOT/'.cache/cp_ga_run.txt').exists() else ROOT/'results_v2/current_run.txt').read_text().strip());begin=time.perf_counter()
    snapshot=folder/'cp_ga/source_snapshot_fixed'
    if not snapshot.exists():
        for d in ('src','scripts','config','tests'):shutil.copytree(ROOT/d,snapshot/d,ignore=shutil.ignore_patterns('__pycache__'))
    main_specs=[(str(folder),'main_8','scale/8/best',8,180),(str(folder),'main_30','base',30,180),(str(folder),'robust_30','robust',30,180)]
    with concurrent.futures.ProcessPoolExecutor(max_workers=3) as pool:list(pool.map(task,main_specs))
    specs=[]
    for row in pd.read_csv(folder/'scenario_results.csv').itertuples():
        if row.scenario=='base':continue
        source=f'scenarios/{row.plan}/{row.scenario}'
        assert json.loads((folder/source/'result.json').read_text())['plan']==json.loads((folder/row.plan/'result.json').read_text())['plan']
        specs.append((str(folder),f'{row.plan}_{row.scenario}',source,30,60))
    with concurrent.futures.ProcessPoolExecutor(max_workers=8) as pool:list(pool.map(task,specs))
    rows=[]
    for _,name,source,n,seconds in main_specs+specs:
        out=folder/'cp_ga/fixed'/name;result=json.loads((out/'result.json').read_text());report=json.loads((out/'solver_report.json').read_text());inst=EventInstance(pd.read_csv(folder/'towns_main.csv').head(n),json.loads((out/'config.json').read_text()))
        rows.append(metrics(inst,result,name=name,instance=n,before=report['before'],gain=result['completed_trips']-report['before'],
            status=report['status'],wall_seconds=report.get('process_wall_seconds',report.get('wall_seconds')),upper_bound=report.get('upper_bound'),
            variables=report.get('variables'),peak_rss_mib=report.get('peak_rss_mib'),result_path=str(out.relative_to(folder))))
    pd.DataFrame(rows).to_csv(folder/'cp_ga/fixed_results.csv',index=False)
    save(folder/'cp_ga/fixed_manifest.json',dict(status='complete',wall_seconds=time.perf_counter()-begin,cases=len(rows),
         memory_limit_gib=20,main_solver_seconds=180,scenario_solver_seconds=60,max_parallel_scenarios=8,
         scope='Same investments, purchase years, planned bases and failure rules; full configured flight grid'))

if __name__=='__main__':main()
