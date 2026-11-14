"""Three self-contained HTML maps with embedded locally rendered OSM tiles."""
from pathlib import Path
import sys,json,math,base64,re,shutil,hashlib
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from droneport.ingest import ROOT,checksum
from droneport.local_osm import Basemap,xy
OUT=ROOT/'artifacts/maps';OUT.mkdir(parents=True,exist_ok=True)
CACHE=ROOT/'.cache/portable_osm_tiles';CACHE.mkdir(parents=True,exist_ok=True)
SOURCE=ROOT/'reports/latex/maps'
data=json.loads((SOURCE/'network_data.js').read_text().removeprefix('window.networkData=').removesuffix(';'))
for p in (SOURCE/'tiles').rglob('*.png'):
 target=CACHE/p.relative_to(SOURCE/'tiles');target.parent.mkdir(parents=True,exist_ok=True)
 if not target.exists():shutil.copy2(p,target)
keys=set()
def rectangle(z,west,south,east,north):
 x1,y1=xy(west,north);x2,y2=xy(east,south);scale=2**z
 for x in range(int(x1*scale),int(x2*scale)+1):
  for y in range(int(y1*scale),int(y2*scale)+1):keys.add((z,x,y))
for z in range(5,11):rectangle(z,30.4,53.25,40.4,59.0)
rectangle(11,36.6,55.3,38.5,56.2)
active={i for tag in 'ABC' for i,y in enumerate(data['networks'][tag]['open_years']) if y}
for i in active:
 t=data['towns'][i]
 for z in (11,12,13):
  x,y=xy(t['lon'],t['lat']);x=int(x*2**z);y=int(y*2**z)
  for dx in (-1,0,1):
   for dy in (-1,0,1):keys.add((z,x+dx,y+dy))
missing=[k for k in sorted(keys) if not (CACHE/str(k[0])/str(k[1])/(str(k[2])+'.png')).exists()]
print('Required tiles',len(keys),'new',len(missing),flush=True)
if missing:
 renderer=Basemap(CACHE)
 for n,(z,x,y) in enumerate(missing,1):
  renderer.tile(z,x,y)
  if n%100==0:print('Rendered',n,'/',len(missing),flush=True)
 del renderer
# Retain existing fixed-view detail tiles too. Images are embedded, never fetched.
tiles={p.relative_to(CACHE).with_suffix('').as_posix():base64.b64encode(p.read_bytes()).decode() for p in sorted(CACHE.rglob('*.png'))}
css=(SOURCE/'assets/leaflet.css').read_text()
# These image-based controls are unused; still remove all relative asset URLs.
css=re.sub(r'url\([^)]*\)', 'none',css)
js=(SOURCE/'assets/leaflet.js').read_text();js=re.sub(r'//# sourceMappingURL=.*','',js)
template=(SOURCE/'index.html').read_text().replace('<link rel="stylesheet" href="assets/leaflet.css">','<style>'+css+'</style>')
template=template.replace('<script src="assets/leaflet.js"></script><script src="network_data.js"></script>', '<script>'+js.replace('</script','<\\/script')+'</script><script>window.networkData='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';</script><script>window.embeddedTiles='+json.dumps(tiles,separators=(',',':'))+';</script>')
old="const tile=L.tileLayer('tiles/{z}/{x}/{y}.png',{maxZoom:12,minZoom:5,tileSize:256,attribution:'© OpenStreetMap contributors · ODbL · локальная выгрузка 03.11.2026'}).addTo(map);tile.on('tileerror',e=>window.tileErrors.push(e.tile.src));"
new="""const EmbeddedOSM=L.GridLayer.extend({createTile(coords,done){
 const canvas=document.createElement('canvas');canvas.width=512;canvas.height=512;canvas.setAttribute('aria-label','Подложка OpenStreetMap');
 let z=coords.z,x=coords.x,y=coords.y,key=z+'/'+x+'/'+y;
 while(z>=5&&!window.embeddedTiles[key]){z--;x=Math.floor(x/2);y=Math.floor(y/2);key=z+'/'+x+'/'+y}
 if(z<5){const ctx=canvas.getContext('2d');ctx.fillStyle='#edf1ed';ctx.fillRect(0,0,512,512);canvas.dataset.outside='true';setTimeout(()=>done(null,canvas),0);return canvas}
 const image=new Image();image.onload=()=>{const ctx=canvas.getContext('2d');const factor=2**(coords.z-z),size=512/factor;ctx.drawImage(image,(coords.x-x*factor)*size,(coords.y-y*factor)*size,size,size,0,0,512,512);canvas.dataset.osm=key;done(null,canvas)};
 image.onerror=()=>{window.tileErrors.push(key);done(new Error('Embedded OSM: '+key),canvas)};
 image.src='data:image/png;base64,'+window.embeddedTiles[key];return canvas;
}});
const tile=new EmbeddedOSM({tileSize:256,minZoom:5,maxZoom:15,attribution:'© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap contributors</a> · ODbL · 03.11.2026'}).addTo(map);
map.setMaxBounds([[53.25,30.4],[59,40.4]]);
"""
assert old in template;template=template.replace(old,new).replace('minZoom:5,maxZoom:12','minZoom:6,maxZoom:15')
template=template.replace("L.marker([lat,lon],{opacity:0,interactive:false})","L.circleMarker([lat,lon],{radius:0,opacity:0,fillOpacity:0,interactive:false})")
template=template.replace('В автономном режиме доступны<br>сохранённые масштабы и виды.','Подложка OSM встроена в HTML.<br>Интернет и сервер не нужны.<br>На сильном увеличении вне портов<br>используется более общий масштаб.')
template=template.replace("+' · север вверху';","+' · OSM внутри файла · работает без интернета';")
# Only the selected variant is offered; each file has year and camera controls.
start=template.index('<select id="variant">');end=template.index('</select>',start)+len('</select>')
template=template[:start]+'<select id="variant" hidden><option>__TAG__</option></select>'+template[end:]
template=template.replace("tag=p.get('variant')||'C'","tag='__TAG__'")
template=template.replace('<title>Дронопорты: локальная карта OSM</title>','<title>__TAG__ · Дронопорты на карте OpenStreetMap</title>')
# A/B regional views are still useful to explore the study territory; no unsupported remote tiles.
license_text=(SOURCE/'assets/LICENSE').read_text().replace('--','- -')
template=template.replace('<!doctype html>','<!doctype html>\n<!-- Leaflet license:\n'+license_text+'\n-->')
files=[]
for tag,name in [('A','A_baseline.html'),('B','B_cp_sat_ga.html'),('C','C_regional.html')]:
 path=OUT/name;path.write_text(template.replace('__TAG__',tag));files.append(dict(variant=tag,file=name,bytes=path.stat().st_size,sha256=checksum(path)))
