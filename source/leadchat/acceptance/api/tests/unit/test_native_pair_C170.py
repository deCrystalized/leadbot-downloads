"""Real Root/Main signed contracts on authored sources; model and CRM stay fake."""

import asyncio
import copy
import hashlib
import importlib
import importlib.util
import io
import json
import os
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypedDict
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select

from app.api.deps import get_redis
from app.api.routes import assistant_office as office_api
from app.models import (
    AssistantNativeAction,
    AssistantNativeOutbound,
    AssistantOfficeWork,
    AssistantResearchWork,
    AvitoAccount,
    Client,
    Conversation,
    Message,
    User,
)
from app.services import (
    assistant_dialogs,
    assistant_identity,
    assistant_outbound,
    assistant_runs,
    assistant_runtime,
    crypto,
    leadbot_reader,
)
from app.services.assistant_actions import NativeActionCoordinator
from app.services.assistant_office import NativeOffice
from app.services.assistant_research import NativeResearchRelay
from app.services.leadbot_native_client import NativeResearchClient
from tests.unit import test_native_actions_0111 as fixtures
from tests.unit import test_native_runtime_0111 as runtime
from tests.unit.browser_control_c181 import operate
from tests.unit.conftest import DEFAULT_PASSWORD

HERE = Path(__file__).resolve().parents[3]
ROOTS = {
    "C126": "C126-Root-policy-candidate266-v2",
    "C147": "C147-pre-review-wording-candidate266-v1",
    "C189": "C189-reviewed-reply-finalization-local266-v1",
    "C190": "C190-composed-reply-preflight-local266-v1",
}
ROOT = HERE.parent / ROOTS[os.environ["C170_ROOT_VERSION"]]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "leadbot/brain")]
root_fixture = importlib.import_module("auto_simulator231")
root_policy = importlib.import_module("assistant_policy")
root_execution = importlib.import_module("native_execution")
root_wire = importlib.import_module("native_execution_protocol")
NativeContext = importlib.import_module("native_context").NativeContext
NativeSources = importlib.import_module("native_sources").NativeSources
ResearchService = importlib.import_module("research_workflow").ResearchService
root_workflow_fixtures = importlib.import_module("test_workflow")

native_action = fixtures.native_action
configured = runtime.configured
READ_KEY = b"authored-C121-source-protocol-key"
EXEC_KEY = b"authored-C121-private-execution-key"


def save_receipt(name, report):
    revision = os.environ["C121_EVIDENCE_REVISION"]
    path = HERE / f"{name}266-{revision}.json"
    with path.open("x") as output:
        json.dump(report, output, indent=2)
        output.write("\n")


class LocalSourceConnection:
    """Only the HTTPS socket boundary is replaced; actual bytes go to ASGI."""

    def __init__(self, bridge, host, port, **kwargs):
        assert host == "188-225-34-82.sslip.io" and port == 443
        self.bridge = bridge

    def request(self, method, path, body, headers):
        response = asyncio.run_coroutine_threadsafe(
            self.bridge.read(method, path, body, headers), self.bridge.loop
        ).result(timeout=20)
        self.status = response.status_code
        self.headers = response.headers
        self.body = io.BytesIO(response.content)

    def getresponse(self):
        return self

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read(self, size):
        return self.body.read(size)

    def close(self):
        pass


class Pair:
    # Root is imported from the isolated candidate, outside Main's type graph.
    gateway: Any
    sim: Any
    root_app: Any

    def __init__(self, main, client):
        self.main, self.client = main, client
        self.loop = asyncio.get_running_loop()
        self.reads, self.commands, self.queue = [], [], []

    async def read(self, method, path, body, headers):
        assert method == "POST" and path == "/api/v1/bot-dialogs/assistant/reader"
        packet = json.loads(body)
        self.reads.append({"operation": packet["operation"], "arguments": packet["arguments"]})
        response = await self.client.request(method, path, content=body, headers=headers)
        assert response.status_code == 200, response.text
        return response

    def execute(self, body, headers):
        packet = root_wire.decode(body, root_wire.MAX_OFFICE_REQUEST)
        self.commands.append(packet)
        status, raw, signed = self.gateway.handle(body, {k.lower(): v for k, v in headers.items()})
        # Existing schedulers execute original commands and model jobs once.
        # The original202 response is preserved; Main must use recover itself.
        for _ in range(50):
            if self.queue:
                self.queue.pop(0)()
            elif self.sim.work:
                self.sim.work.pop(0)()
            else:
                break
        else:
            raise AssertionError("Authored local scheduler did not settle")
        return httpx.Response(
            status, content=raw, headers={"content-type": "application/json", **signed}
        )

    async def private(self, request):
        return await asyncio.to_thread(self.execute, request.content, dict(request.headers))


