"""Equal 600-second SA budgets, isolated outputs and bounded-memory workers."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import argparse,json,time,shutil
from concurrent.futures import ProcessPoolExecutor,as_completed
import pandas as pd
from droneport.ingest import ROOT,checksum
from droneport.event_model import EventInstance,anneal
from droneport.pipeline_v2 import export,metrics,save


def worker(args):
    folder,n,seed,seconds=args;folder=Path(folder)
    cfg=json.loads((folder/'config.json').read_text());cfg['annealing_iterations']=0;cfg['annealing_seconds']=seconds
    towns=pd.read_csv(folder/'towns_main.csv').head(n);inst=EventInstance(towns,cfg)
    plan=json.loads((folder/f'scale/{n}/greedy/plan.json').read_text());start=time.perf_counter()
    best,history=anneal(inst,plan,seed);result=inst.evaluate(best);elapsed=time.perf_counter()-start
    destination=folder/f'time_budget_study/scale/{n}/seed_{seed}';export(inst,result,destination)
    pd.DataFrame(history).to_csv(destination/'history.csv',index=False)
    row=metrics(inst,result,instance=n,method='annealing',seed=seed,wall_seconds=elapsed,gap=None,status='FEASIBLE')
    row['iterations']=len(history);save(destination/'metrics.json',row)
    return row


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--seconds',type=float,default=600);parser.add_argument('--workers',type=int,default=16);parser.add_argument('--resume',action='store_true');args=parser.parse_args()
    folder=Path((ROOT/'results_v2/current_run.txt').read_text().strip());out=folder/'time_budget_study';out.mkdir(exist_ok=True)
    snapshot=out/('resume_source_snapshot_'+time.strftime('%Y%m%d_%H%M%S') if args.resume else 'source_snapshot')
    for directory in ('src','scripts','config'):shutil.copytree(ROOT/directory,snapshot/directory,ignore=shutil.ignore_patterns('__pycache__'),dirs_exist_ok=True)
    start=time.perf_counter();rows=[];pending=[]
    for n in (8,12,20,30):
        for seed in range(10):
            saved=out/f'scale/{n}/seed_{seed}/metrics.json'
            if args.resume and saved.exists():
                row=json.loads(saved.read_text());assert row['wall_seconds']>=args.seconds;rows.append(row)
            else:pending.append((str(folder),n,seed,args.seconds))
    resumed_count=len(rows)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        jobs=[pool.submit(worker,job) for job in pending]
        for future in as_completed(jobs):
            row=future.result();rows.append(row);pd.DataFrame(rows).sort_values(['instance','seed']).to_csv(out/'seed_results.csv',index=False)
            print(f'{len(rows)}/40: n={row["instance"]}, seed={row["seed"]}, trips={row["completed_trips"]}, seconds={row["wall_seconds"]:.1f}',flush=True)
    save(out/'manifest.json',dict(status='calculated',seconds_per_seed=args.seconds,workers=args.workers,wall_seconds=time.perf_counter()-start,resumed_count=resumed_count,
        summed_worker_seconds=sum(r['wall_seconds'] for r in rows),initial='Saved identical greedy plan for each size; seeds 0..9',
        timing_scope='Concurrent CPU workers; elapsed wall time per run includes resource contention. wall_seconds covers this invocation only; earlier completed per-run timings are retained. Compare quality at equal elapsed limits, not isolated CPU throughput.',
        code_hashes={str(p.relative_to(snapshot)):checksum(p) for p in snapshot.rglob('*.py')}))

if __name__=='__main__':main()
