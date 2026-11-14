"""Extract a modest local OSM basemap; no public tile downloads."""
from pathlib import Path
import sys,json,time,hashlib,gzip,os,resource
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import osmium
from shapely.geometry import LineString,Polygon,box
from droneport.ingest import ROOT,checksum

pbf=ROOT/'central-fed-district-261103.osm.pbf';out=ROOT/'data/cartography';out.mkdir(exist_ok=True)
target=out/'basemap.json.gz'
if target.exists():
    print('Existing basemap preserved:',target);sys.exit(0)
resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3))
clip=box(30.4,53.25,40.4,59.0)
roads={'motorway','trunk','primary','secondary','tertiary','unclassified','residential','motorway_link','trunk_link','primary_link','secondary_link','tertiary_link'}
cache=ROOT/'.cache/osm_cartography_locations';start=time.monotonic()
if cache.exists():cache.unlink()
features=[];places=[];seen=0
tags=[('highway',r) for r in roads]+[('waterway',r) for r in ('river','canal','stream')]+[('natural','water'),('railway','rail'),('place','city'),('place','town'),('place','village')]
processor=osmium.FileProcessor(str(pbf)).with_locations('sparse_file_array,'+str(cache)).with_filter(osmium.filter.TagFilter(*tags))
for obj in processor:
    seen+=1
    if seen%100000==0:print('Tagged objects',seen,'features',len(features),'seconds',round(time.monotonic()-start),flush=True)
    if obj.is_node():
        if obj.tags.get('place') in ('city','town','village') and obj.location.valid():
            x,y=obj.location.lon,obj.location.lat
            if 30.4<=x<=40.4 and 53.25<=y<=59.0:
                places.append([round(x,6),round(y,6),obj.tags.get('name:ru',obj.tags.get('name','')),obj.tags.get('place'),obj.id])
        continue
    if not obj.is_way():continue
    highway=obj.tags.get('highway');water=obj.tags.get('waterway');natural=obj.tags.get('natural');rail=obj.tags.get('railway')
    if highway in roads:kind='road';subtype=highway
    elif water in ('river','canal','stream'):kind='waterline';subtype=water
    elif natural=='water' and obj.is_closed():kind='water';subtype=obj.tags.get('water','water')
    elif rail=='rail':kind='rail';subtype='rail'
    else:continue
    coords=[(n.lon,n.lat) for n in obj.nodes if n.location.valid()]
    if len(coords)<2:continue
    xs,ys=zip(*coords)
    if max(xs)<30.4 or min(xs)>40.4 or max(ys)<53.25 or min(ys)>59.0:continue
    try:
        g=Polygon(coords) if kind=='water' and len(coords)>=4 else LineString(coords)
        if not g.is_valid:g=g.buffer(0) if kind=='water' else g
        if g.is_empty:continue
        g=g.intersection(clip).simplify(.00006,preserve_topology=True)
        pieces=list(g.geoms) if hasattr(g,'geoms') else [g]
        for part in pieces:
            if part.geom_type not in ('LineString','Polygon'):continue
            co=list(part.exterior.coords) if part.geom_type=='Polygon' else list(part.coords)
            features.append([kind,subtype,[[round(x,6),round(y,6)] for x,y in co],obj.id])
    except (ValueError,RuntimeError):continue
with gzip.open(target,'wt',encoding='utf-8',compresslevel=6) as f:json.dump(dict(bounds=[30.4,53.25,40.4,59.0],features=features,places=places),f,ensure_ascii=False,separators=(',',':'))
meta=dict(source=pbf.name,source_sha256=checksum(pbf),source_date='2026-11-03',features=len(features),places=len(places),seconds=time.monotonic()-start,max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,bounds=[30.4,53.25,40.4,59.0],output_sha256=checksum(target),attribution='© OpenStreetMap contributors, ODbL 1.0',limitations=['Selective cartography: roads, rail, water lines and closed water ways, settlement labels','Not the full standard OSM Carto style; water relations and buildings are not rendered','Network segments are modelled flights, not roads or authorized aviation routes'])
(out/'provenance.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2))
del processor
if cache.exists():cache.unlink()
print(json.dumps(meta,ensure_ascii=False),flush=True)
