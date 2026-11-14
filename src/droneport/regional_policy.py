"""Optional region coverage policy; commissioning and baseline service are distinct."""
def groups(instance):
    policy=instance.cfg.get('regional_coverage',{})
    return {str(r):[i for i,v in enumerate(instance.towns.region_code) if str(int(v))==str(r)]
            for r in policy.get('regions',[])}


def ports_ok(instance,plan):
    deadline=instance.cfg.get('regional_coverage',{}).get('deadline_year',3)
    return all(any(0<plan['open_years'][i]<=deadline for i in nodes) for nodes in groups(instance).values())


def service_applies(cfg,scenario):
    p=cfg.get('regional_coverage',{})
    return bool(p.get('min_flights',0)) and scenario.get('failed') is None and scenario.get('max_range') is None and scenario.get('factor',1.)==1.


def service_ok(instance,flights,scenario):
    if not service_applies(instance.cfg,scenario):return True
    p=instance.cfg['regional_coverage'];year=p.get('deadline_year',3)
    for nodes in groups(instance).values():
        ids={instance.ids[i] for i in nodes}
        if sum(f['year']==year and (f['origin_id'] in ids or f['destination_id'] in ids) for f in flights)<p['min_flights']:return False
    return True