async def current_proposal_seed(f, leased):
    app = f.pair.root_app
    body = {
        "owner": app.research.native_authority.owner,
        "ctx": {"convId": str(f.cid)},
        "native_run": {
            "run_id": str(f.live.run_id),
            "generation": f.live.generation,
            "operator_id": str(f.author.id),
        },
    }
    current = await asyncio.to_thread(app.research.prepare_source, app, body)
    proposal = root_workflow_fixtures.WorkflowTests().proposal(current["ctx"])
    proposal["lead"].update(copy.deepcopy(leased["form"]["form_extraction"]["lead"]))
    proposal["revision"] = leased["form"]["revision"]
    proposal["form_reference"] = leased["form"]["form_reference"]
    proposal["lead"]["service_comment"] = "https://lead.test/chats/" + str(f.cid)
    return proposal


@pytest.fixture
async def paired(native_action, client, app, configured, monkeypatch, request):
    f = native_action
    f.now[0] = time.time()
    environment = patch.dict(os.environ, {}, clear=False)
    environment.start()
    sim = root_fixture.Simulation()
    bridge = Pair(f, client)
    bridge.sim = sim
    try:
        monkeypatch.setenv("LEADBOT_READER_ENABLED", "1")
        monkeypatch.setattr(assistant_identity, "proof_key", lambda: READ_KEY)
        app.dependency_overrides[get_redis] = lambda: f.redis
        async with f.sessions() as db:
            author = await db.get(User, f.author.id)
            assert author is not None
            author.full_name = "Тестовый оператор C181"
            f.author_name = author.full_name
            conv = await db.get(Conversation, f.cid)
            account = await db.get(AvitoAccount, conv.account_id)
            account.title, account.lead_partner_number, account.lead_origin = (
                "Учебный КП",
                "624",
                "С1",
            )
            conv.item_title, conv.item_city_slug = "Ремонт компьютеров", "chita"
            (await db.get(Client, conv.client_id)).name = "Иван"
            message = await db.scalar(select(Message).where(Message.conversation_id == f.cid))
            message.body = root_workflow_fixtures.WorkflowTests().ctx(True)["messages"][0]["body"]
            if getattr(request, "param", None) == "reply":
                account.title = "Учебный МНЧ"
                conv.item_title = "Мастер на час"
                message.body = "Нужно повесить полку."
            elif getattr(request, "param", None) == "single_dialogue":
                message.body = root_workflow_fixtures.WorkflowTests().ctx()["messages"][0]["body"]
            await db.commit()
        source = NativeSources(
            "https://188-225-34-82.sslip.io",
            key=lambda: READ_KEY,
            header_guard=lambda header: None,
            cid_guard=lambda cids: (
                (_ for _ in ()).throw(AssertionError("Foreign test CID"))
                if cids != [str(f.cid)]
                else None
            ),
            connection_factory=lambda *a, **k: LocalSourceConnection(bridge, *a, **k),
        )
        native = NativeContext(source, sim.root / "actual-main-source")
        old = sim.service
        base = ResearchService(
            sim.root / "paired-research",
            shared_lock=sim.root / "paired-provider.lock",
            corpus_factory=old.corpus_factory,
            request=sim.provider,
            schedule=sim.work.append,
            native_context=native,
            proposal_enabled=True,
            intake_form_enabled=True,
            owner_auto_enabled=True,
            native_crm_only_enabled=True,
            **(
                {"unique_replies_enabled": True, "price_wording_enabled": True}
                if os.environ["C170_ROOT_VERSION"] in {"C147", "C189", "C190"}
                else {}
            ),
        )
        sim.service = base
        apps = root_execution.NativeApplications(sim.app.store, base)
        app_root = apps(str(f.principal.id))
        versions = (
            root_policy.VERSION,
            base.code_version,
            base._map_version(),
            base.corpus_factory().initial,
        )
        admission = assistant_runs.RuntimeAdmission(*versions, True, True)
        async with f.sessions() as db:
            stopped = await assistant_runs.stop(
                db, f.principal.id, expected_generation=f.live.generation
            )
            stopped_generation = stopped["generation"]
            assert isinstance(stopped_generation, int)
            await assistant_runs.start(
                db,
                f.principal.id,
                f.author.id,
                expected_generation=stopped_generation,
                mode="auto",
                admission=admission,
            )
            await db.commit()
            status = await assistant_runs.status(db, f.principal.id)
            import uuid

            run_id, generation = status["run_id"], status["generation"]
            assert isinstance(run_id, str) and isinstance(generation, int)
            f.live = await assistant_runs.authority(
                db, f.principal.id, uuid.UUID(run_id), generation, admission
            )
            await assistant_dialogs.enroll(
                db, f.principal, f.author, f.cid, expected_assignee_id=None, manual=False
            )
            snapshot = await leadbot_reader._snapshot(
                db,
                str(f.cid),
                {"principal_id": str(f.principal.id), "operator_id": str(f.author.id)},
            )
            f.source = snapshot[0]["source_sha256"]
        bridge.gateway = root_execution.Gateway(
            sim.root / "actual-Main-commands",
            key=lambda: EXEC_KEY,
            app_factory=apps,
            clock=time.time,
            schedule=bridge.queue.append,
            actions_enabled=True,
            office_enabled=True,
            notifications_enabled=False,
        )
        rpc = NativeResearchClient(
            enabled=True,
            key=lambda: EXEC_KEY,
            clock=time.time,
            transport=httpx.MockTransport(bridge.private),
        )
        f.service = NativeActionCoordinator(
            f.sessions,
            admission=admission,
            client=rpc,
            redis=f.redis,
            job_redis=f.service.job_redis,
            enabled=True,
            clock=time.time,
        )
        f.office = NativeOffice(
            f.sessions,
            f.redis,
            admission=admission,
            actions=f.service,
            enabled=True,
            crm_only=True,
            clock=time.time,
        )
        f.relay = NativeResearchRelay(
            f.sessions, admission=admission, client=rpc, enabled=True, clock=time.time
        )
        import uuid

        f.executor = uuid.uuid4()
        f.key = f.live.work_key(f.cid, f.source, "intake_form")
        configured.value.update(zip(("policy", "runtime", "map", "memory"), versions, strict=True))
        configured.value.update(
            auto_ready=True,
            office_enabled=True,
            crm_only=True,
            notifications_enabled=False,
            max_dialogs=1,
            scan_batch=1,
            settle_seconds=2.0,
        )
        configured.path.write_text(json.dumps(configured.value))
        app.dependency_overrides[office_api.office_service] = lambda: f.office
        bridge.root_app = app_root
        f.pair = bridge
        yield f
    finally:
        sim.tmp.cleanup()
        environment.stop()


