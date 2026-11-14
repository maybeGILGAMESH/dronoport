"""Select current scenario manifest; retain supplemental historical cases explicitly."""
from pathlib import Path
import json,argparse
import pandas as pd
root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--run-dir');args=parser.parse_args()
folder=Path(args.run_dir or (root/'.cache/cp_ga_run.txt' if (root/'.cache/cp_ga_run.txt').exists() else root/'results_v2/current_run.txt').read_text().strip())
allowed={'main_8','main_30','robust_30'}|{f'{r.plan}_{r.scenario}' for r in pd.read_csv(folder/'scenario_results.csv').itertuples() if r.scenario!='base'}
frame=pd.read_csv(folder/'cp_ga/fixed_results.csv');extras=frame[~frame.name.isin(allowed)]
extras.to_csv(folder/'cp_ga/historical_extra_fixed_cases.csv',index=False)
frame=frame[frame.name.isin(allowed)];assert set(frame.name)==allowed
for row in frame.itertuples():
    if row.name.startswith(('base_','robust_')):
        label=row.name.split('_')[0]
        assert json.loads((folder/row.result_path/'result.json').read_text())['plan']==json.loads((folder/label/'result.json').read_text())['plan']
frame.to_csv(folder/'cp_ga/fixed_results.csv',index=False)
p=folder/'cp_ga/fixed_manifest.json';manifest=json.loads(p.read_text());manifest.update(cases=len(frame),historical_extra_cases=len(extras),selection='Explicit scenario_results.csv; inherited obsolete directories excluded')
p.write_text(json.dumps(manifest,ensure_ascii=False,indent=2));print(manifest)
