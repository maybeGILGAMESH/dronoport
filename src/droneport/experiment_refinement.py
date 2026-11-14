"""Feasible warm candidates, retaining raw greedy measurements for audit."""
from pathlib import Path
from copy import deepcopy
import json
import pandas as pd
from .event_model import EventInstance
from .pipeline_v2 import export,metrics,save
from .ingest import checksum


def refine(folder):
    folder=Path(folder);raw=folder/'experiments_raw.csv'
    if not raw.exists():raw.write_bytes((folder/'experiments.csv').read_bytes())
    frame=pd.read_csv(raw);towns=pd.read_csv(folder/'towns_main.csv')
    reference=json.loads((folder/'scale/30/greedy/plan.json').read_text());rows=[];budget_pool=[]
    # Low-budget plans remain candidates at higher budgets. No interpolation,
    # monotonic smoothing or substitution of uncomputed objective values.
    ordered=frame.copy();ordered['_order']=ordered.experiment.ne('budget').astype(int)
    for row in ordered.sort_values(['_order','value']).to_dict('records'):
        tag=row['experiment'];value=row['value'];name=f'{tag}_{value:g}'
        if tag=='grid_small':rows.append({k:v for k,v in row.items() if k!='_order'});continue
        # Existing filenames encode float multipliers, including 1.0.
        options=[p for p in (folder/'experiments').iterdir() if p.is_dir() and p.name.startswith(tag+'_') and float(p.name[len(tag)+1:])==value]
        assert len(options)==1,(tag,value,options)
        source=options[0];cfg=json.loads((source/'config.json').read_text());instance=EventInstance(towns,cfg)
        original=json.loads((source/'result.json').read_text());candidates=[original]
        for plan in [reference]+(budget_pool if tag=='budget' else []):
            ev=instance.evaluate(plan)
            if ev is not None:candidates.append(ev)
        chosen=max(candidates,key=lambda r:(r['completed_trips'],-sum(b['spend_rub'] for b in r['budget'])))
        if tag=='budget':budget_pool.append(chosen['plan'])
        output=folder/'experiments_portfolio'/name;export(instance,chosen,output)
        rows.append(metrics(instance,chosen,experiment=tag,value=value,wall_seconds=row['wall_seconds'],
            raw_completed_trips=original['completed_trips'],selection='raw greedy + feasible common baseline + lower-budget plans',
            result_path=str(output.relative_to(folder)),raw_result_path=str(source.relative_to(folder))))
    pd.DataFrame(rows).to_csv(folder/'experiments.csv',index=False)
    save(folder/'experiment_refinement.json',dict(method='Feasible candidate portfolio, original greedy results retained unchanged',
        raw_csv_sha256=checksum(raw),code_sha256=checksum(Path(__file__)),
        timing_note='wall_seconds retains original greedy timing; portfolio checks are postprocessing and are not algorithm timing comparisons'))
