"""Read only three address-object XML members from the official 58 GB GAR ZIP.

HTTP Range fetches the central directory and selected members, not the full ZIP.
Keep all active official settlements, including unmatched coordinates/population.
"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import json
import re
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime,timezone
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from remotezip import RemoteZip
from droneport.ingest import ROOT,normalize,checksum


def main():
    out=ROOT/'data/processed_v2';out.mkdir(exist_ok=True);raw=ROOT/'data/raw/gar_20261103';raw.mkdir(parents=True,exist_ok=True)
    url='https://fias-file.nalog.ru/downloads/2026.11.03/gar_xml.zip'
    session=requests.Session();session.mount('https://',HTTPAdapter(max_retries=Retry(total=4,backoff_factor=1)))
    sources=[]
    with RemoteZip(url,session=session,timeout=60) as archive:
        members=[f for f in archive.infolist() if re.match(r'^(50|67|69)/AS_ADDR_OBJ_\d',f.filename) or f.filename.startswith('AS_OBJECT_LEVELS_')]
        assert len(members)==4
        for entry in members:
            target=raw/(entry.filename.replace('/','_'))
            if not target.exists() or target.stat().st_size!=entry.file_size:
                partial=target.with_suffix('.partial')
                with archive.open(entry.filename) as src,partial.open('wb') as dst: shutil.copyfileobj(src,dst,1024*1024)
                partial.rename(target)
            sources.append(dict(url=url,member=entry.filename,compressed_bytes=entry.compress_size,bytes=target.stat().st_size,
                local_file=str(target.relative_to(ROOT)),sha256=checksum(target),downloaded_at=datetime.now(timezone.utc).isoformat()))
            print('GAR member:',entry.filename,flush=True)
    levels=next(raw.glob('AS_OBJECT_LEVELS_*.XML')); dictionary={r.attrib['LEVEL']:r.attrib['NAME'] for r in ET.parse(levels).getroot()}
    assert dictionary['5']=='Город' and dictionary['6']=='Населенный пункт'
    records=[]; excluded={}
    settlement_types={'г','д','с','п','пгт','рп','дп','х','нп','ст','ж/д ст','ж/д рзд','м-ко','рзд','сл','п/о'}
    for region in ('50','67','69'):
        source=next(raw.glob(region+'_AS_ADDR_OBJ_*.XML'))
        for _,element in ET.iterparse(source,events=('end',)):
            a=element.attrib
            kind=a.get('TYPENAME','').replace('.','').strip()
            if a.get('ISACTIVE')=='1' and a.get('ISACTUAL')=='1' and a.get('LEVEL') in ('2','5','6') and kind in settlement_types:
                records.append(dict(gar_id=a['OBJECTGUID'],gar_object_id=a['OBJECTID'],region_code=region,name_original=a['NAME'],
                    name_normalized=normalize(a['NAME']),settlement_type=a['TYPENAME'],gar_level=a['LEVEL'],updated_at=a['UPDATEDATE']))
            element.clear()
    official=pd.DataFrame(records);assert not official.gar_id.duplicated().any()
    official.to_csv(out/'gar_all_active_settlements.csv',index=False)
    eligible=official[official.name_normalized.str[0].isin(list('ЖЗИКЛ'))].copy()
    osm=pd.read_csv(out/'towns_all.csv',dtype={'region_code':str}); rows=[]
    groups=eligible.groupby(['region_code','name_normalized'])
    for row in eligible.to_dict('records'):
        options=osm[(osm.region_code==row['region_code'])&(osm.name_normalized==row['name_normalized'])]
        kind=row['settlement_type'].replace('.','').strip()
        urban=kind in ('г','пгт','рп','дп')
        if urban: options=options[options.settlement_type.isin(['city','town'])]
        else: options=options[~options.settlement_type.isin(['city','town'])]
        counterpart=groups.get_group((row['region_code'],row['name_normalized']))
        counterpart=counterpart[counterpart.settlement_type.isin(['г.','пгт.','рп.','дп.'])] if urban else counterpart[~counterpart.settlement_type.isin(['г.','пгт.','рп.','дп.'])]
        matched=len(options)==1 and len(counterpart)==1
        row.update(osm_candidates=len(options),match_status='unique_region_name_type' if matched else 'unresolved',
            place_id=options.iloc[0].place_id if matched else None,lat=options.iloc[0].lat if matched else None,
            lon=options.iloc[0].lon if matched else None,population=options.iloc[0].population if matched else None,
            population_year=options.iloc[0].population_year if matched else None)
        rows.append(row)
    registry=pd.DataFrame(rows)
    duplicate=registry.place_id.notna() & registry.place_id.duplicated(keep=False)
    registry.loc[duplicate,['place_id','lat','lon','population','population_year']]=None;registry.loc[duplicate,'match_status']='ambiguous_reused_osm_object'
    registry.to_csv(out/'registry_gar.csv',index=False)
    matched=set(registry.place_id.dropna());osm[~osm.place_id.isin(matched)].to_csv(out/'osm_unresolved_against_gar.csv',index=False)
    summary=dict(source_url=url,version='2026-11-03',source_levels={k:dictionary[k] for k in ('2','5','6')},settlement_types=sorted(settlement_types),
        active_official_settlements=len(official),eligible_official_settlements=len(registry),matched_coordinates=int(registry.lat.notna().sum()),
        unresolved_official_rows=int(registry.lat.isna().sum()),osm_unresolved=int((~osm.place_id.isin(matched)).sum()),
        eligible_by_region=registry.groupby('region_code').size().to_dict(),complete_official_list_for_selected_levels=True,
        geographic_crosswalk_complete=bool(registry.lat.notna().all()),missing_population_policy='preserve_null',frozen_samples_unchanged=True,
        limitation='Active actual settlement types at levels 2/5/6; includes cities at administrative district level, excludes municipal formations, territories and roads; geographic matching remains partial')
    (out/'gar_audit.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));(out/'gar_sources.json').write_text(json.dumps(sources,ensure_ascii=False,indent=2))
    print(json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