async def advance_until(f, service, key, wanted):
    steps = []
    for _ in range(160):
        value = await service.advance(key)
        steps.append(value)
        if value["state"] in wanted:
            return value
        assert value["state"] not in ("blocked", "stopped", "expired", "parked"), steps
        await asyncio.sleep(0.25)
    raise AssertionError(steps)


async def prepared_form(f):
    await f.office.heartbeat(f.live, f.executor)
    assert (await f.office.capacity(f.live, f.cid, f.source))["capacity"] is True
    action = await f.service.screen(f.live, f.cid, f.source)
    await advance_until(f, f.service, action["action_key"], {"screened"})
    work = await f.relay.enqueue(f.live, f.cid, f.source, "intake_form")
    await advance_until(f, f.relay, work["work_id"], {"ready"})
    await f.office.offer(
        f.live, f.cid, f.source, research_key=work["work_id"], screen_key=action["action_key"]
    )
    # The actual host keeps heartbeating while Root builds and reviews a form.
    # Renew that same executor through the public service, never extend a grant.
    assert (await f.office.heartbeat(f.live, f.executor))["available"] is True
    leased = await f.office.poll(f.live, f.executor)
    assert "lease_id" in leased, leased
    return leased


async def test_actual_signed_Root_Main_source_form_and_office_contract(paired):
    f = paired
    leased = await prepared_form(f)
    assert leased["form"]["completion_mode"] == "crm_only"
    assert leased["form"]["form_extraction"]["lead"]["review"] is True
    assert str(leased["form"]["form_extraction"]["lead"]["partner"]) == "624"
    assert leased["source_sha256"] == f.source
    assert len(f.pair.sim.requests) == 2
    assert {"run_authority", "headers", "history"}.issubset({x["operation"] for x in f.pair.reads})
    assert any(x["operation"] == "recover" for x in f.pair.commands)
    report = {
        "source_sha256": f.source,
        "form_reference": leased["form"]["form_reference"],
        "mode": leased["form"]["completion_mode"],
        "simulated_model_calls": len(f.pair.sim.requests),
        "read_operations": [x["operation"] for x in f.pair.reads],
        "private_operations": [x["operation"] for x in f.pair.commands],
        "versions": list(f.live.versions),
        "leased": leased,
        "real_provider_calls": 0,
    }
    save_receipt("C121-real-Root-Main-form-receipt", report)


