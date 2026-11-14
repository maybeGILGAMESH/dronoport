"""Lift the saved v1 schedules to the v2 time grid without changing passengers."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import json
import shutil
import pandas as pd
from droneport.ingest import ROOT,checksum
from droneport.event_model import EventInstance
from droneport.pipeline_v2 import export,save


def main():
    folder=Path((ROOT/'results_v2/current_run.txt').read_text().strip());cfg=json.loads((folder/'config.json').read_text())
    towns=pd.read_csv(folder/'towns_main.csv');rows=[]
    for n,source in [(8,ROOT/'runs/20261105_171655/small/0'),(30,ROOT/'artifacts/preserved_20261105_171655/results')]:
        if not source.exists():
            candidates=sorted((ROOT/'runs').glob(f'*/comparisons/legacy_source_{n}'))
            if not candidates:raise FileNotFoundError(f'Missing preserved legacy source for {n} nodes')
            source=candidates[-1]
        inst=EventInstance(towns.head(n),cfg);plan=inst.empty();flights=pd.read_csv(source/'flights_and_schedule.csv').to_dict('records');trips=pd.read_csv(source/'passenger_itineraries.csv').to_dict('records')
        for f in flights:
            a=inst.index[f['origin_id']];b=inst.index[f['destination_id']]
            for i in (a,b):plan['open_years'][i]=min(plan['open_years'][i] or f['year'],f['year'])
            f['arrival_min']=f['departure_min']+int(inst.travel[a,b]);f['charge_end_min']=f['arrival_min']+inst.charge
        for aid in sorted({f['aircraft_id'] for f in flights}):
            first=min((f for f in flights if f['aircraft_id']==aid),key=lambda f:(f['year'],f['departure_min']))
            plan['aircraft'].append(dict(id=aid,year=first['year'],home=inst.index[first['origin_id']]))
        by_id={f['flight_id']:f for f in flights}
        for trip in trips:trip['arrival_min']=by_id[json.loads(trip['flight_ids'])[-1]]['arrival_min']
        annual=[sum(t['year']==y for t in trips)*cfg['operating_days'] for y in (1,2,3)]
        energy=[sum(f['energy_cost_rub'] for f in flights if f['year']==y)*cfg['operating_days'] for y in (1,2,3)]
        result=dict(plan=plan,flights=flights,itineraries=trips,annual_completed=annual,completed_trips=sum(annual),budget=inst.fixed_budget(plan,energy),scenario={},relocations=[],allocation_status=[])
        destination=folder/'comparisons'/f'legacy_in_v2_{n}';export(inst,result,destination)
        copy=folder/'comparisons'/f'legacy_source_{n}';copy.mkdir(exist_ok=True)
        for name in ['flights_and_schedule.csv','passenger_itineraries.csv','budget_by_year.csv']:
            if (source/name).resolve()!=(copy/name).resolve():shutil.copy2(source/name,copy/name)
        rows.append(dict(nodes=n,completed_trips=sum(annual),transformation='Flight/charging durations rounded upwards to v2 grid; same departures, aircraft, assets and passenger journeys',
            source_hashes={name:checksum(source/name) for name in ['flights_and_schedule.csv','passenger_itineraries.csv']},validation='passed'))
    save(folder/'comparisons/legacy_lift.json',rows);print(rows)

if __name__=='__main__':main()
