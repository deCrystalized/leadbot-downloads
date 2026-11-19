"""Trusted native worker wiring and observable readiness, all default disabled.

Configuration is a server-owned release file. Reading status never starts a
Run; worker restart resumes only existing explicit launches through the same
fresh authority gates. Observer tabs do not own this task or its lifetime.
"""

import asyncio
import contextlib
import hashlib
import math
import os
import stat
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import structlog

from app.core.config import settings
from app.services import assistant_identity, assistant_outbound, assistant_runs
from app.services.assistant_actions import NativeActionCoordinator
from app.services.assistant_driver import NativeDialogDriver
from app.services.assistant_observation import NativeObservation
from app.services.assistant_office import NativeOffice
from app.services.assistant_research import NativeResearchRelay
from app.services.leadbot_execution_protocol import decode, encode
from app.services.leadbot_native_client import NativeResearchClient

log = structlog.get_logger("app.assistant_runtime")
HEALTH_KEY = "assistant-native:worker-readiness:v1"
SCAN_LOCK = "assistant-native:header-scan:v1"


async def _release_scan(redis, marker):
    # Only our own cache lock. It is never evidence of model/job liveness.
    async with redis.pipeline(transaction=True) as pipe:
        await pipe.watch(SCAN_LOCK)
        current = await pipe.get(SCAN_LOCK)
        if current in (marker, marker.encode()):
            pipe.multi()
            pipe.delete(SCAN_LOCK)
            await pipe.execute()


@dataclass(frozen=True)
class NativeConfiguration:
    admission: assistant_runs.RuntimeAdmission
    stamp: str
    max_dialogs: int
    scan_batch: int
    settle_seconds: float
    office_enabled: bool = False
    notifications_enabled: bool = False
    crm_only: bool = False


def configuration() -> NativeConfiguration | None:
    if getattr(settings, "assistant_native_enabled", False) is not True:
        return None  # No release/credential file read, construction or network.
    path = Path(getattr(settings, "assistant_native_manifest", ""))
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Private native release configuration required")
    info = path.stat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid not in (0, os.getuid())
        or info.st_mode & 0o022
        or not 0 < info.st_size <= 16000
    ):
        raise ValueError("Trusted native release configuration required")
    raw = path.read_bytes()
    value = decode(raw, 16000)
    required = {
        "v",
        "policy",
        "runtime",
        "map",
        "memory",
        "auto_ready",
        "max_dialogs",
        "scan_batch",
        "settle_seconds",
    }
    if (
        not isinstance(value, dict)
        or set(value) - {"office_enabled", "notifications_enabled", "crm_only"} != required
        or type(value.get("office_enabled", False)) is not bool
        or type(value.get("notifications_enabled", False)) is not bool
        or type(value.get("crm_only", False)) is not bool
        or value.get("crm_only", False)
        and (not value.get("office_enabled", False) or value.get("notifications_enabled", False))
        or value.get("notifications_enabled", False)
        and not value.get("office_enabled", False)
        or type(value["v"]) is not int
        or value["v"] != 1
        or type(value["auto_ready"]) is not bool
        or any(
            not isinstance(value[k], str) or not value[k].strip() or len(value[k]) > 256
            for k in ("policy", "runtime", "map", "memory")
        )
        or any(
            type(value[k]) is not int or not 1 <= value[k] <= 100
            for k in ("max_dialogs", "scan_batch")
        )
        or type(value["settle_seconds"]) not in (int, float)
        or not math.isfinite(value["settle_seconds"])
        or not 0 <= value["settle_seconds"] <= 10
    ):
        raise ValueError("Exact bounded native release fields required")
    return NativeConfiguration(
        assistant_runs.RuntimeAdmission(
            value["policy"],
            value["runtime"],
            value["map"],
            value["memory"],
            worker_ready=True,
            auto_ready=value["auto_ready"],
        ),
        hashlib.sha256(raw).hexdigest(),
        value["max_dialogs"],
        value["scan_batch"],
        value["settle_seconds"],
        value.get("office_enabled", False),
        value.get("notifications_enabled", False),
        value.get("crm_only", False),
    )


