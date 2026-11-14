"""Prepare attributed maps and fixed camera positions for all published networks."""
from pathlib import Path
import json,sys,shutil,hashlib
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from droneport.ingest import ROOT,checksum

out=ROOT/'reports/latex/maps';out.mkdir(parents=True,exist_ok=True)
shutil.copytree(ROOT/'reports/article/maps/assets',out/'assets',dirs_exist_ok=True)
folder=ROOT/'runs/20261106_154352_regional';towns=pd.read_csv(folder/'towns_main.csv');townlist=json.loads(towns[['place_id','name_original','lat','lon','region_code']].to_json(orient='records',force_ascii=False))
networks={};sources={}
for tag,sub,label in [('A','base','Базовая временная модель'),('B','cp_ga/final_best','CP-SAT и сравнение GA/SA'),('C','regional/final_best','Порты и рейсы в трёх областях')]:
    path=folder/sub/'result.json';r=json.loads(path.read_text());sources[str(path.relative_to(ROOT))]=checksum(path)
    networks[tag]=dict(label=label,open_years=r['plan']['open_years'],flights=[{k:f[k] for k in ('year','origin_id','destination_id','passengers')} for f in r['flights']],annual=r['annual_completed'])
legacy=ROOT/'data/cartography/legacy_network.json'
if not legacy.exists():
    fs=pd.read_csv(ROOT/'runs/20261105_171655/flights_and_schedule.csv');inv=pd.read_csv(ROOT/'runs/20261105_171655/investment_fleet_plan.csv')
    openings={}
    for row in inv.itertuples():
        if row.new_aircraft<=0:continue
        for key in (row.origin_id,row.destination_id):openings[key]=min(openings.get(key,4),row.year)
    data=dict(label='Ранняя коридорная модель',open_years=[int(openings.get(i,0)) for i in towns.place_id],flights=json.loads(fs[['year','origin_id','destination_id','passengers']].to_json(orient='records')),annual=[int(fs[fs.year==y].passengers.sum()*330) for y in (1,2,3)],source_run='20261105_171655',source_hashes={str(p.relative_to(ROOT)):checksum(p) for p in [ROOT/'runs/20261105_171655/flights_and_schedule.csv',ROOT/'runs/20261105_171655/investment_fleet_plan.csv']})
    assert sum(data['annual'])==343200
    legacy.write_text(json.dumps(data,ensure_ascii=False))
networks['L']=json.loads(legacy.read_text());sources[str(legacy.relative_to(ROOT))]=checksum(legacy)
boundaries=json.loads((ROOT/'data/processed/region_boundaries.geojson').read_text())
data=dict(towns=townlist,networks=networks,boundaries=boundaries)
(out/'network_data.js').write_text('window.networkData='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';')
views=[]
for tag in ('A','B','C'):
    for y in (1,2,3):
        for kind in ('overview','detail'):
            views.append(dict(id=f'{tag}_y{y}_{kind}',variant=tag,year=y,view=kind,title=f'{tag}: год {y}, '+('обзор трёх областей' if kind=='overview' else 'подробная сеть')))
