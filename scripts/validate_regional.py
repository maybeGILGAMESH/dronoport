"""Reconcile regional claims independently with saved flights and budgets."""
from pathlib import Path
import sys,json,argparse
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import pandas as pd
from droneport.ingest import ROOT,checksum
from droneport.event_validation import validate
from droneport.pipeline_v2 import save

parser=argparse.ArgumentParser();parser.add_argument('--run-dir',required=True);args=parser.parse_args()
folder=Path(args.run_dir).resolve();root=folder/'regional';towns=pd.read_csv(folder/'towns_main.csv')
best=json.loads((root/'final_best/result.json').read_text());cfg=json.loads((root/'config.json').read_text())
assert cfg['regional_coverage']==dict(regions=['50','67','69'],deadline_year=3,min_flights=1)
preserved=json.loads((root/'preservation.json').read_text());source=folder/'cp_ga/final_best/result.json'
assert checksum(source)==preserved['baseline_result_sha256']
parent=Path(preserved['parent'])
if parent.exists():
    assert checksum(parent/'report/report.pdf')==preserved['parent_report_sha256']
    assert checksum(parent/'cp_ga/final_best/result.json')==checksum(source)
checks=[]
for path in root.rglob('result.json'):
    r=json.loads(path.read_text());c=json.loads((path.parent/'config.json').read_text());check=validate(towns,r,c)
    assert check['valid'],(path,check)
    checks.append(dict(path=str(path.relative_to(folder)),**check))
service=pd.read_csv(root/'region_service.csv')
for row in service.itertuples():
    ids=set(towns[towns.region_code==row.region_code].place_id)
    ports=sum(0<y<=row.year and towns.iloc[i].region_code==row.region_code for i,y in enumerate(best['plan']['open_years']))
    flights=[f for f in best['flights'] if f['year']==row.year and (f['origin_id'] in ids or f['destination_id'] in ids)]
    trips=[t for t in best['itineraries'] if t['year']==row.year and (t['origin_id'] in ids or t['destination_id'] in ids)]
    assert row.ports==ports and row.daily_flights==len(flights) and row.loaded_flights==sum(f['passengers']>0 for f in flights)
    assert row.annual_od_trips==len(trips)*cfg['operating_days']
assert len(service)==9 and set(service.region_code)=={50,67,69}
assert (service[service.year==3][['ports','daily_flights','loaded_flights']]>0).all().all()
mapping={'previous':source,'construction_only':root/'construction_only/result.json','regional_service':root/'final_best/result.json'}
for row in pd.read_csv(root/'comparison.csv').itertuples():
    r=json.loads(mapping[row.method].read_text());assert row.completed_trips==r['completed_trips']
    assert row.cost_rub==sum(b['spend_rub'] for b in r['budget'])
idle=json.loads((root/'construction_only/result.json').read_text());errors=validate(towns,idle,cfg)['errors']
assert errors and {e['code'] for e in errors}=={'regional_service'}
scenarios=pd.read_csv(root/'scenarios.csv');expected={'base','demand_070','demand_130','range_160'}|{f'failed_{towns.iloc[i].place_id}' for i,y in enumerate(best['plan']['open_years']) if y}
assert set(scenarios.scenario)==expected
for row in scenarios.itertuples():
    r=json.loads((root/'scenarios'/row.scenario/'result.json').read_text());assert r['plan']==best['plan']
    assert row.completed_trips==r['completed_trips'] and row.cost_rub==sum(b['spend_rub'] for b in r['budget'])
save(root/'validation.json',dict(valid=True,checks=checks,regions=[50,67,69],source_sha256={str(p.relative_to(ROOT)):checksum(p) for d in ('src','tests') for p in (ROOT/d).rglob('*.py')},result_sha256=checksum(root/'final_best/result.json')))
print(f'Regional checks passed: {len(checks)} plans, {len(scenarios)} scenarios')
