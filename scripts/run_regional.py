"""Preserve the published study, enumerate regional tours, refine fixed assets."""
import os
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ[k]='1'
from pathlib import Path
import sys,json,shutil,time,argparse
from datetime import datetime
from copy import deepcopy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import pandas as pd
from droneport.ingest import ROOT,checksum
from droneport.event_model import EventInstance
from droneport.event_cpsat import solve_isolated
from droneport.regional_search import make_tour,region_metrics
from droneport.pipeline_v2 import export,save,metrics,stress

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--baseline');args=parser.parse_args()
    parent=Path(args.baseline or (ROOT/'results_v2/current_run.txt').read_text().strip()).resolve()
    folder=ROOT/'runs'/(datetime.now().strftime('%Y%m%d_%H%M%S')+'_regional')
    shutil.copytree(parent,folder,ignore=shutil.ignore_patterns('__pycache__','regional'))
    (ROOT/'.cache/regional_run.txt').write_text(str(folder))
    out=folder/'regional';out.mkdir()
    manifest=json.loads((folder/'run_manifest.json').read_text());manifest.update(run_id=folder.name,status='regional_in_progress',baseline_run=parent.name)
    save(folder/'run_manifest.json',manifest)
    for d in ('src','scripts','config','tests'):shutil.copytree(ROOT/d,out/'source_snapshot'/d,ignore=shutil.ignore_patterns('__pycache__'))
    source=folder/'cp_ga/final_best/result.json';base=json.loads(source.read_text())
    cfg=json.loads((source.parent/'config.json').read_text());cfg['regional_coverage']=dict(regions=['50','67','69'],deadline_year=3,min_flights=1)
    save(out/'config.json',cfg);towns=pd.read_csv(folder/'towns_main.csv');inst=EventInstance(towns,cfg)
    save(out/'preservation.json',dict(parent=str(parent),baseline_result_sha256=checksum(source),parent_report_sha256=checksum(parent/'report/report.pdf')))
    rows=[];candidates=[];start=time.perf_counter()
    for sm in towns.index[towns.region_code==67]:
        for tv in towns.index[towns.region_code==69]:
            if inst.distance[sm,tv]>cfg['range_km']:continue
            for a in base['plan']['aircraft']:
                for shift in (0,30,60):
                    result=make_tour(inst,base,[int(sm),int(tv)],a['id'],shift)
                    tag=f's{sm}_t{tv}_{a["id"]}_{shift}'
                    row=dict(candidate=tag,smolensk=int(sm),tver=int(tv),aircraft=a['id'],shift=shift,feasible=result is not None)
                    if result:
                        row.update(metrics(inst,result));candidates.append((result,tag));export(inst,result,out/'candidates'/tag)
                        print(tag,result['completed_trips'],flush=True)
                    rows.append(row)
    pd.DataFrame(rows).to_csv(out/'candidate_results.csv',index=False)
    if not candidates:raise RuntimeError('No feasible regional tour')
    rank=lambda pair:(pair[0]['completed_trips'],-sum(b['spend_rub'] for b in pair[0]['budget']))
    candidates.sort(key=rank,reverse=True);best=deepcopy(candidates[0][0]);export(inst,best,out/'constructive_best')
    seen=set();reports=[]
    for candidate,tag in candidates:
        sig=tuple(candidate['plan']['open_years'])
        if sig in seen:continue
        seen.add(sig)
        result,report=solve_isolated(inst,candidate['plan'],candidate,seconds=180,workers=8,memory_gib=20)
        report['candidate']=tag;reports.append(report);save(out/'cp_reports.json',reports)
        if result:
            export(inst,result,out/'cp'/tag)
            if rank((result,tag))>rank((best,'')):best=result
        print('CP',tag,report['status'],result['completed_trips'] if result else None,flush=True)
        if len(seen)>=3:break
    # Independent passenger allocation on the selected real flights.
    polished=deepcopy(best);trips=[]
    for y in (1,2,3):
        fs=[f for f in polished['flights'] if f['year']==y]
        for f in fs:f['passengers']=0;f['empty']=True
        ts,_=inst.allocate(fs,y);trips+=ts
    polished['itineraries']=trips;polished['annual_completed']=[sum(t['year']==y for t in trips)*cfg['operating_days'] for y in (1,2,3)]
    polished['completed_trips']=sum(polished['annual_completed'])
    if polished['completed_trips']>=best['completed_trips']:best=polished
    export(inst,best,out/'final_best');pd.DataFrame(region_metrics(inst,best)).to_csv(out/'region_service.csv',index=False)
    # Construction alone deliberately does not satisfy the flight requirement.
    idle=deepcopy(base);idle['plan']['open_years']=deepcopy(best['plan']['open_years'])
    relaxed=deepcopy(cfg);relaxed['regional_coverage']['min_flights']=0;other=EventInstance(towns,relaxed)
    energy=[sum(f['energy_cost_rub'] for f in idle['flights'] if f['year']==y)*cfg['operating_days'] for y in (1,2,3)]
    _,re,_,_=other.relocations(idle['plan']);idle['budget']=other.fixed_budget(idle['plan'],energy,re)
    export(other,idle,out/'construction_only')
    comparison=[metrics(inst,base,method='previous'),metrics(other,idle,method='construction_only'),metrics(inst,best,method='regional_service')]
    pd.DataFrame(comparison).to_csv(out/'comparison.csv',index=False)
    inst.cache[(inst.key(best['plan']),1.,None,None)]=deepcopy(best)
    scenarios=[]
    for name,result in stress(inst,best['plan']):
        export(inst,result,out/'scenarios'/name);scenarios.append(metrics(inst,result,scenario=name))
        print('Scenario',name,result['completed_trips'],flush=True)
    pd.DataFrame(scenarios).to_csv(out/'scenarios.csv',index=False)
    save(out/'manifest.json',dict(status='complete',scope='Fixed old investments plus two year-3 ports; closed-tour enumeration and CP-SAT for up to three distinct port sets. Not a global investment optimum.',wall_seconds=time.perf_counter()-start,candidates=len(rows),feasible=len(candidates),cp_attempts=len(reports),regional_coverage=cfg['regional_coverage'],baseline_result_sha256=checksum(source)))
    manifest['status']='calculated';save(folder/'run_manifest.json',manifest)
    print('DONE',folder,flush=True)

if __name__=='__main__':main()
