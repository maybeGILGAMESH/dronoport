"""Independent reconciliation of the added experiments and their source plans."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import argparse,json
import pandas as pd
from droneport.ingest import ROOT,checksum
from droneport.event_model import EventInstance
from droneport.event_validation import validate
from droneport.pipeline_v2 import metrics,save


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir');args=parser.parse_args()
    folder=Path(args.run_dir) if args.run_dir else Path((ROOT/'results_v2/current_run.txt').read_text().strip())
    towns=pd.read_csv(folder/'towns_main.csv');records=[]
    for filename in ('fixed_results.csv','search_results.csv','search_best_scenarios.csv'):
        frame=pd.read_csv(folder/'cp_ga'/filename)
        for row in frame.to_dict('records'):
            out=folder/row['result_path'];r=json.loads((out/'result.json').read_text());cfg=json.loads((out/'config.json').read_text())
            inst=EventInstance(towns.head(len(r['plan']['open_years'])),cfg);check=validate(inst.towns,r,cfg);assert check['valid'],(out,check)
            actual=metrics(inst,r)
            for k in ('completed_trips','demand','served_share','cost_rub','ports','fleet'):
                assert abs(float(row[k])-actual[k])<1e-7,(filename,k,row[k],actual[k])
            if filename=='fixed_results.csv':
                report=json.loads((out/'solver_report.json').read_text());source=folder/report['source']/'result.json';warm=json.loads(source.read_text())
                assert checksum(source)==report['source_sha256'];assert r['plan']==warm['plan']
                assert row['before']==warm['completed_trips'] and row['gain']==r['completed_trips']-row['before']
                if row['name'].startswith(('base_','robust_')):
                    assert r['plan']==json.loads((folder/row['name'].split('_')[0]/'result.json').read_text())['plan']
            records.append(dict(table=filename,path=row['result_path'],valid=True))
    search=pd.read_csv(folder/'cp_ga/search_results.csv');assert search.groupby('method').size().to_dict()=={'ga':10,'sa':10}
    for method in ('ga','sa'):assert set(search[search.method==method].seed)==set(range(10))
    start=folder/'cp_ga/search_start/result.json';best_score=json.loads(start.read_text())['completed_trips']
    for row in search.itertuples():
        report=json.loads((folder/row.result_path/'search_report.json').read_text())
        assert report['start_sha256']==checksum(start) and report['time_limit_seconds']==600
        assert report['cp_seconds']==10 and report['cp_deterministic_limit']==.2
        assert report['start_trips']==best_score and report['best_trips']==row.completed_trips
        h=pd.read_csv(folder/row.result_path/'history.csv');assert (h.best.diff().dropna()>=0).all()
    cp=json.loads((folder/'cp_ga/portfolio_30/result.json').read_text());base=json.loads((folder/'base/result.json').read_text())
    assert cp['plan']==base['plan'];assert cp['completed_trips']>=base['completed_trips']
    new=json.loads((folder/'cp_ga/search_best/result.json').read_text())
    winner=search.sort_values(['completed_trips','cost_rub'],ascending=[False,True]).iloc[0]
    assert new==json.loads((folder/winner.result_path/'result.json').read_text())
    scenarios=pd.read_csv(folder/'cp_ga/search_best_scenarios.csv')
    expected={'base','demand_070','demand_130','range_160'}|{f'failed_{towns.iloc[i].place_id}' for i,y in enumerate(new['plan']['open_years']) if y}
    assert set(scenarios.scenario)==expected
    for row in scenarios.itertuples():assert json.loads((folder/row.result_path/'result.json').read_text())['plan']==new['plan']
    manifest=json.loads((folder/'run_manifest.json').read_text());old=ROOT/'runs'/manifest['baseline_run']
    if old.exists():
        for name in ('base/result.json','method_comparison.csv','seed_results.csv','scenario_results.csv'):
            assert checksum(folder/name)==checksum(old/name),'Baseline numeric artifact changed'
    summary=json.loads((folder/'cp_ga/report_summary.json').read_text())
    final=json.loads((folder/'cp_ga/final_best/result.json').read_text())
    assert validate(towns,final,json.loads((folder/'config.json').read_text()))['valid']
    assert final['plan']==new['plan'] and final['completed_trips']>=new['completed_trips']
    assert final==json.loads((folder/'cp_ga/search_best_scenarios/base/result.json').read_text())
    assert summary['baseline_trips']==base['completed_trips'] and summary['fixed_cp_trips']==cp['completed_trips'] and summary['best_search_trips']==new['completed_trips'] and summary['best_trips']==final['completed_trips']
    assert summary['best_worst_scenario']==scenarios.completed_trips.min()
    for path in (folder/'cp_ga').rglob('solver_report.json'):
        report=json.loads(path.read_text());upper=report.get('upper_bound');value=report.get('completed_trips')
        if upper is not None and value is not None:assert upper>=value-1e-6
    save(folder/'cp_ga/validation.json',dict(valid=True,rows=records,paired_seeds=10,shared_start=True,fixed_investments=True,
        source_sha256={str(p.relative_to(ROOT)):checksum(p) for name in ('src','tests') for p in (ROOT/name).rglob('*.py')}))
    print(f'CP/GA reconciliation passed: {len(records)} rows, 10 paired seeds')

if __name__=='__main__':main()
