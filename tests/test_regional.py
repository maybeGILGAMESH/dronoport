from copy import deepcopy
from test_event_cpsat import pair
from droneport.event_model import EventInstance
from droneport.event_validation import validate
from droneport.event_cpsat import solve_isolated
from droneport.evolution import Chromosomes

def regional_pair():
    old,p=pair();towns=old.towns.copy();towns['region_code']=[50,67]
    cfg=deepcopy(old.cfg);cfg['regional_coverage']=dict(regions=['50','67'],deadline_year=3,min_flights=1)
    return EventInstance(towns,cfg),p

def test_idle_regional_ports_do_not_satisfy_service():
    inst,p=regional_pair();p['aircraft']=[]
    assert inst.evaluate(p) is None
    old=EventInstance(inst.towns,{k:v for k,v in inst.cfg.items() if k!='regional_coverage'})
    idle=old.evaluate(p);check=validate(inst.towns,idle,inst.cfg)
    assert {e['code'] for e in check['errors']}=={'regional_service'}

def test_cpsat_enforces_regional_service_and_failure_can_interrupt_it():
    inst,p=regional_pair();r,report=solve_isolated(inst,p,seconds=10)
    assert r is not None,report
    assert validate(inst.towns,r,inst.cfg)['valid']
    assert any(f['year']==3 for f in r['flights'])
    failed,report=solve_isolated(inst,p,scenario={'failed':0},seconds=5)
    assert failed is not None and not failed['flights'],report
    assert validate(inst.towns,failed,inst.cfg)['valid']

def test_regional_port_constraint_and_chromosome_repair():
    inst,p=regional_pair();p['open_years'][1]=0
    result,report=solve_isolated(inst,p,seconds=1)
    assert result is None and report['status']=='INFEASIBLE_REGIONAL_PORTS'
    codec=Chromosomes(inst);repaired=codec.decode(codec.encode(p))
    assert all(0<y<=3 for y in repaired['open_years'])

def test_three_region_chain_and_unreachable_region():
    import pandas as pd
    inst,_=regional_pair();cfg=deepcopy(inst.cfg);cfg['regional_coverage']['regions']=['50','67','69']
    towns=pd.DataFrame(dict(place_id=['A','B','C'],name_original=['A','B','C'],lat=[55.,55.,55.],lon=[0.,1.8,3.6],population=[1000,1000,1000],region_code=[50,69,67]))
    inst=EventInstance(towns,cfg);p=inst.empty();p['open_years']=[1,1,1];p['aircraft']=[dict(id='chain',year=1,home=0)]
    r,report=solve_isolated(inst,p,seconds=10)
    assert r is not None and validate(towns,r,cfg)['valid'],report
    for node in towns.place_id:assert any(f['year']==3 and node in (f['origin_id'],f['destination_id']) for f in r['flights'])
    towns.loc[2,'lon']=50.;isolated=EventInstance(towns,cfg)
    r,report=solve_isolated(isolated,p,seconds=5)
    assert r is None and report['status']=='INFEASIBLE',report
