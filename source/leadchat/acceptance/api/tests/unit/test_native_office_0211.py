"""Actual ORM/Run/source/action journal; CRM and private peer are simulated."""

import importlib.util
import json
import time
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, inspect, select

from app.api.routes import assistant_office as api
from app.core.errors import ApiError
from app.models import (
    AssistantNativeAction,
    AssistantNativeCommand,
    AssistantNativeOutbound,
    AssistantOfficeResource,
    AssistantOfficeWork,
    AssistantResearchWork,
    AssistantRun,
    AuditLog,
    Conversation,
    Message,
    User,
)
from app.services import assistant_dialogs, assistant_runs, assistant_runtime, leadbot_reader
from app.services import leadbot_execution_protocol as wire
from app.services.assistant_driver import NativeDialogDriver
from app.services.assistant_office import CORE_FIELDS, NativeOffice
from app.services.assistant_research import NativeResearchRelay
from app.workers.assistant_office import native_office_step
from tests.unit import test_native_actions_0111 as fixtures
from tests.unit import test_native_driver_0111 as driver_fixtures
from tests.unit import test_native_office_protocol_0211 as protocol

native_action = fixtures.native_action
configured = importlib.import_module("tests.unit.test_native_runtime_0111").configured
BASE = "/api/v1/bot-dialogs/assistant/native-office"


class OfficePeer:
    def __init__(self, f):
        self.f, self.calls, self.originals = f, [], {}
        self.lost = None
        self.hook = None
        self.reject_inspect = False
        self.reject_operation = None

    async def __call__(self, request):
        f = self.f
        packet, nonce = wire.verify(fixtures.KEY, request.content, request.headers, now=f.now[0])
        operation, args = packet["operation"], packet["arguments"]
        self.calls.append(packet)
        if self.hook:
            await self.hook(packet)
        if operation == "recover":
            value = self.originals[args["command_id"]]
            data = {
                "ok": True,
                "command_id": args["command_id"],
                "command_state": "done",
                "original_result": value,
                "original_status": 200,
            }
        elif operation == "inspect":
            data = {
                "ok": True,
                "eligible": True,
                "step": "prepare_crm",
                "source_sha256": args["source_sha256"],
                "operation_id": "office-original",
                "revision": "rev-original",
                "message_revision": "c" * 64,
                "crm_required_fields": ["улица", "дом", "отзыв"],
            }
        elif operation == "reserve_office":
            data = {
                "ok": True,
                "reserved": True,
                "execution_allowed": False,
                "grant_id": "office-grant-original",
            }
        elif operation == "consume_office":
            data = {
                "ok": True,
                "execution_allowed": True,
                "customer_effect_confirmed": False,
                "grant_id": args["grant_id"],
                "dispatch_before": f.now[0] + 10,
                "kind": "create_crm",
                "chat": args["cid"],
                "operator_id": packet["operator_id"],
                "source_sha256": args["source_sha256"],
                "revision": args["revision"],
                "operation_id": args["operation_id"],
                "snapshot_hash": args["snapshot_hash"],
                "form_reference": args["proposal"]["form_reference"],
                "native_launch_binding": "b" * 64,
            }
        else:
            raise AssertionError("No model/vendor/CRM/Telegram endpoint is available")
        result = {"ok": True, "data": data, "can_send_or_create": False}
        if operation == self.reject_operation or operation == "inspect" and self.reject_inspect:
            result = {
                "ok": False,
                "data": {"code": "synthetic_hard_error"},
                "can_send_or_create": False,
            }
        self.originals[packet["command_id"]] = result
        if self.lost == operation:
            self.lost = None
            raise httpx.ReadTimeout("Synthetic observation loss")
        raw = wire.encode(result)
        return httpx.Response(
            200,
            content=raw,
            headers={
                "content-type": "application/json",
                "X-LB-Exec-Signature": wire.response_signature(fixtures.KEY, raw, nonce, 200),
            },
        )


@pytest.fixture
async def office(native_action):
    f = native_action
    f.now[0] = time.time() + 2
    f.executor = uuid.uuid4()
    f.office = NativeOffice(
        f.sessions,
        f.redis,
        admission=fixtures.READY,
        actions=f.service,
        enabled=True,
        clock=lambda: f.now[0],
    )
    f.peer = OfficePeer(f)
    f.service.client = fixtures.NativeResearchClient(
        enabled=True,
        key=lambda: fixtures.KEY,
        clock=lambda: f.now[0],
        transport=httpx.MockTransport(f.peer),
    )
    async with f.sessions() as db:
        await assistant_dialogs.enroll(
            db, f.principal, f.author, f.cid, expected_assignee_id=None, manual=False
        )
        source = await leadbot_reader._snapshot(
            db,
            str(f.cid),
            {
                "principal_id": str(f.principal.id),
                "operator_id": str(f.author.id),
            },
        )
        f.source = source[0]["source_sha256"]
    f.key = f.live.work_key(f.cid, f.source, "intake_form")
    f.proposal = protocol.office_packet()["arguments"]["proposal"]
    f.proposal.update(revision="rev-original", form_reference="a" * 64)
    f.proposal["lead"].update(
        partner_note="Проверенная служебная запись", addr={"street": "Тестовая", "building": "1"}
    )
    yield f