async def pump_office(f):
    for _ in range(4):
        for key in await f.service.due():
            await f.service.advance(key)
        for key in await f.office.due():
            await f.office.advance(key)


class Trace(TypedDict):
    method: str
    route: str
    status: int


async def start_in_panel(f, client, tmp_path, design):
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": f.principal.email, "password": DEFAULT_PASSWORD, "remember": True},
    )
    assert response.status_code == 200
    # The synthetic paired fixture supplies an enrolled conversation. Start the run
    # under test through the panel, before issuing any of its CRM work.
    async with f.sessions() as db:
        baseline = await assistant_runs.stop(
            db, f.principal.id, expected_generation=f.live.generation
        )
        await db.commit()
    started = await operate(client, f.redis, tmp_path, design, "start", f.author_name)
    generation = baseline["generation"]
    assert isinstance(generation, int)
    assert started["generation"] == generation + 1
    config = assistant_runtime.configuration()
    assert config is not None
    async with f.sessions() as db:
        f.live = await assistant_runs.authority(
            db, f.principal.id, uuid.UUID(started["runId"]), started["generation"], config.admission
        )
    assert f.live.operator_id == f.author.id
    return started


@pytest.mark.parametrize("paired", ["reply"], indirect=True)
async def test_c190_panel_start_to_one_reviewed_reply(paired, client, tmp_path):
    f = paired
    started = await start_in_panel(f, client, tmp_path, "classic")
    service = f.pair.root_app.research
    owner = service.native_authority.owner
    assert service.unique_replies_enabled is True
    full = "Здравствуйте! Из какого материала стены?"
    short = "Из какого материала стены?"
    wording = "Здравствуйте! Из какого материала у Вас стена?"
    root_reply_fixtures = importlib.import_module("test_unique_replies296")
    prior = root_reply_fixtures.proposed(service.jobs, 1, full, owner=owner)
    root_reply_fixtures.accept(service.jobs, prior)
    service.jobs.finalize(
        prior[0],
        prior[2],
        fresh=lambda: prior[2],
        finish=lambda _: {"reply": full, "needs_operator": False, "validation": []},
    )
    assert service.jobs.reply_available(owner, short)
    assert not service.jobs.reply_available(owner, full)
    meaning = {
        "intent": "Клиент хочет повесить полку.",
        "meaning": "Нужно повесить полку.",
        "note": "Материал стены ещё не указан.",
    }
    f.pair.sim.scripted_candidates = [dict(meaning, reply=short), dict(meaning, reply=wording)]
    delivery = await deliver_reviewed_reply(f, expected_text=wording, requires_rewording=True)
    stopped = await operate(client, f.redis, tmp_path, "classic", "stop", f.author_name)
    assert stopped["runId"] == started["runId"]
    assert stopped["generation"] == started["generation"] + 1
    save_receipt(
        "C191-classic-reply",
        {
            "start": started,
            "stop": stopped,
            "reply_revised_before_review": True,
            "model_fixture_roles": delivery["roles"],
            "local_messages": 1,
            "synthetic_vendor_calls": delivery["synthetic_vendor_calls"],
            "actual_provider_or_business_calls": 0,
        },
    )


