from copy import deepcopy
import json
from pathlib import Path
import pandas as pd
import pytest
import yaml
from droneport.event_model import EventInstance,greedy,recover
from droneport.event_mip import solve
from droneport.event_validation import validate

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def example():
    cfg=yaml.safe_load((ROOT/'config/model.yaml').read_text());cfg.update(yaml.safe_load((ROOT/'config/expanded.yaml').read_text()))
    towns=pd.read_csv(ROOT/'data/processed/towns_main.csv').head(8)
    inst=EventInstance(towns,cfg); plan,_=greedy(inst); result=inst.evaluate(plan)
    return inst,result

def test_free_rotations_and_transfers(example):
    inst,result=example
    assert validate(inst.towns,result,inst.cfg)['valid']
    assert any(t['transfers']>0 for t in result['itineraries'])
    assert any(len({f['destination_id'] for f in result['flights'] if f['aircraft_id']==a['id']})>2 for a in result['plan']['aircraft'])

def test_sequential_extension_preserves_executed_history(example):
    from droneport.event_warmstart import extend_year
    inst,previous=example
    result=extend_year(inst,previous,3)
    assert validate(inst.towns,result,inst.cfg)['valid']
    for field in ('flights','itineraries'):
        assert [r for r in result[field] if r['year']<3]==[r for r in previous[field] if r['year']<3]
    assert result['annual_completed'][2]>=previous['annual_completed'][2]
    assert result['budget'][:2]==previous['budget'][:2]

@pytest.mark.parametrize('mutation,code',[
    ('capacity','capacity'),('charging','charge_duration'),('duplicate','duplicate_trip'),
    ('budget','budget_cost'),('closed','closed_port'),('teleport','initial_location'),('time','working_day')])
def test_invalid_plans_rejected(example,mutation,code):
    inst,original=example; r=deepcopy(original)
    if mutation=='capacity': r['flights'][0]['passengers']=11
    elif mutation=='charging': r['flights'][0]['charge_end_min']=r['flights'][0]['arrival_min']
    elif mutation=='duplicate': r['itineraries'].append(deepcopy(r['itineraries'][0]))
    elif mutation=='budget': r['budget'][0]['spend_rub']-=1
    elif mutation=='closed': r['plan']['open_years'][inst.index[r['flights'][0]['origin_id']]]=0
    elif mutation=='teleport':
        aid=r['flights'][0]['aircraft_id']; asset=next(a for a in r['plan']['aircraft'] if a['id']==aid); asset['home']=(asset['home']+1)%inst.n
    else: r['flights'][0]['departure_min']=0
    check=validate(inst.towns,r,inst.cfg)
    assert not check['valid'] and code in {e['code'] for e in check['errors']}

def test_known_pair_mip(example):
    inst,_=example; towns=pd.read_csv(ROOT/'data/processed/towns_main.csv')
    pair=towns[towns.name_original.isin(['Люберцы','Котельники'])].reset_index(drop=True)
    ii=EventInstance(pair,inst.cfg); result,report=solve(ii,10)
    # Two ports, 16 movements each per day -> at most 16 flights * 10 places.
    assert result['completed_trips']==158400
    assert report['upper_bound']==158400
    assert validate(ii.towns,result,ii.cfg)['valid']

def test_resource_failure_does_not_publish_zero_bound(example,monkeypatch):
    from types import SimpleNamespace
    from droneport.event_model import SparseMILP
    inst,_=example;towns=pd.read_csv(ROOT/'data/processed/towns_main.csv')
    pair=towns[towns.name_original.isin(['Люберцы','Котельники'])].reset_index(drop=True);ii=EventInstance(pair,inst.cfg)
    original=SparseMILP.solve
    monkeypatch.setattr(SparseMILP,'solve',lambda self,*args,**kwargs:SimpleNamespace(x=None,message='Memory limit reached',mip_dual_bound=0,mip_gap=float('inf')) if any(self.integer) else original(self,*args,**kwargs))
    result,report=solve(ii,10)
    assert result is None and report['upper_bound']==158400 and report['gap'] is None

