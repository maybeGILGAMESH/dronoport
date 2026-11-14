"""Fixed-investment CP-SAT: aircraft cycles and integer passenger flows.

Full mode uses every feasible flight on the configured time grid. Pool mode
restricts departure arcs to deterministic constructive schedules, but can
recombine them freely. Its bound is ONLY for that pool and fixed investments.
The native solver runs in a separate process from HiGHS.
"""
from collections import defaultdict, Counter
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time


def solve_isolated(instance, plan, warm=None, seconds=30, mode='full', scenario=None,
                   pool_seeds=3, seed=0, memory_gib=20, deterministic_limit=None,workers=1):
    begin=time.perf_counter()
    payload=dict(towns=instance.towns.to_dict('records'),cfg=instance.cfg,plan=plan,warm=warm,
                 seconds=seconds,mode=mode,scenario=scenario or {},pool_seeds=pool_seeds,
                 seed=seed,memory_gib=memory_gib,deterministic_limit=deterministic_limit,workers=workers)
    env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]),
             OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
    try:
        proc=subprocess.run([sys.executable,'-m','droneport.event_cpsat'],input=json.dumps(payload),
                            text=True,capture_output=True,env=env,timeout=seconds+180)
        if proc.returncode: raise RuntimeError(proc.stderr[-3000:])
        answer=json.loads(proc.stdout)
    except (subprocess.TimeoutExpired,RuntimeError,json.JSONDecodeError) as exc:
        return deepcopy(warm),dict(status='PROCESS_FAILED',error=str(exc),upper_bound=None,
                                    wall_seconds=time.perf_counter()-begin,mode=mode)
    answer['report']['process_wall_seconds']=time.perf_counter()-begin
    return answer['result'],answer['report']