for y in (1,2,3):views.append(dict(id=f'L_y{y}_detail',variant='L',year=y,view='detail',title=f'Ранняя коридорная модель: год {y}'))
for kind,name in [('moscow','московское ядро'),('smolensk','Кардымово'),('tver','Зубцов')]:views.append(dict(id='C_y3_'+kind,variant='C',year=3,view=kind,title='C: год 3, '+name))
views.append(dict(id='ABC_y3_overlay',variant='ABC',year=3,view='detail',title='Наложение трёх вариантов: год 3'))
(out/'views.json').write_text(json.dumps(views,ensure_ascii=False,indent=2))
(out/'source_manifest.json').write_text(json.dumps(dict(sources=sources,basemap=json.loads((ROOT/'data/cartography/provenance.json').read_text()),views=len(views)),ensure_ascii=False,indent=2))
(out/'index.html').write_text('''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Дронопорты: локальная карта OSM</title><link rel="stylesheet" href="assets/leaflet.css"><style>
html,body{margin:0;width:100%;height:100%;font:14px system-ui;background:#fff;color:#172033}#header{height:88px;box-sizing:border-box;padding:13px 24px;border-bottom:1px solid #dce2e8}h1{margin:0;font-size:23px}#subtitle{margin-top:6px;color:#536376}#map{position:absolute;top:88px;bottom:0;left:0;right:0;background:#fafbf9}.legend{position:absolute;right:16px;top:104px;z-index:1000;background:#fffffff2;padding:13px 16px;max-width:325px;border:1px solid #dce2e8;border-radius:5px;font-size:12px;line-height:1.6}.legend b{font-size:13px}.legend .swatch{display:inline-block;width:24px;border-top:3px solid;margin-right:5px;vertical-align:middle}.port-label{background:white;border:1px solid #cad4dc;border-radius:3px;box-shadow:none;padding:3px 5px;font-size:12px;font-weight:600;color:#172033}.leaflet-tooltip:before{display:none}.leaflet-control-attribution{font-size:10px}.selector{position:absolute;right:16px;bottom:32px;z-index:1000;background:white;padding:7px;border:1px solid #cad4dc}select{padding:5px;border:1px solid #cad4dc;background:white}body.capture .selector{display:none}
</style><header id="header"><h1 id="title"></h1><div id="subtitle"></div></header><div id="map"></div><div class="legend" id="legend"></div><div class="selector"><select id="variant"><option>A</option><option>B</option><option>C</option><option value="L">Коридорная</option><option value="ABC">Наложение A/B/C</option></select> <select id="year"><option>1</option><option>2</option><option>3</option></select> <select id="view"><option value="detail">Сеть подробно</option><option value="overview">Три области</option><option value="moscow">Московское ядро</option><option value="smolensk">Кардымово</option><option value="tver">Зубцов</option></select></div>
<script src="assets/leaflet.js"></script><script src="network_data.js"></script><script>
const p=new URLSearchParams(location.search),tag=p.get('variant')||'C',year=+(p.get('year')||3),view=p.get('view')||'detail';if(p.has('capture'))document.body.classList.add('capture');
const d=window.networkData,colors={A:'#0072b2',B:'#007f5f',C:'#bb4e12',L:'#76549c'},towns=Object.fromEntries(d.towns.map(t=>[t.place_id,t]));
const map=L.map('map',{preferCanvas:true,zoomControl:true,zoomAnimation:false,fadeAnimation:false,markerZoomAnimation:false,minZoom:5,maxZoom:12,zoomSnap:0.25,zoomDelta:0.5}).setView([56,35.4],7);window.projectMap=map;window.tileErrors=[];
const tile=L.tileLayer('tiles/{z}/{x}/{y}.png',{maxZoom:12,minZoom:5,tileSize:256,attribution:'© OpenStreetMap contributors · ODbL · локальная выгрузка 03.11.2026'}).addTo(map);tile.on('tileerror',e=>window.tileErrors.push(e.tile.src));
L.control.scale({imperial:false,maxWidth:160,position:'bottomleft'}).addTo(map);
L.geoJSON(d.boundaries,{style:f=>({color:'#9caeb7',weight:1.1,fill:false,dashArray:'5 4'})}).addTo(map);
const selected=tag==='ABC'?['A','B','C']:[tag],active=[],portLabels=[];
const safe=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
for(const key of selected){const n=d.networks[key],edges={};n.flights.filter(f=>f.year===year).forEach(f=>{const k=[f.origin_id,f.destination_id].sort().join('|');if(!edges[k])edges[k]={flights:0,passengers:0};edges[k].flights++;edges[k].passengers+=f.passengers});
for(const [edge,v] of Object.entries(edges)){const [a,b]=edge.split('|').map(i=>towns[i]);const width=tag==='ABC'?({A:9,B:6,C:2.5}[key]):2+Math.min(5,v.flights*.4);L.polyline([[a.lat,a.lon],[b.lat,b.lon]],{color:colors[key],weight:width,opacity:.85,dashArray:tag==='ABC'&&key==='C'?'8 5':null}).bindTooltip(safe(a.name_original+' ↔ '+b.name_original)+': '+v.flights+' рейсов, '+v.passengers+' занятых мест/сутки').addTo(map)}
n.open_years.forEach((v,i)=>{if(v>0&&v<=year){const t=d.towns[i];active.push([t.lat,t.lon]);const circle=L.circleMarker([t.lat,t.lon],{radius:6,color:'#fff',weight:2,fillColor:colors[key],fillOpacity:1}).addTo(map);if(tag!=='ABC'||key==='C'){const direction=t.name_original==='Котельники'||t.name_original==='Ивантеевка'?'bottom':'top';circle.bindTooltip(safe(t.name_original),{permanent:true,direction,className:'port-label',offset:[0,direction==='bottom'?5:-5]});portLabels.push({circle,t,direction})}}});}
if(view==='overview')map.fitBounds([[53.3,30.6],[58.98,40.35]],{paddingTopLeft:[45,35],paddingBottomRight:[350,35]});
else if(view==='moscow')map.fitBounds([[55.38,36.65],[56.15,38.45]],{paddingTopLeft:[40,35],paddingBottomRight:[350,35]});
else if(view==='smolensk')map.setView([54.8914,32.432],11);
else if(view==='tver')map.setView([56.175,34.58],11);
else map.fitBounds(active,{paddingTopLeft:[70,65],paddingBottomRight:[360,65],maxZoom:11});
let clusterLabel=null;
function updatePortLabels(){const close=map.getZoom()>=9;const mo=[];for(const {circle,t,direction} of portLabels){circle.unbindTooltip();const visible=close||t.region_code!==50;circle.bindTooltip(safe(t.name_original),{permanent:visible,direction,className:'port-label',offset:[0,direction==='bottom'?5:-5]});if(t.region_code===50)mo.push(t)}if(clusterLabel){map.removeLayer(clusterLabel);clusterLabel=null}if(!close&&mo.length){const unique=Array.from(new Map(mo.map(t=>[t.place_id,t])).values());const lat=unique.reduce((a,t)=>a+t.lat,0)/unique.length,lon=unique.reduce((a,t)=>a+t.lon,0)/unique.length;clusterLabel=L.marker([lat,lon],{opacity:0,interactive:false}).bindTooltip('Московское ядро · портов: '+unique.length,{permanent:true,direction:'right',className:'port-label',offset:[12,0]}).addTo(map)}}
updatePortLabels();map.on('zoomend',updatePortLabels);
const heading=tag==='ABC'?'Наложение A, B и C':tag+' · '+d.networks[tag].label;document.getElementById('title').textContent=heading+' · год '+year;
const count=tag==='ABC'?'Сопоставление географии фактически выполненных рейсов':'Портов: '+new Set(active.map(x=>x.join(','))).size+' · '+d.networks[tag].annual[year-1].toLocaleString('ru-RU')+' завершённых поездок за год';
document.getElementById('subtitle').textContent=count+' · '+(view==='overview'?'Обзор территории':'Подробный вид')+' · север вверху';
document.getElementById('legend').innerHTML='<b>Условные обозначения</b><br>'+selected.map(k=>'<span class="swatch" style="border-color:'+colors[k]+'"></span> '+k+': фактические рейсы').join('<br>')+'<br>● Введённый дронопорт<br>Толщина линии: число рейсов в сутки'+(tag==='ABC'?'<br>В наложении толщина различает версии':'')+'<br>Серый пунктир: границы областей<br>Светлые линии: дороги, синие: вода<br><br>Рейсы показаны прямыми участками.<br>Это не дорожные и не разрешённые<br>авиационные трассы.<br>В автономном режиме доступны<br>сохранённые масштабы и виды.';
if(tag==='ABC')document.getElementById('legend').innerHTML=document.getElementById('legend').innerHTML.replace('Толщина линии: число рейсов в сутки<br>В наложении толщина различает версии','Толщина и штрих различают версии;<br>совпадающие линии частично перекрыты');
for(const [id,val] of [['variant',tag],['year',year],['view',view]]){document.getElementById(id).value=val;document.getElementById(id).onchange=()=>{const q=new URLSearchParams({variant:document.getElementById('variant').value,year:document.getElementById('year').value,view:document.getElementById('view').value});location.search=q.toString()}};
window.captureReady=false;window.mapReady=true;window.mapState={variant:tag,year,view,ports:active.length,zoom:map.getZoom(),center:map.getCenter()};
function ready(){if(!tile.isLoading())window.captureReady=true}tile.on('load',ready);setTimeout(ready,500);
</script></html>''',encoding='utf-8')
print('Prepared',len(views),'views; sources',len(sources))