async def ready(f, *, form_extra=None):
    await f.office.heartbeat(f.live, f.executor)
    assert (await f.office.capacity(f.live, f.cid, f.source))["capacity"] is True
    f.screen = (await f.service.screen(f.live, f.cid, f.source))["action_key"]
    assert (await f.service.advance(f.screen))["state"] == "screened"
    form = {
        "ok": True,
        "action": "ready",
        "auto_enabled": False,
        "needs_operator": False,
        "can_send_or_create": False,
        "reply": "",
        "intake_form_ready": True,
        "form_reference": "a" * 64,
        "revision": "rev-original",
        "form_extraction": {"ok": True, "lead": {"problem": "Работа"}},
        "routing": {"direction": "kp"},
        "facts": {},
        "lead": {},
        "crm_flags": {},
        "crm_route": {},
        "research_job_id": "original-form-job",
        "policy_version": "policy",
    }
    if form_extra:
        form.update(form_extra)
    async with f.sessions() as db:
        db.add(
            AssistantResearchWork(
                key=f.key,
                principal_id=f.live.principal_id,
                operator_id=f.live.operator_id,
                run_id=f.live.run_id,
                generation=f.live.generation,
                conversation_id=f.cid,
                dialog_version=1,
                versions=wire.encode(f.live.versions).decode(),
                source_hash=f.source,
                purpose="intake_form",
                stage="ready",
                deadline=f.now[0] + 300,
                due=f.now[0],
                lease_until=0,
                result=json.dumps(form),
            )
        )
        await db.commit()
    value = await f.office.offer(f.live, f.cid, f.source, research_key=f.key, screen_key=f.screen)
    assert value["state"] == "ready" and value["execution_allowed"] is False
    leased = await f.office.poll(f.live, f.executor)
    f.lease = uuid.UUID(leased["lease_id"])
    assert set(leased["form"]) <= set(form)
    return leased


async def reserved(f):
    await ready(f)
    await f.office.prepare(f.live, f.key, f.executor, f.lease, f.proposal)
    assert (await f.office.advance(f.key))["state"] == "authorizing"
    async with f.sessions() as db:
        work = await db.get(AssistantOfficeWork, f.key)
        f.action = work.action_key
    assert (await f.service.advance(f.action))["state"] == "reserve_action"
    assert (await f.service.advance(f.action))["state"] == "office_reserved"
    assert (await f.office.advance(f.key))["state"] == "office_reserved"


async def consumable(f):
    await reserved(f)
    await f.office.request_create(f.live, f.key, f.executor, f.lease)
    await f.office.advance(f.key)
    assert (await f.service.advance(f.action))["state"] == "apply"
    assert (await f.service.advance(f.action))["state"] == "office_ready"


async def issued(f):
    await consumable(f)
    permitted = await f.office.issue_create(f.live, f.key, f.executor, f.lease)
    assert permitted["execution_allowed"] is True
    return permitted


async def created(f):
    await issued(f)
    f.report = {
        "id": "123456",
        "url": "https://kp-lead-centre.ru/admin/domain/customer-request/update?id=123456",
    }
    return await f.office.capture_created(f.live, f.key, f.executor, f.lease, f.report)


async def card_report(f):
    async with f.sessions() as db:
        work = await db.get(AssistantOfficeWork, f.key)
        fields = json.loads(work.required_fields)
        return {
            **f.report,
            "snapshot_hash": work.snapshot_hash,
            "form_reference": "a" * 64,
            "message_revision": "c" * 64,
            "policy_version": "policy",
            "warnings": [],
            "verified": {"checked": len(fields), "diffs": [], "fields": fields},
        }


async def stop(f):
    async with f.sessions() as db:
        await assistant_runs.stop(db, f.principal.id, expected_generation=f.live.generation)
        await db.commit()


async def assert_no_effects(f):
    async with f.sessions() as db:
        # enroll() legitimately keeps its original internal assignment event.
        assert (
            await db.scalar(
                select(func.count()).select_from(Message).where(Message.direction == "out")
            )
            == 0
        )
        assert await db.scalar(select(func.count()).select_from(AssistantNativeOutbound)) == 0
        conv = await db.get(Conversation, f.cid)
        assert conv.crm_request_id is None and conv.status != "closed"


async def test_offline_executor_waits_before_any_form_or_private_request(office):
    f = office
    value = await f.office.capacity(f.live, f.cid, f.source)
    assert value == {"state": "waiting_executor", "model_started": False}
    async with f.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(AssistantOfficeWork)) == 0
        assert await db.scalar(select(func.count()).select_from(AssistantResearchWork)) == 0
    assert f.peer.calls == []


async def test_availability_is_exact_single_executor_but_never_starts_a_run(office):
    f = office
    assert (await f.office.heartbeat(f.live, f.executor))["available"] is True
    assert (await f.office.heartbeat(f.live, uuid.uuid4()))["available"] is False
    f.now[0] += 91
    assert await f.office.available(f.live) is False
    assert (await f.office.heartbeat(f.live, uuid.uuid4()))["available"] is True
    await stop(f)
    with pytest.raises(ApiError):
        await f.office.heartbeat(f.live, f.executor)
    await assert_no_effects(f)


async def test_ready_form_lease_preserves_original_and_conditional_read_requirements(office):
    f = office
    leased = await ready(f)
    assert CORE_FIELDS | {"улица", "дом", "отзыв"} == set(leased["required_fields"])
    assert leased["source_sha256"] == f.source and leased["execution_allowed"] is False
    assert leased["form"]["research_job_id"] == "original-form-job"
    assert "model_task" not in leased["form"]
    original_deadline = leased["deadline"]
    f.now[0] += 10
    later = await f.office.poll(f.live, f.executor)
    assert later["lease_id"] == str(f.lease) and later["deadline"] == original_deadline
    await assert_no_effects(f)


async def test_office_reservation_does_not_automatically_consume_or_use_outbox(office):
    f = office
    await reserved(f)
    for _ in range(3):
        assert (await f.service.advance(f.action))["state"] == "office_reserved"
        assert (await f.office.advance(f.key))["state"] == "office_reserved"
    assert [p["operation"] for p in f.peer.calls] == ["inspect", "inspect", "reserve_office"]
    await assert_no_effects(f)


