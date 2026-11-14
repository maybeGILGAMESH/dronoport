"""Re-run only recourse/robustness after a recovery change; preserve solved MIPs."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from copy import deepcopy
import json,time,shutil
import pandas as pd
from droneport.ingest import ROOT,checksum
from droneport.event_model import EventInstance,anneal
from droneport.pipeline_v2 import stress,export,metrics,game,save


def main():
    folder=Path((ROOT/'results_v2/current_run.txt').read_text().strip());cfg=json.loads((folder/'config.json').read_text());towns=pd.read_csv(folder/'towns_main.csv')
    instance=EventInstance(towns,cfg);base=json.loads((folder/'base/plan.json').read_text());begin=time.perf_counter()
    # The published timetable may be a MIP or a fixed-schedule asset refinement.
    # Preserve that feasible reference rather than regenerate a weaker baseline.
    instance.cache[instance.key(base),1.,None,None]=json.loads((folder/'base/result.json').read_text())
    snapshot=folder/'recourse_source_snapshot'/time.strftime('%Y%m%d_%H%M%S')
    code_names=['src/droneport/event_model.py','src/droneport/event_validation.py','src/droneport/pipeline_v2.py','scripts/refine_recourse_v2.py']
    code_hashes={name:checksum(ROOT/name) for name in code_names}
    for name in code_names:
        target=snapshot/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,target)
    def objective(plan):return min(r['completed_trips'] for _,r in stress(instance,plan))
    print('Baseline worst with safe recovery:',objective(base),flush=True)
    best,trace=anneal(instance,base,1042,iterations=60,score=objective)
    export(instance,instance.evaluate(best),folder/'robust');save(folder/'robust_search.json',trace)
    rows=[]
    for label,plan in [('base',base),('robust',best)]:
        for scenario,result in stress(instance,plan):
            export(instance,result,folder/'scenarios'/label/scenario)
            rows.append(metrics(instance,result,plan=label,scenario=scenario))
    pd.DataFrame(rows).to_csv(folder/'scenario_results.csv',index=False)
    small=EventInstance(towns.head(8),cfg);plans=[json.loads((folder/'scale/8/greedy/plan.json').read_text())]
    for path in sorted((folder/'scale/8').glob('seed_*/plan.json')):plans.append(json.loads(path.read_text()))
    for node in range(8):
        p=deepcopy(plans[0]);p['aircraft']=[a for a in p['aircraft'] if a['home']!=node];p['open_years'][node]=0
        if small.evaluate(p) is not None:plans.append(p)
    save(folder/'minimax_results.json',game(small,plans))
    save(folder/'recourse_revision.json',dict(version='safe_rotations_v3_actual_bases',source_snapshot=str(snapshot.relative_to(folder)),wall_seconds=time.perf_counter()-begin,
        scope='Recomputed robust search, all scenarios and game; investment baseline and previously solved MIPs retained',
        code_hashes=code_hashes,base_result_sha256=checksum(folder/'base/result.json'),
        base_worst=min(r['completed_trips'] for r in rows if r['plan']=='base'),robust_worst=min(r['completed_trips'] for r in rows if r['plan']=='robust')))
    print('Safe recovery refinement complete',flush=True)

if __name__=='__main__':main()