def test_resource_failure_retains_valid_provided_timetable(example,monkeypatch):
    from types import SimpleNamespace
    from droneport.event_model import SparseMILP
    inst,warm=example;original=SparseMILP.solve
    monkeypatch.setattr(SparseMILP,'solve',lambda self,*args,**kwargs:SimpleNamespace(x=None,message='Memory limit reached',mip_dual_bound=0,mip_gap=float('inf')) if any(self.integer) else original(self,*args,**kwargs))
    result,report=solve(inst,10,warm_result=warm)
    assert result==warm and report['incumbent']==warm['completed_trips']
    assert report['solver_incumbent'] is None and 'retained' in report['solution_origin']
    assert report['upper_bound']>=report['incumbent'] and report['status']=='Memory limit reached'

def test_inferior_solver_incumbent_does_not_replace_better_start(example,monkeypatch):
    from types import SimpleNamespace
    import numpy as np
    from droneport.event_model import SparseMILP
    inst,warm=example;original=SparseMILP.solve
    monkeypatch.setattr(SparseMILP,'solve',lambda self,*args,**kwargs:SimpleNamespace(x=np.zeros(len(self.c)),message='Time limit reached',status=1,mip_dual_bound=-10**9,mip_gap=float('inf')) if any(self.integer) else original(self,*args,**kwargs))
    result,report=solve(inst,10,warm_result=warm)
    assert result==warm and report['solver_incumbent']==0
    assert report['incumbent']==warm['completed_trips'] and 'dominates' in report['solution_origin']

def test_relocation_is_real_and_costed(example):
    inst,_=example; towns=pd.read_csv(ROOT/'data/processed/towns_main.csv')
    towns=towns[towns.name_original.isin(['Люберцы','Котельники','Лыткарино'])].reset_index(drop=True)
    ii=EventInstance(towns,inst.cfg); p=ii.empty();p['open_years']=[1]*3
    p['aircraft']=[dict(id='a',year=1,home=0,homes={'2':1,'3':1})]
    r=ii.evaluate(p); assert r is not None
    assert len(r['relocations'])==1 and r['budget'][1]['relocation_energy_rub']>0
    assert validate(ii.towns,r,ii.cfg)['valid']
    broken=deepcopy(r); broken['relocations']=[]
    assert 'missing_relocation' in {e['code'] for e in validate(ii.towns,broken,ii.cfg)['errors']}
    failed=ii.evaluate(p,failed=0)
    assert not failed['flights']
    assert validate(ii.towns,failed,ii.cfg)['valid']

def test_isolated_demand_is_retained(example):
    inst,_=example; p=inst.empty();r=inst.evaluate(p)
    assert inst.demand.sum()>0 and r['completed_trips']==0
    assert validate(inst.towns,r,inst.cfg)['valid']

def test_failed_future_base_keeps_healthy_aircraft_available(example):
    inst,_=example; towns=pd.read_csv(ROOT/'data/processed/towns_main.csv')
    towns=towns[towns.name_original.isin(['Люберцы','Котельники','Лыткарино'])].reset_index(drop=True)
    ii=EventInstance(towns,inst.cfg);p=ii.empty();p['open_years']=[1]*3
    p['aircraft']=[dict(id='a',year=1,home=0,homes={'2':1,'3':1})]
    r=ii.evaluate(p,failed=1)
    assert r is not None and r['completed_trips']>0
    assert all(r['actual_homes'][str(y)]['a']==0 for y in (1,2,3))
    assert not any(r['blocked_aircraft'].values()) and not r['relocations']
    assert validate(ii.towns,r,ii.cfg)['valid']
    broken=deepcopy(r);broken['actual_homes']['2']['a']=2
    assert 'missing_relocation' in {e['code'] for e in validate(ii.towns,broken,ii.cfg)['errors']}