async def test_exact_original_consume_is_emitted_physically_once_and_lost_ack_does_not_repeat(
    office,
):
    f = office
    first = await issued(f)  # Pretend the caller never receives this response.
    again = await f.office.issue_create(f.live, f.key, f.executor, f.lease)
    assert first["state"] == "create_started" and again["execution_allowed"] is False
    assert again["reconciliation_only"] is True
    async with f.sessions() as db:
        action = await db.get(AssistantNativeAction, f.action)
        command = await db.get(AssistantNativeCommand, action.consume_command_id)
        assert action.stage == "office_issued" and command.http_status == 200
        assert json.loads(command.request)["operation"] == "consume_office"
    assert sum(p["operation"] == "consume_office" for p in f.peer.calls) == 1
    await assert_no_effects(f)


@pytest.mark.parametrize("change", ["stop", "source", "role", "takeover", "lease", "deadline"])
async def test_fresh_gates_reject_changes_before_physical_issue(office, change):
    f = office
    await consumable(f)
    if change == "stop":
        await stop(f)
    elif change == "source":
        async with f.sessions() as db:
            db.add(
                Message(
                    conversation_id=f.cid,
                    direction="in",
                    sender_type="client",
                    body="Исправление: другая работа.",
                    attachments=[],
                    delivery_status="delivered",
                )
            )
            await db.commit()
    elif change == "role":
        async with f.sessions() as db:
            user = await db.get(User, f.principal.id)
            user.is_active = False
            await db.commit()
    elif change == "takeover":
        async with f.sessions() as db:
            conv = await db.get(Conversation, f.cid)
            conv.assignee_id = f.principal.id
            await db.commit()
    elif change == "lease":
        f.lease = uuid.uuid4()
    else:
        f.now[0] += 11  # Original Root consume deadline, not a newly minted window.
    with pytest.raises((ValueError, ApiError)):
        await f.office.issue_create(f.live, f.key, f.executor, f.lease)
    async with f.sessions() as db:
        assert (await db.get(AssistantOfficeWork, f.key)).create_issued_at is None
    await assert_no_effects(f)


async def test_private_observation_loss_recovers_same_office_command_without_second_reservation(
    office,
):
    f = office
    await ready(f)
    await f.office.prepare(f.live, f.key, f.executor, f.lease, f.proposal)
    await f.office.advance(f.key)
    async with f.sessions() as db:
        f.action = (await db.get(AssistantOfficeWork, f.key)).action_key
    await f.service.advance(f.action)
    f.peer.lost = "reserve_office"
    assert (await f.service.advance(f.action))["state"] == "reserve_action"
    assert (await f.service.advance(f.action))["state"] == "office_reserved"
    operations = [p["operation"] for p in f.peer.calls]
    assert operations.count("reserve_office") == 1 and operations.count("recover") == 1
    await assert_no_effects(f)


@pytest.mark.parametrize("invalid", ["credential", "form", "history", "changed"])
async def test_invalid_or_changed_proposal_is_not_silently_repaired_or_replaced(office, invalid):
    f = office
    await ready(f)
    if invalid == "credential":
        f.proposal["lead"]["api_key"] = "synthetic-never-a-real-key"
    elif invalid == "form":
        f.proposal["form_reference"] = "d" * 64
    elif invalid == "history":
        f.proposal["history"] = "Unrelated body is not an allowed office payload"
    else:
        await f.office.prepare(f.live, f.key, f.executor, f.lease, f.proposal)
        f.proposal["lead"]["comment"] = "Changed after original preparation"
    before = len(f.peer.calls)
    with pytest.raises(ValueError):
        await f.office.prepare(f.live, f.key, f.executor, f.lease, f.proposal)
    assert len(f.peer.calls) == before
    async with f.sessions() as db:
        work = await db.get(AssistantOfficeWork, f.key)
        if invalid != "changed":
            assert work.proposal is None


async def test_original_form_mutation_blocks_even_a_previously_reserved_form(office):
    f = office
    await reserved(f)
    async with f.sessions() as db:
        form = await db.get(AssistantResearchWork, f.key)
        value = json.loads(form.result)
        value["lead"] = {"phone": "invented"}
        form.result = json.dumps(value)
        await db.commit()
    with pytest.raises(ValueError):
        await f.office.request_create(f.live, f.key, f.executor, f.lease)


async def test_accepted_visit_evidence_is_preserved_for_existing_extension_projection(office):
    f = office
    # A separate current accepted original includes the authorized reply
    # window. It must reach projectAcceptedVisit, not fall back to old dates.
    window = {
        "source": "authorized_extension_reply",
        "appointment_created": False,
        "proposal_message_id": "proposal",
        "answer_message_id": "answer",
        "operation_id": "window-operation",
        "proposal_quote": "После 16 часов",
        "answer_quote": "Да, так удобно",
        "min_minutes": 60,
        "earliest_at": f.now[0] + 3600,
        "latest_at": f.now[0] + 7200,
        "timezone": "Europe/Moscow",
    }
    await ready(f, form_extra={"accepted_visit": window})
    leased = await f.office.poll(f.live, f.executor)
    assert leased["form"]["accepted_visit"] == window
    await assert_no_effects(f)


async def test_created_id_is_only_unverified_evidence_and_survives_stop_without_new_action(office):
    f = office
    await issued(f)
    await stop(f)
    report = {
        "id": "123456",
        "url": "https://kp-lead-centre.ru/admin/domain/customer-request/update?id=123456",
    }
    value = await f.office.capture_created(f.live, f.key, f.executor, f.lease, report)
    assert value["state"] == "created_unverified" and value["created_id_verified"] is False
    value2 = await f.office.capture_created(f.live, f.key, f.executor, f.lease, report)
    assert value2 == value
    report["id"] = "654321"
    with pytest.raises(ValueError):
        await f.office.capture_created(f.live, f.key, f.executor, f.lease, report)
    await assert_no_effects(f)


