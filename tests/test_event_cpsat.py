import json
from pathlib import Path
import pandas as pd
import yaml
import pytest
from droneport.event_model import EventInstance
from droneport.event_cpsat import solve_isolated
from droneport.event_validation import validate

ROOT=Path(__file__).resolve().parents[1]

def pair():
    cfg=yaml.safe_load((ROOT/'config/model.yaml').read_text());cfg.update(yaml.safe_load((ROOT/'config/expanded.yaml').read_text()))
    towns=pd.read_csv(ROOT/'data/processed/towns_main.csv')
    towns=towns[towns.name_original.isin(['Люберцы','Котельники'])].reset_index(drop=True)
    inst=EventInstance(towns,cfg);plan=inst.empty();plan['open_years']=[1,1]
    plan['aircraft']=[dict(id='cp_test',year=1,home=0)]
    return inst,plan

def test_full_cpsat_known_pair_and_fixed_assets():
    inst,plan=pair();result,report=solve_isolated(inst,plan,inst.evaluate(plan),seconds=10)
    assert result is not None,report
    assert result['plan']==plan
    assert result['completed_trips']==158400
    assert report['status']=='OPTIMAL' and report['upper_bound']==158400
    assert validate(inst.towns,result,inst.cfg)['valid']

def test_cpsat_failed_base_blocks_aircraft_but_keeps_fixed_costs():
    inst,plan=pair();result,report=solve_isolated(inst,plan,scenario={'failed':0},seconds=5)
    assert result is not None,report
    assert result['completed_trips']==0 and not result['flights']
    assert result['budget'][0]['aircraft_capex_rub']==inst.cfg['aircraft_capex_rub']
    assert validate(inst.towns,result,inst.cfg)['valid']

def test_pool_cpsat_preserves_feasible_start_and_budget():
    inst,plan=pair();warm=inst.evaluate(plan)
    result,report=solve_isolated(inst,plan,warm,seconds=3,mode='pool')
    assert result is not None,report
    assert result['completed_trips']>=warm['completed_trips']
    assert result['plan']==warm['plan'] and validate(inst.towns,result,inst.cfg)['valid']
    assert 'pool only' in report['scope']


@pytest.mark.parametrize('asymmetric',[False,True])
def test_cpsat_finds_required_multileg_trip_and_empty_return(asymmetric):
    inst,_=pair();cfg=dict(inst.cfg)
    if asymmetric:cfg['demand']={**cfg['demand'],'alpha':.9,'beta':.1}
    towns=pd.DataFrame(dict(place_id=['A','B','C'],name_original=['A','B','C'],
        lat=[55.,55.,55.],lon=[0.,1.8,3.6],population=[10000,1,1000 if asymmetric else 10000]))
    inst=EventInstance(towns,cfg);p=inst.empty();p['open_years']=[1,1,1];p['aircraft']=[dict(id='chain',year=1,home=0)]
    assert inst.distance[0,2]>cfg['range_km'] and inst.distance[0,1]<cfg['range_km']
    result,report=solve_isolated(inst,p,seconds=10)
    assert result is not None,report
    assert result['completed_trips']==int(inst.demand.sum()*cfg['operating_days'])
    assert any(t['transfers']>0 for t in result['itineraries'])
    if asymmetric:assert any(f['empty'] for f in result['flights'])
    assert validate(inst.towns,result,cfg)['valid']