@pytest.mark.parametrize('mutation,code',[('range','range'),('double_use','overlap'),('charger','charger_capacity'),('future','future_tranche'),('transfer','transfer_time')])
def test_v2_resource_counterexamples(example,mutation,code):
    inst,original=example;r=deepcopy(original);cfg=deepcopy(inst.cfg)
    if mutation=='range':r['scenario']['max_range']=1
    elif mutation=='double_use':
        f=deepcopy(r['flights'][0]);f['flight_id']='duplicate_resource';r['flights'].append(f)
    elif mutation=='charger':
        for k in range(2):
            f=deepcopy(r['flights'][0]);f['flight_id']=f'charger_conflict_{k}';f['aircraft_id']=f'additional_{k}'
            r['plan']['aircraft'].append(dict(id=f['aircraft_id'],year=1,home=inst.index[f['origin_id']]))
            r['flights'].append(f)
    elif mutation=='future':cfg['yearly_tranche_rub']=1
    else:
        trip=next(t for t in r['itineraries'] if t['transfers']>0);ids=json.loads(trip['flight_ids']);fs={f['flight_id']:f for f in r['flights']}
        fs[ids[1]]['departure_min']=fs[ids[0]]['arrival_min']
    assert code in {e['code'] for e in validate(inst.towns,r,cfg)['errors']}

def test_quality_does_not_modify_observations(example):
    inst,_=example;c=deepcopy(inst.cfg);c['population_cap_quantile']=.95
    other=EventInstance(inst.towns,c)
    assert other.towns.population.equals(inst.towns.population)
    assert (other.demand<=inst.demand).all()

def test_network_identity_ignores_aircraft_labels_and_order(example):
    from droneport.pipeline_v2 import network_signature
    _,r=example;p=deepcopy(r['plan']);q=deepcopy(p)
    q['aircraft'].reverse()
    for k,a in enumerate(q['aircraft']):a['id']=f'renamed_{k}'
    assert network_signature(p)==network_signature(q)
    q['aircraft'][0]['year']=1 if q['aircraft'][0]['year']!=1 else 2
    assert network_signature(p)!=network_signature(q)

def test_recourse_never_discards_valid_surviving_trips(example):
    inst,base=example
    for failed,y in enumerate(base['plan']['open_years']):
        if not y:continue
        retained=recover(inst,base['plan'],failed=failed,mode='retain')
        best=recover(inst,base['plan'],failed=failed)
        assert best['completed_trips']>=retained['completed_trips']
        assert validate(inst.towns,retained,inst.cfg)['valid']
        assert validate(inst.towns,best,inst.cfg)['valid']

def test_empty_return_is_costed(example):
    inst,_=example; towns=pd.read_csv(ROOT/'data/processed/towns_main.csv')
    pair=towns[towns.name_original.isin(['Люберцы','Котельники'])].reset_index(drop=True)
    pair['population']=[1000000,1]; c=deepcopy(inst.cfg)
    probe=EventInstance(pair,c);d=probe.distance[0,1]
    c['demand']['K']=1.1*(1+d/c['demand']['distance_scale_km'])**c['demand']['gamma']/1000000**c['demand']['alpha']
    ii=EventInstance(pair,c);p=ii.empty();p['open_years']=[1,1];p['aircraft']=[dict(id='empty_return',year=1,home=0)]
    r=ii.evaluate(p)
    assert r['completed_trips']==990
    assert any(f['empty'] and f['energy_cost_rub']>0 for f in r['flights'])
    assert validate(ii.towns,r,c)['valid']

def test_sequential_mip_freezes_past_operations(example):
    inst,_=example;towns=pd.read_csv(ROOT/'data/processed/towns_main.csv')
    pair=towns[towns.name_original.isin(['Люберцы','Котельники'])].reset_index(drop=True)
    ii=EventInstance(pair,inst.cfg);p,_=greedy(ii);previous=None
    def historical(result,year):
        return sorted((f['year'],f['origin_id'],f['destination_id'],f['departure_min'],f['arrival_min']) for f in result['flights'] if f['year']<year)
    for year in (1,2,3):
        r,report=solve(ii,10,objective_years=[year],fixed=previous,warm_result=previous or ii.evaluate(p))
        assert r is not None and validate(ii.towns,r,ii.cfg)['valid']
        if previous:assert historical(r,year)==historical(previous,year)
        previous=r