async def deliver_reviewed_reply(f, *, expected_text=None, requires_rewording=False):
    service = f.pair.root_app.research
    work = await f.relay.enqueue(f.live, f.cid, f.source, "reply")
    ready = await advance_until(f, f.relay, work["work_id"], {"ready"})
    assert ready["can_send_or_create"] is False
    async with f.sessions() as db:
        original = await db.get(AssistantResearchWork, work["work_id"])
        result = json.loads(original.result)
        job = json.loads(original.binding)["research_job_id"]
    wording = result["reply"]
    assert result["validation"] == [] and wording.strip()
    if expected_text is not None:
        assert wording == expected_text
    if requires_rewording:
        receipt = service.jobs.audit_read(service.native_authority.owner, job)
        assert any(e["event"] == "reply_revision_required" for e in receipt["events"])
    roles = [json.loads(packet["instructions"])["role"] for packet in f.pair.sim.requests]
    assert roles == (
        ["research", "research", "review"] if requires_rewording else ["research", "review"]
    )
    action = await f.service.enqueue(f.live, f.cid, f.source, research_key=work["work_id"])
    await advance_until(f, f.service, action["action_key"], {"dispatch"})
    async with f.sessions() as db:
        messages = (
            await db.scalars(
                select(Message).where(Message.conversation_id == f.cid, Message.direction == "out")
            )
        ).all()
        assert len(messages) == 1 and messages[0].body == wording
        assert messages[0].sender_user_id == f.author.id
        message_id = messages[0].id
        assert await db.get(AssistantNativeOutbound, message_id) is not None
    guard = await assistant_outbound.for_message(
        {
            "db_session_factory": f.sessions,
            "native_delivery_runtime": assistant_outbound.NativeDeliveryRuntime(
                f.service.admission, True, time.time
            ),
        },
        message_id,
    )
    assert guard is not None
    vendor = AsyncMock(return_value="authored-c191-delivery")
    assert await guard.send(0, wording, vendor) == "authored-c191-delivery"
    assert await guard.send(0, wording, vendor) == "authored-c191-delivery"
    assert vendor.await_count == 1
    return {
        "roles": roles,
        "message_id": message_id,
        "action_key": action["action_key"],
        "synthetic_vendor_calls": vendor.await_count,
    }


@pytest.mark.parametrize("design", ["classic", "new"])
@pytest.mark.parametrize("failure", ["permission", "card"])
async def test_lost_ack_recovery_after_native_ui_resume(
    paired, client, tokens, tmp_path, design, failure
):
    f = paired
    started = await start_in_panel(f, client, tmp_path, design)
    report = await recover_office(f, client, tokens, tmp_path, design, failure, started)
    save_receipt("C182-" + design + "-" + failure, report)


