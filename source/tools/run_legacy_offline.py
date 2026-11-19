"""Run existing regressions with a process-wide network deny and isolated cache."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "test-artifacts"
OUT.mkdir(exist_ok=True)
SCRIPTS = ["test_leadchat.py", "test_router_guards.py", "test_answer_cache.py", "test_filials_kp.py"]
GUARD = """
import os,runpy,socket,sys
def deny(*args,**kwargs): raise RuntimeError('Offline verification: network disabled')
socket.socket.connect=deny
socket.create_connection=deny
socket.getaddrinfo=deny
runpy.run_path(sys.argv[1],run_name='__main__')
"""
results = []
with tempfile.TemporaryDirectory() as temp:
    for script in SCRIPTS:
        env = dict(os.environ, LEADBOT_ASSISTANT_DB=str(Path(temp) / (script + ".sqlite")), LEADBOT_SERVICE_TOKEN="test-only-token",
                   LEADBOT_CACHE_FILE=str(Path(temp) / "answer-cache.json"))
        result = subprocess.run([sys.executable, "-c", GUARD, str(ROOT / "leadbot/analysis" / script)], cwd=ROOT,
                                env=env, capture_output=True, text=True, timeout=90)
        (OUT / (script + ".log")).write_text(result.stdout + result.stderr)
        results.append({"script": script, "exit": result.returncode, "network": "disabled"})
(OUT / "legacy-results.json").write_text(json.dumps(results, indent=2))
print(json.dumps(results))
sys.exit(int(any(row["exit"] for row in results)))
