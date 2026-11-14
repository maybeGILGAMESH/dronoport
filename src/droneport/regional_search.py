"""Construct regional service with a real closed tour, retaining earlier years."""
from copy import deepcopy
from collections import Counter
import math
import networkx as nx
from .event_validation import validate


def make_tour(instance,source,regional_nodes,aircraft_id,departure_shift=0):
    plan=deepcopy(source['plan']);year=instance.cfg['regional_coverage']['deadline_year']
    for i in regional_nodes:plan['open_years'][i]=min(plan['open_years'][i] or year,year)
    if any(b['carry_rub']<0 for b in instance.fixed_budget(plan)):return None
    asset=next(a for a in plan['aircraft'] if a['id']==aircraft_id)
    if asset['year']>year:return None
    home=int(asset.get('homes',{}).get(str(year),asset['home']))
    active=[i for i,y in enumerate(plan['open_years']) if 0<y<=year]
    graph=nx.Graph();graph.add_nodes_from(active)
    for a in active:
        for b in active:
            if a<b and instance.distance[a,b]<=instance.cfg['range_km']:graph.add_edge(a,b,weight=int(instance.travel[a,b])+instance.charge)
    target=regional_nodes[0]
    if not nx.has_path(graph,home,target):return None
    forward=nx.shortest_path(graph,home,target,weight='weight');route=forward+forward[-2::-1]
    if any(i not in route for i in regional_nodes):return None
    flights=[deepcopy(f) for f in source['flights'] if not(f['year']==year and f['aircraft_id']==aircraft_id)]
    movement=Counter();charging=Counter();c=instance.cfg
    for f in flights:
        if f['year']!=year:continue
        a=instance.index[f['origin_id']];b=instance.index[f['destination_id']]
        movement[a,(f['departure_min']-instance.start)//c['movement_window_minutes']]+=1
        movement[b,(f['arrival_min']-instance.start)//c['movement_window_minutes']]+=1
        for t in range(f['arrival_min'],f['charge_end_min'],instance.step):charging[b,t]+=1
    ready=instance.start+departure_shift
    for a,b in zip(route,route[1:]):
        placed=False
        for dep in range(ready,instance.end,instance.step):
            arr=dep+int(instance.travel[a,b]);end=arr+instance.charge
            if end>instance.end:break
            ma=(a,(dep-instance.start)//c['movement_window_minutes']);mb=(b,(arr-instance.start)//c['movement_window_minutes'])
            if movement[ma]>=c['max_movements_per_window'] or movement[mb]>=c['max_movements_per_window']:continue
            if any(charging[b,t]>=c['chargers_per_port'] for t in range(arr,end,instance.step)):continue
            movement[ma]+=1;movement[mb]+=1
            for t in range(arr,end,instance.step):charging[b,t]+=1
            flights.append(dict(year=year,flight_id=f'y{year}_region_{len(flights)}',aircraft_id=aircraft_id,origin_id=instance.ids[a],destination_id=instance.ids[b],
                departure_min=dep,arrival_min=arr,charge_end_min=end,distance_km=instance.distance[a,b],
                energy_cost_rub=math.ceil(instance.distance[a,b]*c['energy_kwh_per_km']*c['electricity_rub_per_kwh']),passengers=0,empty=True))
            ready=end;placed=True;break
        if not placed:return None
    fs=[f for f in flights if f['year']==year]
    for f in fs:f['passengers']=0;f['empty']=True
    trips,status=instance.allocate(fs,year)
    trips=[deepcopy(t) for t in source['itineraries'] if t['year']!=year]+trips
    relocation=instance.relocations(plan)
    if relocation is None:return None
    rr,re,blocked,actual=relocation
    energy=[sum(f['energy_cost_rub'] for f in flights if f['year']==y)*c['operating_days'] for y in (1,2,3)]
    budget=instance.fixed_budget(plan,energy,re)
    if any(b['carry_rub']<0 for b in budget):return None
    annual=[sum(t['year']==y for t in trips)*c['operating_days'] for y in (1,2,3)]
    result=dict(plan=plan,flights=flights,itineraries=trips,budget=budget,annual_completed=annual,completed_trips=sum(annual),scenario={},
        relocations=rr,actual_homes={str(y):v for y,v in actual.items()},blocked_aircraft={str(y):sorted(v) for y,v in blocked.items()},allocation_status=[status])
    if not validate(instance.towns,result,c)['valid']:return None
    return result


def region_metrics(instance,result):
    rows=[]
    for region in sorted(set(instance.towns.region_code)):
        ids={instance.ids[i] for i,v in enumerate(instance.towns.region_code) if v==region}
        for y in (1,2,3):
            nodes=[i for i,v in enumerate(instance.towns.region_code) if v==region and 0<result['plan']['open_years'][i]<=y]
            flights=[f for f in result['flights'] if f['year']==y and (f['origin_id'] in ids or f['destination_id'] in ids)]
            trips=[t for t in result['itineraries'] if t['year']==y and (t['origin_id'] in ids or t['destination_id'] in ids)]
            rows.append(dict(region_code=int(region),year=y,ports=len(nodes),port_names='; '.join(instance.towns.iloc[i].name_original for i in nodes),
                daily_flights=len(flights),loaded_flights=sum(f['passengers']>0 for f in flights),annual_od_trips=len(trips)*instance.cfg['operating_days']))
    return rows
