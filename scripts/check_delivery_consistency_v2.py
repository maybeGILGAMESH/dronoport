"""Independently reconcile all primary comparison rows with their saved plans."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import json,subprocess,xml.etree.ElementTree as ET,argparse
import pandas as pd
from droneport.ingest import ROOT,checksum
from droneport.event_model import EventInstance
from droneport.pipeline_v2 import metrics,save


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-dir');args=parser.parse_args()
    folder=Path(args.run_dir) if args.run_dir else Path((ROOT/'results_v2/current_run.txt').read_text().strip());towns=pd.read_csv(folder/'towns_main.csv');checks=[]
    assert towns.equals(pd.read_csv(ROOT/'data/processed/towns_main.csv'))
    registry=pd.read_csv(ROOT/'data/processed_v2/registry_gar.csv');assert set(towns.place_id)<=set(registry.place_id.dropna())
    def compare(row,path,table):
        result=json.loads((path/'result.json').read_text());cfg=json.loads((path/'config.json').read_text());selected=pd.read_csv(path/'towns.csv') if (path/'towns.csv').exists() else towns.head(len(result['plan']['open_years']))
        expected=metrics(EventInstance(selected,cfg),result)
        for key in ('completed_trips','demand','served_share','cost_rub','ports','fleet'):
            assert abs(float(row[key])-expected[key])<=1e-8,(table,key,path,row[key],expected[key])
        checks.append(dict(table=table,path=str(path.relative_to(folder)),valid=True))
    methods=pd.read_csv(folder/'method_comparison.csv')
    for _,row in methods.iterrows():
        n=int(row.instance);paths={'greedy':f'scale/{n}/greedy','annealing_best':f'scale/{n}/timed_best','annealing_preliminary':f'preliminary_iteration_study/scale/{n}/best','deployment_polish':f'deployment_polish/{n}/best','mip':f'scale/{n}/mip','sequential_greedy':f'sequential/{n}','sequential_mip':f'sequential_mip/{n}'}
        compare(row,folder/paths[row.method],'methods')
    seeds=pd.read_csv(folder/'seed_results.csv');assert seeds.groupby('instance').size().to_dict()=={8:10,12:10,20:10,30:10}
    for _,row in seeds.iterrows():compare(row,folder/f'scale/{int(row.instance)}/seed_{int(row.seed)}','seeds')
    experiments=pd.read_csv(folder/'experiments.csv')
    for _,row in experiments.iterrows():
        path=folder/row.result_path if isinstance(row.result_path,str) else folder/f'grid/{int(row.value)}'
        compare(row,path,'experiments')
    assert (experiments[experiments.experiment=='budget'].sort_values('value').completed_trips.diff().dropna()>=0).all()
    budget=experiments[experiments.experiment=='budget'].sort_values('value')
    for a,b in zip(budget.to_dict('records'),budget.to_dict('records')[1:]):
        if (a['ports'],a['fleet'])!=(b['ports'],b['fleet']):assert b['value']-a['value']<=10
    for _,row in pd.read_csv(folder/'scenario_results.csv').iterrows():compare(row,folder/f'scenarios/{row.plan}/{row.scenario}','scenarios')
    paths=pd.read_csv(folder/'bfs_astar.csv');reachable=paths[paths.reachable];assert (reachable.astar_minutes<=reachable.bfs_minutes+1e-8).all()
    sources=[p for directory in ('src','tests') for p in (ROOT/directory).rglob('*.py')]
    before={str(p.relative_to(ROOT)):checksum(p) for p in sources}
    completed=subprocess.run([sys.executable,'-m','pytest','-q','--junitxml=reports/tests_v2.xml'],cwd=ROOT)
    assert completed.returncode==0
    assert before=={str(p.relative_to(ROOT)):checksum(p) for p in sources},'Source changed during tests'
    suites=ET.parse(ROOT/'reports/tests_v2.xml').getroot().findall('testsuite')
    tests=sum(int(s.attrib['tests']) for s in suites);assert all(int(s.attrib['failures'])==int(s.attrib['errors'])==0 for s in suites)
    save(folder/'test_validation.json',dict(tests=tests,source_sha256=before,junit_sha256=checksum(ROOT/'reports/tests_v2.xml'),requirements_sha256=checksum(ROOT/'requirements.txt')))
    save(folder/'comparison_consistency.json',dict(valid=True,rows=checks,frozen_sample_equal=True,all_sample_points_matched_gar=True,nondecreasing_budget_values=True,astar_not_slower_than_bfs=True))
    print(f'Reconciled {len(checks)} comparison rows; {tests} tests passed')

if __name__=='__main__':main()