async def recover_office(f, client, tokens, tmp_path, design, failure, started, *, calls_before=0):
    duplicate = failure == "duplicate"
    f.key = f.live.work_key(f.cid, f.source, "intake_form")
    leased = await prepared_form(f)
    seed = {
        "principal_id": str(f.principal.id),
        "operator_id": str(f.author.id),
        "run_id": str(f.live.run_id),
        "cid": str(f.cid),
        "executor_id": str(f.executor),
        "lease_id": leased["lease_id"],
        "work_id": f.key,
        "source_sha256": f.source,
        "form": leased["form"],
        "message_revision": leased["message_revision"],
        "required_fields": leased["required_fields"],
        "now_ms": time.time() * 1000,
        "scenario": "duplicate_match" if duplicate else "lost_ack",
        "seed": await current_proposal_seed(f, leased),
    }
    environment = {
        k: v
        for k, v in os.environ.items()
        if k in ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR")
    }
    owned = HERE / ("C121-node-owned-" + uuid.uuid4().hex)
    owned.mkdir(mode=0o700)
    environment.update(
        NODE_OPTIONS="--require=" + str(HERE / "C114-local-network-guards266-v1/node-guard.cjs"),
        CODEX_LOCAL_TEST_GUARD_ROOT=str(owned),
        CODEX_LOCAL_TEST_GUARD_NONCE=uuid.uuid4().hex,
    )
    process = await asyncio.create_subprocess_exec(
        "node",
        str(HERE / "paired-client.cjs"),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=environment,
    )
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    incoming, outgoing = process.stdout, process.stdin
    errors = asyncio.create_task(process.stderr.read())
    outgoing.write((json.dumps({"kind": "seed", "data": seed}) + "\n").encode())
    await outgoing.drain()
    headers = {"Authorization": "Bearer " + tokens["admin"]}
    trace: list[Trace] = []
    result = None
    lost = False
    original_boundary = None
    resumed = None
    issued = None
    old_permit_status = None
    failed_reply = None
    recovered_reason = None

    async def exchange():
        nonlocal result, lost, issued, original_boundary, resumed, old_permit_status
        nonlocal failed_reply, recovered_reason
        while line := await incoming.readline():
            request = json.loads(line)
            if request["kind"] == "done":
                result = request["result"]
                return
            assert request["kind"] == "request"
            method, route = request["method"], request["route"]
            if method == "CONTROL":
                assert route == "stop" and resumed is None
                if duplicate:
                    assert not lost and issued is None and failed_reply is not None
                else:
                    assert lost and issued is not None
                original_boundary = await operate(
                    client,
                    f.redis,
                    tmp_path,
                    design,
                    "blocked" if failure == "permission" else "stop",
                    f.author_name,
                )
                resumed = await operate(client, f.redis, tmp_path, design, "start", f.author_name)
                # Probe the original request after the new Run is active. The
                # extension itself is allowed to read only the original status.
                if issued is not None:
                    original_route, original_body = issued
                    replay = await client.post(
                        "/api/v1" + original_route, json=original_body, headers=headers
                    )
                    old_permit_status = replay.status_code
                    assert old_permit_status == 409
                trace.append({"method": "CONTROL", "route": "stop_and_resume", "status": 200})
                outgoing.write((json.dumps({"id": request["id"], "data": None}) + "\n").encode())
                await outgoing.drain()
                continue

            assert route.startswith("/bot-dialogs/assistant/")
            if duplicate:
                assert not route.endswith(
                    ("/request-create", "/issue-create", "/created", "/card", "/followup")
                )
            await pump_office(f)
            if route.endswith("/card"):
                async with f.sessions() as db:
                    conv = await db.get(Conversation, f.cid)
                    assert conv.status != "closed"
            response = await client.request(
                method, "/api/v1" + route, json=request.get("body"), headers=headers
            )
            trace.append({"method": method, "route": route, "status": response.status_code})
            body = response.json()
            if duplicate and route.endswith("/failed"):
                assert request["body"]["stop_reason"] == "crm_existing_request"
                assert set(request["body"]) == {
                    "expected_principal_id",
                    "operator_id",
                    "run_id",
                    "generation",
                    "executor_id",
                    "work_id",
                    "lease_id",
                    "stop_reason",
                }
                assert response.status_code == 200 and body["state"] == "stopped"
                assert body["reason_code"] == "crm_existing_request"
                failed_reply = body
            if duplicate and resumed and route.endswith("/status"):
                assert response.status_code == 200 and body["state"] == "stopped"
                assert body["execution_allowed"] is False
                assert body["crm_request_id"] is None
                recovered_reason = body.get("reason_code")
            reply = {"id": request["id"], "data": body}
            if response.status_code >= 400:
                reply = {"id": request["id"], "error": "HTTP " + str(response.status_code)}
            if duplicate and route.endswith("/failed"):
                reply = {"id": request["id"], "error": "Lost original duplicate-stop response"}
            if route.endswith("/issue-create") and body.get("execution_allowed") is True:
                assert issued is None and response.status_code == 200
                issued = (route, request["body"])
                if failure == "permission":
                    lost = True
                    reply = {"id": request["id"], "error": "Lost original create permit response"}
            if route.endswith("/card"):
                assert failure == "card" and not lost
                assert response.status_code == 200 and body["dialog_closed"] is True
                lost = True
                reply = {"id": request["id"], "error": "Lost original confirmed card response"}
            outgoing.write((json.dumps(reply) + "\n").encode())
            await outgoing.drain()

    try:
        await asyncio.wait_for(exchange(), timeout=80)
        await asyncio.wait_for(process.wait(), timeout=5)
        stderr = (await errors).decode()
        assert process.returncode == 0, stderr
        assert result is not None, stderr
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except TimeoutError:
                process.kill()
                await process.wait()
        if not errors.done():
            await errors
    assert result["telegramReads"] == 0
    if duplicate:
        assert failed_reply is not None and issued is None and old_permit_status is None
    else:
        assert lost and old_permit_status == 409
    assert original_boundary is not None and resumed is not None
    assert original_boundary["runId"] == started["runId"]
    assert original_boundary["generation"] == started["generation"] + 1
    assert resumed["runId"] != started["runId"]
    assert resumed["generation"] == original_boundary["generation"] + 1
    recovery = trace[next(i for i, r in enumerate(trace) if r["method"] == "CONTROL") + 1 :]
    assert recovery and all(r["route"].endswith("/status") and r["status"] == 200 for r in recovery)
    if duplicate:
        config = assistant_runtime.configuration()
        assert config is not None
        async with f.sessions() as db:
            resumed_live = await assistant_runs.authority(
                db,
                f.principal.id,
                uuid.UUID(resumed["runId"]),
                resumed["generation"],
                config.admission,
            )
        assert await f.office.observe_owned(resumed_live, f.cid) == {
            "state": "prior_attempt_review",
            "execution_allowed": False,
        }
        observed = await operate(client, f.redis, tmp_path, design, "duplicate", f.author_name)
        assert observed["runId"] == resumed["runId"]
    final_stop = await operate(client, f.redis, tmp_path, design, "stop", f.author_name)
    assert final_stop["runId"] == resumed["runId"]
    assert final_stop["generation"] == resumed["generation"] + 1

    if duplicate:
        assert result["physical_crm_posts"] == result["CRM_POST_count"] == 0
        assert result["submitted"] == result["verified"] == []
        assert result["events"] == ["DUPLICATE_LOOKUP"]
        assert result["createOutcomes"] == [
            {"skipped": True, "dispatched": False, "existing_case_identified": True}
        ]
        assert recovered_reason == "crm_existing_request"
        assert sorted(result["records"], key=lambda record: record["state"]) == [
            {"state": "no_write", "created_id": None},
            {
                "state": "stopped_before_create",
                "created_id": None,
                "reason_code": recovered_reason,
            },
        ]
        async with f.sessions() as db:
            conv = await db.get(Conversation, f.cid)
            office = await db.get(AssistantOfficeWork, f.key)
            assert conv.status != "closed" and conv.crm_request_id is None
            assert office is not None and office.stage == "stopped"
            assert office.create_issued_at is None and office.created_id is None
            assert office.reason_code == recovered_reason
            assert (
                await db.scalars(
                    select(AssistantOfficeWork.key).where(
                        AssistantOfficeWork.conversation_id == f.cid
                    )
                )
            ).all() == [f.key]
        assert not any(
            p["operation"] in ("consume_office", "reserve_followup") for p in f.pair.commands
        )
        assert len(f.pair.sim.requests) == calls_before + 2
        return {
            "design": design,
            "result": result,
            "trace": trace,
            "preexisting_card_not_written": True,
            "dialog_open_without_crm_id": True,
            "stop_reason_from_api": recovered_reason,
            "stop_reason_shown_in_panel": True,
            "resumed_run_observes_original_attempt_only": True,
            "original_create_permission_issued": False,
            "models": len(f.pair.sim.requests),
            "actual_provider_or_business_calls": 0,
        }

    completed = failure == "card"
    assert result["physical_crm_posts"] == int(completed), (result, trace)
    assert result["CRM_POST_count"] == int(completed)
    records = [r for r in result["records"] if r["state"] == "completed"]
    assert len(records) == int(completed), (result, trace)
    async with f.sessions() as db:
        conv = await db.get(Conversation, f.cid)
        office = await db.get(AssistantOfficeWork, f.key)
        assert office is not None and office.create_issued_at is not None
        assert office.stage == ("completed" if completed else "created_review")
        assert office.created_id == ("1234567" if completed else None)
        assert (conv.status == "closed") == completed
        assert conv.crm_request_id == ("1234567" if completed else None)
    if completed:
        assert "отзыв" in result["verified"][-1]["fields"]
        assert result["verified"][-1]["diffs"] == []
        assert records[0]["created_id"] == "1234567" and records[0]["telegram_confirmed"] is False
        assert result["submitted"] == [
            {
                "branch": str(result["prepared_proposal"]["sel"]["cityId"]),
                "partner": "id-624",
                "review": "1",
            }
        ]
    assert sum(p["operation"] == "reserve_office" for p in f.pair.commands) == 1
    assert sum(p["operation"] == "consume_office" for p in f.pair.commands) == 1
    assert len(f.pair.sim.requests) == calls_before + 2
    report = {
        "lost_response": failure,
        "design": design,
        "start_from_chromium": started,
        "original_boundary_from_chromium": original_boundary,
        "resume_from_chromium": resumed,
        "final_stop_from_chromium": final_stop,
        "old_permit_replay_http_status": old_permit_status,
        "result": result,
        "trace": trace,
        "source_sha256": f.source,
        "form_reference": leased["form"]["form_reference"],
        "simulated_model_calls": len(f.pair.sim.requests),
        "Root_private_operations": [p["operation"] for p in f.pair.commands],
        "Main_signed_read_operations": [p["operation"] for p in f.pair.reads],
        "Node_exit": process.returncode,
        "actual_provider_or_business_calls": 0,
    }
    return report