async def test_unknown_physical_result_keeps_global_create_fence(office):
    f = office
    await issued(f)
    assert (await f.office.fail(f.live, f.key, f.executor, f.lease))["state"] == "created_review"
    async with f.sessions() as db:
        assert (await db.get(AssistantOfficeResource, "crm")).work_key == f.key
    assert (await f.office.status(f.live, f.key, f.executor, f.lease))["state"] == "created_review"
    async with f.sessions() as db:
        run = await db.get(AssistantRun, f.principal.id)
        assert run.state == "blocked" and run.generation == f.live.generation + 1
    with pytest.raises(ApiError):
        await f.office.poll(f.live, f.executor)
    with pytest.raises(ApiError):
        await f.office.request_create(f.live, f.key, f.executor, f.lease)


async def test_each_same_id_followup_has_its_own_single_issue_and_cannot_consume_create_again(
    office,
):
    f = office
    await created(f)
    for kind in ("partner_note", "customer_contact"):
        value = await f.office.followup(f.live, f.key, f.executor, f.lease, "123456", kind)
        assert value["execution_allowed"] is True and value["kind"] == kind
        repeated = await f.office.followup(f.live, f.key, f.executor, f.lease, "123456", kind)
        assert repeated["execution_allowed"] is False
    with pytest.raises(ValueError):
        await f.office.followup(f.live, f.key, f.executor, f.lease, "654321", "partner_note")
    assert sum(p["operation"] == "consume_office" for p in f.peer.calls) == 1


@pytest.mark.parametrize(
    "invalid", ["missing_field", "diff", "warning", "snapshot", "policy", "id"]
)
async def test_card_requires_every_field_original_binding_and_no_unresolved_differences(
    office, invalid
):
    f = office
    await created(f)
    report = await card_report(f)
    if invalid == "missing_field":
        report["verified"]["fields"].remove("отзыв")
    elif invalid == "diff":
        report["verified"]["diffs"] = ["Номер не совпал"]
    elif invalid == "warning":
        report["warnings"] = ["Не проверен дом"]
    else:
        report[{"snapshot": "snapshot_hash", "policy": "policy_version", "id": "id"}[invalid]] = (
            "wrong"
        )
    with pytest.raises(ValueError):
        await f.office.capture_card(f.live, f.key, f.executor, f.lease, report)
    async with f.sessions() as db:
        assert (await db.get(AssistantOfficeWork, f.key)).card_receipt is None
    await assert_no_effects(f)


async def test_verified_card_releases_crm_resource_but_cannot_fake_telegram_or_close(office):
    f = office
    await created(f)
    value = await f.office.capture_card(f.live, f.key, f.executor, f.lease, await card_report(f))
    assert value["state"] == "waiting_notification"
    assert value["telegram_confirmed"] is False and value["dialog_closed"] is False
    async with f.sessions() as db:
        assert (await db.get(AssistantOfficeResource, "crm")).work_key is None
        with pytest.raises(ApiError) as exc:
            await assistant_dialogs.complete(
                db, f.principal, f.cid, f.author.id, 1, "123456", telegram_confirmed=True
            )
        assert exc.value.code == "assistant_native_notification_required"
    assert (await f.office.observe_owned(f.live, f.cid))["state"] == "waiting_notification"
    assert (await f.office.status(f.live, f.key, f.executor, f.lease))[
        "state"
    ] == "waiting_notification"
    await assert_no_effects(f)


async def test_main_real_crm_duplicate_link_blocks_successful_card_promotion(office):
    f = office
    await created(f)
    async with f.sessions() as db:
        source = await db.get(Conversation, f.cid)
        db.add(
            Conversation(
                id=uuid.uuid4(),
                channel=source.channel,
                account_id=source.account_id,
                external_chat_id="synthetic-duplicate",
                client_id=source.client_id,
                crm_request_id="123456",
            )
        )
        await db.commit()
    value = await f.office.capture_card(f.live, f.key, f.executor, f.lease, await card_report(f))
    assert value["state"] == "created_review" and value["duplicate_found"] is True
    async with f.sessions() as db:
        assert (await db.get(AssistantOfficeResource, "crm")).work_key == f.key
    await assert_no_effects(f)


def request_body(f, work=False):
    value = {
        "expected_principal_id": str(f.principal.id),
        "operator_id": str(f.author.id),
        "run_id": str(f.live.run_id),
        "generation": f.live.generation,
        "executor_id": str(f.executor),
    }
    if work:
        value.update(work_id=f.key, lease_id=str(f.lease))
    return value


@pytest.mark.parametrize("role", ["head", "manager", "observer"])
async def test_office_API_requires_real_admin_before_heartbeats(office, client, app, tokens, role):
    app.dependency_overrides[api.office_service] = lambda: office.office
    response = await client.post(
        BASE + "/heartbeat",
        json=request_body(office),
        headers={"Authorization": "Bearer " + tokens[role]},
    )
    assert response.status_code == 403
    assert await office.office.available(office.live) is False


async def test_office_API_binds_actual_principal_and_never_treats_body_as_authority(
    office, client, app, tokens
):
    f = office
    app.dependency_overrides[api.office_service] = lambda: f.office
    body = request_body(f)
    body["expected_principal_id"] = str(uuid.uuid4())
    response = await client.post(
        BASE + "/heartbeat", json=body, headers={"Authorization": "Bearer " + tokens["admin"]}
    )
    assert response.status_code == 409
    assert await f.office.available(f.live) is False
    body = request_body(f)
    response = await client.post(
        BASE + "/heartbeat", json=body, headers={"Authorization": "Bearer " + tokens["admin"]}
    )
    assert response.status_code == 200 and response.json()["available"] is True
    body["mode"] = "auto"
    response = await client.post(
        BASE + "/heartbeat", json=body, headers={"Authorization": "Bearer " + tokens["admin"]}
    )
    assert response.status_code == 400