def optimize(instance,plan,warm=None,seconds=30,mode='full',scenario=None,pool_seeds=3,
             seed=0,deterministic_limit=None,workers=1):
    from ortools.sat.python import cp_model
    import networkx as nx
    from .event_validation import validate
    begin=time.perf_counter(); c=instance.cfg; scenario=scenario or {}
    from .regional_policy import ports_ok,groups as regional_groups,service_applies
    if not ports_ok(instance,plan):return None,dict(status='INFEASIBLE_REGIONAL_PORTS',upper_bound=None)
    factor=scenario.get('factor',1.);failed=scenario.get('failed');limit=scenario.get('max_range') or c['range_km']
    relocation=instance.relocations(plan,scenario.get('max_range'),failed)
    if relocation is None:return None,dict(status='INFEASIBLE_RELOCATION',upper_bound=None)
    rr,re,blocked,actual=relocation
    fixed=instance.fixed_budget(plan,relocation_energy=re)
    if any(b['carry_rub']<0 for b in fixed):return None,dict(status='INFEASIBLE_FIXED_BUDGET',upper_bound=None)
    supplied_warm=warm is not None
    if warm is not None:
        assert warm['plan']==plan and validate(instance.towns,warm,c)['valid']
        assert warm.get('scenario',{}).get('factor',1.)==factor
        assert warm.get('scenario',{}).get('failed')==failed
        assert warm.get('scenario',{}).get('max_range')==scenario.get('max_range')
    else:
        warm=dict(plan=deepcopy(plan),flights=[],itineraries=[],budget=fixed,annual_completed=[0]*3,
                  completed_trips=0,scenario=dict(factor=factor,failed=failed,max_range=scenario.get('max_range')),
                  relocations=rr,actual_homes={str(y):v for y,v in actual.items()},
                  blocked_aircraft={str(y):sorted(v) for y,v in blocked.items()},allocation_status=[])
    m=cp_model.CpModel(); step=instance.step;T=c['day_minutes']//step;charge=instance.charge//step
    aw={};af={};pw={};pf={};q={};year_arcs={};year_homes={};year_nodes={};energy=[[] for _ in range(3)]
    allvars=[];hints=Counter()
    def var(hi):
        v=m.new_int_var(0,int(hi),'');allvars.append(v);return v
    def hint(v,k=1):hints[v.index]+=k
    for y in (1,2,3):
        nodes=[i for i,v in enumerate(plan['open_years']) if 0<v<=y and i!=failed]
        groups=defaultdict(list)
        for a in plan['aircraft']:
            if a['year']<=y and a['id'] not in blocked[y]:groups[actual[y][a['id']]].append(a)
        year_homes[y]=groups;year_nodes[y]=nodes
        graph=nx.DiGraph();graph.add_nodes_from(nodes)
        for a in nodes:
            for b in nodes:
                if a!=b and instance.distance[a,b]<=limit:graph.add_edge(a,b,weight=int(instance.travel[a,b])//step+charge)
        shortest=dict(nx.all_pairs_dijkstra_path_length(graph,weight='weight'))
        arcs=set()
        def add_flights(fs):
            for f in fs:
                if f['year']!=y:continue
                a=instance.index[f['origin_id']];b=instance.index[f['destination_id']]
                arcs.add((a,b,(f['departure_min']-instance.start)//step,
                          (f['arrival_min']-instance.start)//step,(f['charge_end_min']-instance.start)//step))
        if mode=='full':
            for a,b in graph.edges:
                duration=int(instance.travel[a,b])//step
                for t in range(T-duration-charge+1):arcs.add((a,b,t,t+duration,t+duration+charge))
        elif mode=='pool':
            for s in range(pool_seeds):
                p=deepcopy(plan);p['schedule_seed']=s
                add_flights(instance.schedule(p,y,factor,scenario.get('max_range'),failed,blocked[y],actual[y]))
        else:raise ValueError(mode)
        add_flights(warm['flights'])
        arcs=sorted(arcs);year_arcs[y]=arcs;movement=defaultdict(list);charging=defaultdict(list);caps=defaultdict(list)
        flight_key={(a,b,t,arr,end):k for k,(a,b,t,arr,end) in enumerate(arcs)}
        for home,assets in groups.items():
            balance=defaultdict(list);count=len(assets)
            reachable=shortest.get(home,{})
            for i in nodes:
                if i not in reachable:continue
                for t in range(T):
                    v=var(count);aw[y,home,i,t]=v;balance[i,t].append(-v);balance[i,t+1].append(v)
            for k,(a,b,t,arr,end) in enumerate(arcs):
                if reachable.get(a,T+1)>t or end+shortest.get(b,{}).get(home,T+1)>T:continue
                v=var(count);af[y,home,k]=v;balance[a,t].append(-v);balance[b,end].append(v);caps[k].append(v)
                movement[a,t*step//c['movement_window_minutes']].append(v)
                movement[b,arr*step//c['movement_window_minutes']].append(v)
                for tcharge in range(arr,end):charging[b,tcharge].append(v)
                cost=math.ceil(instance.distance[a,b]*c['energy_kwh_per_km']*c['electricity_rub_per_kwh'])
                energy[y-1].append(v*cost*c['operating_days'])
            balance[home,0].append(count);balance[home,T].append(-count)
            for terms in balance.values():m.add(sum(terms)==0)
            for asset in assets:
                loc=home;ready=0
                for f in sorted((f for f in warm['flights'] if f['year']==y and f['aircraft_id']==asset['id']),key=lambda f:f['departure_min']):
                    tag=(instance.index[f['origin_id']],instance.index[f['destination_id']],(f['departure_min']-instance.start)//step,(f['arrival_min']-instance.start)//step,(f['charge_end_min']-instance.start)//step)
                    a,b,t,arr,end=tag
                    for wait in range(ready,t):hint(aw[y,home,loc,wait])
                    hint(af[y,home,flight_key[tag]]);loc=b;ready=end
                for wait in range(ready,T):hint(aw[y,home,loc,wait])
        maxflow=sum(len(a) for a in groups.values())*c['capacity_per_flight']*T
        for dest in nodes:
            balance=defaultdict(list)
            for origin in nodes:
                demand=math.floor(int(instance.demand[y-1,origin,dest])*factor)
                if origin==dest or not demand:continue
                v=var(demand);q[y,origin,dest]=v;balance[origin,0].append(v);balance[dest,T].append(-v)
            for i in nodes:
                for t in range(T):
                    v=var(maxflow);pw[y,dest,i,t]=v;balance[i,t].append(-v);balance[i,t+1].append(v)
            for k,(a,b,t,arr,end) in enumerate(arcs):
                if a==dest or not caps[k]:continue
                arrival=min(T,arr+math.ceil(c['minimum_transfer_minutes']/step))
                v=var(c['capacity_per_flight']*sum(len(a) for a in groups.values()));pf[y,dest,k]=v
                balance[a,t].append(-v);balance[b,arrival].append(v)
            for terms in balance.values():m.add(sum(terms)==0)
        for k in range(len(arcs)):
            loads=[pf[y,d,k] for d in nodes if (y,d,k) in pf]
            if loads:m.add(sum(loads)<=c['capacity_per_flight']*sum(caps[k]))
        for terms in movement.values():m.add(sum(terms)<=c['max_movements_per_window'])
        for terms in charging.values():m.add(sum(terms)<=c['chargers_per_port'])
        # Every completed trip uses at least one flight; each flight consumes
        # two movements. This redundant bound helps CP-SAT certify small cases.
        movement_bound=(len(nodes)*math.ceil(c['day_minutes']/c['movement_window_minutes'])*c['max_movements_per_window']//2)*c['capacity_per_flight']
        m.add(sum(v for (yy,o,d),v in q.items() if yy==y)<=movement_bound)
        fdict={f['flight_id']:f for f in warm['flights'] if f['year']==y}
        for trip in (t for t in warm['itineraries'] if t['year']==y):
            origin=instance.index[trip['origin_id']];dest=instance.index[trip['destination_id']];loc=origin;ready=0
            hint(q[y,origin,dest])
            for fid in json.loads(trip['flight_ids']):
                f=fdict[fid];a=instance.index[f['origin_id']];b=instance.index[f['destination_id']]
                tag=(a,b,(f['departure_min']-instance.start)//step,(f['arrival_min']-instance.start)//step,(f['charge_end_min']-instance.start)//step)
                for wait in range(ready,tag[2]):hint(pw[y,dest,loc,wait])
                hint(pf[y,dest,flight_key[tag]]);loc=b;ready=min(T,tag[3]+math.ceil(c['minimum_transfer_minutes']/step))
            for wait in range(ready,T):hint(pw[y,dest,loc,wait])
    if service_applies(c,scenario):
        policy=c['regional_coverage'];year=policy.get('deadline_year',3)
        for nodes in regional_groups(instance).values():
            terms=[v for (y,h,k),v in af.items() if y==year and (year_arcs[y][k][0] in nodes or year_arcs[y][k][1] in nodes)]
            m.add(sum(terms)>=policy['min_flights'])
    for y in range(3):m.add(sum(term for terms in energy[:y+1] for term in terms)<=fixed[y]['carry_rub'])
    objective=sum(q.values());m.maximize(objective)
    m.add(objective>=warm['completed_trips']//c['operating_days'])
    for v in allvars:m.add_hint(v,hints[v.index])
    solver=cp_model.CpSolver();solver.parameters.max_time_in_seconds=float(seconds)
    solver.parameters.num_search_workers=workers;solver.parameters.random_seed=int(seed)
    if deterministic_limit is not None:solver.parameters.max_deterministic_time=deterministic_limit
    report=dict(mode=mode,scope='Fixed investments and actual bases; '+('all grid flight arcs' if mode=='full' else 'candidate flight pool only'),
                variables=len(allvars),constraints=len(m.proto.constraints),build_seconds=time.perf_counter()-begin,
                seconds=seconds,seed=seed,pool_seeds=pool_seeds,deterministic_limit=deterministic_limit,workers=workers)
    status=solver.solve(m);report.update(status=solver.status_name(status),solve_seconds=solver.wall_time,
        upper_bound=solver.best_objective_bound*c['operating_days'] if status in (cp_model.FEASIBLE,cp_model.OPTIMAL) else None,
        solver_incumbent=round(solver.objective_value)*c['operating_days'] if status in (cp_model.FEASIBLE,cp_model.OPTIMAL) else None)
    result=deepcopy(warm)
    if status in (cp_model.FEASIBLE,cp_model.OPTIMAL):
        values={v.index:solver.value(v) for v in allvars};flights=[];trips=[];flight_arcs=defaultdict(list)
        for y,groups in year_homes.items():
            arcs=year_arcs[y]
            for home,assets in groups.items():
                adjacency=defaultdict(list)
                for (yy,h,i,t),v in aw.items():
                    if yy==y and h==home:adjacency[i,t].append((v.index,i,t+1,None))
                for k,(a,b,t,arr,end) in enumerate(arcs):
                    if (y,home,k) in af:adjacency[a,t].append((af[y,home,k].index,b,end,k))
                for asset in assets:
                    state=(home,0)
                    while state!=(home,T):
                        v,b,end,k=next(item for item in adjacency[state] if values[item[0]]>0)
                        values[v]-=1;state=(b,end)
                        if k is None:continue
                        a,b,t,arr,end=arcs[k];d=instance.distance[a,b]
                        f=dict(year=y,flight_id=f'y{y}_cp{len(flights)}',aircraft_id=asset['id'],origin_id=instance.ids[a],destination_id=instance.ids[b],
                               departure_min=instance.start+t*step,arrival_min=instance.start+arr*step,charge_end_min=instance.start+end*step,
                               distance_km=d,energy_cost_rub=math.ceil(d*c['energy_kwh_per_km']*c['electricity_rub_per_kwh']),passengers=0,empty=True)
                        flights.append(f);flight_arcs[y,k].append(f)
            for dest in year_nodes[y]:
                adjacency=defaultdict(list)
                for i in year_nodes[y]:
                    for t in range(T):adjacency[i,t].append((pw[y,dest,i,t].index,i,t+1,None))
                for k,(a,b,t,arr,end) in enumerate(arcs):
                    if (y,dest,k) in pf:adjacency[a,t].append((pf[y,dest,k].index,b,min(T,arr+math.ceil(c['minimum_transfer_minutes']/step)),k))
                for origin in year_nodes[y]:
                    if (y,origin,dest) not in q:continue
                    for _ in range(solver.value(q[y,origin,dest])):
                        state=(origin,0);legs=[]
                        while state!=(dest,T):
                            v,b,t,k=next(item for item in adjacency[state] if values[item[0]]>0)
                            values[v]-=1;state=(b,t)
                            if k is not None:
                                f=next(f for f in flight_arcs[y,k] if f['passengers']<c['capacity_per_flight'])
                                f['passengers']+=1;f['empty']=False;legs.append(f)
                        trips.append(dict(year=y,trip_id=f'y{y}_cp_p{len(trips)}',origin_id=instance.ids[origin],destination_id=instance.ids[dest],
                                          flight_ids=json.dumps([f['flight_id'] for f in legs]),arrival_min=legs[-1]['arrival_min'],transfers=len(legs)-1,annual_weight=c['operating_days']))
        annual=[sum(t['year']==y for t in trips)*c['operating_days'] for y in (1,2,3)]
        costs=[sum(f['energy_cost_rub'] for f in flights if f['year']==y)*c['operating_days'] for y in (1,2,3)]
        candidate=dict(warm,flights=flights,itineraries=trips,annual_completed=annual,completed_trips=sum(annual),budget=instance.fixed_budget(plan,costs,re))
        assert validate(instance.towns,candidate,c)['valid'],validate(instance.towns,candidate,c)['errors'][:3]
        assert candidate['completed_trips']==report['solver_incumbent']
        rank=lambda r:(r['completed_trips'],-sum(b['spend_rub'] for b in r['budget']))
        if rank(candidate)>rank(result) or not validate(instance.towns,result,c)['valid']:result=candidate
    if not validate(instance.towns,result,c)['valid']:
        assert not supplied_warm
        report.update(completed_trips=None,improvement=None,wall_seconds=time.perf_counter()-begin,solution_origin='no_valid_incumbent')
        return None,report
    report.update(completed_trips=result['completed_trips'],improvement=result['completed_trips']-warm['completed_trips'],
                  wall_seconds=time.perf_counter()-begin,solution_origin='solver' if result is not warm and result['flights']!=warm['flights'] else 'retained_start')
    if report['upper_bound'] is not None:assert report['upper_bound']>=result['completed_trips']-1e-5
    return result,report


if __name__=='__main__':
    payload=json.load(sys.stdin)
    import resource
    cap=int(payload.pop('memory_gib')*1024**3);resource.setrlimit(resource.RLIMIT_AS,(cap,cap))
    import pandas as pd
    from .event_model import EventInstance
    instance=EventInstance(pd.DataFrame(payload.pop('towns')),payload.pop('cfg'))
    result,report=optimize(instance,**payload)
    report['peak_rss_mib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
    print(json.dumps(dict(result=result,report=report),default=lambda v:v.item() if hasattr(v,'item') else str(v)))
