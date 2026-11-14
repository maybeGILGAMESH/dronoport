"""Check the deployment timetable as another candidate at each budget."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from copy import deepcopy
import json
import pandas as pd
from droneport.ingest import ROOT,checksum
from droneport.event_model import EventInstance
from droneport.pipeline_v2 import export,metrics,save

def main():
    folder=Path((ROOT/'results_v2/current_run.txt').read_text().strip());rows=pd.read_csv(folder/'experiments.csv')
    base=json.loads((folder/'base/result.json').read_text());towns=pd.read_csv(folder/'towns_main.csv');changed=[]
    for index,row in rows[rows.experiment=='budget'].iterrows():
        cfg=json.loads((folder/'config.json').read_text());cfg['yearly_tranche_rub']=int(row.value*1000000);inst=EventInstance(towns,cfg)
        result=deepcopy(base);energy=[sum(f['energy_cost_rub'] for f in result['flights'] if f['year']==y)*cfg['operating_days'] for y in (1,2,3)]
        ferry=[sum(f['energy_cost_rub'] for f in result.get('relocations',[]) if f['year']==y) for y in (1,2,3)]
        result['budget']=inst.fixed_budget(result['plan'],energy,ferry)
        if any(b['carry_rub']<0 for b in result['budget']):continue
        cost=sum(b['spend_rub'] for b in result['budget'])
        if (result['completed_trips'],-cost)<=(row.completed_trips,-row.cost_rub):continue
        path=folder/f'experiments_portfolio/budget_{row.value:g}/deployment_candidate';export(inst,result,path)
        rows.loc[index,'prior_portfolio_result_path']=row.result_path;rows.loc[index,'result_path']=str(path.relative_to(folder))
        rows.loc[index,'selection']='Prior portfolio plus independently validated deployment timetable'
        for key,value in metrics(inst,result).items():rows.loc[index,key]=value
        changed.append(float(row.value))
    rows.to_csv(folder/'experiments.csv',index=False)
    save(folder/'deployment_budget_revision.json',dict(budgets_updated_million=changed,base_sha256=checksum(folder/'base/result.json'),scope='Feasible candidate reuse, not equal-time budget optimization or an optimal frontier'))
    print('Deployment candidate reused at budgets:',changed)

if __name__=='__main__':main()
