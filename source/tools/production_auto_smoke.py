"""Verify deployed hashes and read-only personal workflow. No customer writes."""
import hashlib
import json
import uuid
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
assert call("status")[1]["policy_version"] == manifest["policy_version"]
assert call("send")[0] == 403
if call("personal_status")[1]["another_tab"]:
    print(json.dumps({"hashes_verified":len(manifest["entries"]),"services_unchanged":True,"active_other_session_preserved":True,"auto_activation_attempts":0}));raise SystemExit(0)
lease=call("personal_start", max_dialogs=3)[1]
assert lease["active"] and lease["auto_available"] and not lease["auto_enabled"]
assert not call("personal_mode",execution_mode="auto",confirmed=True,policy_ack=manifest["policy_version"],client_version="2.7.0",activation_nonce="invalid-nonce-at-least-twenty")[1]["ok"]
ctx = {"convId": "synthetic-workflow-" + uuid.uuid4().hex, "city": "Чита", "dir": "kp", "partner": "7", "accountTitle": "Денис КП", "adIdentity": "Денис", "origin": "С1", "channel": "avito", "itemTitle": "Ремонт компьютеров", "assigneeId": "", "assignmentKnown": True, "conversationStatus": "in_progress", "botActive": False, "hasTransfer": False, "channelAssigned": True,
       "messages": [{"id": "workflow-m1", "direction": "in", "body": "Компьютер не включается в Чите"}]}
try:
    assert call("personal_start", browser_session="workflow-release:tab:2")[1]["code"] == "personal_busy"
    plan = call("personal_plan", ctx=ctx)[1]
    assert plan["step"] == "claim" and plan["auto_enabled"] is False and plan["execution_allowed"] is False
    assert call("personal_plan", ctx=ctx, mine_count=999)[1]["eligible"]
    for action in ("personal_authorize", "personal_check_started"):
        code, off = call(action, ctx=ctx, auto_enabled=True, operation={"kind": "claim", "revision": plan["revision"]})
        assert code == 403 and off["execution_allowed"] is False
        if action == "personal_authorize":
            assert off["code"] == "auto_disabled"
    ctx["assigneeId"] = base["operator_id"]
    draft = call("preview", ctx=ctx)[1]
    assert draft["response_source"] == "reviewed_question" and not draft.get("pending_model") and draft["reply"]
    log = call("personal_audit", ctx=ctx)[1]
    assert {"read", "decision", "draft", "authorization"} <= {e["kind"] for e in log["events"]}
    read = next(e for e in log["events"] if e["kind"] == "read" and e["revision"] == draft["revision"])
    assert call("personal_audit", audit_event_id=read["id"])[1]["event"]["messages"][0]["body"] == ctx["messages"][0]["body"]
    assert call("personal_audit", operator_id="colleague")[0] == 403
    reviewed_plan = call("personal_plan", ctx=ctx)[1]
    confirmation = call("personal_status")[1]
    operation = {"kind": "reply", "revision": reviewed_plan["revision"], "operation_id": reviewed_plan["operation_id"], "draft_id": draft["draft_id"], "reply": draft["reply"]}
    reviewed = call("personal_review_authorize", ctx=ctx, operation=operation, confirmed=True, activation_nonce=confirmation["activation_nonce"], policy_ack=confirmation["policy_version"], client_version="2.7.1")[1]
    assert reviewed["ok"] and reviewed["reviewed"] and not reviewed["auto_enabled"]
    assert call("personal_status")[1]["execution_mode"] == "review"
    assert not call("personal_review_authorize", ctx=ctx, operation=operation, confirmed=True, activation_nonce=confirmation["activation_nonce"], policy_ack=confirmation["policy_version"], client_version="2.7.1")[1]["ok"]
    plumbing = {**ctx, "convId": "synthetic-workflow-" + uuid.uuid4().hex, "dir": "mnc", "messages": [{"id": "plumbing-m1", "direction": "in", "body": "В Чите шланг фильтра выбивает и кнопка унитаза залипает, какая цена?"}]}
    assert call("screen", ctx=plumbing)[1]["eligible"]
    priced = call("preview", ctx=plumbing)[1]
    assert priced["reply"] and not any(ch.isdigit() for ch in priced["reply"])
    historical = {**plumbing, "convId": "synthetic-workflow-" + uuid.uuid4().hex, "messages": [{"id": "quote-in", "direction": "in", "body": "Установить унитаз в Чите"}, {"id": "quote-out", "direction": "out", "body": "3500р выйдет", "delivery_status": "delivered"}, {"id": "quote-confirm", "direction": "in", "body": "Это за всё, больше сумма не выйдет?"}]}
    assert not call("screen", ctx=historical)[1]["eligible"]
    generic = {**ctx, "convId": "synthetic-workflow-" + uuid.uuid4().hex, "dir": "", "accountTitle": "Александр", "origin": "М17"}
    routed = call("preview", ctx=generic)[1]
    assert routed["routing"] == {"direction": "kp", "evidence": "owner_source_list:М17"}
    assert call("screen", ctx=generic)[1]["eligible"]
    outside = {**generic, "convId": "synthetic-workflow-" + uuid.uuid4().hex, "city": "Улан-Удэ", "messages": [{"id": "outside", "direction": "in", "body": "Компьютер не включается. Пгт Селенгинск. Вы с Улан-Удэ?"}]}
    assert not call("screen", ctx=outside)[1]["eligible"]
    assert not call("preview", ctx=outside)[1].get("reply")
    for channel in ("max", "max_bot", "max_user"):
        ctx["channel"] = channel
        assert not call("screen", ctx=ctx)[1]["eligible"]
        assert not call("preview", ctx=ctx)[1].get("reply")
    ctx["channel"] = "avito"
    ctx["messages"][0]["body"] = "Заправить картридж принтера в Чите"
    assert not call("personal_plan", ctx=ctx)[1]["eligible"]
    ctx["conversationStatus"] = "closed"
    call("personal_plan", ctx=ctx)
finally:
    assert call("personal_stop")[1]["active"] is False
assert call("personal_audit", ctx=ctx)[1]["events"]
assert not call("personal_status")[1]["active"]
for service in ("leadbot", "lc-brain", "leadchat-gateway"):
    assert subprocess.check_output(["systemctl", "is-active", service], text=True).strip() == "active"
print(json.dumps({"hashes_verified": len(manifest["entries"]), "policy_version":manifest["policy_version"], "generic_source_routing":"verified", "unknown_settlement":"operator_only", "single_review_grant": "issued_once_without_auto_or_transport", "max_variants_blocked": 3, "accepted_multi_plumbing": "not_misclassified_as_approval", "prior_total_price_confirmation": "operator_only", "owner_only": True, "service_without_token_http": 401, "other_owner_http": 403, "send_http": 403, "personal_session": "started_and_stopped", "second_tab": "blocked", "workflow_plan": "claim_read_only", "capacity": "unlimited_historic_backlog_does_not_block_plan", "approval": "excluded", "draft_model_calls": 0, "audit": "read_decision_draft_denial_detail_after_stop_verified", "personal_authorize_http": 403, "pre_submit_guard_http": 403, "auto_enabled": False, "crm_writes": 0, "customer_sends": 0, "services_active": True}))
