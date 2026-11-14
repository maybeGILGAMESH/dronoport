"""Check archived result JSONs against the complete live-run inventory, without extraction."""
from pathlib import Path
import hashlib,json,zipfile
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
known=set(pd.read_csv(ROOT/'reports/research_audit/all_run_results.csv').sha256)
names=['droneport_20261105_181440_v2.zip','droneport_20261106_142509_cp_ga.zip','droneport_20261106_154352_regional.zip']
rows=[]
for name in names:
 p=ROOT/'artifacts'/name
 if not p.exists():p=next((ROOT/'variants').rglob(name))
 with p.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
 with zipfile.ZipFile(p) as z:
  results=[n for n in z.namelist() if n.endswith('/result.json')]
  hashes={hashlib.sha256(z.read(n)).hexdigest() for n in results}
  missing=sorted(hashes-known);assert not missing,(name,missing)
  rows.append(dict(archive=name,sha256=digest,result_records=len(results),unique_result_files=len(hashes),missing_from_all_saved_runs=missing))
report=dict(valid=True,archives=rows,scope='Every result.json in the three preserved original archives has a byte-identical copy in the seven saved run directories')
(ROOT/'reports/research_audit/original_archive_results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2))