async def test_office_API_preserves_original_create_report_after_stop(office, client, app, tokens):
    f = office
    await issued(f)
    await stop(f)
    app.dependency_overrides[api.office_service] = lambda: f.office
    body = request_body(f, work=True) | {
        "report": {
            "id": "123456",
            "url": "https://kp-lead-centre.ru/admin/domain/customer-request/update?id=123456",
        }
    }
    response = await client.post(
        BASE + "/created", json=body, headers={"Authorization": "Bearer " + tokens["admin"]}
    )
    assert response.status_code == 200 and response.json()["state"] == "created_unverified"
    response = await client.post(
        BASE + "/issue-create",
        json=request_body(f, work=True),
        headers={"Authorization": "Bearer " + tokens["admin"]},
    )
    assert response.status_code == 409
    await assert_no_effects(f)


@pytest.mark.parametrize("boundary", ["reserved", "requested", "issued"])
async def test_office_duplicate_stop_requires_reserved_work_before_consume(
    office, client, app, tokens, boundary
):
    f = office
    if boundary == "issued":
        await issued(f)
    else:
        await reserved(f)
        if boundary == "requested":
            await f.office.request_create(f.live, f.key, f.executor, f.lease)
    app.dependency_overrides[api.office_service] = lambda: f.office
    headers = {"Authorization": "Bearer " + tokens["admin"]}
    original = request_body(f, work=True)
    response = await client.post(
        BASE + "/failed", json=original | {"stop_reason": "crm_existing_request"}, headers=headers
    )
    assert response.status_code == 200
    expected = {
        "reserved": ("stopped", "crm_existing_request"),
        "requested": ("stopped", "executor_stopped_before_create"),
        "issued": ("created_review", "create_result_unknown"),
    }
    state, code = expected[boundary]
    assert (response.json()["state"], response.json()["reason_code"]) == (state, code)
    if boundary == "reserved":
        # The pre-upgrade request body remains valid and preserves existing evidence.
        again = await client.post(BASE + "/failed", json=original, headers=headers)
        assert again.status_code == 200 and again.json()["reason_code"] == code
    async with f.sessions() as db:
        resource = await db.get(AssistantOfficeResource, "crm")
        assert resource.work_key == (f.key if boundary == "issued" else None)
    await assert_no_effects(f)


async def test_office_manifest_flag_default_off_and_explicitly_typed(configured):
    assert configured.config.office_enabled is False
    configured.value["office_enabled"] = True
    configured.path.write_text(json.dumps(configured.value))
    assert assistant_runtime.configuration().office_enabled is True
    configured.value["office_enabled"] = 1
    configured.path.write_text(json.dumps(configured.value))
    with pytest.raises(ValueError):
        assistant_runtime.configuration()


async def test_driver_waits_for_office_before_paid_form_but_old_routes_remain_office_free(office):
    f = office
    # Reuse the actual driver and Root screen, not a fake successful driver.
    research = NativeResearchRelay(
        f.sessions,
        admission=fixtures.READY,
        client=f.service.client,
        enabled=True,
        clock=lambda: f.now[0],
    )
    research.enqueue = AsyncMock(side_effect=AssertionError("No offline paid form"))
    queue = driver_fixtures.Queue()
    driver = NativeDialogDriver(
        f.sessions,
        admission=fixtures.READY,
        actions=f.service,
        research=research,
        redis=f.redis,
        arq=queue,
        office=f.office,
        enabled=True,
        settle_seconds=0,
        clock=lambda: f.now[0],
    )
    assert (await driver._drive_owned(f.live, f.cid))["state"] == "screening"
    screen = (await f.service.screen(f.live, f.cid, f.source))["action_key"]
    await f.service.advance(screen)
    assert (await driver._drive_owned(f.live, f.cid))["state"] == "waiting_executor"
    research.enqueue.assert_not_awaited()
    await assert_no_effects(f)


async def test_worker_uses_existing_durable_office_and_default_is_disabled(office):
    f = office
    assert (await native_office_step({}, f.key))["state"] == "disabled"
    await ready(f)
    await f.office.prepare(f.live, f.key, f.executor, f.lease, f.proposal)
    assert f.key in await f.office.due()
    value = await native_office_step({"native_office": f.office}, f.key)
    assert value["state"] == "authorizing" and value["execution_allowed"] is False
    await assert_no_effects(f)


async def test_office_disabled_service_cannot_even_advertise_availability(office):
    f = office
    disabled = NativeOffice(f.sessions, f.redis, admission=fixtures.READY)
    assert await disabled.available(f.live) is False
    with pytest.raises(ValueError):
        await disabled.heartbeat(f.live, f.executor)
    with pytest.raises(ValueError):
        await f.office.heartbeat(replace(f.live, operator_id=f.principal.id), f.executor)


async def test_disabled_office_cannot_mutate_original_evidence_or_release_resource(office):
    f = office
    await issued(f)
    disabled = NativeOffice(f.sessions, f.redis, admission=fixtures.READY)
    with pytest.raises(ValueError):
        await disabled.fail(f.live, f.key, f.executor, f.lease)
    async with f.sessions() as db:
        assert (await db.get(AssistantOfficeWork, f.key)).stage == "create_started"
        assert (await db.get(AssistantOfficeResource, "crm")).work_key == f.key
    await assert_no_effects(f)


