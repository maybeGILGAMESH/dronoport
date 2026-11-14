"""Publish traceable transfer and asymmetric empty-return examples."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from copy import deepcopy
import json,math
import pandas as pd
from droneport.ingest import ROOT,checksum
from droneport.event_model import EventInstance
from droneport.pipeline_v2 import export,save


def main():
    folder=Path((ROOT/'results_v2/current_run.txt').read_text().strip())
    towns=pd.read_csv(folder/'towns_main.csv');cfg=json.loads((folder/'config.json').read_text())
    found=None
    for candidate in sorted((folder/'scale').rglob('result.json')):
        result=json.loads(candidate.read_text());fs={f['flight_id']:f for f in result['flights']}
        for t in result['itineraries']:
            if t['transfers']>0 and len({fs[f]['aircraft_id'] for f in json.loads(t['flight_ids'])})>1:
                found=(candidate,result,t);break
        if found:break
    if found:
        original,small,trip=found;small_cfg=json.loads((original.parent/'config.json').read_text())
        ii=EventInstance(towns.head(len(small['plan']['open_years'])),small_cfg)
    else:
        # Quick runs may have no aircraft-changing itinerary. Keep the example
        # explicit and separate instead of forcing transfers into the main plan.
        selected=towns.set_index('name_original').loc[['Люберцы','Котельники','Лыткарино']].reset_index()
        ii=EventInstance(selected,cfg);plan=ii.empty();plan['open_years']=[1]*3
        plan['aircraft']=[dict(id='transfer_a',year=1,home=0),dict(id='transfer_b',year=1,home=1)]
        flights=[];trips=[]
        for year in (1,2,3):
            for k,(a,b,t,aid) in enumerate([(0,1,480,'transfer_a'),(1,2,600,'transfer_b'),(2,1,690,'transfer_b'),(1,0,780,'transfer_a')]):
                arrival=t+int(ii.travel[a,b]);distance=float(ii.distance[a,b])
                flights.append(dict(year=year,flight_id=f'y{year}_example_{k}',aircraft_id=aid,origin_id=ii.ids[a],destination_id=ii.ids[b],departure_min=t,arrival_min=arrival,charge_end_min=arrival+ii.charge,distance_km=distance,energy_cost_rub=math.ceil(distance*cfg['energy_kwh_per_km']*cfg['electricity_rub_per_kwh']),passengers=int(k<2),empty=k>=2))
            trips.append(dict(year=year,trip_id=f'y{year}_transfer',origin_id=ii.ids[0],destination_id=ii.ids[2],flight_ids=json.dumps([f'y{year}_example_0',f'y{year}_example_1']),arrival_min=600+int(ii.travel[1,2]),transfers=1,annual_weight=cfg['operating_days']))
        energy=[sum(f['energy_cost_rub'] for f in flights if f['year']==y)*cfg['operating_days'] for y in (1,2,3)]
        small=dict(plan=plan,flights=flights,itineraries=trips,annual_completed=[330]*3,completed_trips=990,budget=ii.fixed_budget(plan,energy),scenario={},relocations=[],allocation_status=[])
        trip=trips[0]
    source=folder/'examples/transfer_source/result.json';export(ii,small,source.parent)
    ii.towns.to_csv(source.parent/'towns.csv',index=False)
    ids=json.loads(trip['flight_ids']);legs=[next(f for f in small['flights'] if f['flight_id']==fid) for fid in ids]
    save(folder/'examples/transfer.json',dict(source=str(source.relative_to(folder)),source_sha256=checksum(source),trip=trip,legs=legs,
        explanation='Одна завершённая поездка с пересадкой, независимо от числа перелётов; годовой вес 330.'))
    pair=towns[towns.name_original.isin(['Люберцы','Котельники'])].reset_index(drop=True)
    pair['population']=[1000000,1];c=deepcopy(cfg);probe=EventInstance(pair,c)
    c['demand']['K']=1.1*(1+probe.distance[0,1]/c['demand']['distance_scale_km'])**c['demand']['gamma']/1000000**c['demand']['alpha']
    ii=EventInstance(pair,c);plan=ii.empty();plan['open_years']=[1,1];plan['aircraft']=[dict(id='empty_return',year=1,home=0)]
    result=ii.evaluate(plan);destination=folder/'examples/empty_return';export(ii,result,destination);pair.to_csv(destination/'towns.csv',index=False)
    assert result['completed_trips']==990 and any(f['empty'] for f in result['flights'])
    save(destination/'example_scope.json',dict(kind='controlled_synthetic',note='Координаты реальные; население и K изменены только в проверочном экземпляре. Основные данные не меняются.',known_answer=990,script_sha256=checksum(Path(__file__))))
    print('Transfer and known-answer empty return examples validated')

if __name__=='__main__':main()