async def readiness(redis, config: NativeConfiguration, *, clock=time.time) -> bool:
    try:
        raw = await redis.get(HEALTH_KEY)
        if isinstance(raw, str):
            raw = raw.encode()
        value, now = decode(raw, 16000), clock()
        return bool(
            isinstance(value, dict)
            and set(value) == {"v", "stamp", "ready", "seen"}
            and type(value["v"]) is int
            and value["v"] == 1
            and value["stamp"] == config.stamp
            and value["ready"] is True
            and type(value["seen"]) in (int, float)
            and math.isfinite(value["seen"])
            and math.isfinite(now)
            and -1 <= now - value["seen"] <= 15
        )
    except Exception:
        return False  # Unknown readiness is not authority to start a new Run.


async def _loop(ctx, config):
    stop, driver, redis = ctx["native_worker_stop"], ctx["native_dialog_driver"], ctx["redis"]
    while not stop.is_set():
        ready = False
        marker, locked = uuid.uuid4().hex, False
        try:
            async with asyncio.timeout(10):
                # Original command/effect observers can advance even when a
                # crashed scanner's metadata lock still has time remaining.
                await driver.schedule_existing()
                locked = bool(await redis.set(SCAN_LOCK, marker, nx=True, ex=30))
                if locked:
                    await driver.tick()
            ready = True
        except asyncio.CancelledError:
            raise
        except Exception:
            # An observation timeout does not prove any durable job terminal.
            # No exception/URL/header/body is written to the journal here.
            log.warning("assistant.native_cycle_observation_interrupted")
        finally:
            if locked:
                try:
                    await _release_scan(redis, marker)
                except Exception:
                    log.warning("assistant.native_scan_lock_observation_unavailable")
        try:
            await redis.set(
                HEALTH_KEY,
                encode(
                    {"v": 1, "stamp": config.stamp, "ready": ready, "seen": time.time()}
                ).decode(),
                ex=15,
            )
        except Exception:
            log.warning("assistant.native_readiness_unavailable")
        try:
            await asyncio.wait_for(stop.wait(), timeout=0.25)
        except TimeoutError:
            pass


async def configure_worker(ctx) -> dict[str, object]:
    config = configuration()
    if config is None:
        return {"configured": False, "run_started": False}
    if config.office_enabled and not (config.notifications_enabled or config.crm_only):
        raise ValueError(
            "Native CRM worker requires the independent notification completion capability"
        )
    # This is the existing Main/Root HMAC credential, not the model API key.
    # Keep it only in trusted transport; never in config, task input or logs.
    key = assistant_identity.proof_key()
    if (
        not isinstance(key, bytes)
        or not 32 <= len(key) <= 512
        or any(chr(c).isspace() for c in key)
    ):
        raise ValueError("Native private transport is not configured")
    del key
    sessions, redis, arq = ctx["db_session_factory"], ctx["redis"], ctx["arq"]
    client = NativeResearchClient(enabled=True, key=assistant_identity.proof_key)
    research = NativeResearchRelay(
        sessions, admission=config.admission, client=client, enabled=True
    )
    actions = NativeActionCoordinator(
        sessions,
        admission=config.admission,
        client=client,
        redis=redis,
        job_redis=arq,
        enabled=True,
    )
    driver = NativeDialogDriver(
        sessions,
        admission=config.admission,
        actions=actions,
        research=research,
        redis=redis,
        arq=arq,
        enabled=True,
        max_dialogs=config.max_dialogs,
        scan_batch=config.scan_batch,
        settle_seconds=config.settle_seconds,
        observer=NativeObservation(sessions, redis, admission=config.admission),
        office=(
            NativeOffice(
                sessions,
                redis,
                admission=config.admission,
                actions=actions,
                enabled=True,
                notifications_enabled=config.notifications_enabled,
                crm_only=config.crm_only,
            )
            if config.office_enabled
            else None
        ),
    )
    ctx.update(
        native_research_relay=research,
        native_action_coordinator=actions,
        native_delivery_runtime=assistant_outbound.NativeDeliveryRuntime(config.admission, True),
        native_dialog_driver=driver,
        native_office=driver.office,
        native_driver_managed=True,
        native_worker_stop=asyncio.Event(),
    )
    ctx["native_worker_task"] = asyncio.create_task(_loop(ctx, config))
    return {"configured": True, "run_started": False}


async def stop_worker(ctx):
    stop, task = ctx.get("native_worker_stop"), ctx.get("native_worker_task")
    if stop is not None:
        stop.set()
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            try:
                await task
            except Exception:
                log.warning("assistant.native_worker_stopped_with_error")
    # Resource cleanup only: no Run stop, customer action or job redispatch.
