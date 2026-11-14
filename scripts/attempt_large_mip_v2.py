"""Attempt full temporal MIPs in a memory-capped child, retaining failure status."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
from pathlib import Path
import sys,argparse,json,subprocess,shutil,time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--nodes',type=int,required=True);parser.add_argument('--worker',action='store_true');parser.add_argument('--memory-gib',type=float,default=3.5);parser.add_argument('--tag',default='');args=parser.parse_args()
    folder=Path((ROOT/'results_v2/current_run.txt').read_text().strip());out=folder/f'extended_mip_attempts/{args.nodes}{args.tag}';out.mkdir(parents=True,exist_ok=True)
    if args.worker:
        os.environ['DRONEPORT_SOLVER_LOG']='1'
        import resource
        resource.setrlimit(resource.RLIMIT_AS,(int(args.memory_gib*1024**3),int(args.memory_gib*1024**3)))
        import pandas as pd
        from droneport.event_model import EventInstance
        from droneport.event_mip import solve
        from droneport.pipeline_v2 import export,save
        cfg=json.loads((folder/'config.json').read_text());cfg['matrix_nonzero_limit']=100000000
        towns=pd.read_csv(folder/'towns_main.csv').head(args.nodes);inst=EventInstance(towns,cfg)
        warm=json.loads((folder/f'scale/{args.nodes}/best/result.json').read_text())
        result,report=solve(inst,1800,warm_result=warm);report['memory_limit_gib']=args.memory_gib
        save(out/'solver_report.json',report)
        if result is not None:export(inst,result,out)
        return
    if (out/'attempt_manifest.json').exists():raise FileExistsError('Use a new --tag to preserve completed attempts')
    from droneport.ingest import checksum
    for directory in ('src','scripts','config'):shutil.copytree(ROOT/directory,out/'source_snapshot'/directory,ignore=shutil.ignore_patterns('__pycache__'),dirs_exist_ok=True)
    start=time.perf_counter()
    with (out/'solver.log').open('w') as log:
        completed=subprocess.run([sys.executable,str(Path(__file__)),'--nodes',str(args.nodes),'--memory-gib',str(args.memory_gib),'--tag',args.tag,'--worker'],stdout=log,stderr=subprocess.STDOUT)
    metadata=dict(nodes=args.nodes,returncode=completed.returncode,wall_seconds=time.perf_counter()-start,memory_limit_gib=args.memory_gib,
        code_hashes={str(p.relative_to(out/'source_snapshot')):checksum(p) for p in (out/'source_snapshot').rglob('*.py')})
    if completed.returncode:
        log=(out/'solver.log').read_text();metadata['failure_tail']=log[-3000:]
        report=dict(nodes=args.nodes,status='MEMORY_LIMIT' if any(s in log for s in ('MemoryError','bad_alloc','insufficient memory','Cannot allocate')) else 'PROCESS_FAILED',
            incumbent=None,upper_bound=None,gap=None,wall_seconds=metadata['wall_seconds'],memory_limit_gib=args.memory_gib,returncode=completed.returncode)
        (out/'solver_report.json').write_text(json.dumps(report,indent=2))
    (out/'attempt_manifest.json').write_text(json.dumps(metadata,indent=2));print(json.loads((out/'solver_report.json').read_text()),flush=True)

if __name__=='__main__':main()
