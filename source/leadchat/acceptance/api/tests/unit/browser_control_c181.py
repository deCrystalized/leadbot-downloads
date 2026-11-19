"""Drive the built LeadChat route against the local API used by the CRM fixture."""

import asyncio
import json
import os
from pathlib import Path
from tempfile import mkdtemp
from typing import Any, cast

import httpx
from fakeredis.aioredis import FakeRedis

from app.services import assistant_runtime
from tests.unit.test_native_browser_C175 import forward

HERE = Path(__file__).resolve().parents[3]


async def operate(
    client: httpx.AsyncClient,
    redis: FakeRedis,
    tmp_path: Path,
    design: str,
    action: str,
    author: str,
) -> dict[str, Any]:
    """Open a fresh Chromium window without sharing the extension test process."""
    config = assistant_runtime.configuration()
    assert config is not None and config.crm_only and not config.notifications_enabled
    assert config.max_dialogs == config.scan_batch == 1
    await forward({"id": 0, "kind": "readiness", "ready": True}, client, redis, config.stamp)
    workspace = Path(mkdtemp(prefix=f"browser-{design}-{action}-", dir=tmp_path))
    env = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "TMPDIR", "PLAYWRIGHT_BROWSERS_PATH")
        if key in os.environ
    }
    env.update(
        C175_PLAYWRIGHT=str(
            HERE.parent
            / "C164-native-leadbot-tab/frontend-classic/node_modules/playwright/index.mjs"
        ),
        CODEX_LOCAL_TEST_GUARD_ROOT=str(workspace),
        CODEX_LOCAL_TEST_GUARD_NONCE=workspace.name,
    )
    guard = HERE / "C114-local-network-guards266-v1/node-guard.cjs"
    process = await asyncio.create_subprocess_exec(
        "node",
        "--require",
        str(guard),
        str(HERE / "browser-control.mjs"),
        design,
        str(HERE / "web"),
        action,
        author,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    stderr = asyncio.create_task(process.stderr.read())
    receipt: dict[str, Any] | None = None
    try:
        async with asyncio.timeout(24):
            while raw := await process.stdout.readline():
                request = json.loads(raw)
                if request["kind"] == "passed":
                    receipt = cast("dict[str, Any]", request)
                    break
                reply = await forward(request, client, redis, config.stamp)
                process.stdin.write(json.dumps(reply).encode() + b"\n")
                await process.stdin.drain()
            assert await process.wait() == 0, (await stderr).decode()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
        await stderr
    assert receipt is not None and receipt["action"] == action
    assert not (workspace / "transport.jsonl").exists()
    return receipt