OFFICE_ROUTES = (
    "heartbeat",
    "poll",
    "prepare",
    "request-create",
    "issue-create",
    "created",
    "followup",
    "card",
    "failed",
    "status",
)


@pytest.mark.parametrize("operation", OFFICE_ROUTES)
@pytest.mark.parametrize("role", ["admin", "head", "manager", "observer", "anonymous"])
async def test_all_office_routes_enforce_real_role_matrix(
    office, client, app, tokens, operation, role
):
    f = office
    f.lease = uuid.uuid4()
    app.dependency_overrides[api.office_service] = lambda: f.office
    body = request_body(f, work=operation not in ("heartbeat", "poll"))
    if operation == "prepare":
        body["proposal"] = f.proposal
    elif operation in ("created", "card"):
        body["report"] = {
            "id": "123456",
            "url": "https://kp-lead-centre.ru/admin/domain/customer-request/update?id=123456",
        }
    elif operation == "followup":
        body.update(crm_request_id="123456", kind="partner_note")
    headers = {} if role == "anonymous" else {"Authorization": "Bearer " + tokens[role]}
    response = await client.post(BASE + "/" + operation, json=body, headers=headers)
    expected = (
        401
        if role == "anonymous"
        else 403
        if role != "admin"
        else (200 if operation in ("heartbeat", "poll") else 409)
    )
    assert response.status_code == expected
    await assert_no_effects(f)


async def test_production_factory_uses_current_session_factory_not_import_time_none(
    office, configured, monkeypatch
):
    f = office
    configured.value["office_enabled"] = True
    configured.path.write_text(json.dumps(configured.value))
    monkeypatch.setattr(api.db_mod, "session_factory", f.sessions)
    monkeypatch.setattr(assistant_runtime, "readiness", AsyncMock(return_value=True))
    service = await api.office_service(f.redis)
    assert service.sessions is f.sessions and service.enabled is True
    assert service.actions is None  # The API never makes a fake ARQ pool.
    monkeypatch.setattr(api.db_mod, "session_factory", None)
    with pytest.raises(ApiError):
        await api.office_service(f.redis)


async def test_worker_restart_does_not_drop_original_created_id_after_stop_or_allow_new_run(
    office, configured, monkeypatch, client, tokens
):
    f = office
    await issued(f)
    await stop(f)
    configured.value["office_enabled"] = True
    configured.path.write_text(json.dumps(configured.value))
    monkeypatch.setattr(api.db_mod, "session_factory", f.sessions)
    ready = AsyncMock(return_value=False)
    monkeypatch.setattr(assistant_runtime, "readiness", ready)
    headers = {"Authorization": "Bearer " + tokens["admin"]}
    response = await client.post(
        BASE + "/created",
        headers=headers,
        json={
            **request_body(f, work=True),
            "report": {
                "id": "123456",
                "url": "https://kp-lead-centre.ru/admin/domain/customer-request/update?id=123456",
            },
        },
    )
    assert response.status_code == 200 and response.json()["crm_request_id"] == "123456"
    ready.assert_not_awaited()
    start = await client.post(
        "/api/v1/bot-dialogs/assistant/native-run/start",
        headers=headers,
        json={
            "expected_principal_id": str(f.principal.id),
            "operator_id": str(f.author.id),
            "expected_generation": 2,
        },
    )
    assert start.status_code == 503
    ready.assert_awaited_once()
    async with f.sessions() as db:
        run = await db.get(AssistantRun, f.principal.id)
        assert run.state == "stopped" and run.generation == 2
    await assert_no_effects(f)


async def another_cid(f):
    async with f.sessions() as db:
        original = await db.get(Conversation, f.cid)
        other = Conversation(
            id=uuid.uuid4(),
            channel=original.channel,
            account_id=original.account_id,
            external_chat_id=uuid.uuid4().hex,
            client_id=original.client_id,
        )
        db.add(other)
        await db.commit()
        await assistant_dialogs.enroll(
            db, f.principal, f.author, other.id, expected_assignee_id=None, manual=False
        )
        snapshot = await leadbot_reader._snapshot(
            db,
            str(other.id),
            {
                "principal_id": str(f.principal.id),
                "operator_id": str(f.author.id),
            },
        )
        return other.id, snapshot[0]["source_sha256"]


async def test_global_crm_capacity_serializes_two_dialogs_before_paid_form_and_expiry_is_not_retry(
    office,
):
    f = office
    await f.office.heartbeat(f.live, f.executor)
    assert (await f.office.capacity(f.live, f.cid, f.source))["capacity"] is True
    cid, source = await another_cid(f)
    assert (await f.office.capacity(f.live, cid, source))["state"] == "crm_busy"
    f.now[0] += 301
    await f.office.heartbeat(f.live, f.executor)
    original = await f.office.capacity(f.live, f.cid, f.source)
    assert original["state"] == "expired" and original["capacity"] is False
    assert (await f.office.capacity(f.live, cid, source))["capacity"] is True
    async with f.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(AssistantResearchWork)) == 0
    assert f.peer.calls == []


async def test_unknown_create_holds_capacity_for_other_cid_even_after_original_deadline(office):
    f = office
    await issued(f)
    cid, source = await another_cid(f)
    f.now[0] += 301
    await f.office.heartbeat(f.live, f.executor)
    assert (await f.office.capacity(f.live, cid, source))["state"] == "crm_reconciliation_required"
    await assert_no_effects(f)


async def changed_source(f):
    async with f.sessions() as db:
        db.add(
            Message(
                conversation_id=f.cid,
                direction="in",
                sender_type="client",
                body="Уточню адрес и характер работы.",
                attachments=[],
                delivery_status="delivered",
            )
        )
        await db.commit()
        snapshot = await leadbot_reader._snapshot(
            db,
            str(f.cid),
            {
                "principal_id": str(f.principal.id),
                "operator_id": str(f.author.id),
            },
        )
        return snapshot[0]["source_sha256"]


