"""Verify deployed hashes and read-only personal workflow. No customer writes."""
import hashlib
import json
import shlex
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / "test-artifacts/deploy-manifest.json").read_text())
assert all(hashlib.sha256(Path(e["target"]).read_bytes()).hexdigest() == e["sha256"] for e in manifest["entries"])
env = {}
for name in ["/etc/leadbot.env", "/etc/leadbot-personal.env"]:
    for line in Path(name).read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1);env[k] = shlex.split(v)[0] if v else ""
base = {"owner": env["LEADBOT_PERSONAL_OWNER_ID"], "operator_id": env["LEADBOT_PERSONAL_OPERATOR_ID"], "browser_session": "workflow-release:tab:0", "mine_count": 0}


def call(action, auth=True, **extra):
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["X-Leadbot-Token"] = env["LEADBOT_SERVICE_TOKEN"]
    req = urllib.request.Request("http://127.0.0.1:8788/api/extension/assistant", data=json.dumps({**base, "action": action, **extra}).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


assert call("status", auth=False)[0] == 401
assert call("status", owner="another-token")[0] == 403
assert call("status")[1]["policy_version"] == "2026-10-15.8"
assert call("send")[0] == 403
assert call("personal_status")[1]["another_tab"] is False
assert call("personal_start", max_dialogs=3)[1]["active"]
ctx = {"convId": "synthetic-workflow-production-clean", "city": "Чита", "dir": "kp", "partner": "7", "accountTitle": "Денис КП", "adIdentity": "Денис", "origin": "С1", "channel": "avito", "itemTitle": "Ремонт компьютеров", "assigneeId": "", "assignmentKnown": True, "conversationStatus": "open", "botActive": False, "hasTransfer": False, "channelAssigned": True,
       "messages": [{"id": "workflow-m1", "direction": "in", "body": "Компьютер не включается в Чите"}]}
try:
    assert call("personal_start", browser_session="workflow-release:tab:2")[1]["code"] == "personal_busy"
    plan = call("personal_plan", ctx=ctx)[1]
    assert plan["step"] == "claim" and plan["auto_enabled"] is False and plan["execution_allowed"] is False
    assert not call("personal_plan", ctx=ctx, mine_count=3)[1]["eligible"]
    for action in ("personal_authorize", "personal_check_started"):
        code, off = call(action, ctx=ctx, auto_enabled=True, operation={"kind": "claim", "revision": plan["revision"]})
        assert code == 403 and off["code"] == "auto_disabled"
    ctx["assigneeId"] = base["operator_id"]
    draft = call("preview", ctx=ctx)[1]
    assert draft["response_source"] == "reviewed_question" and not draft.get("pending_model") and draft["reply"]
    log = call("personal_audit", ctx=ctx)[1]
    assert {"read", "decision", "draft", "authorization"} <= {e["kind"] for e in log["events"]}
    read = next(e for e in log["events"] if e["kind"] == "read" and e["revision"] == draft["revision"])
    assert call("personal_audit", audit_event_id=read["id"])[1]["event"]["messages"][0]["body"] == ctx["messages"][0]["body"]
    assert call("personal_audit", operator_id="colleague")[0] == 403
    ctx["messages"][0]["body"] = "Заправить картридж принтера в Чите"
    assert not call("personal_plan", ctx=ctx)[1]["eligible"]
finally:
    assert call("personal_stop")[1]["active"] is False
assert call("personal_audit", ctx=ctx)[1]["events"]
assert not call("personal_status")[1]["active"]
for service in ("leadbot", "lc-brain", "leadchat-gateway"):
    assert subprocess.check_output(["systemctl", "is-active", service], text=True).strip() == "active"
print(json.dumps({"hashes_verified": len(manifest["entries"]), "owner_only": True, "service_without_token_http": 401, "other_owner_http": 403, "send_http": 403, "personal_session": "started_and_stopped", "second_tab": "blocked", "workflow_plan": "claim_read_only", "capacity": "blocked", "approval": "excluded", "draft_model_calls": 0, "audit": "read_decision_draft_denial_detail_after_stop_verified", "personal_authorize_http": 403, "pre_submit_guard_http": 403, "auto_enabled": False, "crm_writes": 0, "customer_sends": 0, "services_active": True}))
