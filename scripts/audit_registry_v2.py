"""Add OSM place polygons without changing the frozen computational samples."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import json
import osmium
import pandas as pd
from shapely.geometry import shape, Point, Polygon, mapping
from shapely.ops import polygonize, unary_union
from shapely.geometry import LineString
from droneport.ingest import ROOT, normalize, match_population


def main():
    out=ROOT/'data/processed_v2'; out.mkdir(exist_ok=True)
    source=ROOT/'data/processed'; nodes=pd.read_parquet(source/'osm_all_places.parquet')
    nodes['region_code']=nodes.region_code.astype(str)
    boundaries=json.loads((source/'region_boundaries.geojson').read_text())
    regions={str(f['properties']['region_code']):shape(f['geometry']) for f in boundaries['features']}
    pbf=str(next(ROOT.glob('*.osm.pbf'))); kinds={'city','town','village','hamlet','isolated_dwelling'}
    relations={}; needed=set(); ways={}; records=[]; log=[]
    for r in osmium.FileProcessor(pbf,entities=osmium.osm.RELATION).with_filter(osmium.filter.KeyFilter('place')):
        tags=dict(r.tags)
        if tags.get('place') not in kinds: continue
        members=[(m.ref,m.role) for m in r.members if m.type=='w']
        relations[r.id]=(tags,members); needed.update(m[0] for m in members)
    for w in osmium.FileProcessor(pbf,entities=osmium.osm.WAY).with_filter(osmium.filter.KeyFilter('place')):
        tags=dict(w.tags)
        if tags.get('place') in kinds:
            ways[w.id]=[n.ref for n in w.nodes]; records.append(('w',w.id,tags))
    if needed:
        for w in osmium.FileProcessor(pbf,entities=osmium.osm.WAY).with_filter(osmium.filter.IdFilter(needed)):
            ways[w.id]=[n.ref for n in w.nodes]
    nodeids={n for refs in ways.values() for n in refs}
    coords={n.id:(n.location.lon,n.location.lat) for n in osmium.FileProcessor(pbf,entities=osmium.osm.NODE).with_filter(osmium.filter.IdFilter(nodeids)) if n.location.valid()}
    records += [('r',rid,tags) for rid,(tags,_) in relations.items()]
    added=[]; features=[]; accepted=[]
    for kind,oid,tags in records:
        pid=f'osm_{kind}{oid}'; name=tags.get('name:ru',tags.get('name',''))
        if not name: continue
        try:
            if kind=='w': geom=Polygon([coords[n] for n in ways[oid]])
            else:
                members=relations[oid][1]
                outer=list(polygonize([LineString([coords[n] for n in ways[w]]) for w,role in members if role in ('','outer')]))
                inner=list(polygonize([LineString([coords[n] for n in ways[w]]) for w,role in members if role=='inner']))
                geom=unary_union(outer).difference(unary_union(inner))
            if geom.is_empty or not geom.is_valid:
                log.append(dict(place_id=pid,action='invalid_geometry')); continue
        except (KeyError,ValueError):
            log.append(dict(place_id=pid,action='incomplete_geometry')); continue
        point=geom.representative_point()
        if regions['77'].covers(point): continue
        codes=[code for code,g in regions.items() if code!='77' and g.covers(point)]
        if len(codes)!=1: continue
        code=codes[0]; normalized=normalize(name)
        candidates=nodes[(nodes.region_code==code)&(nodes.name_normalized==normalized)]
        duplicates=[r.place_id for r in candidates.itertuples() if geom.covers(Point(r.lon,r.lat))]
        # Same-name nested polygons are not automatically duplicates: shared OSM
        # relation member identity or a unique enclosed node is required.
        if len(duplicates)==1:
            log.append(dict(place_id=pid,action='polygon_of_existing_node',canonical_id=duplicates[0],rule='same_region_name_and_unique_contained_node')); continue
        if len(duplicates)>1:
            log.append(dict(place_id=pid,action='ambiguous_contained_nodes',canonical_id=';'.join(duplicates))); continue
        if kind=='w' and any(oid in [w for w,_ in members] for _,members in relations.values()):
            log.append(dict(place_id=pid,action='relation_member_polygon')); continue
        row=dict(place_id=pid,gar_id='',name_original=name,name_normalized=normalized,region_code=code,municipality='',settlement_type=tags['place'],
            lat=point.y,lon=point.x,coordinate_source_id='osm_place_polygon_representative_point',osm_population_unverified=tags.get('population',''),
            osm_population_date=tags.get('population:date',''),osm_wikidata=tags.get('wikidata',''))
        added.append(row); log.append(dict(place_id=pid,action='added_polygon'))
        features.append(dict(type='Feature',properties={'place_id':pid,'name':name},geometry=mapping(geom)))
    full=pd.concat([nodes,pd.DataFrame(added)],ignore_index=True)
    eligible=full[full.name_normalized.str[0].isin(list('ЖЗИКЛ'))].copy()
    population=pd.read_csv(source/'rosstat_settlements.csv',dtype={'region_code':str})
    matched,crosswalk=match_population(eligible,population)
    matched.to_csv(out/'towns_all.csv',index=False); pd.DataFrame(log).to_csv(out/'polygon_audit.csv',index=False)
    crosswalk.to_csv(out/'population_crosswalk.csv',index=False)
    (out/'added_polygons.geojson').write_text(json.dumps({'type':'FeatureCollection','features':features},ensure_ascii=False))
    official=population[population.name_normalized.str[0].isin(list('ЖЗИКЛ'))].copy()
    counts=eligible.groupby(['region_code','name_normalized']).size().to_dict()
    official['osm_name_candidates']=[counts.get((r.region_code,r.name_normalized),0) for r in official.itertuples()]
    official.to_csv(out/'official_table_crosscheck.csv',index=False)
    audit=dict(frozen_samples=True,osm_nodes=len(nodes),added_polygons=len(added),eligible=len(eligible),official_rows_checked=len(official),
        full_registry_verified=False,official_source_scope='Rosstat table 5: urban settlements and rural settlements of at least 3000 residents; not full registry',
        registry_download='https://fias.nalog.ru/Frontend',required_regions=['50','67','69'],
        missing_population_policy='preserve_null',ambiguous_geometry=sum(r['action']=='ambiguous_contained_nodes' for r in log))
    (out/'audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)); print(json.dumps(audit,ensure_ascii=False),flush=True)

if __name__=='__main__': main()
