"""Matched GA/SA experiment: same data, start, decoder, operators and budgets."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import argparse,json,time,shutil,concurrent.futures
import pandas as pd
from droneport.ingest import ROOT,checksum
from droneport.event_model import EventInstance
from droneport.evolution import search
from droneport.pipeline_v2 import save,export,metrics


def task(spec):
    folder,method,seed,seconds=spec;folder=Path(folder);out=folder/f'cp_ga/search/{method}/seed_{seed}'
    if (out/'search_report.json').exists():return str(out)
    inst=EventInstance(pd.read_csv(folder/'towns_main.csv'),json.loads((folder/'config.json').read_text()))
    source=folder/'cp_ga/search_start/result.json';start=json.loads(source.read_text())
    save(out/'started.json',dict(method=method,seed=seed,seconds=seconds,source_sha256=checksum(source)))
    result,report=search(inst,start,method,seed,seconds=seconds)
    export(inst,result,out);pd.DataFrame(report.pop('history')).to_csv(out/'history.csv',index=False)
    pd.DataFrame(report.pop('decoder_records')).to_csv(out/'decoder_evaluations.csv',index=False)
    report['start_sha256']=checksum(source);save(out/'search_report.json',report)
    print(method,seed,report['best_trips'],report['iterations'],report['decoder_calls'],flush=True)
    return str(out)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--seconds',type=float,default=600);parser.add_argument('--workers',type=int,default=10)
    parser.add_argument('--seeds',type=int,default=10);parser.add_argument('--run-dir');args=parser.parse_args()
    folder=Path(args.run_dir or (ROOT/'.cache/cp_ga_run.txt' if (ROOT/'.cache/cp_ga_run.txt').exists() else ROOT/'results_v2/current_run.txt').read_text().strip());begin=time.perf_counter()
    assert json.loads((folder/'cp_ga/fixed_manifest.json').read_text())['status']=='complete'
    assert (folder/'cp_ga/portfolio_30/solver_report.json').exists()
    inst=EventInstance(pd.read_csv(folder/'towns_main.csv'),json.loads((folder/'config.json').read_text()))
    candidates=[folder/'cp_ga/fixed/main_30',folder/'cp_ga/portfolio_30']
    winner=max(candidates,key=lambda p:(json.loads((p/'result.json').read_text())['completed_trips'],-sum(b['spend_rub'] for b in json.loads((p/'result.json').read_text())['budget'])))
    export(inst,json.loads((winner/'result.json').read_text()),folder/'cp_ga/search_start')
    save(folder/'cp_ga/search_start/source.json',dict(path=str(winner.relative_to(folder)),sha256=checksum(winner/'result.json')))
    snapshot=folder/'cp_ga/source_snapshot_search'
    if not snapshot.exists():
        for d in ('src','scripts','config','tests'):shutil.copytree(ROOT/d,snapshot/d,ignore=shutil.ignore_patterns('__pycache__'))
    specs=[(str(folder),method,seed,args.seconds) for seed in range(args.seeds) for method in ('sa','ga')]
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:outputs=list(pool.map(task,specs))
    rows=[];inst=EventInstance(pd.read_csv(folder/'towns_main.csv'),json.loads((folder/'config.json').read_text()))
    for name in outputs:
        out=Path(name);result=json.loads((out/'result.json').read_text());report=json.loads((out/'search_report.json').read_text())
        rows.append(metrics(inst,result,method=report['method'],seed=report['seed'],wall_seconds=report['wall_seconds'],
            iterations=report['iterations'],decoder_calls=report['decoder_calls'],cache_hits=report['cache_hits'],
            start_trips=report['start_trips'],gain=report['best_trips']-report['start_trips'],result_path=str(out.relative_to(folder))))
    frame=pd.DataFrame(rows);frame.to_csv(folder/'cp_ga/search_results.csv',index=False)
    best=frame.sort_values(['completed_trips','cost_rub'],ascending=[False,True]).iloc[0];out=folder/best.result_path
    export(inst,json.loads((out/'result.json').read_text()),folder/'cp_ga/search_best')
    save(folder/'cp_ga/search_manifest.json',dict(status='complete',wall_seconds=time.perf_counter()-begin,
        summed_run_seconds=float(frame.wall_seconds.sum()),workers=args.workers,seeds=args.seeds,seconds_per_seed=args.seconds,
        selected=str(out.relative_to(folder)),shared_decoder='Three constructive flight pools plus candidate warm timetable; CP-SAT 0.2 deterministic units / 10 wall seconds, single worker, seed 0',
        shared_start='cp_ga/search_start/result.json',population_size=12,chromosome='Port opening years and up to 12 aircraft purchase years / annual bases',
        comparison='Paired seeds; same start, mutations, repair and decoder; wall time includes solver subprocesses, repairs and validation'))

if __name__=='__main__':main()
