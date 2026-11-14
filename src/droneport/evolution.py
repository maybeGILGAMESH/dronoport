"""GA and annealing with identical chromosomes, repair and CP-SAT decoder."""
from copy import deepcopy
import math
import time
import hashlib
import json
import numpy as np
from .event_cpsat import solve_isolated
from .event_validation import validate


def investment_key(plan):
    assets=sorted((a['year'],tuple(int(a.get('homes',{}).get(str(y),a['home'])) for y in range(a['year'],4))) for a in plan['aircraft'])
    return hashlib.sha256(json.dumps([plan['open_years'],assets]).encode()).hexdigest()


class Chromosomes:
    def __init__(self,instance):
        self.instance=instance;self.n=instance.n
        self.slots=3*instance.cfg['yearly_tranche_rub']//instance.cfg['aircraft_capex_rub']

    def encode(self,plan):
        genes=list(plan['open_years'])+[0]*(4*self.slots)
        assert len(plan['aircraft'])<=self.slots
        for k,a in enumerate(plan['aircraft']):
            genes[self.n+4*k]=a['year']
            for y in (1,2,3):genes[self.n+4*k+y]=int(a.get('homes',{}).get(str(y),a['home']))
        return tuple(genes)

    def decode(self,genes):
        inst=self.instance;plan=inst.empty();plan['open_years']=[int(x) for x in genes[:self.n]]
        for k in range(self.slots):
            year=int(genes[self.n+4*k]);homes=[int(x) for x in genes[self.n+4*k+1:self.n+4*k+4]]
            if not year:continue
            a=dict(id=f'e{k}',year=year,home=homes[year-1],homes={str(y):homes[y-1] for y in range(year,4)})
            plan['aircraft'].append(a)
            for y in range(year,4):
                h=homes[y-1];plan['open_years'][h]=min(plan['open_years'][h] or y,y)
        from .regional_policy import groups
        regions=groups(inst);policy=inst.cfg.get('regional_coverage',{});deadline=policy.get('deadline_year',3)
        for region,nodes in regions.items():
            if not nodes:raise ValueError('Required region is absent from the fixed sample: '+region)
            if not any(0<plan['open_years'][i]<=deadline for i in nodes):
                preferred=policy.get('preferred_place_ids',{}).get(region)
                node=next((i for i in nodes if inst.ids[i]==preferred),max(nodes,key=lambda i:inst.towns.iloc[i].population))
                plan['open_years'][node]=deadline
        # Repair uses cumulative fixed costs, never borrows a future tranche.
        # Actual flight/ferry energy remains a hard constraint in the decoder.
        while any(b['carry_rub']<0 for b in inst.fixed_budget(plan)):
            used={int(h) for a in plan['aircraft'] for h in a['homes'].values()}
            protected={next(i for i in nodes if 0<plan['open_years'][i]<=deadline) for nodes in regions.values() if sum(0<plan['open_years'][i]<=deadline for i in nodes)==1}
            spare=[i for i,y in enumerate(plan['open_years']) if y and i not in used and i not in protected]
            if spare:plan['open_years'][max(spare,key=lambda i:(plan['open_years'][i],i))]=0
            elif plan['aircraft']:plan['aircraft'].remove(max(plan['aircraft'],key=lambda a:(a['year'],a['id'])))
            else:break
        return plan

    def mutate(self,genes,rng):
        g=list(genes);operator=int(rng.integers(5))
        if operator==0:g[int(rng.integers(self.n))]=int(rng.integers(4))
        elif operator==1:
            slot=int(rng.integers(self.slots));g[self.n+4*slot]=int(rng.integers(4))
        elif operator==2:
            slot=int(rng.integers(self.slots));year=int(rng.integers(1,4));g[self.n+4*slot+year]=int(rng.integers(self.n))
        elif operator==3:
            slot=int(rng.integers(self.slots));home=int(rng.integers(self.n));g[self.n+4*slot+1:self.n+4*slot+4]=[home]*3
        else:
            # Coordinated new purchase and base move, useful beyond one-gene steps.
            slot=int(rng.integers(self.slots));year=int(rng.integers(1,4));home=int(rng.integers(self.n))
            g[self.n+4*slot:self.n+4*slot+4]=[year,home,home,home]
        return tuple(g),operator

    def crossover(self,a,b,rng):
        genes=[int(a[i] if rng.random()<.5 else b[i]) for i in range(self.n)]
        for k in range(self.slots):
            parent=a if rng.random()<.5 else b;genes.extend(parent[self.n+4*k:self.n+4*k+4])
        return tuple(genes)


def canonical_warm(instance,result):
    codec=Chromosomes(instance);genes=codec.encode(result['plan']);p=codec.decode(genes)
    assert len(p['aircraft'])==len(result['plan']['aircraft'])
    mapping={old['id']:new['id'] for old,new in zip(result['plan']['aircraft'],p['aircraft'])}
    out=deepcopy(result);out['plan']=p
    for name in ('flights','relocations'):
        for row in out.get(name,[]):row['aircraft_id']=mapping[row['aircraft_id']]
    out['actual_homes']={y:{mapping[k]:v for k,v in homes.items()} for y,homes in out.get('actual_homes',{}).items()}
    out['blocked_aircraft']={y:[mapping[k] for k in ids] for y,ids in out.get('blocked_aircraft',{}).items()}
    assert validate(instance.towns,out,instance.cfg)['valid']
    return genes,out


