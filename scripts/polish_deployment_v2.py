"""Remove unused assets without changing flights, then test feasible additions.

This is a separately timed deployment refinement, not a replacement for seed data.
"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from copy import deepcopy
import json,time,shutil
import pandas as pd
from droneport.ingest import ROOT,checksum
from droneport.event_model import EventInstance
from droneport.pipeline_v2 import export,metrics,save,route_comparison


def trim(inst,result):
    result=deepcopy(result);plan=result['plan'];needed={}
    def use(node,year):needed[node]=min(needed.get(node,year),year)
    active_ids={f['aircraft_id'] for f in result['flights']}|{f['aircraft_id'] for f in result.get('relocations',[])}
    plan['aircraft']=[a for a in plan['aircraft'] if a['id'] in active_ids]
    for f in result['flights']+result.get('relocations',[]):
        for key in ('origin_id','destination_id'):use(inst.index[f[key]],f['year'])
    for a in plan['aircraft']:
        use(a['home'],a['year'])
        for y in range(a['year'],4):use(int(a.get('homes',{}).get(str(y),a['home'])),y)
    plan['open_years']=[needed.get(i,0) for i in range(inst.n)]
    energy=[sum(f['energy_cost_rub'] for f in result['flights'] if f['year']==y)*inst.cfg['operating_days'] for y in (1,2,3)]
    ferry=[sum(f['energy_cost_rub'] for f in result.get('relocations',[]) if f['year']==y) for y in (1,2,3)]
    result['budget']=inst.fixed_budget(plan,energy,ferry)
    return result


def main():
    folder=Path((ROOT/'results_v2/current_run.txt').read_text().strip());out=folder/'deployment_polish'
    if (out/'manifest.json').exists():raise FileExistsError('Deployment refinement already exists')
    out.mkdir(exist_ok=True);cfg=json.loads((folder/'config.json').read_text());towns=pd.read_csv(folder/'towns_main.csv');rows=[];trace=[]
    for d in ('src','scripts','config'):shutil.copytree(ROOT/d,out/'source_snapshot'/d,ignore=shutil.ignore_patterns('__pycache__'),dirs_exist_ok=True)
    for n in (8,12,20,30):
        inst=EventInstance(towns.head(n),cfg);begin=time.perf_counter();original=json.loads((folder/f'scale/{n}/best/result.json').read_text());best=trim(inst,original)
        export(inst,original,out/f'{n}/original');export(inst,best,out/f'{n}/trimmed')
        def rank(r):return (r['completed_trips'],-sum(b['spend_rub'] for b in r['budget']))
        for step in range(6):
            candidate_best=best;tested=0;feasible=0
            for year in (1,2,3):
                for home in range(n):
                    plan=deepcopy(best['plan']);plan['open_years'][home]=min(plan['open_years'][home] or year,year)
                    plan['aircraft'].append(dict(id=f'polish_{step}_{year}_{home}',year=year,home=home))
                    candidate=inst.evaluate(plan);tested+=1
                    if candidate is not None:
                        feasible+=1;candidate=trim(inst,candidate)
                        if rank(candidate)>rank(candidate_best):candidate_best=candidate
                    if len(inst.cache)>32:inst.cache.clear()
            trace.append(dict(instance=n,step=step,tested=tested,feasible=feasible,completed=candidate_best['completed_trips'],cost=sum(b['spend_rub'] for b in candidate_best['budget']),improved=rank(candidate_best)>rank(best)))
            if rank(candidate_best)<=rank(best):break
            best=candidate_best;export(inst,best,out/f'{n}/step_{step}')
        export(inst,best,out/f'{n}/best');export(inst,best,folder/f'scale/{n}/best')
        row=metrics(inst,best,instance=n,method='deployment_polish',wall_seconds=time.perf_counter()-begin,gap=None,status='FEASIBLE');rows.append(row)
        if n==30:export(inst,best,folder/'base');pd.DataFrame(route_comparison(inst,best)).to_csv(folder/'bfs_astar.csv',index=False)
        print(n,best['completed_trips'],sum(b['spend_rub'] for b in best['budget']),flush=True)
    methods=pd.read_csv(folder/'method_comparison.csv')
    mips=json.loads((folder/'mip_reports.json').read_text())
    for row in rows:
        n=row['instance'];inputs=methods[(methods.instance==n)&methods.method.isin(['greedy','annealing_best','annealing_preliminary','mip'])]
        initial=float(inputs.wall_seconds.sum())
        if not (inputs.method=='mip').any():initial+=sum(r.get('wall_seconds',0) or 0 for r in mips if r['nodes']==n)
        row['refinement_seconds']=row['wall_seconds'];row['initial_plan_seconds']=initial;row['wall_seconds']+=initial
    pd.concat([methods,pd.DataFrame(rows)],ignore_index=True).to_csv(folder/'method_comparison.csv',index=False)
    annual=pd.read_csv(folder/'annual_comparison.csv');annual=annual[annual['mode']!='joint'].to_dict('records')
    for n in (8,30):
        r=json.loads((folder/f'scale/{n}/best/result.json').read_text())
        annual.extend(dict(instance=n,mode='joint',**b,completed_trips=r['annual_completed'][i]) for i,b in enumerate(r['budget']))
    pd.DataFrame(annual).to_csv(folder/'annual_comparison.csv',index=False)
    save(out/'manifest.json',dict(protocol='Fixed-schedule asset trimming, followed by best feasible single-aircraft additions with optional base opening; at most six iterations. All seed results unchanged.',
        metrics=rows,trace=trace,source_sha256=checksum(Path(__file__))))

if __name__=='__main__':main()
