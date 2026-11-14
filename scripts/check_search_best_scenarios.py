"""Replan the new winning network under the same demand/range/failure scenarios."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import json,time,concurrent.futures,argparse
from copy import deepcopy
from collections import defaultdict
import pandas as pd
from droneport.ingest import ROOT,checksum
from droneport.event_model import EventInstance,recover
from droneport.event_cpsat import solve_isolated
from droneport.pipeline_v2 import export,save,metrics
from droneport.evolution import investment_key
from droneport.event_validation import validate


def task(spec):
    folder,name,kw=spec;folder=Path(folder);out=folder/'cp_ga/search_best_scenarios'/name
    if (out/'solver_report.json').exists():return str(out)
    inst=EventInstance(pd.read_csv(folder/'towns_main.csv'),json.loads((folder/'config.json').read_text()))
    best=json.loads((folder/'cp_ga/search_best/result.json').read_text());plan=best['plan']
    inst.cache[(inst.key(plan),1.,None,None)]=best
    warm=recover(inst,plan,**kw);assert warm is not None
    reused=[]
    # Reuse independently valid old recourse only if every investment and base
    # is physically identical. Aircraft names/order cannot make it inapplicable.
    for label in ('base','robust'):
        source=folder/f'scenarios/{label}/{name}/result.json'
        if not source.exists():continue
        previous=json.loads(source.read_text())
        if investment_key(previous['plan'])!=investment_key(plan):continue
        def tag(a):return a['year'],tuple(int(a.get('homes',{}).get(str(y),a['home'])) for y in range(a['year'],4))
        available=defaultdict(list)
        for a in plan['aircraft']:available[tag(a)].append(a['id'])
        mapping={a['id']:available[tag(a)].pop() for a in previous['plan']['aircraft']}
        old=deepcopy(previous);old['plan']=deepcopy(plan)
        for field in ('flights','relocations'):
            for row in old.get(field,[]):row['aircraft_id']=mapping[row['aircraft_id']]
        old['actual_homes']={y:{mapping[k]:v for k,v in homes.items()} for y,homes in old['actual_homes'].items()}
        old['blocked_aircraft']={y:[mapping[k] for k in ids] for y,ids in old['blocked_aircraft'].items()}
        assert validate(inst.towns,old,inst.cfg)['valid']
        rank=lambda r:(r['completed_trips'],-sum(b['spend_rub'] for b in r['budget']))
        if rank(old)>rank(warm):warm=old
        reused.append(dict(path=str(source.relative_to(folder)),sha256=checksum(source)))
    result,report=solve_isolated(inst,plan,warm,seconds=60,scenario=warm.get('scenario',{}))
    export(inst,result,out);report.update(before=warm['completed_trips'],source_sha256=checksum(folder/'cp_ga/search_best/result.json'),reused_feasible_scenarios=reused)
    save(out/'solver_report.json',report);print(name,result['completed_trips'],flush=True);return str(out)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir');args=parser.parse_args()
    folder=Path(args.run_dir or (ROOT/'.cache/cp_ga_run.txt' if (ROOT/'.cache/cp_ga_run.txt').exists() else ROOT/'results_v2/current_run.txt').read_text().strip());start=time.perf_counter();best=json.loads((folder/'cp_ga/search_best/result.json').read_text())
    inst=EventInstance(pd.read_csv(folder/'towns_main.csv'),json.loads((folder/'config.json').read_text()))
    scenarios=[('base',{}),('demand_070',{'factor':.7}),('demand_130',{'factor':1.3}),('range_160',{'max_range':160})]
    scenarios += [(f'failed_{inst.ids[i]}',dict(failed=i)) for i,y in enumerate(best['plan']['open_years']) if y]
    with concurrent.futures.ProcessPoolExecutor(max_workers=8) as pool:outputs=list(pool.map(task,[(str(folder),n,kw) for n,kw in scenarios]))
    rows=[]
    for p in outputs:
        p=Path(p);report=json.loads((p/'solver_report.json').read_text());result=json.loads((p/'result.json').read_text())
        rows.append(metrics(inst,result,scenario=p.name,wall_seconds=report.get('process_wall_seconds'),status=report['status'],result_path=str(p.relative_to(folder))))
    pd.DataFrame(rows).to_csv(folder/'cp_ga/search_best_scenarios.csv',index=False)
    candidates=[folder/'cp_ga/search_best',folder/'cp_ga/search_best_scenarios/base']
    chosen=max(candidates,key=lambda p:(json.loads((p/'result.json').read_text())['completed_trips'],-sum(b['spend_rub'] for b in json.loads((p/'result.json').read_text())['budget'])))
    export(inst,json.loads((chosen/'result.json').read_text()),folder/'cp_ga/final_best')
    save(folder/'cp_ga/final_best/source.json',dict(path=str(chosen.relative_to(folder)),sha256=checksum(chosen/'result.json'),stage='Separate post-search passenger reallocation and CP validation'))
    save(folder/'cp_ga/search_best_scenario_manifest.json',dict(cases=len(rows),wall_seconds=time.perf_counter()-start,seconds_per_case=60,workers=8,
        source_sha256=checksum(folder/'cp_ga/search_best/result.json'),investment_fixed=True))
    manifest=json.loads((folder/'run_manifest.json').read_text());manifest.update(status='calculated',cp_ga_finished=True)
    save(folder/'run_manifest.json',manifest)

if __name__=='__main__':main()