async def test_new_source_replaces_only_unissued_capacity_and_does_not_adopt_old_form(office):
    f = office
    await ready(f)
    new_source = await changed_source(f)
    assert new_source != f.source
    assert (await f.office.capacity(f.live, f.cid, new_source))["state"] == "awaiting_form"
    async with f.sessions() as db:
        old = await db.get(AssistantOfficeWork, f.key)
        assert old.stage == "replaced"
    with pytest.raises(ValueError):
        await f.office.prepare(f.live, f.key, f.executor, f.lease, f.proposal)
    await assert_no_effects(f)


async def test_new_input_after_physical_issue_is_review_not_a_new_form(office):
    f = office
    await issued(f)
    await changed_source(f)
    assert (await f.office.observe_owned(f.live, f.cid))["state"] == "created_review"
    with pytest.raises(ValueError):
        await f.office.request_create(f.live, f.key, f.executor, f.lease)
    await assert_no_effects(f)


async def test_successful_read_only_screen_refresh_does_not_renew_original_office_or_form(office):
    f = office
    await ready(f)
    before = len(f.peer.calls)
    f.now[0] += 301
    newer = await f.service.screen(f.live, f.cid, f.source)
    assert newer["action_key"] != f.screen
    assert newer["state"] == "inspect"
    assert len(f.peer.calls) == before
    again = await f.service.screen(f.live, f.cid, f.source)
    assert again == newer
    assert (await f.service.advance(newer["action_key"]))["state"] == "screened"
    await f.office.heartbeat(f.live, f.executor)
    old = await f.office.capacity(f.live, f.cid, f.source)
    assert old["state"] == "expired" and old["capacity"] is False
    async with f.sessions() as db:
        assert (await db.get(AssistantNativeAction, f.screen)).stage == "screened"
        assert (await db.get(AssistantOfficeWork, f.key)).deadline < f.now[0]
        assert await db.scalar(select(func.count()).select_from(AssistantResearchWork)) == 1
    assert all(p["operation"] == "inspect" for p in f.peer.calls)
    await assert_no_effects(f)


async def test_read_only_refresh_does_not_repeat_a_failed_original_inspection(office):
    f = office
    screen = await f.service.screen(f.live, f.cid, f.source)
    f.peer.reject_inspect = True
    assert (await f.service.advance(screen["action_key"]))["state"] == "blocked"
    f.now[0] += 301
    observed = await f.service.screen(f.live, f.cid, f.source)
    assert observed["action_key"] == screen["action_key"] and observed["state"] == "blocked"
    assert len(f.peer.calls) == 1
    await assert_no_effects(f)


async def blocked_reservation(f):
    await ready(f)
    await f.office.prepare(f.live, f.key, f.executor, f.lease, f.proposal)
    await f.office.advance(f.key)
    async with f.sessions() as db:
        f.action = (await db.get(AssistantOfficeWork, f.key)).action_key
    await f.service.advance(f.action)
    f.peer.reject_operation = "reserve_office"
    assert (await f.service.advance(f.action))["state"] == "blocked"


async def test_first_current_private_office_error_blocks_original_run_without_next_model_step(
    office,
):
    f = office
    await blocked_reservation(f)
    before = len(f.peer.calls)
    assert (await f.office.advance(f.key))["state"] == "stopped"
    async with f.sessions() as db:
        run = await db.get(AssistantRun, f.principal.id)
        assert run.state == "blocked" and run.generation == f.live.generation + 1
    assert len(f.peer.calls) == before
    await assert_no_effects(f)


async def test_changed_source_is_not_misreported_as_a_current_global_office_error(office):
    f = office
    await blocked_reservation(f)
    await changed_source(f)
    assert (await f.office.advance(f.key))["state"] == "stopped"
    async with f.sessions() as db:
        run = await db.get(AssistantRun, f.principal.id)
        assert run.state == "running" and run.generation == f.live.generation
    await assert_no_effects(f)


async def test_old_unknown_create_cannot_stop_a_later_owner_run(office):
    f = office
    await issued(f)
    await stop(f)
    async with f.sessions() as db:
        newer = await assistant_runs.start(
            db,
            f.principal.id,
            f.author.id,
            expected_generation=2,
            mode="auto",
            admission=fixtures.READY,
        )
        await db.commit()
    await f.office.fail(f.live, f.key, f.executor, f.lease)
    async with f.sessions() as db:
        run = await db.get(AssistantRun, f.principal.id)
        assert run.state == "running" and str(run.run_id) == newer["run_id"]
        assert run.generation == newer["generation"]
    await assert_no_effects(f)


async def test_original_executor_can_refresh_only_ownership_after_issue_not_create_or_deadline(
    office,
):
    f = office
    first = await issued(f)
    async with f.sessions() as db:
        original = await db.get(AssistantOfficeWork, f.key)
        deadline, old_lease = original.deadline, original.client_lease_until
    f.now[0] += 80
    await f.office.heartbeat(f.live, f.executor)
    observed = await f.office.poll(f.live, f.executor)
    assert observed["reconciliation_only"] is True and observed["execution_allowed"] is False
    assert observed["lease_id"] == str(f.lease) and observed["lease_until"] > old_lease
    assert observed["deadline"] == deadline and observed["snapshot_hash"] == first["snapshot_hash"]
    again = await f.office.issue_create(f.live, f.key, f.executor, f.lease)
    assert again["execution_allowed"] is False
    assert sum(p["operation"] == "consume_office" for p in f.peer.calls) == 1
    f.now[0] = deadline + 1
    await f.office.heartbeat(f.live, f.executor)
    with pytest.raises(ValueError):
        await f.office.poll(f.live, f.executor)
    await assert_no_effects(f)