class Decoder:
    def __init__(self,instance,start,cp_seconds=10,deterministic_limit=.2):
        self.instance=instance;self.codec=Chromosomes(instance);self.cp_seconds=cp_seconds
        self.deterministic_limit=deterministic_limit;self.calls=0;self.hits=0;self.records=[]
        genes,warm=canonical_warm(instance,start);self.start_genes=genes;self.start=warm
        self.cache={investment_key(warm['plan']):warm}

    def evaluate(self,genes):
        plan=self.codec.decode(genes);key=investment_key(plan)
        if key in self.cache:self.hits+=1;return self.cache[key]
        begin=time.perf_counter();warm=self.instance.evaluate(plan)
        result,report=solve_isolated(self.instance,plan,warm,seconds=self.cp_seconds,mode='pool',
                                    pool_seeds=3,seed=0,deterministic_limit=self.deterministic_limit,memory_gib=20)
        self.calls+=1;self.records.append(dict(call=self.calls,key=key,wall_seconds=time.perf_counter()-begin,
            status=report['status'],completed_trips=result['completed_trips'] if result else None,
            solver_incumbent=report.get('solver_incumbent'),upper_bound_pool_only=report.get('upper_bound'),
            peak_rss_mib=report.get('peak_rss_mib'),cp_improvement=report.get('improvement')))
        if result is not None:assert validate(self.instance.towns,result,self.instance.cfg)['valid']
        if len(self.cache)>=64:self.cache={investment_key(self.start['plan']):self.start}
        self.cache[key]=result
        if len(self.instance.cache)>64:self.instance.cache.clear()
        return result


def search(instance,start,method,seed,seconds=600,population_size=12,max_evaluations=None):
    if method not in ('ga','sa'):raise ValueError(method)
    rng=np.random.default_rng(seed);decoder=Decoder(instance,start);codec=decoder.codec
    current=decoder.start_genes;current_result=decoder.start;best=decoder.start;best_genes=current
    history=[];population=[(current,current_result)];begin=time.perf_counter();iteration=0
    rank=lambda r:(r['completed_trips'],-sum(b['spend_rub'] for b in r['budget'])) if r is not None else (-1,-float('inf'))
    while time.perf_counter()-begin<seconds:
        if max_evaluations is not None and iteration>=max_evaluations:break
        iteration+=1
        if method=='sa':candidate,operator=codec.mutate(current,rng)
        elif len(population)<population_size:
            candidate=best_genes
            for _ in range(int(rng.integers(1,4))):candidate,operator=codec.mutate(candidate,rng)
        else:
            def tournament():return max((population[int(rng.integers(len(population)))] for _ in range(3)),key=lambda p:rank(p[1]))[0]
            candidate=codec.crossover(tournament(),tournament(),rng)
            candidate,operator=codec.mutate(candidate,rng)
            if rng.random()<.2:candidate,operator=codec.mutate(candidate,rng)
        result=decoder.evaluate(candidate);accepted=False
        if result is not None:
            if rank(result)>rank(best):best=result;best_genes=candidate
            if method=='sa':
                delta=result['completed_trips']-current_result['completed_trips']
                temp=max(1.,.05*max(1,decoder.start['completed_trips'])*(1-(time.perf_counter()-begin)/seconds))
                accepted=rank(result)>=rank(current_result) or (delta<0 and rng.random()<math.exp(max(-700,delta/temp)))
                if accepted:current=candidate;current_result=result
            else:
                signature=investment_key(result['plan']);existing={investment_key(r['plan']) for _,r in population}
                if signature not in existing:
                    population.append((candidate,result));population.sort(key=lambda p:rank(p[1]),reverse=True)
                    if len(population)>population_size:
                        # Preserve two elites, retain some diverse weaker candidates.
                        drop=len(population)-1 if rng.random()<.8 else int(rng.integers(2,len(population)))
                        removed=population.pop(drop);accepted=removed[0]!=candidate
                    else:accepted=True
        history.append(dict(iteration=iteration,elapsed=time.perf_counter()-begin,operator=operator,accepted=accepted,
            candidate=result['completed_trips'] if result else None,best=best['completed_trips'],best_cost=sum(b['spend_rub'] for b in best['budget']),
            population=len(population),decoder_calls=decoder.calls,cache_hits=decoder.hits))
    return best,dict(method=method,seed=seed,time_limit_seconds=seconds,wall_seconds=time.perf_counter()-begin,
        iterations=iteration,decoder_calls=decoder.calls,cache_hits=decoder.hits,population_size=population_size if method=='ga' else 1,
        start_trips=decoder.start['completed_trips'],best_trips=best['completed_trips'],cp_seconds=decoder.cp_seconds,
        cp_deterministic_limit=decoder.deterministic_limit,best_genome=list(best_genes),history=history,decoder_records=decoder.records)
