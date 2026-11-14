"""Promote the completed equal-time series after the original MIPs finish."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import json,shutil
import pandas as pd
from droneport.ingest import ROOT,checksum
from droneport.event_model import EventInstance
from droneport.pipeline_v2 import export,metrics,route_comparison,save


def main():
    folder=Path((ROOT/'results_v2/current_run.txt').read_text().strip());study=folder/'time_budget_study'
    manifest=json.loads((folder/'run_manifest.json').read_text());assert manifest['status'] in ('running','calculated')
    timed=json.loads((study/'manifest.json').read_text());assert timed['status']=='calculated'
    backup=folder/'preliminary_iteration_study'
    if backup.exists():raise FileExistsError('Promotion already started; inspect before repeating')
    backup.mkdir()
    for name in ('scale','base','robust','scenarios'):
        shutil.copytree(folder/name,backup/name)
    for name in ('config.json','method_comparison.csv','seed_results.csv','search_history.csv','annual_comparison.csv','bfs_astar.csv','scenario_results.csv','recourse_revision.json','robust_search.json','minimax_results.json','mip_reports.json'):
        shutil.copy2(folder/name,backup/name)
    cfg=json.loads((folder/'config.json').read_text());cfg['annealing_iterations']=0;cfg['annealing_seconds']=timed['seconds_per_seed'];save(folder/'config.json',cfg)
    towns=pd.read_csv(folder/'towns_main.csv');seeds=pd.read_csv(study/'seed_results.csv')
    methods=pd.read_csv(folder/'method_comparison.csv');methods=methods[methods.method!='annealing_best'].to_dict('records')
    annual=pd.read_csv(folder/'annual_comparison.csv');annual=annual[annual['mode']!='joint'].to_dict('records');history=[];summary=[];selections=[]
    for n in (8,12,20,30):
        ii=EventInstance(towns.head(n),cfg);group=seeds[seeds.instance==n]
        assert len(group)==10 and set(group.seed)==set(range(10))
        for seed in range(10):
            source=study/f'scale/{n}/seed_{seed}';shutil.copytree(source,folder/f'scale/{n}/seed_{seed}',dirs_exist_ok=True)
            h=pd.read_csv(source/'history.csv');h['instance']=n;history.append(h)
        winner=group.sort_values(['completed_trips','cost_rub'],ascending=[False,True]).iloc[0]
        result=json.loads((folder/f'scale/{n}/seed_{int(winner.seed)}/result.json').read_text());export(ii,result,folder/f'scale/{n}/timed_best')
        methods.append(metrics(ii,result,instance=n,method='annealing_best',wall_seconds=group.wall_seconds.sum(),gap=None,status='FEASIBLE'))
        preliminary=json.loads((backup/f'scale/{n}/best/result.json').read_text())
        old_seeds=pd.read_csv(backup/'seed_results.csv');old_time=old_seeds[old_seeds.instance==n].wall_seconds.sum()
        methods.append(metrics(ii,preliminary,instance=n,method='annealing_preliminary',wall_seconds=old_time,gap=None,status='FEASIBLE'))
        candidates=[(f'scale/{n}/timed_best/result.json',result),(f'preliminary_iteration_study/scale/{n}/best/result.json',preliminary)]
        mip=folder/f'scale/{n}/mip/result.json'
        if mip.exists():candidates.append((str(mip.relative_to(folder)),json.loads(mip.read_text())))
        selected,result=max(candidates,key=lambda item:(item[1]['completed_trips'],-sum(b['spend_rub'] for b in item[1]['budget'])))
        selections.append(dict(instance=n,selected=selected,completed_trips=result['completed_trips'],candidates=[dict(path=p,completed_trips=r['completed_trips']) for p,r in candidates]))
        export(ii,result,folder/f'scale/{n}/best')
        greedy=json.loads((folder/f'scale/{n}/greedy/result.json').read_text())['completed_trips']
        summary.append(dict(instance=n,seeds=10,greedy=greedy,best=int(group.completed_trips.max()),minimum=int(group.completed_trips.min()),
            mean=float(group.completed_trips.mean()),median=float(group.completed_trips.median()),std=float(group.completed_trips.std()),
            mean_paired_gain=float((group.completed_trips-greedy).mean()),min_paired_gain=int((group.completed_trips-greedy).min()),
            mean_run_seconds=float(group.wall_seconds.mean()),summed_seconds=float(group.wall_seconds.sum())))
        if n in (8,30):annual += [dict(instance=n,mode='joint',**b,completed_trips=result['annual_completed'][i]) for i,b in enumerate(result['budget'])]
        if n==30:
            export(ii,result,folder/'base');pd.DataFrame(route_comparison(ii,result)).to_csv(folder/'bfs_astar.csv',index=False)
    pd.DataFrame(methods).sort_values(['instance','method']).to_csv(folder/'method_comparison.csv',index=False)
    seeds.to_csv(folder/'seed_results.csv',index=False);pd.concat(history,ignore_index=True).to_csv(folder/'search_history.csv',index=False)
    pd.DataFrame(summary).to_csv(folder/'seed_summary.csv',index=False);pd.DataFrame(annual).to_csv(folder/'annual_comparison.csv',index=False)
    manifest['timed_seed_study']=dict(path='time_budget_study/manifest.json',sha256=checksum(study/'manifest.json'),timing_scope=timed['timing_scope'])
    save(folder/'best_plan_selection.json',selections)
    manifest['selection_note']='The 600-second SA series and preliminary series are compared separately. The deployment base retains the best validated known plan across both and MIP. MIP warm starts used preliminary plans.'
    save(folder/'run_manifest.json',manifest)
    print('Timed series promoted; rerun recourse refinement and report before publication',flush=True)

if __name__=='__main__':main()
