"""Checkpointed experimental suite for expanded rotations, separate from legacy runs."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from copy import deepcopy
import argparse
import json
import shutil
import time
import hashlib
import numpy as np
import pandas as pd
import networkx as nx
import yaml
from .ingest import ROOT,checksum
from .event_model import EventInstance,greedy,anneal,recover
from .event_validation import validate


def save(path,value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=lambda v:v.item() if hasattr(v,'item') else str(v)),encoding='utf-8')


def export(instance,result,folder):
    check=validate(instance.towns,result,instance.cfg)
    if not check['valid']:
        save(folder/'rejected.json',dict(result=result,validation=check)); raise RuntimeError(str(check['errors'][:5]))
    save(folder/'result.json',result); save(folder/'validation.json',check); save(folder/'config.json',instance.cfg)
    for name,key in [('budget_by_year','budget'),('flights_and_schedule','flights'),('passenger_itineraries','itineraries'),('interyear_relocations','relocations')]:
        pd.DataFrame(result.get(key,[])).to_csv(folder/(name+'.csv'),index=False)
    save(folder/'plan.json',result['plan'])
    return check


def metrics(inst,result,**tags):
    total=int(np.floor(inst.demand*result.get('scenario',{}).get('factor',1.)).sum()*inst.cfg['operating_days'])
    return dict(**tags,completed_trips=result['completed_trips'],demand=total,
        served_share=result['completed_trips']/max(1,total),
        cost_rub=sum(r['spend_rub'] for r in result['budget']),ports=result['budget'][-1]['active_ports'],
        fleet=result['budget'][-1]['active_aircraft'],transfers=sum(t['transfers']>0 for t in result['itineraries']),
        empty_flights=sum(f['empty'] for f in result['flights']))


def stress(instance,plan):
    scenarios=[('base',{}),('demand_070',dict(factor=.7)),('demand_130',dict(factor=1.3)),('range_160',dict(max_range=160))]
    scenarios += [(f'failed_{instance.ids[i]}',dict(failed=i)) for i,y in enumerate(plan['open_years']) if y]
    records=[]
    for name,kw in scenarios:
        result=recover(instance,plan,**kw)
        if result is None:
            # Cost feasibility is part of recourse; holding all aircraft idle is
            # always feasible when fixed costs are feasible.
            relocation=instance.relocations(plan,kw.get('max_range'),kw.get('failed'))
            if relocation is None: raise RuntimeError('No feasible interyear relocation for fixed investment plan')
            rr,re,blocked,actual=relocation
            result=dict(plan=deepcopy(plan),flights=[],itineraries=[],annual_completed=[0]*3,completed_trips=0,
                budget=instance.fixed_budget(plan,relocation_energy=re),relocations=rr,blocked_aircraft={str(y):sorted(v) for y,v in blocked.items()},actual_homes={str(y):v for y,v in actual.items()},
                scenario=dict(factor=kw.get('factor',1.),max_range=kw.get('max_range'),failed=kw.get('failed')),allocation_status=[])
        records.append((name,result))
    return records


def route_comparison(instance,result):
    records=[]; n=instance.n; c=instance.cfg
    for label,year in [('potential',0)]+[('built',y) for y in (1,2,3)]:
        g=nx.DiGraph(); g.add_nodes_from(range(n))
        if year==0:
            pairs=[(a,b) for a in range(n) for b in range(n) if a!=b and instance.distance[a,b]<=c['range_km']]
        else: pairs={(instance.index[f['origin_id']],instance.index[f['destination_id']]) for f in result['flights'] if f['year']==year}
        for a,b in pairs: g.add_edge(a,b,weight=instance.distance[a,b]/c['flight_speed_kmh']*60+c['landing_minutes']+c['charging_minutes'])
        for a in range(n):
            for b in range(n):
                if a==b: continue
                row=dict(graph=label,year=year,origin=instance.ids[a],destination=instance.ids[b],reachable=nx.has_path(g,a,b))
                if row['reachable']:
                    start=time.perf_counter(); bfs=nx.shortest_path(g,a,b); row['bfs_seconds']=time.perf_counter()-start
                    start=time.perf_counter(); astar=nx.astar_path(g,a,b,heuristic=lambda u,v:instance.distance[u,v]/c['flight_speed_kmh']*60,weight='weight'); row['astar_seconds']=time.perf_counter()-start
                    row.update(bfs_hops=len(bfs)-1,astar_hops=len(astar)-1,bfs_minutes=nx.path_weight(g,bfs,'weight'),astar_minutes=nx.path_weight(g,astar,'weight'))
                    assert abs(row['astar_minutes']-nx.dijkstra_path_length(g,a,b))<1e-6
                if year:
                    arrivals={a:instance.start-c['minimum_transfer_minutes']}
                    for f in sorted((f for f in result['flights'] if f['year']==year),key=lambda f:f['departure_min']):
                        u=instance.index[f['origin_id']]; v=instance.index[f['destination_id']]
                        if arrivals.get(u,float('inf'))+c['minimum_transfer_minutes']<=f['departure_min']:
                            arrivals[v]=min(arrivals.get(v,float('inf')),f['arrival_min'])
                    row['schedule_reachable']=b in arrivals; row['earliest_arrival']=arrivals.get(b)
                records.append(row)
    return records


def network_signature(plan):
    fleet=sorted((a['year'],a['home'],tuple(int(a.get('homes',{}).get(str(y),a['home'])) for y in range(a['year'],4))) for a in plan['aircraft'])
    return json.dumps([plan['open_years'],fleet])


def game(instance,plans):
    unique={}
    for p in plans:unique.setdefault(network_signature(p),p)
    tree=[]; actions=[];leaf_checks=[]
    for p in list(unique.values())[:10]:
        base=instance.evaluate(p); children=[]; labels=[]
        for i,y in enumerate(p['open_years']):
            if not y: continue
            failed=instance.ids[i]
            recovered=recover(instance,p,failed=i); retained=recover(instance,p,failed=i,mode='retain')
            for response,result in [('retain',retained),('reschedule',recovered)]:
                check=validate(instance.towns,result,instance.cfg)
                assert check['valid'],check
                leaf_checks.append(dict(network=len(tree),failed_node=failed,response=response,**check))
            recourse=recovered['completed_trips']
            cancel=retained['completed_trips']
            children.append([cancel,recourse]); labels.append(failed)
        if children: tree.append(children); actions.append(dict(plan=p,failed_nodes=labels))
    def run(prune):
        visits=0
        def walk(node,depth,alpha,beta):
            nonlocal visits
            visits+=1
            if not isinstance(node,list): return node
            maxi=depth%2==0; value=-float('inf') if maxi else float('inf')
            for child in node:
                score=walk(child,depth+1,alpha,beta); value=max(value,score) if maxi else min(value,score)
                if maxi: alpha=max(alpha,value)
                else: beta=min(beta,value)
                if prune and alpha>=beta: break
            return value
        start=time.perf_counter(); value=walk(tree,0,-float('inf'),float('inf'))
        return dict(value=value,visited_nodes=visits,wall_seconds=time.perf_counter()-start)
    full=run(False); ab=run(True); assert full['value']==ab['value']
    return dict(network_actions=len(tree),tree=tree,actions=actions,leaf_validation=leaf_checks,full=full,alpha_beta=ab,
        scope='Finite listed networks and two explicit heuristic recourse actions; not a bound over all networks')


def main(args=None):
    parser=argparse.ArgumentParser(); parser.add_argument('--model-version',default='v2'); parser.add_argument('--experiments',choices=['full','quick'],default='full')
    parser.add_argument('--seed',type=int,default=0); parser.add_argument('--solver-seconds',type=float,default=1800)
    parser.add_argument('--report-only',action='store_true'); parser.add_argument('--run-dir'); parser.add_argument('--skip-mip',action='store_true'); parser.add_argument('--resume',action='store_true')
    opts=parser.parse_args(args)
    if opts.report_only:
        from .report_v2 import generate
        generate(Path(opts.run_dir) if opts.run_dir else Path((ROOT/'results_v2/current_run.txt').read_text().strip())); return
    cfg=yaml.safe_load((ROOT/'config/model.yaml').read_text()); cfg.update(yaml.safe_load((ROOT/'config/expanded.yaml').read_text())); cfg['mip_seconds']=opts.solver_seconds
    full=opts.experiments=='full'; cfg['annealing_iterations']=0 if full else 8
    if opts.resume:
        folder=Path(opts.run_dir) if opts.run_dir else Path((ROOT/'results_v2/current_run.txt').read_text().strip()); run_id=folder.name
        if json.loads((folder/'config.json').read_text())!=cfg: raise ValueError('Resume configuration differs from saved configuration')
    else:
        run_id=datetime.now(ZoneInfo('Europe/Moscow')).strftime('%Y%m%d_%H%M%S')+'_v2'; folder=ROOT/'runs'/run_id; folder.mkdir()
    (ROOT/'results_v2').mkdir(exist_ok=True); (ROOT/'results_v2/current_run.txt').write_text(str(folder))
    towns=pd.read_csv(ROOT/'data/processed/towns_main.csv',dtype={'region_code':str}); towns.to_csv(folder/'towns_main.csv',index=False)
    invocation=datetime.now(ZoneInfo('Europe/Moscow')).strftime('%Y%m%d_%H%M%S_%f')
    if (folder/'run_manifest.json').exists():shutil.copy2(folder/'run_manifest.json',folder/f'previous_manifest_{invocation}.json')
    save(folder/'config.json',cfg); save(folder/'run_manifest.json',dict(run_id=run_id,status='running',model_version=cfg['model_version'],experiment_mode=opts.experiments))
    # Snapshot code before execution; later report-only edits cannot silently
    # replace the implementation that produced these numerical results.
    source_root=folder/'source_snapshot'
    if source_root.exists():source_root=folder/'source_snapshots'/invocation
    for directory in ('src','config','scripts','tests'):
        shutil.copytree(ROOT/directory,source_root/directory,ignore=shutil.ignore_patterns('__pycache__'))
    old_seeds=pd.read_csv(folder/'seed_results.csv') if opts.resume and (folder/'seed_results.csv').exists() else pd.DataFrame()
    old_trace=pd.read_csv(folder/'search_history.csv') if opts.resume and (folder/'search_history.csv').exists() else pd.DataFrame()
    old_experiments=pd.read_csv(folder/'experiments.csv') if opts.resume and (folder/'experiments.csv').exists() else pd.DataFrame()
    started=time.perf_counter(); comparison=[]; seeds=[]; history=[]; instances={}; plans={}; game_plans=[]
    sizes=[8,12,20,30] if full else [8,30]
    for n in sizes:
        print(f'V2 scale {n}: greedy',flush=True); inst=EventInstance(towns.head(n),cfg); instances[n]=inst
        begin=time.perf_counter(); p,h=greedy(inst); elapsed=time.perf_counter()-begin; result=inst.evaluate(p)
        export(inst,result,folder/'scale'/str(n)/'greedy'); plans[n]=p
        comparison.append(metrics(inst,result,instance=n,method='greedy',wall_seconds=elapsed,gap=None,status='FEASIBLE'))
        if n==8: game_plans.append(p)
        for seed in range(opts.seed,opts.seed+(10 if full else 2)):
            saved=folder/'scale'/str(n)/f'seed_{seed}'/'result.json'
            if opts.resume and saved.exists():
                result=json.loads(saved.read_text()); sp=result['plan']; inst.cache[inst.key(sp),1.,None,None]=result
                trace=old_trace[(old_trace.instance==n)&(old_trace.seed==seed)].drop(columns=['instance']).to_dict('records')
                elapsed=float(old_seeds[(old_seeds.instance==n)&(old_seeds.seed==seed)].wall_seconds.iloc[0])
            else:
                begin=time.perf_counter(); sp,trace=anneal(inst,p,seed); result=inst.evaluate(sp); elapsed=time.perf_counter()-begin
            export(inst,result,folder/'scale'/str(n)/f'seed_{seed}')
            row=metrics(inst,result,instance=n,method='annealing',seed=seed,wall_seconds=elapsed,gap=None,status='FEASIBLE')
            seeds.append(row); history += [dict(instance=n,**r) for r in trace]
            if result['completed_trips']>inst.evaluate(plans[n])['completed_trips']: plans[n]=sp
            if n==8: game_plans.append(sp)
            print(f'V2 n={n} seed={seed}: {result["completed_trips"]}, {elapsed:.2f}s',flush=True)
            pd.DataFrame(seeds).to_csv(folder/'seed_results.csv',index=False); pd.DataFrame(history).to_csv(folder/'search_history.csv',index=False)
            # Retain only selected plans between runs, avoiding unbounded caching.
            inst.cache={k:v for k,v in inst.cache.items() if k[0] in {inst.key(p),inst.key(plans[n])}}
        best=inst.evaluate(plans[n]); export(inst,best,folder/'scale'/str(n)/'best')
        comparison.append(metrics(inst,best,instance=n,method='annealing_best',wall_seconds=sum(r['wall_seconds'] for r in seeds if r['instance']==n),gap=None,status='FEASIBLE'))
        pd.DataFrame(comparison).to_csv(folder/'method_comparison.csv',index=False)
    inst=instances[30]; base=inst.evaluate(plans[30]); export(inst,base,folder/'base')
    print('V2 budgets and sensitivity',flush=True); experiments=[]
    def experiment(tag,value,changes):
        cc=deepcopy(cfg)
        for key,val in changes.items():
            if key.startswith('demand.'): cc['demand'][key.split('.')[1]]=val
            else: cc[key]=val
        ii=EventInstance(towns,cc); begin=time.perf_counter(); name=f'{tag}_{value}'; saved=folder/'experiments'/name/'result.json'
        if opts.resume and saved.exists():
            if json.loads((saved.parent/'config.json').read_text())!=cc: raise ValueError('Cached experiment configuration differs')
            rr=json.loads(saved.read_text()); oldrow=old_experiments[(old_experiments.experiment==tag)&(old_experiments.value==value)]
            elapsed=float(oldrow.wall_seconds.iloc[0]) if len(oldrow) else None
        else:
            pp,_=greedy(ii); rr=ii.evaluate(pp); elapsed=time.perf_counter()-begin
        export(ii,rr,folder/'experiments'/name)
        experiments.append(metrics(ii,rr,experiment=tag,value=value,wall_seconds=elapsed))
        pd.DataFrame(experiments).to_csv(folder/'experiments.csv',index=False)
    amounts=list(range(250,1001,50)) if full else [500,1000]
    for amount in amounts: experiment('budget',amount,{'yearly_tranche_rub':amount*1000000})
    budgetrows=[r for r in experiments if r['experiment']=='budget']; refine=[]
    if full:
        for a,b in zip(budgetrows,budgetrows[1:]):
            if (a['ports'],a['fleet'])!=(b['ports'],b['fleet']): refine+=list(range(a['value']+10,b['value'],10))
        for amount in refine: experiment('budget',amount,{'yearly_tranche_rub':amount*1000000})
    for key in ('port_capex_rub','aircraft_capex_rub','port_opex_rub_per_year','aircraft_opex_rub_per_year','flight_speed_kmh'):
        for factor in (.8,1.2): experiment(key,factor,{key:int(cfg[key]*factor)})
    for minutes in (20,45): experiment('charging_minutes',minutes,{'charging_minutes':minutes})
    for gamma in (1.2,1.8): experiment('demand.gamma',gamma,{'demand.gamma':gamma})
    for growth in (1.,1.1): experiment('demand.yearly_growth',growth,{'demand.yearly_growth':growth})
    experiment('quality_cap',.95,{'population_cap_quantile':.95})
    for step in (5,15):
        cc=deepcopy(cfg); cc['time_step_minutes']=step; ii=EventInstance(towns.head(8),cc)
        begin=time.perf_counter(); pp,_=greedy(ii); rr=ii.evaluate(pp); export(ii,rr,folder/'grid'/str(step))
        experiments.append(metrics(ii,rr,experiment='grid_small',value=step,wall_seconds=time.perf_counter()-begin))
    pd.DataFrame(experiments).to_csv(folder/'experiments.csv',index=False)
    annual=[]
    for n in (8,30):
        ii=instances[n]; begin=time.perf_counter(); pp,_=greedy(ii,sequential=True); rr=ii.evaluate(pp); export(ii,rr,folder/'sequential'/str(n))
        comparison.append(metrics(ii,rr,instance=n,method='sequential_greedy',wall_seconds=time.perf_counter()-begin,gap=None,status='FEASIBLE'))
        for mode,res in [('sequential',rr),('joint',ii.evaluate(plans[n]))]:
            for year,row in enumerate(res['budget']): annual.append(dict(instance=n,mode=mode,**row,completed_trips=res['annual_completed'][year]))
    pd.DataFrame(annual).to_csv(folder/'annual_comparison.csv',index=False)
    print('V2 robust search',flush=True)
    def objective(p): return min(r['completed_trips'] for _,r in stress(inst,p))
    if opts.resume and (folder/'robust/result.json').exists():
        saved=json.loads((folder/'robust/result.json').read_text());rp=saved['plan'];inst.cache[inst.key(rp),1.,None,None]=saved
        trace=json.loads((folder/'robust_search.json').read_text())
    else: rp,trace=anneal(inst,plans[30],1042,iterations=60 if full else 4,score=objective)
    save(folder/'robust_search.json',trace); export(inst,inst.evaluate(rp),folder/'robust'); scenarios=[]
    for label,p in [('base',plans[30]),('robust',rp)]:
        for scenario,rr in stress(inst,p):
            export(inst,rr,folder/'scenarios'/label/scenario)
            scenarios.append(metrics(inst,rr,plan=label,scenario=scenario))
    pd.DataFrame(scenarios).to_csv(folder/'scenario_results.csv',index=False)
    # Enrich the finite action set with explicitly saved feasible networks.
    for node in range(8):
        pp=deepcopy(plans[8]); pp['aircraft']=[a for a in pp['aircraft'] if a['home']!=node]; pp['open_years'][node]=0
        if instances[8].evaluate(pp) is not None: game_plans.append(pp)
    save(folder/'minimax_results.json',game(instances[8],game_plans))
    pd.DataFrame(route_comparison(inst,base)).to_csv(folder/'bfs_astar.csv',index=False)
    reports=[]; bounds=[]
    from .event_mip import solve
    from .event_bound import upper_bound
    for n in sizes:
        print(f'V2 MIP n={n}',flush=True)
        if opts.skip_mip: result=None; report=dict(status='SKIPPED_BY_CLI',nodes=n)
        else: result,report=solve(instances[n],opts.solver_seconds,warm_result=instances[n].evaluate(plans[n]))
        if result is not None:
            export(instances[n],result,folder/'scale'/str(n)/'mip')
            comparison.append(metrics(instances[n],result,instance=n,method='mip',wall_seconds=report['wall_seconds'],gap=report['gap'],status=report['status']))
        reports.append(report); save(folder/'mip_reports.json',reports)
        bound=upper_bound(instances[n]); bound['nodes']=n; bounds.append(bound);save(folder/'aggregate_bounds.json',bounds)
    # Same temporal formulation for sequential MIP; past assets and actual
    # flights are frozen, rather than re-optimizing historical operations.
    for n in (8,30):
        previous=None; seq_reports=[]
        for year in (1,2,3):
            if opts.skip_mip: break
            print(f'V2 sequential MIP n={n}, year={year}',flush=True)
            from .event_warmstart import extend_year
            warm=extend_year(instances[n],previous,year) if previous is not None else instances[n].evaluate(plans[n])
            rr,report=solve(instances[n],opts.solver_seconds/3,objective_years=[year],fixed=previous,warm_result=warm)
            seq_reports.append(report); save(folder/'sequential_mip'/str(n)/'solver_reports.json',seq_reports)
            if rr is None: break
            previous=rr
        if previous is not None and len(seq_reports)==3:
            export(instances[n],previous,folder/'sequential_mip'/str(n))
            comparison.append(metrics(instances[n],previous,instance=n,method='sequential_mip',wall_seconds=sum(r['wall_seconds'] for r in seq_reports),gap=seq_reports[-1]['gap'],status=seq_reports[-1]['status']))
    pd.DataFrame(comparison).to_csv(folder/'method_comparison.csv',index=False)
    manifest=dict(run_id=run_id,status='calculated',model_version=cfg['model_version'],experiment_mode=opts.experiments,
        wall_seconds=time.perf_counter()-started,resumed=opts.resume,timing_note='wall_seconds covers this invocation; per-experiment timings retain original computation time when resumed',data_sha256=checksum(ROOT/'data/processed/towns_main.csv'),
        source_snapshot=str(source_root.relative_to(folder)),code_and_config_hashes={str(p.relative_to(source_root)):checksum(p) for base in ('src','scripts','config') for p in (source_root/base).rglob('*') if p.suffix in ('.py','.yaml','.sh')},
        limitations=['Official registry completeness unverified; population nulls preserved',
                     'MIP resource guard may prevent full model solution on larger instances',
                     'Heuristic recourse lower values are not certified worst-case optimal recourse values'])
    save(folder/'run_manifest.json',manifest)
    from .experiment_refinement import refine
    refine(folder)
    import subprocess,sys
    subprocess.run([sys.executable,str(ROOT/'scripts/compare_legacy_v2.py')],check=True)
    subprocess.run([sys.executable,str(ROOT/'scripts/build_examples_v2.py')],check=True)
    from .report_v2 import generate
    generate(folder)
    print(f'V2 DONE {folder}',flush=True)
