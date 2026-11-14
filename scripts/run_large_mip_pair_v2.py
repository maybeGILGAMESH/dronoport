"""Run memory-isolated large instances sequentially to avoid concurrent RAM peaks."""
from pathlib import Path
import subprocess,sys

ROOT=Path(__file__).resolve().parents[1]
for nodes,memory,tag in [(20,12,'_complete_start'),(30,14,'_complete_start')]:
    subprocess.run([sys.executable,str(ROOT/'scripts/attempt_large_mip_v2.py'),'--nodes',str(nodes),'--memory-gib',str(memory),'--tag',tag],check=True)
