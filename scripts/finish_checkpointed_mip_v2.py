"""Complete only missing sequential MIPs, checkpointing every annual solution."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import json,time,shutil,argparse
import pandas as pd
from droneport.ingest import ROOT,checksum
from droneport.event_model import EventInstance
from droneport.event_mip import solve
from droneport.pipeline_v2 import export,metrics,save


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--total-seconds',type=float,default=1800);args=parser.parse_args()
    folder=Path((ROOT/'results_v2/current_run.txt').read_text().strip());cfg=json.loads((folder/'config.json').read_text());towns=pd.read_csv(folder/'towns_main.csv')
    snapshot=folder/('sequential_resume_source_snapshot_'+time.strftime('%Y%m%d_%H%M%S'));snapshot.mkdir(exist_ok=True)
    for d in ('src','scripts','config'):shutil.copytree(ROOT/d,snapshot/d,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
    begin=time.perf_counter()
    for n in (8,30):
        inst=EventInstance(towns.head(n),cfg);out=folder/f'sequential_mip/{n}';out.mkdir(parents=True,exist_ok=True)
        if (out/'result.json').exists():continue
        prior=out/'solver_reports.json';backup=out/'interrupted_solver_reports.json'
        if prior.exists() and not backup.exists():shutil.copy2(prior,backup)
        reports=[];previous=None
        warm_paths=list((folder/f'scale/{n}').glob('*/result.json'))+list((folder/f'time_budget_study/scale/{n}').glob('*/result.json'))
        warm_candidates=[json.loads(p.read_text()) for p in warm_paths]
        warm=max(warm_candidates,key=lambda r:r['annual_completed'][0])
        for y in (1,2,3):
            checkpoint=out/f'year_{y}'
            if (checkpoint/'result.json').exists():
                result=json.loads((checkpoint/'result.json').read_text());report=json.loads((checkpoint/'solver_report.json').read_text())
            else:
                print(f'Sequential temporal MIP: n={n}, year={y}',flush=True)
                result,report=solve(inst,args.total_seconds/3,objective_years=[y],fixed=previous,warm_result=previous or warm)
                report['comparison_budget']='One third of the 1800-second total per instance, matching the joint solve budget'
                save(checkpoint/'solver_report.json',report)
                if result is not None:export(inst,result,checkpoint)
            reports.append(report);save(prior,reports)
            if result is None:break
            previous=result
        if previous is not None and len(reports)==3:export(inst,previous,out)
    # Reconstruct the comparison from persisted results, not lost process state.
    methods=pd.read_csv(folder/'method_comparison.csv');methods=methods[~methods.method.isin(['mip','sequential_mip','sequential_greedy'])].to_dict('records')
    mips=json.loads((folder/'mip_reports.json').read_text())
    for n in (8,12,20,30):
        inst=EventInstance(towns.head(n),cfg)
        for method,path in [('mip',folder/f'scale/{n}/mip'),('sequential_mip',folder/f'sequential_mip/{n}'),('sequential_greedy',folder/f'sequential/{n}')]:
            if not (path/'result.json').exists():continue
            result=json.loads((path/'result.json').read_text())
            if method=='mip':report=next(r for r in mips if r['nodes']==n);elapsed=report['wall_seconds']
            elif method=='sequential_mip':rs=json.loads((path/'solver_reports.json').read_text());report=rs[-1];elapsed=sum(r['wall_seconds'] for r in rs)
            else:report={'status':'FEASIBLE','gap':None};elapsed=None
            methods.append(metrics(inst,result,instance=n,method=method,wall_seconds=elapsed,gap=report.get('gap'),status=report['status']))
    pd.DataFrame(methods).to_csv(folder/'method_comparison.csv',index=False)
    manifest=json.loads((folder/'run_manifest.json').read_text());manifest.update(status='calculated',sequential_resume_wall_seconds=time.perf_counter()-begin,
        sequential_resume_source_hashes={str(p.relative_to(snapshot)):checksum(p) for p in snapshot.rglob('*.py')},
        interruption_note='Original process ended without a final checkpoint; previously exported results retained. Sequential solves restarted with per-year checkpoints.')
    save(folder/'run_manifest.json',manifest);print('Checkpointed numerical completion ready',flush=True)

if __name__=='__main__':main()
