"""Attach isolated larger-MIP attempts to the completed comparison table."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import json
import pandas as pd
from droneport.ingest import ROOT,checksum
from droneport.event_model import EventInstance
from droneport.pipeline_v2 import export,metrics,save,route_comparison


def main():
    folder=Path((ROOT/'results_v2/current_run.txt').read_text().strip())
    manifest=json.loads((folder/'run_manifest.json').read_text());assert manifest['status']=='calculated'
    reports=json.loads((folder/'mip_reports.json').read_text());methods=pd.read_csv(folder/'method_comparison.csv')
    records=[]
    for n in (20,30):
        attempts=[p.parent for p in (folder/'extended_mip_attempts').glob(f'{n}*/attempt_manifest.json')]
        if not attempts:continue
        feasible=[p for p in attempts if (p/'result.json').exists()]
        if feasible:
            winner=max(feasible,key=lambda p:json.loads((p/'result.json').read_text())['completed_trips'])
            result=json.loads((winner/'result.json').read_text());cfg=json.loads((winner/'config.json').read_text())
            inst=EventInstance(pd.read_csv(folder/'towns_main.csv').head(n),cfg);export(inst,result,folder/f'scale/{n}/mip')
            existing=json.loads((folder/f'scale/{n}/best/result.json').read_text())
            def rank(r):return (r['completed_trips'],-sum(b['spend_rub'] for b in r['budget']))
            if rank(result)>rank(existing):
                export(inst,result,folder/f'scale/{n}/best')
                selection=json.loads((folder/'best_plan_selection.json').read_text())
                for entry in selection:
                    if entry['instance']==n:entry.update(before_mip=entry['selected'],selected=f'scale/{n}/mip/result.json',completed_trips=result['completed_trips'])
                save(folder/'best_plan_selection.json',selection)
                if n==30:
                    export(inst,result,folder/'base');pd.DataFrame(route_comparison(inst,result)).to_csv(folder/'bfs_astar.csv',index=False)
                    annual=pd.read_csv(folder/'annual_comparison.csv');annual=annual[~((annual.instance==30)&(annual['mode']=='joint'))]
                    extra=[dict(instance=n,mode='joint',**b,completed_trips=result['annual_completed'][i]) for i,b in enumerate(result['budget'])]
                    pd.concat([annual,pd.DataFrame(extra)],ignore_index=True).to_csv(folder/'annual_comparison.csv',index=False)
            report=json.loads((winner/'solver_report.json').read_text())
            methods=methods[~((methods.instance==n)&(methods.method=='mip'))]
            row=metrics(inst,result,instance=n,method='mip',wall_seconds=report['wall_seconds'],gap=report['gap'],status=report['status'])
            methods=pd.concat([methods,pd.DataFrame([row])],ignore_index=True)
        else:
            winner=max(attempts,key=lambda p:(p/'attempt_manifest.json').stat().st_mtime)
            report=json.loads((winner/'solver_report.json').read_text())
        report['isolated_attempt_path']=str(winner.relative_to(folder))
        reports=[r for r in reports if r['nodes']!=n]+[report]
        records.append(dict(nodes=n,selected=str(winner.relative_to(folder)),attempts=[str(p.relative_to(folder)) for p in attempts],source_report_sha256=checksum(winner/'solver_report.json')))
    save(folder/'mip_reports.json',sorted(reports,key=lambda r:r['nodes']));methods.to_csv(folder/'method_comparison.csv',index=False)
    save(folder/'large_mip_revision.json',records);print(records)
    manifest=json.loads((folder/'run_manifest.json').read_text());manifest['additional_mip_pending']=False;save(folder/'run_manifest.json',manifest)

if __name__=='__main__':main()
