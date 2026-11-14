from copy import deepcopy
import numpy as np
import pytest
from test_event_cpsat import pair
from droneport.evolution import Chromosomes,canonical_warm,investment_key
from droneport.event_validation import validate


def test_chromosome_roundtrip_preserves_schedule():
    inst,p=pair();r=inst.evaluate(p);genes,normalized=canonical_warm(inst,r)
    assert normalized['completed_trips']==r['completed_trips']
    assert investment_key(normalized['plan'])==investment_key(p)
    assert validate(inst.towns,normalized,inst.cfg)['valid']


def test_crossover_and_repair_do_not_spend_future_tranches():
    inst,p=pair();codec=Chromosomes(inst);rng=np.random.default_rng(17);g=codec.encode(p)
    for _ in range(200):
        child,_=codec.mutate(g,rng);g=codec.crossover(g,child,rng);plan=codec.decode(g)
        assert all(b['carry_rub']>=0 for b in inst.fixed_budget(plan))
        for a in plan['aircraft']:
            for y in range(a['year'],4):assert 0<plan['open_years'][a['homes'][str(y)]]<=y


def test_population_diversity_ignores_aircraft_names():
    _,p=pair();other=deepcopy(p);other['aircraft'][0]['id']='different'
    assert investment_key(p)==investment_key(other)


@pytest.mark.parametrize('method',['ga','sa'])
def test_search_retains_known_feasible_lower_bound(method):
    from droneport.evolution import search
    inst,p=pair();start=inst.evaluate(p)
    result,report=search(inst,start,method,17,seconds=30,max_evaluations=4)
    assert result['completed_trips']>=start['completed_trips']
    assert validate(inst.towns,result,inst.cfg)['valid']
    assert report['iterations']==4 and report['cp_deterministic_limit']==.2
