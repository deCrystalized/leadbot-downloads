"""Reuse only the existing service's environment on the host; never print it."""
import subprocess
import os
import time
import urllib.request
from pathlib import Path

root=Path(__file__).resolve().parents[1]
pid=subprocess.check_output(['systemctl','show','-p','MainPID','--value','lc-brain'],text=True).strip()
env=dict(v.split('=',1) for v in Path('/proc/'+pid+'/environ').read_text().split('\0') if '=' in v)
if os.environ.get('REVIEW_ROUND'):env['REVIEW_ROUND']=os.environ['REVIEW_ROUND']
for attempt in range(20):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8789/api/health',timeout=1) as r:
            if r.status==200:break
    except Exception:time.sleep(0.2)
else:raise RuntimeError('Isolated HTTP handler did not start')
subprocess.run(['/opt/lead-centre/runtime/node/bin/node',str(root/'tools/run_real_review.js')],cwd=root,env=env,check=True)