async def test_new_executor_cannot_adopt_issued_create_even_when_availability_expires(office):
    f = office
    await issued(f)
    f.now[0] += 91
    other = uuid.uuid4()
    assert (await f.office.heartbeat(f.live, other))["available"] is True
    observed = await f.office.poll(f.live, other)
    assert observed["reconciliation_only"] is True and "lease_id" not in observed
    async with f.sessions() as db:
        work = await db.get(AssistantOfficeWork, f.key)
        assert work.executor_id == f.executor and work.client_lease_id == f.lease
    await assert_no_effects(f)


async def test_unissued_recovery_returns_exact_stored_proposal_and_authoritative_snapshot(office):
    f = office
    await ready(f)
    f.proposal["territory"]["distance"] = 1e-7
    prepared = await f.office.prepare(f.live, f.key, f.executor, f.lease, f.proposal)
    assert prepared["snapshot_hash"] == wire.sha(wire.encode(f.proposal))
    observed = await f.office.poll(f.live, f.executor)
    assert observed["proposal"] == f.proposal
    assert observed["snapshot_hash"] == prepared["snapshot_hash"]
    assert observed["source_sha256"] == f.source
    assert observed["execution_allowed"] is False
    await assert_no_effects(f)


async def test_known_card_failure_stops_current_original_source_without_renewing_deadline(office):
    f = office
    await created(f)
    async with f.sessions() as db:
        deadline = (await db.get(AssistantOfficeWork, f.key)).deadline
    f.now[0] = deadline + 1
    result = await f.office.fail(f.live, f.key, f.executor, f.lease)
    assert result["state"] == "created_review" and result["crm_request_id"] == "123456"
    async with f.sessions() as db:
        assert (await db.get(AssistantRun, f.principal.id)).state == "blocked"
        assert (await db.get(AssistantOfficeWork, f.key)).deadline == deadline
    await assert_no_effects(f)


async def test_known_created_id_new_client_input_is_review_not_a_false_global_incident(office):
    f = office
    await created(f)
    await changed_source(f)
    result = await f.office.fail(f.live, f.key, f.executor, f.lease)
    assert result["state"] == "created_review"
    async with f.sessions() as db:
        run = await db.get(AssistantRun, f.principal.id)
        assert run.state == "running" and run.generation == f.live.generation
    await assert_no_effects(f)


async def test_office_journal_distinguishes_issue_report_card_and_unconfirmed_telegram(office):
    f = office
    await created(f)
    await f.office.capture_card(f.live, f.key, f.executor, f.lease, await card_report(f))
    async with f.sessions() as db:
        rows = list(
            (
                await db.scalars(
                    select(AuditLog).where(
                        AuditLog.action == "assistant.office_step",
                    )
                )
            ).all()
        )
    kinds = [r.details["kind"] for r in rows]
    for kind in (
        "capacity_reserved_before_model",
        "original_form_accepted",
        "executor_leased",
        "original_proposal_prepared",
        "private_authorization_reserved",
        "physical_create_permission_issued",
        "created_id_reported_unverified",
        "card_read_by_extension",
    ):
        assert kinds.count(kind) == 1
    assert all(
        r.details["source_sha256"] == f.source
        and r.details["telegram_confirmed"] is False
        and r.details["dialog_closed"] is False
        for r in rows
    )
    assert fixtures.KEY.decode() not in json.dumps([r.details for r in rows])
    await assert_no_effects(f)


async def test_generic_completion_rechecks_native_fence_after_conversation_lock(
    office, monkeypatch
):
    f = office
    await ready(f)
    original = assistant_dialogs.conversations.get_conversation_for_update

    async def locked_then_issue_marker(db, cid):
        conv = await original(db, cid)
        work = await db.get(AssistantOfficeWork, f.key)
        work.create_issued_at = f.now[0]
        work.stage = "create_started"
        await db.flush()  # Simulated concurrent issue visible after taking the lock.
        return conv

    monkeypatch.setattr(
        assistant_dialogs.conversations, "get_conversation_for_update", locked_then_issue_marker
    )
    async with f.sessions() as db:
        with pytest.raises(ApiError) as exc:
            await assistant_dialogs.complete(
                db, f.principal, f.cid, f.author.id, 1, "123456", telegram_confirmed=True
            )
        assert exc.value.code == "assistant_native_notification_required"
    await assert_no_effects(f)


async def test_office_0102_migration_is_additive_and_downgrade_keeps_prior_message_table(db):
    path = Path(__file__).parents[2] / "app/db/migrations/versions/0102_assistant_native_office.py"
    spec = importlib.util.spec_from_file_location("office_migration256", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    connection = await db.connection()

    def roundtrip(sync):
        # Work in this isolated test schema; no production migration is run.
        sync.exec_driver_sql("DROP TABLE assistant_native_office_resource")
        sync.exec_driver_sql("DROP TABLE assistant_native_office")
        ops = Operations(MigrationContext.configure(sync))
        original = module.op
        module.op = ops
        try:
            module.upgrade()
            names = inspect(sync).get_table_names()
            assert "messages" in names and "assistant_native_actions" in names
            assert (
                sync.exec_driver_sql(
                    "SELECT COUNT(*) FROM assistant_native_office_resource"
                ).scalar_one()
                == 1
            )
            module.downgrade()
            assert "messages" in inspect(sync).get_table_names()
            assert "assistant_native_actions" in inspect(sync).get_table_names()
            module.upgrade()
        finally:
            module.op = original

    await connection.run_sync(roundtrip)
