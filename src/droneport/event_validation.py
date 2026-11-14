"""Independent v2 validation; never reads optimization matrices or cached objective."""
from collections import Counter, defaultdict
import json
import math
import numpy as np
from pyproj import Geod


def validate(towns,result,cfg):
    errors=[]
    def check(ok,code,detail=''):
        if not ok: errors.append(dict(code=code,detail=str(detail)))
    points={r['place_id']:r for r in towns.to_dict('records')}; ids=list(points)
    plan=result['plan']; fs=result['flights']; trips=result['itineraries']; scenario=result.get('scenario',{})
    failed=scenario.get('failed'); failed_id=ids[failed] if failed is not None else None
    fleet={a['id']:a for a in plan['aircraft']}; fdict={f['flight_id']:f for f in fs}
    check(len(fdict)==len(fs),'duplicate_flight'); check(len(fleet)==len(plan['aircraft']),'duplicate_aircraft')
    check(len(plan['open_years'])==len(ids),'open_shape')
    check(all(v in (0,1,2,3) for v in plan['open_years']),'open_year')
    policy=cfg.get('regional_coverage',{});deadline=policy.get('deadline_year',3)
    for region in policy.get('regions',[]):
        nodes=[k for k,r in points.items() if str(int(r['region_code']))==str(region)]
        check(any(0<plan['open_years'][ids.index(k)]<=deadline for k in nodes),'regional_port',region)
        # Failures may legitimately interrupt service; infrastructure remains
        # commissioned. The service guarantee is for the normal operating case.
        baseline=failed is None and scenario.get('max_range') is None and scenario.get('factor',1.)==1.
        if baseline:
            count=sum(f['year']==deadline and (f['origin_id'] in nodes or f['destination_id'] in nodes) for f in fs)
            check(count>=policy.get('min_flights',0),'regional_service',region)
    geod=Geod(ellps='WGS84'); charges=defaultdict(list); movements=Counter(); aircraft=defaultdict(list)
    limit=scenario.get('max_range') or cfg['range_km']; start=cfg['day_start_minutes']; end=start+cfg['day_minutes']
    for asset in fleet.values():
        for year in range(asset['year'],4):
            planned=int(asset.get('homes',{}).get(str(year),asset['home']))
            actual=int(result.get('actual_homes',{}).get(str(year),{}).get(asset['id'],planned))
            check(0<=actual<len(ids),'home_index',asset['id'])
            if not 0<=actual<len(ids): continue
            check(0<plan['open_years'][actual]<=year,'home_closed',asset['id'])
            if year==asset['year']: check(actual==asset['home'],'initial_location',asset['id'])
            if failed is None and scenario.get('max_range') is None: check(actual==planned,'planned_home',asset['id'])
            claimed=asset['id'] in result.get('blocked_aircraft',{}).get(str(year),[])
            check(claimed==(actual==failed),'blocked_location',asset['id'])
    for f in fs:
        year=f['year']; a=f['origin_id']; b=f['destination_id']; fid=f['flight_id']
        check(a in points and b in points and a!=b,'flight_nodes',fid)
        if a not in points or b not in points: continue
        check(f['aircraft_id'] in fleet,'unowned_aircraft',fid)
        if f['aircraft_id'] in fleet:
            asset=fleet[f['aircraft_id']]
            check(asset['year']<=year,'aircraft_not_commissioned',fid)
            check(f['aircraft_id'] not in result.get('blocked_aircraft',{}).get(str(year),[]),'blocked_aircraft',fid)
            actual=int(result.get('actual_homes',{}).get(str(year),{}).get(asset['id'],asset.get('homes',{}).get(str(year),asset['home'])))
            check(actual!=failed,'blocked_base',fid)
        for node in (a,b): check(0<plan['open_years'][ids.index(node)]<=year,'closed_port',fid)
        check(failed_id not in (a,b),'failed_port',fid)
        distance=geod.inv(points[a]['lon'],points[a]['lat'],points[b]['lon'],points[b]['lat'])[2]/1000
        check(distance<=limit+1e-7,'range',fid); check(abs(distance-f['distance_km'])<1e-5,'distance',fid)
        check(f['arrival_min']-f['departure_min']>=distance/cfg['flight_speed_kmh']*60+cfg['landing_minutes']-1e-7,'duration',fid)
        check(f['charge_end_min']-f['arrival_min']>=cfg['charging_minutes'],'charge_duration',fid)
        check(start<=f['departure_min']<f['arrival_min']<=f['charge_end_min']<=end,'working_day',fid)
        check(all((f[k]-start)%cfg['time_step_minutes']==0 for k in ('departure_min','arrival_min','charge_end_min')),'time_grid',fid)
        check(0<=f['passengers']<=10 and int(f['passengers'])==f['passengers'],'capacity',fid)
        check(f['empty']==(f['passengers']==0),'empty_flag',fid)
        check(f['energy_cost_rub']==math.ceil(distance*cfg['energy_kwh_per_km']*cfg['electricity_rub_per_kwh']),'energy',fid)
        charges[year,b]+=[(f['arrival_min'],1),(f['charge_end_min'],-1)]
        movements[year,a,(f['departure_min']-start)//cfg['movement_window_minutes']]+=1
        movements[year,b,(f['arrival_min']-start)//cfg['movement_window_minutes']]+=1
        aircraft[year,f['aircraft_id']].append(f)
    for tag,events in charges.items():
        count=0
        for _,delta in sorted(events): count+=delta; check(count<=cfg['chargers_per_port'],'charger_capacity',tag)
    check(all(v<=cfg['max_movements_per_window'] for v in movements.values()),'movements')
    for (year,aid),rows in aircraft.items():
        rows=sorted(rows,key=lambda r:r['departure_min'])
        if aid not in fleet: continue
        home=ids[int(result.get('actual_homes',{}).get(str(year),{}).get(aid,fleet[aid].get('homes',{}).get(str(year),fleet[aid]['home'])))]
        check(rows[0]['origin_id']==home,'initial_location',aid)
        check(rows[-1]['destination_id']==home,'daily_cycle',aid)
        for p,q in zip(rows,rows[1:]):
            check(p['destination_id']==q['origin_id'],'teleportation',aid)
            check(p['charge_end_min']<=q['departure_min'],'overlap',aid)
    loads=Counter(); completed=Counter(); seen=set(); totals=[0]*3
    for trip in trips:
        check(trip['trip_id'] not in seen,'duplicate_trip'); seen.add(trip['trip_id'])
        legs=json.loads(trip['flight_ids']); check(bool(legs) and all(f in fdict for f in legs),'unknown_flight')
        if not legs or not all(f in fdict for f in legs): continue
        rows=[fdict[f] for f in legs]; y=trip['year']
        check(all(f['year']==y for f in rows),'trip_year'); check(rows[0]['origin_id']==trip['origin_id'] and rows[-1]['destination_id']==trip['destination_id'],'trip_od')
        check(trip['arrival_min']==rows[-1]['arrival_min'],'trip_arrival'); check(trip['transfers']==len(rows)-1,'transfer_count')
        for p,q in zip(rows,rows[1:]):
            check(p['destination_id']==q['origin_id'],'transfer_location')
            check(q['departure_min']>=p['arrival_min']+cfg['minimum_transfer_minutes'],'transfer_time')
        loads.update(legs); completed[y,trip['origin_id'],trip['destination_id']]+=1
        check(trip['annual_weight']==cfg['operating_days'],'annual_weight'); totals[y-1]+=cfg['operating_days']
    for fid,f in fdict.items(): check(loads[fid]==f['passengers'],'load_balance',fid)
    params=cfg['demand']; population={i:r['population'] for i,r in points.items()}
    if cfg.get('population_cap_quantile'):
        cap=float(np.quantile(list(population.values()),cfg['population_cap_quantile'])); population={i:min(p,cap) for i,p in population.items()}
    for (y,a,b),count in completed.items():
        d=geod.inv(points[a]['lon'],points[a]['lat'],points[b]['lon'],points[b]['lat'])[2]/1000
        q=math.floor(params['K']*population[a]**params['alpha']*population[b]**params['beta']/(1+d/params['distance_scale_km'])**params['gamma']*params['yearly_growth']**(y-1))
        q=math.floor(q*cfg.get('demand_factor',1.)); q=math.floor(q*scenario.get('factor',1.))
        check(count<=q,'demand_exceeded',(y,a,b))
    check(result['annual_completed']==totals,'annual_completion'); check(result['completed_trips']==sum(totals),'total_completion')
    relocation_energy=Counter(); relocations=defaultdict(list); relocation_resources=defaultdict(list); relocation_movements=Counter()
    for r in result.get('relocations',[]):
        y=r['year']; aid=r['aircraft_id']; a=r['origin_id']; b=r['destination_id']; day=r['transition_day']
        check(aid in fleet and a in points and b in points,'relocation_identity')
        if aid not in fleet or a not in points or b not in points: continue
        check(fleet[aid]['year']<y,'relocation_before_purchase'); check(0<=day<365-cfg['operating_days'],'relocation_day')
        check(failed_id not in (a,b),'relocation_failed_port')
        for node in (a,b): check(0<plan['open_years'][ids.index(node)]<=y,'relocation_closed_port')
        distance=geod.inv(points[a]['lon'],points[a]['lat'],points[b]['lon'],points[b]['lat'])[2]/1000
        check(distance<=limit+1e-7,'relocation_range'); check(start<=r['departure_min']<r['arrival_min']<=r['charge_end_min']<=end,'relocation_hours')
        check(r['arrival_min']-r['departure_min']>=distance/cfg['flight_speed_kmh']*60+cfg['landing_minutes']-1e-7,'relocation_duration')
        check(r['charge_end_min']-r['arrival_min']>=cfg['charging_minutes'],'relocation_charge')
        expected=math.ceil(distance*cfg['energy_kwh_per_km']*cfg['electricity_rub_per_kwh'])
        check(r['energy_cost_rub']==expected,'relocation_energy'); relocation_energy[y]+=expected
        relocations[y,aid].append(r); relocation_resources[y,day,b]+=[(r['arrival_min'],1),(r['charge_end_min'],-1)]
        relocation_movements[y,day,a,(r['departure_min']-start)//cfg['movement_window_minutes']]+=1
        relocation_movements[y,day,b,(r['arrival_min']-start)//cfg['movement_window_minutes']]+=1
    check(all(v<=cfg['max_movements_per_window'] for v in relocation_movements.values()),'relocation_movements')
    for events in relocation_resources.values():
        occupied=0
        for _,delta in sorted(events): occupied+=delta; check(occupied<=cfg['chargers_per_port'],'relocation_chargers')
    for asset in fleet.values():
        for y in (2,3):
            if asset['year']>=y: continue
            before=int(result.get('actual_homes',{}).get(str(y-1),{}).get(asset['id'],asset.get('homes',{}).get(str(y-1),asset['home'])))
            after=int(result.get('actual_homes',{}).get(str(y),{}).get(asset['id'],asset.get('homes',{}).get(str(y),asset['home'])))
            rows=sorted(relocations[y,asset['id']],key=lambda r:(r['transition_day'],r['departure_min']))
            if before!=after or rows:
                check(bool(rows),'missing_relocation',asset['id'])
                if rows: check(rows[0]['origin_id']==ids[before] and rows[-1]['destination_id']==ids[after],'relocation_endpoints')
            for p,q in zip(rows,rows[1:]):
                check(p['destination_id']==q['origin_id'],'relocation_teleportation')
                check(p['transition_day']*1440+p['charge_end_min']<=q['transition_day']*1440+q['departure_min'],'relocation_overlap')
    carry=0
    for year in (1,2,3):
        rows=[r for r in result['budget'] if r['year']==year]; check(len(rows)==1,'budget_year')
        if len(rows)!=1: continue
        row=rows[0]; np_=sum(v==year for v in plan['open_years']); ap=sum(0<v<=year for v in plan['open_years'])
        na=sum(a['year']==year for a in fleet.values()); aa=sum(a['year']<=year for a in fleet.values())
        energy=sum(f['energy_cost_rub'] for f in fs if f['year']==year)*cfg['operating_days']
        spent=np_*cfg['port_capex_rub']+ap*cfg['port_opex_rub_per_year']+na*cfg['aircraft_capex_rub']+aa*cfg['aircraft_opex_rub_per_year']+energy+relocation_energy[year]
        available=carry+cfg['yearly_tranche_rub']; carry=available-spent
        check(carry>=0,'future_tranche',year); check(spent==row['spend_rub'],'budget_cost',year)
        check(row['available_rub']==available and row['carry_rub']==carry,'budget_balance',year)
        check(row['active_ports']==ap and row['active_aircraft']==aa,'asset_count',year)
    return dict(valid=not errors,errors=errors,completed_trips=sum(totals),flights=len(fs),
        transfer_trips=sum(t['transfers']>0 for t in trips),empty_flights=sum(f['empty'] for f in fs))
