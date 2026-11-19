"""The actual production HTTP handler, isolated config/db, no channel pollers."""
import json
import os
import sys
import tempfile
from http.server import ThreadingHTTPServer
from pathlib import Path

brain_path = Path('/opt/leadbot/brain') if '--installed-brain' in sys.argv else Path(__file__).resolve().parents[1] / 'leadbot/brain'
sys.path.insert(0, str(brain_path))
os.environ["LEADBOT_SERVICE_TOKEN"] = "test-only-service-token-not-a-credential"

import server
assert Path(server.__file__).resolve().parent == brain_path.resolve()
from assistant_store import Store
if "--workflow-enabled" in sys.argv:
    # Isolated test process only. Production server never reads this switch.
    os.environ["LEADBOT_PERSONAL_AUTO_AVAILABLE"] = "1"

if '--fixed-clock137' in sys.argv:
    # Only this isolated fixture accepts the switch, never the deployed server.
    from datetime import datetime
    from unittest.mock import patch
    import assistant_policy
    import personal_workflow
    frozen = datetime.fromisoformat('2026-10-21T09:00:03+00:00')
    patch('time.time', return_value=frozen.timestamp()).start()
    patch('assistant_policy._visit_question_now', side_effect=lambda zone: frozen.astimezone(zone)).start()
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen.astimezone(tz) if tz else frozen.replace(tzinfo=None)
    personal_workflow.datetime = FixedDateTime

temp = tempfile.TemporaryDirectory()
server._REQUEST_STORE = Store(str(Path(temp.name) / "isolated.sqlite"))


class Handler(server.Handler):
    def log_message(self, *_args):
        pass


httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
print(json.dumps({"port": httpd.server_port}), flush=True)
httpd.serve_forever()