async def refresh_source(f):
    async with f.sessions() as db:
        snapshot = await leadbot_reader._snapshot(
            db,
            str(f.cid),
            {"principal_id": str(f.principal.id), "operator_id": str(f.author.id)},
        )
    f.source = snapshot[0]["source_sha256"]
    return f.source


def load_worker_delivery():
    worker = HERE.parent / "C171-exact-worker-c165"
    relative = "workers/deliver.py"
    source = worker / "worker/app" / relative
    manifest = json.loads((worker / "C171-local-c165-overlay.json").read_text())
    assert hashlib.sha256(source.read_bytes()).hexdigest() == manifest["files_sha256"][relative]
    spec = importlib.util.spec_from_file_location("c192_worker_delivery", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("paired", ["single_dialogue"], indirect=True)
@pytest.mark.parametrize("design", ["classic", "new"])
async def test_c192_one_dialogue_from_reply_to_recovered_card(
    paired, client, tokens, tmp_path, monkeypatch, design
):
    f = paired
    started = await start_in_panel(f, client, tmp_path, design)
    incoming_source = f.source
    delivery = await deliver_reviewed_reply(f)
    async with f.sessions() as db:
        conv = await db.get(Conversation, f.cid)
        account = await db.get(AvitoAccount, conv.account_id)
        account.access_token_enc = crypto.encrypt_token("authored-c192-transport-token")
        account.refresh_token_enc = crypto.encrypt_token("authored-c192-refresh-token")
        await db.commit()
    fake = SimpleNamespace(send_message=AsyncMock(return_value="must-not-send-again"))
    deliver = load_worker_delivery()
    monkeypatch.setattr(deliver._OutboundClient, "fresh", AsyncMock(return_value=fake))
    monkeypatch.setattr(deliver.AvitoRateLimiter, "acquire", AsyncMock())
    await deliver.deliver_message(
        {
            "db_session_factory": f.sessions,
            "redis": f.redis,
            "job_try": 1,
            "native_delivery_runtime": assistant_outbound.NativeDeliveryRuntime(
                f.service.admission, True, time.time
            ),
        },
        delivery["message_id"],
    )
    fake.send_message.assert_not_awaited()
    observed = await f.service.observe(delivery["action_key"])
    assert observed["state"] == "delivered" and observed["customer_effect_confirmed"] is True

    before_consent = await refresh_source(f)
    assert before_consent != incoming_source
    check = await f.service.screen(f.live, f.cid, before_consent)
    await advance_until(f, f.service, check["action_key"], {"screened"})
    async with f.sessions() as db:
        screen = await db.get(AssistantNativeAction, check["action_key"])
        step = json.loads(screen.result)["step"]
        assert step != "prepare_crm"
        assert not (await db.scalars(select(AssistantOfficeWork))).all()
        fixture = root_workflow_fixtures.WorkflowTests()
        first = fixture.ctx()["messages"][0]["body"]
        complete = fixture.ctx(True)["messages"][0]["body"]
        assert complete.startswith(first)
        db.add(
            Message(
                conversation_id=f.cid,
                direction="in",
                sender_type="client",
                external_message_id="authored-c192-consent",
                body="Да, согласен, оформляйте заявку на выезд." + complete.removeprefix(first),
                attachments=[],
                delivery_status="delivered",
            )
        )
        await db.commit()

    after_consent = await refresh_source(f)
    assert after_consent not in {incoming_source, before_consent}
    report = await recover_office(
        f, client, tokens, tmp_path, design, "card", started, calls_before=2
    )
    events = report["result"]["events"]
    assert events.index("DUPLICATE_LOOKUP") < events.index("CRM_POST") < events.index("CARD_READ")
    async with f.sessions() as db:
        outbound = (
            await db.scalars(
                select(Message).where(Message.conversation_id == f.cid, Message.direction == "out")
            )
        ).all()
        assert len(outbound) == 1 and outbound[0].id == delivery["message_id"]
        assert outbound[0].delivery_status == "delivered"
    report.update(
        cid=str(f.cid),
        initial_source_sha256=incoming_source,
        delivered_source_sha256=before_consent,
        consent_source_sha256=after_consent,
        step_before_consent=step,
        original_reply_deliveries=delivery["synthetic_vendor_calls"],
        duplicate_lookup_before_crm=True,
    )
    save_receipt("C192-" + design + "-same-dialogue", report)


@pytest.mark.parametrize("design", ["classic", "new"])
async def test_c194_existing_crm_request_reason_survives_lost_ack_and_restart(
    paired, client, tokens, tmp_path, design
):
    f = paired
    started = await start_in_panel(f, client, tmp_path, design)
    report = await recover_office(f, client, tokens, tmp_path, design, "duplicate", started)
    save_receipt("C194-" + design + "-existing-card", report)