manifest=dict(schema='portable-osm-maps-1',files=files,tiles=len(tiles),embedded_image_bytes=sum((CACHE/(k+'.png')).stat().st_size for k in tiles),all_assets_embedded=True,external_requests_required=False,coverage=[30.4,53.25,40.4,59.0],native_zoom_overview=[5,10],native_zoom_near_ports=[11,12,13],max_display_zoom=15,overzoom='Crop and scale an embedded ancestor tile where detail is unavailable',source_provenance=json.loads((ROOT/'data/cartography/provenance.json').read_text()),sources={str(p.relative_to(ROOT)):checksum(p) for p in [SOURCE/'network_data.js',SOURCE/'index.html',ROOT/'scripts/build_portable_osm_maps.py']})
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
(OUT/'README.txt').write_text('ТРИ САМОСТОЯТЕЛЬНЫЕ КАРТЫ С ПОДЛОЖКОЙ OSM\n\nA_baseline.html: базовая временная модель.\nB_cp_sat_ga.html: CP-SAT и сравнение GA/SA.\nC_regional.html: порты и рейсы во всех трёх областях.\n\nОткройте любой HTML двойным щелчком. Его можно отдельно перенести, переименовать и отправить: все изображения, Leaflet, границы и данные сети находятся внутри. Сервер, VPN и интернет не нужны. Внизу справа выбираются год и вид. По умолчанию показана сеть третьего года. Наведите мышь на линию для числа рейсов и загрузки.\n\nПодложка отрисована по реальным локальным данным OpenStreetMap от 03.11.2026: дороги, железные дороги, вода и названия поселений. Это светлый выборочный стиль, не полный стандартный OSM Carto; здания и составные водные объекты не включены. Подробные масштабы сохранены вокруг портов; вне них используется увеличение более общего изображения. Географическое покрытие: три исследуемые области, а не весь мир. Прямые линии сети обозначают модельные перелёты, не дороги или разрешённые воздушные трассы.\n\n© OpenStreetMap contributors, ODbL 1.0: https://www.openstreetmap.org/copyright\nИсходная локальная база и её происхождение находятся в основном комплекте: data/cartography/basemap.json.gz и provenance.json. Leaflet распространяется по BSD-2-Clause; текст лицензии включён в каждый HTML.\n\nПересборка из проекта: .venv/bin/python scripts/build_portable_osm_maps.py\nПроверка: .venv/bin/python scripts/check_portable_osm_maps.py\n')
print(json.dumps(dict(files=files,tiles=len(tiles)),ensure_ascii=False,indent=2),flush=True)
