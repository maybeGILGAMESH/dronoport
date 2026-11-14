"""Free aircraft rotations and all timetable passenger paths (no spatial path shortlist).

The heuristic restricts its neighbourhood, not the feasibility definition. Passenger
allocation is a destination-commodity integer flow on the complete chosen timetable.
All times in exported artifacts are absolute minutes, all money integer RUB.
"""
from __future__ import annotations
from collections import defaultdict, Counter
from copy import deepcopy
import hashlib
import json
import math
import time
import numpy as np
import pandas as pd
from scipy.optimize import milp, Bounds, LinearConstraint
from scipy.sparse import coo_matrix
from .ingest import GEOD


class SparseMILP:
    def __init__(self):
        from array import array
        self.c=[]; self.lo=[]; self.hi=[]; self.integer=[]
        self.rr=array('i'); self.cc=array('i'); self.vv=array('d')
        self.lb=[]; self.ub=[]

    def var(self, cost=0, lo=0, hi=np.inf, integer=1):
        k=len(self.c); self.c.append(cost); self.lo.append(lo); self.hi.append(hi); self.integer.append(integer)
        return k

    def row(self, entries, lo=-np.inf, hi=np.inf):
        row=len(self.lb)
        for col,value in entries:
            if value:
                self.rr.append(row); self.cc.append(col); self.vv.append(float(value))
        self.lb.append(lo); self.ub.append(hi)

    def solve(self, seconds, warm_start=None):
        coordinates=coo_matrix((np.asarray(self.vv), (np.asarray(self.rr), np.asarray(self.cc))),
                          shape=(len(self.lb),len(self.c)))
        if warm_start is not None:
            import highspy
            import os
            from types import SimpleNamespace
            solver=highspy.Highs(); solver.setOptionValue('output_flag',bool(os.environ.get('DRONEPORT_SOLVER_LOG'))); solver.setOptionValue('threads',1)
            solver.setOptionValue('time_limit',float(seconds)); solver.setOptionValue('mip_rel_gap',0.)
            solver.addCols(len(self.c),np.array(self.c),np.array(self.lo),np.array(self.hi),0,np.zeros(len(self.c)+1,dtype=np.int32),np.array([],dtype=np.int32),np.array([],dtype=float))
            rows=coordinates.tocsr(); solver.addRows(len(self.lb),np.array(self.lb),np.array(self.ub),rows.nnz,rows.indptr.astype(np.int32,copy=False),rows.indices.astype(np.int32,copy=False),rows.data)
            del rows,coordinates
            solver.changeColsIntegrality(len(self.c),np.arange(len(self.c),dtype=np.int32),np.array(self.integer,dtype=np.uint8))
            if isinstance(warm_start,np.ndarray):
                activity=coo_matrix((np.asarray(self.vv),(np.asarray(self.rr),np.asarray(self.cc))),shape=(len(self.lb),len(self.c)))@warm_start
                if np.any(activity<np.asarray(self.lb)-1e-5) or np.any(activity>np.asarray(self.ub)+1e-5):raise ValueError('Complete warm start violates model rows')
                solver.setSolution(len(warm_start),np.arange(len(warm_start),dtype=np.int32),warm_start)
            else:
                solver.setSolution(len(warm_start),np.array(list(warm_start),dtype=np.int32),np.array(list(warm_start.values()),dtype=float))
            solver.run(); info=solver.getInfo(); solution=solver.getSolution(); status=solver.getModelStatus()
            feasible=info.primal_solution_status==highspy.SolutionStatus.kSolutionStatusFeasible
            return SimpleNamespace(x=np.array(solution.col_value) if feasible else None,fun=info.objective_function_value if feasible else None,
                mip_gap=info.mip_gap,mip_dual_bound=info.mip_dual_bound,status=0 if status==highspy.HighsModelStatus.kOptimal else 1,
                message=solver.modelStatusToString(status))
        import warnings
        matrix=coordinates.tocsc()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            return milp(self.c,integrality=self.integer,bounds=Bounds(self.lo,self.hi),
                constraints=LinearConstraint(matrix,self.lb,self.ub),
                options={'time_limit':float(seconds),'mip_rel_gap':0.,'threads':1})


