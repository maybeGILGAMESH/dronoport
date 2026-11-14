"""Finish scenarios and checks; leave the report available for visual review."""
from pathlib import Path
import sys,subprocess,argparse,json
root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--run-dir');args=parser.parse_args()
folder=Path(args.run_dir or (root/'.cache/cp_ga_run.txt').read_text()).resolve()
assert json.loads((folder/'cp_ga/search_manifest.json').read_text())['status']=='complete'
def run(script,*args):subprocess.run([sys.executable,script,*map(str,args)],cwd=root,check=True)
run('scripts/check_search_best_scenarios.py','--run-dir',folder)
run('scripts/run_project.py','--report-only','--run-dir',folder)
run('scripts/check_delivery_consistency_v2.py','--run-dir',folder)
run('scripts/validate_cp_ga.py','--run-dir',folder)
run('scripts/check_offline_map.py',folder/'report/maps/network.html','--output',folder/'report/browser_checks')
run('scripts/check_offline_map.py',folder/'report/maps/network_cp_ga.html','--output',folder/'report/browser_checks_cp_ga')
run('scripts/publish_v2.py','--validate-only','--run-dir',folder)
print('Ready for visual review:',folder/'report/report.pdf',flush=True)
