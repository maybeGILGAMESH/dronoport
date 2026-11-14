"""Time-expanded mixed integer model; all directed flights and timetable paths.

Home commodities enforce identity-level daily cycles. Bases may change between
years through costed ferry flows. The reported bound explicitly has that scope.
The matrix size guard returns a resource status, never a fabricated solution.
"""
import math
import time
from collections import defaultdict
import numpy as np
from .event_model import SparseMILP


def solve(instance,seconds=None,objective_years=None,fixed=None,warm_result=None):
    begin=time.perf_counter(); c=instance.cfg; n=instance.n; step=instance.step
    T=c['day_minutes']//step; charge=instance.charge//step
    import networkx as nx
    spatial=nx.DiGraph();spatial.add_nodes_from(range(n))
    for a in range(n):
        for b in range(n):
            if a!=b and instance.distance[a,b]<=c['range_km']:
                spatial.add_edge(a,b,weight=int(instance.travel[a,b])//step+charge)
    earliest=dict(nx.all_pairs_dijkstra_path_length(spatial,weight='weight'))
    arcs=[]
    for a in range(n):
        for b in range(n):
            if a==b or instance.distance[a,b]>c['range_km']: continue
            duration=int(instance.travel[a,b])//step
            for t in range(T-duration-charge+1):
                arcs.append((a,b,t,t+duration,t+duration+charge))
    estimate=3*(len(arcs)*n*12+n*n*T*4)
    objective_years=objective_years or [1,2,3]
    last_active=max(objective_years) if len(objective_years)==1 else 3
    policy=c.get('regional_coverage',{})
    if policy:last_active=3
    report=dict(model_version='time_network_v2',scope='Configured time grid; free rotations and interyear relocation; full recharge after every flight',objective_years=objective_years,
        nodes=n,time_limit_seconds=seconds or c['mip_seconds'],estimated_nonzeros=estimate)
    if estimate>c['matrix_nonzero_limit']:
        return None,dict(report,status='RESOURCE_GUARD',reason='Estimated sparse matrix exceeds configured nonzero limit',wall_seconds=time.perf_counter()-begin,
                         incumbent=None,upper_bound=None,gap=None)
    m=SparseMILP(); openvars={}; buy={}; stock={}; reloc={}; fleet={}; fv={}; pv={}; pw={}; qvars={}; xupper=max(1,3*c['yearly_tranche_rub']//c['aircraft_capex_rub'])
    finance=[[] for _ in range(3)]; flight_totals=defaultdict(list)
    for y in range(3):
        for i in range(n):
            x=m.var(hi=1); openvars[y,i]=x
            b=m.var(hi=xupper); buy[y,i]=b
            stock[y,i]=m.var(hi=xupper)
            if y>=last_active:
                # With no future reward, zero future investment/operations and
                # unchanged bases are always an equally good feasible extension.
                m.row([(x,1),(openvars[y-1,i],-1)],0,0);m.row([(b,1)],0,0)
            if fixed is not None and y+1<min(objective_years):
                p=fixed['plan']; opened=int(0<p['open_years'][i]<=y+1)
                purchases=sum(a['year']==y+1 and a['home']==i for a in p['aircraft'])
                positioned=sum(a['year']<=y+1 and int(a.get('homes',{}).get(str(y+1),a['home']))==i for a in p['aircraft'])
                m.row([(x,1)],opened,opened); m.row([(b,1)],purchases,purchases); m.row([(stock[y,i],1)],positioned,positioned)
            if y: m.row([(openvars[y-1,i],1),(x,-1)],hi=0)
            for horizon in range(y,3):
                # Port opening represented by x_y-x_(y-1); OPEX for each active year.
                finance[horizon].append((x,c['port_capex_rub']+c['port_opex_rub_per_year']))
                if y: finance[horizon].append((openvars[y-1,i],-c['port_capex_rub']))
                finance[horizon].append((b,c['aircraft_capex_rub']+(horizon-y+1)*c['aircraft_opex_rub_per_year']))
            m.row([(stock[y,i],1),(x,-xupper)],hi=0)
    for y in range(3):
        balance=defaultdict(list)
        if y and y<last_active:
            for a in range(n):
                for b in range(n):
                    if a==b or instance.distance[a,b]>c['range_km']: continue
                    energy=math.ceil(instance.distance[a,b]*c['energy_kwh_per_km']*c['electricity_rub_per_kwh'])
                    v=m.var(cost=energy*1e-10,hi=xupper); reloc[y,a,b]=v
                    m.row([(v,1),(openvars[y,a],-xupper)],hi=0); m.row([(v,1),(openvars[y,b],-xupper)],hi=0)
                    balance[a].append((v,-1)); balance[b].append((v,1))
                    for h in range(y,3): finance[h].append((v,energy))
        for i in range(n):
            entries=balance[i]+[(buy[y,i],1),(stock[y,i],-1)]
            if y: entries.append((stock[y-1,i],1))
            m.row(entries,0,0)
    for y in range(3):
        if y>=last_active:continue
        movements=defaultdict(list); chargers=defaultdict(list); capacities=defaultdict(list)
        fixed_counts=defaultdict(int)
        if fixed is not None and y+1<min(objective_years):
            assets={a['id']:a for a in fixed['plan']['aircraft']}
            lookup={(a,b,t,arr,end):k for k,(a,b,t,arr,end) in enumerate(arcs)}
            for f in fixed['flights']:
                if f['year']!=y+1: continue
                asset=assets[f['aircraft_id']]; home=int(asset.get('homes',{}).get(str(y+1),asset['home']))
                tag=(instance.index[f['origin_id']],instance.index[f['destination_id']],(f['departure_min']-instance.start)//step,(f['arrival_min']-instance.start)//step,(f['charge_end_min']-instance.start)//step)
                fixed_counts[home,lookup[tag]]+=1
        for home in range(n):
            balance=defaultdict(list)
            for i in range(n):
                for t in range(T):
                    v=m.var(hi=xupper); fleet[y,home,i,t]=v
                    balance[i,t].append((v,-1)); balance[i,t+1].append((v,1))
            for k,(a,b,t,arr,end) in enumerate(arcs):
                # Such arcs are forced to zero by flow conservation and the
                # daily home cycle. Remove them before allocating sparse rows.
                if earliest[home].get(a,float('inf'))>t or end+earliest[b].get(home,float('inf'))>T:continue
                v=m.var(hi=xupper); fv[y,home,k]=v
                if fixed is not None and y+1<min(objective_years): m.row([(v,1)],fixed_counts[home,k],fixed_counts[home,k])
                balance[a,t].append((v,-1)); balance[b,end].append((v,1)); capacities[k].append((v,-10))
                m.row([(v,1),(openvars[y,a],-xupper)],hi=0); m.row([(v,1),(openvars[y,b],-xupper)],hi=0)
                movements[a,t*step//90].append((v,1)); movements[b,arr*step//90].append((v,1))
                for s in range(arr,end): chargers[b,s].append((v,1))
                energy=math.ceil(instance.distance[a,b]*c['energy_kwh_per_km']*c['electricity_rub_per_kwh'])*c['operating_days']
                for h in range(y,3): finance[h].append((v,energy))
            balance[home,0].append((stock[y,home],1)); balance[home,T].append((stock[y,home],-1))
            for entries in balance.values(): m.row(entries,0,0)
        for dest in range(n):
            balance=defaultdict(list)
            for origin in range(n):
                if origin==dest: continue
                q=m.var(cost=-c['operating_days'] if y+1 in objective_years else 0,hi=int(instance.demand[y,origin,dest])); qvars[y,origin,dest]=q
                balance[origin,0].append((q,1)); balance[dest,T].append((q,-1))
            for i in range(n):
                for t in range(T):
                    v=m.var()
                    if t==0:pw[y,dest,i]=v
                    balance[i,t].append((v,-1)); balance[i,t+1].append((v,1))
            for k,(a,b,t,arr,end) in enumerate(arcs):
                if a==dest: continue
                arrival=min(T,arr+math.ceil(c['minimum_transfer_minutes']/step))
                v=m.var(hi=10*xupper); pv[y,dest,k]=v
                balance[a,t].append((v,-1)); balance[b,arrival].append((v,1)); capacities[k].append((v,1))
            for entries in balance.values(): m.row(entries,0,0)
        for entries in capacities.values(): m.row(entries,hi=0)
        for entries in movements.values(): m.row(entries,hi=c['max_movements_per_window'])
        for entries in chargers.values(): m.row(entries,hi=c['chargers_per_port'])
    from .regional_policy import groups
    for nodes in groups(instance).values():
        year=policy.get('deadline_year',3)-1
        m.row([(openvars[year,i],1) for i in nodes],lo=1)
        if policy.get('min_flights',0):
            m.row([(v,1) for (y,h,k),v in fv.items() if y==year and (arcs[k][0] in nodes or arcs[k][1] in nodes)],lo=policy['min_flights'])
    for y in range(3): m.row(finance[y],hi=(y+1)*c['yearly_tranche_rub'])
    from .event_bound import upper_bound
    aggregate=upper_bound(instance,objective_years=objective_years)
    report['aggregate_relaxation']=aggregate
    if aggregate['upper_bound'] is not None:
        m.row([(v,c['operating_days']) for (y,a,b),v in qvars.items() if y+1 in objective_years],hi=aggregate['upper_bound']+1e-5)
    report.update(variables=len(m.c),constraints=len(m.lb),nonzeros=len(m.vv),build_seconds=time.perf_counter()-begin)
    hints=None
    if warm_result is not None:
        hints=np.zeros(len(m.c))
        p=warm_result['plan']; assets={a['id']:a for a in p['aircraft']}
        for (y,i),v in openvars.items():hints[v]=int(0<p['open_years'][i]<=min(y+1,last_active))
        for (y,i),v in buy.items():hints[v]=sum(a['year']==y+1 and a['home']==i for a in p['aircraft']) if y<last_active else 0
        for (y,i),v in stock.items():
            yy=min(y+1,last_active);hints[v]=sum(a['year']<=yy and int(a.get('homes',{}).get(str(yy),a['home']))==i for a in p['aircraft'])
        for r in warm_result.get('relocations',[]):
            key=(r['year']-1,instance.index[r['origin_id']],instance.index[r['destination_id']])
            if key in reloc:hints[reloc[key]]+=1
        lookup={(a,b,t,arr,end):k for k,(a,b,t,arr,end) in enumerate(arcs)}
        flight_keys={};grouped=defaultdict(list)
        for f in warm_result['flights']:
            y=f['year']-1
            if y>=last_active:continue
            tag=(instance.index[f['origin_id']],instance.index[f['destination_id']],(f['departure_min']-instance.start)//step,(f['arrival_min']-instance.start)//step,(f['charge_end_min']-instance.start)//step)
            flight_keys[f['flight_id']]=lookup[tag];grouped[y,f['aircraft_id']].append(f)
        for y in range(last_active):
            for asset in p['aircraft']:
                if asset['year']>y+1:continue
                home=int(asset.get('homes',{}).get(str(y+1),asset['home']));location=home;ready=0
                for f in sorted(grouped[y,asset['id']],key=lambda f:f['departure_min']):
                    k=flight_keys[f['flight_id']];a,b,t,arr,end=arcs[k]
                    for waiting in range(ready,t):hints[fleet[y,home,location,waiting]]+=1
                    hints[fv[y,home,k]]+=1;location=b;ready=end
                for waiting in range(ready,T):hints[fleet[y,home,location,waiting]]+=1
        import json
        for trip in warm_result['itineraries']:
            y=trip['year']-1
            if y>=last_active:continue
            origin=instance.index[trip['origin_id']];dest=instance.index[trip['destination_id']];location=origin;ready=0
            hints[qvars[y,origin,dest]]+=1
            for fid in json.loads(trip['flight_ids']):
                k=flight_keys[fid];a,b,t,arr,end=arcs[k]
                hints[pw[y,dest,location]+ready:pw[y,dest,location]+t]+=1
                hints[pv[y,dest,k]]+=1;location=b;ready=min(T,arr+math.ceil(c['minimum_transfer_minutes']/step))
            hints[pw[y,dest,location]+ready:pw[y,dest,location]+T]+=1
        report['warm_start']='Complete validated aircraft, passenger, investment and relocation flow'
    # Sparse rows already own numerical coefficients. These construction-only
    # dictionaries otherwise coexist with the solver's copy of the whole model.
    del pv,finance,movements,chargers,capacities,balance
    import gc
    gc.collect()
    try:
        solved=m.solve(seconds or c['mip_seconds'],hints)
    except MemoryError:
        from types import SimpleNamespace
        solved=SimpleNamespace(x=None,message='Memory limit reached',mip_dual_bound=None,mip_gap=None)
    # HiGHS can return a default zero bound when allocation failed before a
    # valid dual bound existed. Never turn that sentinel into an upper bound.
    raw_dual=getattr(solved,'mip_dual_bound',None)
    valid_stop=getattr(solved,'status',None)==0 or 'Time limit reached' in str(solved.message)
    if not valid_stop or raw_dual is None or not np.isfinite(raw_dual):raw_dual=None
    raw_gap=getattr(solved,'mip_gap',None)
    if raw_gap is None or not np.isfinite(raw_gap):raw_gap=None
    report.update(status=str(solved.message),wall_seconds=time.perf_counter()-begin,
        incumbent=float(sum(round(solved.x[v])*c['operating_days'] for (y,a,b),v in qvars.items() if y+1 in objective_years)) if solved.x is not None else None,
        upper_bound=float(math.floor((-float(raw_dual)+3*c['yearly_tranche_rub']*1e-10+1e-5)/c['operating_days'])*c['operating_days']) if raw_dual is not None else None,
        gap=float(raw_gap) if raw_gap is not None else None)
    lower=report['incumbent'] or 0
    if warm_result is not None:lower=max(lower,sum(warm_result['annual_completed'][y-1] for y in objective_years))
    if report['upper_bound'] is not None and report['upper_bound']<lower-1e-5:report['upper_bound']=None
    if aggregate['upper_bound'] is not None:
        report['upper_bound']=min(report['upper_bound'] if report['upper_bound'] is not None else float('inf'),math.floor((aggregate['upper_bound']+1e-5)/c['operating_days'])*c['operating_days'])
        if report['incumbent']:
            report['solver_gap']=report['gap']; report['gap']=max(0.,(report['upper_bound']-report['incumbent'])/report['incumbent'])
    if solved.x is None:
        if warm_result is not None:
            from .event_validation import validate
            cutoff=min(objective_years)
            past_ok=fixed is None or [f for f in warm_result['flights'] if f['year']<cutoff]==[f for f in fixed['flights'] if f['year']<cutoff]
            if past_ok and validate(instance.towns,warm_result,c)['valid']:
                from copy import deepcopy
                report['solver_incumbent']=None
                report['incumbent']=sum(warm_result['annual_completed'][y-1] for y in objective_years)
                report['solution_origin']='Validated provided timetable retained; solver returned no incumbent'
                report['materialized_completed']=warm_result['completed_trips']
                report['gap']=(report['upper_bound']-report['incumbent'])/report['incumbent'] if report['upper_bound'] is not None and report['incumbent'] else None
                return deepcopy(warm_result),report
        return None,report
    values=np.rint(solved.x).astype(int); plan=instance.empty(); plan['source']='time_network_mip'
    for i in range(n): plan['open_years'][i]=next((y+1 for y in range(3) if values[openvars[y,i]]),0)
    import networkx as nx
    for y in range(3):
        for i in range(n):
            for _ in range(values[buy[y,i]]): plan['aircraft'].append(dict(id=f'm{len(plan["aircraft"])}',year=y+1,home=i,homes={}))
        positions=defaultdict(list)
        for a in plan['aircraft']: positions[int(a['homes'].get(str(y),a['home']))].append(a)
        deficit={i:int(values[stock[y,i]])-len(positions[i]) for i in range(n)}
        graph=nx.DiGraph()
        for (yy,a,b),v in reloc.items():
            if yy==y and values[v]>0: graph.add_edge(a,b,remaining=int(values[v]))
        for i in range(n):
            while deficit[i]<0:
                targets=[j for j in range(n) if deficit[j]>0 and i in graph and j in graph and nx.has_path(graph,i,j)]
                if not targets: raise RuntimeError('Relocation decomposition failed')
                target=targets[0]; path=nx.shortest_path(graph,i,target); asset=positions[i].pop(); positions[target].append(asset)
                for a,b in zip(path,path[1:]):
                    graph[a][b]['remaining']-=1
                    if graph[a][b]['remaining']==0: graph.remove_edge(a,b)
                deficit[i]+=1; deficit[target]-=1
        for i,assets in positions.items():
            for a in assets:
                a['homes'][str(y+1)]=i
                if a['year']==y+1: a['home']=i
    flights=[]; trips=[]; statuses=[]; energies=[]
    for y in range(3):
        if y>=last_active:
            energies.append(0);statuses.append(dict(status='FUTURE_IDLE_EXTENSION'));continue
        fs=[]
        for home in range(n):
            adjacency=defaultdict(list)
            for i in range(n):
                for t in range(T): adjacency[i,t].append((fleet[y,home,i,t],i,t+1,None))
            for k,(a,b,t,arr,end) in enumerate(arcs):
                if (y,home,k) in fv:adjacency[a,t].append((fv[y,home,k],b,end,k))
            for aircraft in [a for a in plan['aircraft'] if a['year']<=y+1 and a['homes'][str(y+1)]==home]:
                state=(home,0)
                while state!=(home,T):
                    choices=[e for e in adjacency[state] if values[e[0]]>0]
                    if not choices: raise RuntimeError('Aircraft decomposition failed')
                    v,b,end,k=choices[0]; values[v]-=1; state=(b,end)
                    if k is None: continue
                    a,b,t,arr,end=arcs[k]; d=instance.distance[a,b]
                    fs.append(dict(year=y+1,flight_id=f'y{y+1}_m{len(fs)}',aircraft_id=aircraft['id'],origin_id=instance.ids[a],destination_id=instance.ids[b],
                        departure_min=instance.start+t*step,arrival_min=instance.start+arr*step,charge_end_min=instance.start+end*step,
                        distance_km=d,energy_cost_rub=math.ceil(d*c['energy_kwh_per_km']*c['electricity_rub_per_kwh']),passengers=0,empty=True))
        ts,status=instance.allocate(fs,y+1); flights+=fs; trips+=ts; statuses.append(status)
        energies.append(sum(f['energy_cost_rub'] for f in fs)*c['operating_days'])
    annual=[sum(t['year']==y for t in trips)*c['operating_days'] for y in (1,2,3)]
    relocation=instance.relocations(plan)
    if relocation is None:
        report['materialization_error']='Interyear relocation exceeds physical window'; return None,report
    rr,re,blocked,actual=relocation
    result=dict(plan=plan,flights=flights,itineraries=trips,budget=instance.fixed_budget(plan,energies,re),annual_completed=annual,
        completed_trips=sum(annual),allocation_status=statuses,scenario={},relocations=rr,blocked_aircraft={str(y):sorted(v) for y,v in blocked.items()},actual_homes={str(y):v for y,v in actual.items()})
    report['solver_incumbent']=report['incumbent']
    materialized=sum(result['annual_completed'][y-1] for y in objective_years)
    if warm_result is not None and sum(warm_result['annual_completed'][y-1] for y in objective_years)>materialized:
        from .event_validation import validate
        cutoff=min(objective_years)
        past_ok=fixed is None or [f for f in warm_result['flights'] if f['year']<cutoff]==[f for f in fixed['flights'] if f['year']<cutoff]
        if past_ok and validate(instance.towns,warm_result,c)['valid']:
            from copy import deepcopy
            result=deepcopy(warm_result)
            report['solution_origin']='Validated provided timetable dominates returned solver incumbent'
    report['incumbent']=sum(result['annual_completed'][y-1] for y in objective_years)
    if report['upper_bound'] is not None:
        assert report['upper_bound']>=report['incumbent']-1e-5,'Bound contradicts a validated feasible timetable'
        report['gap']=(report['upper_bound']-report['incumbent'])/report['incumbent'] if report['incumbent'] else None
    report['materialized_completed']=result['completed_trips']
    return result,report
