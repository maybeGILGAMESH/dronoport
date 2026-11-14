"""Isolated native OR-Tools loader; do not import highspy in this process."""
import json
import sys
import pandas as pd
from .scheduling import _cp_sat_schedule_check_local

if __name__=='__main__':
    payload=json.load(sys.stdin)
    print(json.dumps(_cp_sat_schedule_check_local(pd.DataFrame(payload['flights']),payload['config'])))
