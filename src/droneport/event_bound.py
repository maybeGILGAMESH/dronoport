"""Continuous aggregate relaxation: a certified upper bound, never a schedule."""
import math
import time
from collections import defaultdict
from .event_model import SparseMILP


def upper_bound(instance,seconds=120,objective_years=None):
    start=time.perf_counter(); c=instance.cfg; n=instance.n; m=SparseMILP(); x={}; fleet={}; finance=[[] for _ in range(3)]; objective_years=objective_years or [1,2,3]
    pairs=[(a,b) for a in range(n) for b in range(n) if a!=b and instance.distance[a,b]<=c['range_km']]
    for y in range(3):
        fleet[y]=m.var(integer=0)
        if y: m.row([(fleet[y-1],1),(fleet[y],-1)],hi=0)
        for h in range(y,3):
            finance[h].append((fleet[y],c['aircraft_capex_rub']+c['aircraft_opex_rub_per_year']))
            if y: finance[h].append((fleet[y-1],-c['aircraft_capex_rub']))
        for i in range(n):
            x[y,i]=m.var(hi=1,integer=0)
            if y: m.row([(x[y-1,i],1),(x[y,i],-1)],hi=0)
            for h in range(y,3):
                finance[h].append((x[y,i],c['port_capex_rub']+c['port_opex_rub_per_year']))
                if y: finance[h].append((x[y-1,i],-c['port_capex_rub']))
    for y in range(3):
        movement=defaultdict(list); cycles=defaultdict(list); capacity={}; hours=[]
        for a,b in pairs:
            v=m.var(integer=0); capacity[a,b]=[(v,-10)]
            movement[a].append((v,1)); movement[b].append((v,1)); cycles[a].append((v,-1));cycles[b].append((v,1))
            hours.append((v,float(instance.travel[a,b]+instance.charge)))
            energy=math.ceil(instance.distance[a,b]*c['energy_kwh_per_km']*c['electricity_rub_per_kwh'])*c['operating_days']
            for h in range(y,3): finance[h].append((v,energy))
        for i in range(n):
            m.row(movement[i]+[(x[y,i],-c['max_movements_per_window']*(c['day_minutes']//c['movement_window_minutes']))],hi=0)
            m.row(cycles[i],0,0)
        m.row(hours+[(fleet[y],-c['day_minutes'])],hi=0)
        for d in range(n):
            conservation=defaultdict(list)
            for o in range(n):
                if o==d: continue
                v=m.var(cost=-c['operating_days'] if y+1 in objective_years else 0,hi=int(instance.demand[y,o,d]),integer=0)
                conservation[o].append((v,1)); conservation[d].append((v,-1))
            for a,b in pairs:
                if a==d: continue
                v=m.var(integer=0);conservation[a].append((v,-1));conservation[b].append((v,1));capacity[a,b].append((v,1))
            for entries in conservation.values():m.row(entries,0,0)
        for entries in capacity.values():m.row(entries,hi=0)
    for y in range(3):m.row(finance[y],hi=(y+1)*c['yearly_tranche_rub'])
    solved=m.solve(seconds)
    # Only a solved LP gives this upper bound; a primal LP time-limit incumbent
    # is NOT an upper bound on the integer maximization problem.
    bound=-float(solved.fun) if solved.status==0 else None
    return dict(status=str(solved.message),upper_bound=bound,wall_seconds=time.perf_counter()-start,
        variables=len(m.c),scope='Continuous aggregate relaxation: fractional assets and flights, no departure slots or transfer timing; relocation cost relaxed to zero')
