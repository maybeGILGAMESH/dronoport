from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from droneport.ingest import ROOT
from droneport.experiment_refinement import refine

if __name__=='__main__':
    refine(Path((ROOT/'results_v2/current_run.txt').read_text().strip()))
