"""Exercise the sealed C164 web bundle against real C160 HTTP handlers."""

import asyncio
import json
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import ApiError
from app.models import AssistantRun, AuditLog, Message, User
from app.models.assistant_dialog import AssistantDialog
from app.models.assistant_notification import AssistantOfficeNotification
from app.models.assistant_office import AssistantOfficeWork
from app.models.assistant_outbound import AssistantNativeOutbound
from app.services import assistant_runs, assistant_runtime

HERE = Path(__file__).resolve().parents[3]
BASE = "/api/v1/bot-dialogs/assistant/native-run"
AUTH = "/api/v1/auth"
CAPABILITIES = "/api/v1/bot-dialogs/assistant/capabilities"
SHELL = {
    "/api/v1/presence": {"status": "active", "revision": 1},
    "/api/v1/ws/ticket": {"ticket": "synthetic-shell-only"},
    "/api/v1/health": {"status": "ok", "db": True, "redis": True, "version": "local"},
    "/api/v1/leadbot": {
        "connection": {"url": "", "token_set": False, "source": "env"},
        "is_ready": False,
        "enabled": False,
        "mode": "suggest",
        "context_messages": 30,
        "account_ids": [],
        "accounts": [],
    },
}
EMPTY = {"items": [], "total": 0, "in_progress": [], "silent": [], "count": 0}


async def forward(
    request: dict[str, Any], client: httpx.AsyncClient, redis: FakeRedis, stamp: str
) -> dict[str, Any]:
    if request["kind"] == "readiness":
        if request["ready"] is True:
            await redis.set(
                assistant_runtime.HEALTH_KEY,
                json.dumps({"v": 1, "stamp": stamp, "ready": True, "seen": time.time()}),
                ex=15,
            )
        else:
            await redis.delete(assistant_runtime.HEALTH_KEY)
        return {"id": request["id"]}

    assert request["kind"] == "http"
    target = request["path"]
    url = urlsplit(target)
    assert not url.scheme and not url.netloc and target.startswith("/api/v1/")
    path, method = url.path, request["method"]
    real = (
        method == "GET"
        and (
            path in (BASE, AUTH + "/me", CAPABILITIES)
            or path.startswith("/api/v1/bot-dialogs/assistant/")
        )
        or method == "POST"
        and path in (BASE + "/start", BASE + "/stop", AUTH + "/refresh")
    )
    if real:
        headers = {"Authorization": request["authorization"]} if request["authorization"] else {}
        response = await client.request(method, target, headers=headers, json=request["body"])
        return {
            "id": request["id"],
            "status": response.status_code,
            "body": response.text,
            "content_type": response.headers.get("content-type", "application/json"),
        }
    if method == "GET" or (method, path) in (
        ("PUT", "/api/v1/presence"),
        ("POST", "/api/v1/ws/ticket"),
    ):
        result = SHELL.get(path, EMPTY)
        return {
            "id": request["id"],
            "status": 200,
            "body": json.dumps(result),
            "content_type": "application/json",
        }
    raise AssertionError(f"Unexpected application mutation {method} {path}")


@pytest.mark.parametrize("design", ["classic", "new"])
async def test_sealed_browser_uses_real_run_control(
    design: str,
    client: httpx.AsyncClient,
    redis: FakeRedis,
    make_user: Callable[..., Awaitable[User]],
    db_sessionmaker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner: User = await make_user(
        "owner@leadchat.test", role="admin", full_name="Тестовый владелец"
    )
    author: User = await make_user(
        "manager@leadchat.test", role="manager", full_name="Оператор тестовой смены"
    )
    login = await client.post(
        AUTH + "/login",
        json={"email": owner.email, "password": "correct horse battery staple", "remember": True},
    )
    assert login.status_code == 200
    monkeypatch.delenv("LEADBOT_ACTOR_PROOF_KEY", raising=False)
    monkeypatch.setattr(assistant_runtime.settings, "assistant_native_enabled", True)
    monkeypatch.setattr(
        assistant_runtime.settings, "assistant_native_manifest", str(HERE / "native-crm-only.json")
    )
    config = assistant_runtime.configuration()
    assert config is not None and config.admission.auto_ready
    assert config.max_dialogs == config.scan_batch == 1
    assert config.crm_only and config.office_enabled and not config.notifications_enabled
    guard = HERE.parent / "C114-local-network-guards266-v1" / "node-guard.cjs"
    environment = dict(
        os.environ,
        C175_PLAYWRIGHT=str(
            HERE.parent
            / "C164-native-leadbot-tab/frontend-classic/node_modules/playwright/index.mjs"
        ),
        CODEX_LOCAL_TEST_GUARD_ROOT=str(tmp_path),
        CODEX_LOCAL_TEST_GUARD_NONCE=tmp_path.name,
    )
    process = await asyncio.create_subprocess_exec(
        "node",
        "--require",
        str(guard),
        str(HERE / "browser-check.mjs"),
        design,
        str(HERE / "package/nginx/payload"),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=environment,
    )
    assert process.stdout and process.stdin and process.stderr
    errors = asyncio.create_task(process.stderr.read())
    receipt = None
    traffic: list[tuple[str, str, int]] = []
    try:
        async with asyncio.timeout(50):
            while line := await process.stdout.readline():
                request = json.loads(line)
                if request["kind"] == "passed":
                    receipt = request
                    break
                reply = await forward(request, client, redis, config.stamp)
                if request["kind"] == "http":
                    path = urlsplit(request["path"]).path
                    traffic.append((request["method"], path, reply["status"]))
                process.stdin.write(json.dumps(reply).encode() + b"\n")
                await process.stdin.drain()
            assert await process.wait() == 0, (traffic, (await errors).decode())
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
        await errors
    assert receipt == {
        "kind": "passed",
        "design": design,
        "mutations": 4,
        "restartedPage": True,
        "responseLoss": design == "new",
        "stoppedWithoutWorker": True,
    }
    assert ("POST", AUTH + "/refresh", 200) in traffic
    assert ("GET", AUTH + "/me", 200) in traffic
    assert ("GET", CAPABILITIES, 200) in traffic
    assert not (tmp_path / "transport.jsonl").exists()

    async with db_sessionmaker() as db:
        run = await db.get(AssistantRun, owner.id)
        assert run is not None and (run.operator_id, run.state, run.generation) == (
            author.id,
            "stopped",
            4,
        )
        events = list(
            await db.scalars(select(AuditLog).where(AuditLog.action == "assistant.run_control"))
        )
        operations = {}
        run_ids = {}
        assert len(events) == 4
        for event in events:
            detail = event.details
            assert event.user_id == owner.id and detail is not None
            assert detail["operator_id"] == str(author.id)
            operations[detail["generation"]] = detail["operation"]
            run_ids[detail["generation"]] = event.entity_id
        assert operations == {1: "start", 2: "stop", 3: "start", 4: "stop"}
        assert run_ids[1] == run_ids[2] != run_ids[3] == run_ids[4] == str(run.run_id)
        for generation in (1, 3):
            with pytest.raises(ApiError) as stopped:
                await assistant_runs.authority(
                    db, owner.id, uuid.UUID(run_ids[generation]), generation, config.admission
                )
            assert stopped.value.code == "assistant_run_stale"
        for model in (
            Message,
            AssistantDialog,
            AssistantNativeOutbound,
            AssistantOfficeWork,
            AssistantOfficeNotification,
        ):
            assert await db.scalar(select(func.count()).select_from(model)) == 0
    print(json.dumps({"design": design, "real_run_commands": 4, "business_effects": 0}))
