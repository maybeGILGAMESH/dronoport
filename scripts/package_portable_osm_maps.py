"""Package the three validated self-contained OSM HTML maps."""
from pathlib import Path
import json,hashlib,zipfile
ROOT=Path(__file__).resolve().parents[1];folder=ROOT/'artifacts/maps';target=ROOT/'artifacts/maps_osm_20261106.zip'
check=json.loads((folder/'validation.json').read_text());assert check['valid'] and len(check['checks'])==36
assert check['external_requests']==check['relative_asset_requests']==0
for name,digest in check['files'].items():assert hashlib.sha256((folder/name).read_bytes()).hexdigest()==digest
if target.exists():raise FileExistsError(target)
files={p.relative_to(folder).as_posix():p for p in sorted(folder.rglob('*')) if p.is_file()}
with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
 for name,path in files.items():z.write(path,'maps/'+name)
with zipfile.ZipFile(target) as z:
 assert len(z.namelist())==len(files)
 for name,path in files.items():assert hashlib.sha256(z.read('maps/'+name)).digest()==hashlib.sha256(path.read_bytes()).digest()
sha=hashlib.sha256(target.read_bytes()).hexdigest();target.with_suffix('.sha256').write_text(sha+'  '+target.name+'\n')
record=dict(valid=True,files=len(files),html_files=3,bytes=target.stat().st_size,sha256=sha,all_archived_bytes_verified=True,browser_checks=36)
target.with_suffix('.verification.json').write_text(json.dumps(record,indent=2));print(json.dumps(record,indent=2))
