"""Основной сквозной запуск расчёта и экспериментов."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
version='v2'
if '--model-version' in sys.argv:
    index=sys.argv.index('--model-version')
    if index+1>=len(sys.argv):raise SystemExit('--model-version requires v1 or v2')
    version=sys.argv[index+1]
if version in ('v1','timed_shuttles_v1'):
    del sys.argv[index:index+2]
    from droneport.pipeline import main
elif version in ('v2','time_network_v2'):
    from droneport.pipeline_v2 import main
else:
    raise SystemExit('Unknown model version: '+version)

if __name__ == "__main__":
    main()
