"""Clone a completed numeric baseline without modifying its published files."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import argparse,json,shutil,hashlib

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--baseline',required=True);args=parser.parse_args()
source=Path(args.baseline).resolve();target=root/'runs'/(datetime.now(ZoneInfo('Europe/Moscow')).strftime('%Y%m%d_%H%M%S')+'_cp_ga')
shutil.copytree(source,target,ignore=shutil.ignore_patterns('__pycache__','cp_ga'))
manifest=json.loads((target/'run_manifest.json').read_text());manifest.update(run_id=target.name,status='cp_ga_in_progress',baseline_run=source.name,
    baseline_manifest_sha256=hashlib.sha256((source/'run_manifest.json').read_bytes()).hexdigest(),additional_mip_pending=False)
(target/'run_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2));(target/'cp_ga').mkdir()
(root/'.cache').mkdir(exist_ok=True);(root/'.cache/cp_ga_run.txt').write_text(str(target));print(target)