class EventInstance:
    def __init__(self,towns,cfg):
        self.towns=towns.reset_index(drop=True).copy(); self.cfg=deepcopy(cfg); self.n=len(towns)
        self.ids=self.towns.place_id.tolist(); self.index={v:k for k,v in enumerate(self.ids)}
        self.distance=np.zeros((self.n,self.n))
        for i,a in self.towns.iterrows():
            for j,b in self.towns.iterrows():
                self.distance[i,j]=GEOD.inv(a.lon,a.lat,b.lon,b.lat)[2]/1000
        p=cfg['demand']; pop=self.towns.population.to_numpy(float)
        if cfg.get('population_cap_quantile'):
            pop=np.minimum(pop,np.quantile(pop,cfg['population_cap_quantile']))
        self.demand=np.array([np.floor(p['K']*pop[:,None]**p['alpha']*pop[None,:]**p['beta']/
            (1+self.distance/p['distance_scale_km'])**p['gamma']*p['yearly_growth']**y).astype(int) for y in range(3)])
        for d in self.demand: np.fill_diagonal(d,0)
        self.demand=np.floor(self.demand*cfg.get('demand_factor',1.)).astype(int)
        self.step=cfg['time_step_minutes']; self.start=cfg['day_start_minutes']; self.end=self.start+cfg['day_minutes']
        self.travel=np.ceil((self.distance/cfg['flight_speed_kmh']*60+cfg['landing_minutes'])/self.step).astype(int)*self.step
        self.charge=math.ceil(cfg['charging_minutes']/self.step)*self.step
        self.cache={}

    def empty(self):
        return {'model_version':'time_network_v2','open_years':[0]*self.n,'aircraft':[], 'schedule_seed':0}

    def key(self,plan): return hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()

    def fixed_budget(self,plan,energy=None,relocation_energy=None):
        c=self.cfg; energy=energy or [0]*3; relocation_energy=relocation_energy or [0]*3; rows=[]; carry=0
        for y in range(1,4):
            opened=sum(0<v<=y for v in plan['open_years']); new=sum(v==y for v in plan['open_years'])
            fleet=sum(a['year']<=y for a in plan['aircraft']); bought=sum(a['year']==y for a in plan['aircraft'])
            pieces={'port_capex_rub':new*c['port_capex_rub'],'aircraft_capex_rub':bought*c['aircraft_capex_rub'],
                'port_opex_rub':opened*c['port_opex_rub_per_year'],'aircraft_opex_rub':fleet*c['aircraft_opex_rub_per_year'],
                'energy_rub':int(energy[y-1]),'relocation_energy_rub':int(relocation_energy[y-1])}
            available=carry+c['yearly_tranche_rub']; spent=sum(pieces.values()); carry=available-spent
            rows.append(dict(year=y,new_ports=new,active_ports=opened,new_aircraft=bought,active_aircraft=fleet,
                **pieces,spend_rub=spent,available_rub=available,carry_rub=carry))
        return rows

    def relocations(self,plan,max_range=None,failed=None):
        """Serialize real interyear ferry legs within the 35 non-operating days.

        New aircraft are delivered directly to their commissioned home. An existing
        aircraft cannot change base by editing metadata alone. Aircraft at failed
        bases remain blocked; unavailable future bases leave healthy aircraft at
        their previous actual base.
        """
        import networkx as nx
        limit=self.cfg['range_km'] if max_range is None else max_range
        records=[]; blocked=set(); blocked_year={}; costs=[0]*3; actual={}; actual_year={}
        for year in (1,2,3):
            graph=nx.Graph(); active=[i for i,y in enumerate(plan['open_years']) if 0<y<=year and i!=failed]
            graph.add_nodes_from(active)
            for i in active:
                for j in active:
                    if i<j and self.distance[i,j]<=limit: graph.add_edge(i,j,weight=math.ceil(self.distance[i,j]*self.cfg['energy_kwh_per_km']*self.cfg['electricity_rub_per_kwh']))
            day=0; clock=self.start; movement=Counter()
            for asset in plan['aircraft']:
                if asset['year']>year or asset['id'] in blocked: continue
                homes=asset.get('homes',{}); home=int(homes.get(str(year),asset['home']))
                previous=actual.setdefault(asset['id'],asset['home'])
                if previous==failed:
                    blocked.add(asset['id']); continue
                if asset['year']==year or home==previous: continue
                # A healthy aircraft cannot become trapped merely because a
                # planned future destination fails. It stays at its actual base.
                if home==failed: continue
                if previous not in graph or home not in graph or not nx.has_path(graph,previous,home):
                    if failed is None and max_range is None: return None
                    continue
                path=nx.shortest_path(graph,previous,home,weight='weight')
                for a,b in zip(path,path[1:]):
                    duration=int(self.travel[a,b])+self.charge
                    while True:
                        if clock+duration>self.end: day+=1; clock=self.start
                        arrival=clock+int(self.travel[a,b])
                        if movement[day,a,(clock-self.start)//90]<self.cfg['max_movements_per_window'] and movement[day,b,(arrival-self.start)//90]<self.cfg['max_movements_per_window']: break
                        clock+=self.step
                    if day>=365-self.cfg['operating_days']: return None
                    energy=math.ceil(self.distance[a,b]*self.cfg['energy_kwh_per_km']*self.cfg['electricity_rub_per_kwh'])
                    records.append(dict(year=year,transition_day=day,aircraft_id=asset['id'],origin_id=self.ids[a],destination_id=self.ids[b],
                        departure_min=clock,arrival_min=clock+int(self.travel[a,b]),charge_end_min=clock+duration,
                        distance_km=self.distance[a,b],energy_cost_rub=energy,passengers=0))
                    movement[day,a,(clock-self.start)//90]+=1;movement[day,b,(arrival-self.start)//90]+=1
                    costs[year-1]+=energy; clock+=duration
                actual[asset['id']]=home
            blocked_year[year]=set(blocked)
            actual_year[year]=dict(actual)
        return records,costs,blocked_year,actual_year

    def schedule(self,plan,year,factor=1.,max_range=None,failed=None,blocked=None,actual_homes=None):
        """Construct rotations, including triangular rotations and empty reposition legs.

        Aircraft keep their delivery base between years in this constructive heuristic.
        Different corridors and departure times are searched within each day.
        """
        c=self.cfg; limit=c['range_km'] if max_range is None else max_range
        active=[i for i,v in enumerate(plan['open_years']) if 0<v<=year and i!=failed]
        aircraft=[{**a,'home':int((actual_homes or {}).get(a['id'],a.get('homes',{}).get(str(year),a['home'])))} for a in plan['aircraft'] if a['year']<=year and a['id'] not in (blocked or set())]
        aircraft=[a for a in aircraft if a['home'] in active]
        rng=np.random.default_rng(plan.get('schedule_seed',0)+year*1009)
        remaining=np.floor(self.demand[year-1]*factor).astype(int)
        movement=Counter(); charging=Counter(); flights=[]
        # Per-aircraft state: daily cycles guarantee both identity and aggregate closure.
        states={a['id']:(a['home'],self.start) for a in aircraft}
        rotations=0
        while states and rotations<1000:
            aid=min(states,key=lambda k:states[k][1]); home,ready=states.pop(aid)
            options=[]
            for j in active:
                if j==home or self.distance[home,j]>limit: continue
                options.append([home,j,home])
                others=[k for k in active if k not in (home,j) and self.distance[j,k]<=limit and self.distance[k,home]<=limit]
                for k in others: options.append([home,j,k,home])
            rng.shuffle(options)
            best=None
            for nodes in options:
                local_m=movement.copy(); local_c=charging.copy(); t=ready; legs=[]; score=0.
                for origin,dest in zip(nodes,nodes[1:]):
                    found=False
                    for dep in range(t,self.end,self.step):
                        arr=dep+int(self.travel[origin,dest]); end=arr+self.charge
                        if end>self.end: break
                        mo=(origin,(dep-self.start)//90); md=(dest,(arr-self.start)//90)
                        if local_m[mo]>=c['max_movements_per_window'] or local_m[md]>=c['max_movements_per_window']: continue
                        if any(local_c[dest,q]>=c['chargers_per_port'] for q in range(arr,end,self.step)): continue
                        local_m[mo]+=1; local_m[md]+=1
                        for q in range(arr,end,self.step): local_c[dest,q]+=1
                        legs.append((origin,dest,dep,arr,end)); t=end; found=True
                        score+=min(c['capacity_per_flight'],remaining[origin,dest])
                        break
                    if not found: break
                if len(legs)!=len(nodes)-1 or score<=0: continue
                # Randomness explores routes while preserving physical feasibility.
                priority=score/(t-ready+1)*(1+rng.uniform(-.18,.18))
                if best is None or priority>best[0]: best=(priority,legs,local_m,local_c,t)
            if best is None: continue
            _,legs,movement,charging,t=best
            for origin,dest,dep,arr,end in legs:
                remaining[origin,dest]=max(0,remaining[origin,dest]-c['capacity_per_flight'])
                flights.append(dict(year=year,flight_id=f'y{year}_f{len(flights)}',aircraft_id=aid,
                    origin_id=self.ids[origin],destination_id=self.ids[dest],departure_min=dep,arrival_min=arr,charge_end_min=end,
                    distance_km=self.distance[origin,dest],energy_cost_rub=math.ceil(self.distance[origin,dest]*c['energy_kwh_per_km']*c['electricity_rub_per_kwh']),
                    passengers=0,empty=True))
            states[aid]=(home,t); rotations+=1
        return flights

    def allocate(self,flights,year,factor=1.):
        """Integer multi-commodity flow on every timetable path, with decomposition."""
        if not flights: return [],{'status':'EMPTY','gap':0.,'bound':0.}
        c=self.cfg; model=SparseMILP(); balance=defaultdict(list); caps=defaultdict(list)
        variables={}; supply={}; adjacency=defaultdict(list)
        times={i:{self.start,self.end} for i in range(self.n)}
        for k,f in enumerate(flights):
            a=self.index[f['origin_id']]; b=self.index[f['destination_id']]
            times[a].add(f['departure_min'])
            times[b].add(min(self.end,f['arrival_min']+c['minimum_transfer_minutes']))
        for dest in range(self.n):
            for origin in range(self.n):
                q=int(math.floor(self.demand[year-1,origin,dest]*factor))
                if origin==dest or q<=0: continue
                v=model.var(cost=-1,hi=q); supply[dest,origin]=v
                balance[dest,origin,self.start].append((v,1)); balance[dest,dest,self.end].append((v,-1))
            for node,ts in times.items():
                st=sorted(ts)
                for t,u in zip(st,st[1:]):
                    v=model.var(); variables[v]=(dest,(node,t),(node,u),None)
                    balance[dest,node,t].append((v,-1)); balance[dest,node,u].append((v,1))
                    adjacency[dest,node,t].append(v)
            for k,f in enumerate(flights):
                a=self.index[f['origin_id']]; b=self.index[f['destination_id']]
                if a==dest: continue
                t=f['departure_min']; u=min(self.end,f['arrival_min']+c['minimum_transfer_minutes'])
                v=model.var(hi=c['capacity_per_flight']); variables[v]=(dest,(a,t),(b,u),k)
                balance[dest,a,t].append((v,-1)); balance[dest,b,u].append((v,1)); caps[k].append((v,1))
                adjacency[dest,a,t].append(v)
        for entries in balance.values(): model.row(entries,0,0)
        for entries in caps.values(): model.row(entries,hi=c['capacity_per_flight'])
        solved=model.solve(c.get('allocation_seconds',15))
        if solved.x is None: return [],{'status':'NO_INCUMBENT','gap':None,'bound':None}
        values=np.rint(solved.x).astype(int); trips=[]
        for (dest,origin),var in supply.items():
            for _ in range(values[var]):
                state=(origin,self.start); legs=[]
                while state!=(dest,self.end):
                    choices=[v for v in adjacency[dest,*state] if values[v]>0]
                    if not choices: raise RuntimeError('Passenger flow decomposition failed')
                    v=choices[0]; values[v]-=1
                    _,_,state,k=variables[v]
                    if k is not None: legs.append(k)
                for k in legs: flights[k]['passengers']+=1; flights[k]['empty']=False
                trips.append(dict(year=year,trip_id=f'y{year}_p{len(trips)}',origin_id=self.ids[origin],destination_id=self.ids[dest],
                    flight_ids=json.dumps([flights[k]['flight_id'] for k in legs]),arrival_min=flights[legs[-1]]['arrival_min'],
                    transfers=len(legs)-1,annual_weight=c['operating_days']))
        return trips,{'status':str(solved.message),'gap':float(solved.mip_gap),'bound':-float(solved.mip_dual_bound)}

    def evaluate(self,plan,factor=1.,max_range=None,failed=None):
        key=(self.key(plan),factor,max_range,failed)
        if key in self.cache: return self.cache[key]
        from .regional_policy import ports_ok,service_ok
        if not ports_ok(self,plan):return None
        fixed=self.fixed_budget(plan)
        if any(r['carry_rub']<0 for r in fixed): return None
        if any(not 0<plan['open_years'][a['home']]<=a['year'] for a in plan['aircraft']): return None
        if any(not 0<plan['open_years'][int(a.get('homes',{}).get(str(y),a['home']))]<=y
               for a in plan['aircraft'] for y in range(a['year'],4)): return None
        relocation=self.relocations(plan,max_range,failed)
        if relocation is None: return None
        relocation_rows,relocation_energy,blocked_year,actual_year=relocation
        flights=[]; trips=[]; statuses=[]; energy=[]
        for year in (1,2,3):
            fs=self.schedule(plan,year,factor,max_range,failed,blocked_year[year],actual_year[year])
            ts,status=self.allocate(fs,year,factor)
            flights+=fs; trips+=ts; statuses.append(status)
            energy.append(sum(f['energy_cost_rub'] for f in fs)*self.cfg['operating_days'])
        budget=self.fixed_budget(plan,energy,relocation_energy)
        if any(r['carry_rub']<0 for r in budget): return None
        annual=[sum(t['year']==y for t in trips)*self.cfg['operating_days'] for y in (1,2,3)]
        result=dict(plan=deepcopy(plan),flights=flights,itineraries=trips,budget=budget,annual_completed=annual,
            completed_trips=sum(annual),allocation_status=statuses,relocations=relocation_rows,
            blocked_aircraft={str(y):sorted(v) for y,v in blocked_year.items()},actual_homes={str(y):v for y,v in actual_year.items()},scenario=dict(factor=factor,max_range=max_range,failed=failed))
        if not service_ok(self,flights,result['scenario']):return None
        self.cache[key]=result
        return result


def greedy(instance, sequential=False):
    """Evaluate actual feasible schedules for candidate asset additions."""
    started=time.perf_counter(); plan=instance.empty(); history=[]
    for year in (1,2,3):
        for _ in range(12):
            current=instance.evaluate(plan); candidates=[]
            ranking=[]
            for i in range(instance.n):
                for j in range(i+1,instance.n):
                    if instance.distance[i,j]<=instance.cfg['range_km']:
                        ranking.append((int(instance.demand[year-1,i,j]+instance.demand[year-1,j,i]),i,j))
            for _,i,j in sorted(ranking,reverse=True)[:12]:
                candidate=deepcopy(plan)
                for k in (i,j):
                    if not candidate['open_years'][k]: candidate['open_years'][k]=year
                candidate['aircraft'].append(dict(id=f'a{len(candidate["aircraft"])}',year=year,home=i))
                ev=instance.evaluate(candidate)
                if ev is None: continue
                metric=(sum(ev['annual_completed'][:year])-sum(current['annual_completed'][:year])) if sequential else ev['completed_trips']-current['completed_trips']
                cost=sum(r['spend_rub'] for r in ev['budget'])-sum(r['spend_rub'] for r in current['budget'])
                if metric>0: candidates.append((metric/max(1,cost),ev['completed_trips'],candidate,ev))
            if not candidates: break
            _,_,plan,ev=max(candidates,key=lambda c:(c[0],c[1]))
            history.append(dict(year=year,completed_trips=ev['completed_trips'],elapsed=time.perf_counter()-started))
    return plan,history


def recover(instance,plan,factor=1.,max_range=None,failed=None,mode='best'):
    """Best of re-optimized rotations and a physically closed cancellation plan.

    A failed new construction must not turn a surviving baseline fleet into a
    zero-service scenario. Cancel entire aircraft-day rotations, reallocate all
    timetable paths, and compare actual feasible outcomes.
    """
    key=('recourse',instance.key(plan),factor,max_range,failed,mode)
    if key in instance.cache:return instance.cache[key]
    proposed=instance.evaluate(plan,factor,max_range,failed) if mode=='best' else None
    baseline=instance.evaluate(plan)
    if baseline is None:return None
    relocation=instance.relocations(plan,max_range,failed)
    if relocation is None:return proposed
    rr,re,blocked,actual=relocation; limit=max_range or instance.cfg['range_km']; failed_id=instance.ids[failed] if failed is not None else None
    remove={(f['year'],f['aircraft_id']) for f in baseline['flights'] if failed_id in (f['origin_id'],f['destination_id'])
            or f['distance_km']>limit or f['aircraft_id'] in blocked[f['year']]}
    groups=defaultdict(list)
    for f in baseline['flights']:groups[f['year'],f['aircraft_id']].append(f)
    for (year,aid),fs in groups.items():
        first=min(fs,key=lambda f:f['departure_min'])
        if instance.index[first['origin_id']]!=actual[year][aid]:remove.add((year,aid))
    flights=[deepcopy(f) for f in baseline['flights'] if (f['year'],f['aircraft_id']) not in remove]
    while True:
        energy=[sum(f['energy_cost_rub'] for f in flights if f['year']==y)*instance.cfg['operating_days'] for y in (1,2,3)]
        budget=instance.fixed_budget(plan,energy,re)
        deficits=[r['year'] for r in budget if r['carry_rub']<0]
        if not deficits:break
        costs=Counter()
        for f in flights:
            if f['year']<=min(deficits):costs[f['year'],f['aircraft_id']]+=f['energy_cost_rub']
        if not costs:return proposed
        dropped=max(costs,key=costs.get);flights=[f for f in flights if (f['year'],f['aircraft_id'])!=dropped]
    # Retain a known feasible passenger assignment even if a later allocation
    # solver reaches its limit without an incumbent.
    retained_flights=deepcopy(flights); by_id={f['flight_id']:f for f in retained_flights}
    for f in retained_flights:f['passengers']=0;f['empty']=True
    retained_trips=[];od=Counter()
    for trip in baseline['itineraries']:
        legs=json.loads(trip['flight_ids']);a=instance.index[trip['origin_id']];b=instance.index[trip['destination_id']];y=trip['year']
        if any(fid not in by_id for fid in legs) or od[y,a,b]>=math.floor(instance.demand[y-1,a,b]*factor):continue
        retained_trips.append(deepcopy(trip));od[y,a,b]+=1
        for fid in legs:by_id[fid]['passengers']+=1;by_id[fid]['empty']=False
    retained_annual=[sum(t['year']==y for t in retained_trips)*instance.cfg['operating_days'] for y in (1,2,3)]
    retained=dict(plan=deepcopy(plan),flights=retained_flights,itineraries=retained_trips,budget=budget,annual_completed=retained_annual,
        completed_trips=sum(retained_annual),allocation_status=[],relocations=rr,blocked_aircraft={str(y):sorted(v) for y,v in blocked.items()},actual_homes={str(y):v for y,v in actual.items()},
        scenario=dict(factor=factor,max_range=max_range,failed=failed),recovery_method='cancel_affected_rotations_retain_itineraries')
    if mode=='retain':instance.cache[key]=retained;return retained
    all_flights=[];trips=[];statuses=[]
    for year in (1,2,3):
        fs=[f for f in flights if f['year']==year]
        for f in fs:f['passengers']=0;f['empty']=True
        ts,status=instance.allocate(fs,year,factor);all_flights+=fs;trips+=ts;statuses.append(status)
    annual=[sum(t['year']==y for t in trips)*instance.cfg['operating_days'] for y in (1,2,3)]
    cancellation=dict(plan=deepcopy(plan),flights=all_flights,itineraries=trips,budget=budget,annual_completed=annual,
        completed_trips=sum(annual),allocation_status=statuses,relocations=rr,blocked_aircraft={str(y):sorted(v) for y,v in blocked.items()},actual_homes={str(y):v for y,v in actual.items()},
        scenario=dict(factor=factor,max_range=max_range,failed=failed),recovery_method='cancel_complete_rotations_and_reallocate')
    result=max([retained,cancellation]+([proposed] if proposed else []),key=lambda r:(r['completed_trips'],-sum(b['spend_rub'] for b in r['budget'])))
    instance.cache[key]=result
    return result


def anneal(instance,initial,seed,seconds=None,iterations=None,score=None):
    rng=np.random.default_rng(seed); current=deepcopy(initial); best=deepcopy(initial)
    objective=score or (lambda p: instance.evaluate(p)['completed_trips'])
    value=objective(current); best_value=value; history=[]; start=time.perf_counter()
    seconds=seconds or instance.cfg.get('annealing_seconds',600)
    iterations=instance.cfg.get('annealing_iterations',200) if iterations is None else iterations
    timed=not iterations
    iterations=iterations or 10**9
    for k in range(iterations):
        if time.perf_counter()-start>seconds: break
        proposal=deepcopy(current); action=int(rng.integers(6))
        if action==0:
            proposal['schedule_seed']=int(rng.integers(1,2**30))
        elif action==1:
            node=int(rng.integers(instance.n)); proposal['open_years'][node]=int(rng.integers(1,4))
        elif action==2 and proposal['aircraft']:
            a=proposal['aircraft'][int(rng.integers(len(proposal['aircraft'])))]; a['home']=int(rng.integers(instance.n)); a['year']=int(rng.integers(1,4))
            a.pop('homes',None)
            proposal['open_years'][a['home']]=min(proposal['open_years'][a['home']] or a['year'],a['year'])
        elif action==3 and proposal['aircraft']:
            proposal['aircraft'].pop(int(rng.integers(len(proposal['aircraft']))))
        elif action==4:
            home=int(rng.integers(instance.n)); y=int(rng.integers(1,4))
            proposal['open_years'][home]=min(proposal['open_years'][home] or y,y)
            proposal['aircraft'].append(dict(id=f's{seed}_{k}',home=home,year=y))
        elif proposal['aircraft']:
            a=proposal['aircraft'][int(rng.integers(len(proposal['aircraft'])))]; y=int(rng.integers(2,4)); home=int(rng.integers(instance.n))
            if a['year']<y:
                homes=a.setdefault('homes',{})
                for future in range(y,4): homes[str(future)]=home
                proposal['open_years'][home]=min(proposal['open_years'][home] or y,y)
        # Explicit repair: opening date must precede delivery; delete latest purchases
        # until fixed costs fit. Full energy feasibility is checked afterwards.
        for a in proposal['aircraft']:
            proposal['open_years'][a['home']]=min(proposal['open_years'][a['home']] or a['year'],a['year'])
        while proposal['aircraft'] and any(r['carry_rub']<0 for r in instance.fixed_budget(proposal)):
            proposal['aircraft'].remove(max(proposal['aircraft'],key=lambda a:a['year']))
        ev=instance.evaluate(proposal); accepted=False; candidate=None
        if ev is not None:
            candidate=objective(proposal); progress=min(1.,(time.perf_counter()-start)/seconds) if timed else k/iterations
            temperature=max(1.,.05*max(1,best_value)*(1-progress))
            accepted=candidate>=value or rng.random()<math.exp(max(-700,(candidate-value)/temperature))
            if accepted: current=proposal; value=candidate
            if candidate>best_value: best=proposal; best_value=candidate
        history.append(dict(seed=seed,iteration=k,action=action,feasible=ev is not None,accepted=accepted,
            candidate=candidate,best=best_value,elapsed=time.perf_counter()-start))
        if len(instance.cache)>64:
            keep={instance.key(initial),instance.key(current),instance.key(best)}
            instance.cache={key:result for key,result in instance.cache.items() if key[0] in keep}
    return best,history
