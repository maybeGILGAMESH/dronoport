"""Construct a feasible current-year continuation while preserving actual history."""
from copy import deepcopy
from .event_validation import validate


def extend_year(instance,previous,year):
    cfg=instance.cfg;start=deepcopy(previous['plan'])
    start['aircraft']=[a for a in start['aircraft'] if a['year']<year]
    start['open_years']=[v if v<year else 0 for v in start['open_years']]
    for asset in start['aircraft']:
        home=int(asset.get('homes',{}).get(str(year-1),asset['home']))
        for future in range(year,4):asset.setdefault('homes',{})[str(future)]=home
    def construct(plan):
        if any(b['carry_rub']<0 for b in instance.fixed_budget(plan)):return None
        relocation=instance.relocations(plan)
        if relocation is None:return None
        rr,re,blocked,actual=relocation;fs=instance.schedule(plan,year,blocked=blocked[year],actual_homes=actual[year]);trips,status=instance.allocate(fs,year)
        fs=[deepcopy(f) for f in previous['flights'] if f['year']<year]+fs
        trips=[deepcopy(t) for t in previous['itineraries'] if t['year']<year]+trips
        energy=[sum(f['energy_cost_rub'] for f in fs if f['year']==y)*cfg['operating_days'] for y in (1,2,3)]
        budget=instance.fixed_budget(plan,energy,re)
        if any(b['carry_rub']<0 for b in budget):return None
        annual=[sum(t['year']==y for t in trips)*cfg['operating_days'] for y in (1,2,3)]
        result=dict(plan=deepcopy(plan),flights=fs,itineraries=trips,budget=budget,annual_completed=annual,completed_trips=sum(annual),scenario={},relocations=rr,
            actual_homes={str(y):v for y,v in actual.items()},blocked_aircraft={str(y):sorted(v) for y,v in blocked.items()},allocation_status=[status])
        return result
    def rank(r):return r['annual_completed'][year-1],-sum(b['spend_rub'] for b in r['budget'])
    best=deepcopy(previous)
    for seed in range(4):
        p=deepcopy(start);p['schedule_seed']=seed;r=construct(p)
        if r is not None and rank(r)>rank(best):best=r
    for step in range(4):
        choices=[];base_cost=sum(b['spend_rub'] for b in best['budget'])
        for home in range(instance.n):
            for buy in (False,True):
                p=deepcopy(best['plan'])
                if not buy and 0<p['open_years'][home]<=year:continue
                p['open_years'][home]=min(p['open_years'][home] or year,year)
                if buy:p['aircraft'].append(dict(id=f'seq_start_{year}_{step}_{home}',year=year,home=home))
                r=construct(p)
                if r is None:continue
                gain=r['annual_completed'][year-1]-best['annual_completed'][year-1]
                cost=sum(b['spend_rub'] for b in r['budget'])-base_cost
                if gain>0:choices.append((gain/max(1,cost),gain,r))
        if not choices:break
        best=max(choices,key=lambda item:item[:2])[2]
    assert validate(instance.towns,best,cfg)['valid']
    assert [f for f in best['flights'] if f['year']<year]==[f for f in previous['flights'] if f['year']<year]
    return best
