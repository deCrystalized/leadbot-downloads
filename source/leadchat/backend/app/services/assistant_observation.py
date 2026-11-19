"""Ephemeral last-stage observation, never execution authority or a receipt.

The existing authorized source snapshot stays inside Main. Only its digest and
fixed stage codes enter Redis; UI reads revalidate the exact current full source.
"""

import asyncio
import math
import re
import time
import uuid
from dataclasses import dataclass

import structlog

from app.models import AssistantDialog, AssistantRun, Conversation
from app.services import assistant_dialogs, assistant_runs, leadbot_reader
from app.services.leadbot_execution_protocol import decode, encode

log = structlog.get_logger("app.assistant_observation")
TTL = 20
# Auxiliary observation may fail unknown; it must not hold execution or a GET.
STEP_BUDGET = 0.25
PAGE_BUDGET = 2
STAGES = frozenset(
    {
        "waiting_original_delivery",
        "research_pending",
        "waiting_model_capacity",
        "collecting_messages",
        "source_review",
        "waiting_transcription",
        "screening",
        "wait",
        "needs_operator",
        "prior_attempt_review",
        "waiting_executor",
        "source_changed",
        "technical_stop",
        "queued",
        "reserve_action",
        "consume_action",
        "apply",
        "dispatch",
        "queue_observing",
        "queue_unknown",
        "delivered",
        "delivery_stopped",
        "blocked",
        "stopped",
        "expired",
    }
)


@dataclass(frozen=True)
class ObservationStamp:
    source: str
    seen: float
    binding: str


class NativeObservation:
    def __init__(
        self, sessions, redis, *, admission: assistant_runs.RuntimeAdmission, clock=time.time
    ):
        if not isinstance(admission, assistant_runs.RuntimeAdmission) or not callable(clock):
            raise ValueError("Trusted observation dependencies required")
        self.sessions, self.redis, self.admission, self.clock = sessions, redis, admission, clock

    @staticmethod
    def key(live, cid):
        return "assistant-native:observation:v1:" + ":".join(
            map(
                str,
                (
                    live.principal_id,
                    live.operator_id,
                    live.run_id,
                    live.generation,
                    cid,
                ),
            )
        )

    async def _source(self, db, live, cid):
        fresh = await assistant_runs.authority(
            db, live.principal_id, live.run_id, live.generation, self.admission
        )
        if fresh != live or fresh.mode != "auto":
            return None
        job = await db.get(AssistantDialog, cid, populate_existing=True)
        conv = await db.get(Conversation, cid, populate_existing=True)
        if (
            job is None
            or conv is None
            or job.principal_id != live.principal_id
            or job.operator_id != live.operator_id
            or job.state != "waiting"
            or conv.status == "closed"
            or conv.crm_request_id
            or conv.transfer_to_id
            or conv.bot_active
            or conv.assignee_id != live.operator_id
            or conv.claimed_by_id != live.operator_id
        ):
            return None
        # Actual ownership/Run/role checks precede the existing bounded source
        # read. Nothing from its customer body is copied to this observation.
        value = await leadbot_reader._snapshot(
            db,
            str(cid),
            {
                "principal_id": str(live.principal_id),
                "operator_id": str(live.operator_id),
            },
        )
        source = value[0]["source_sha256"] if value else None
        return source if isinstance(source, str) and re.fullmatch(r"[0-9a-f]{64}", source) else None

    async def capture(self, live, cid):
        try:
            async with asyncio.timeout(STEP_BUDGET):
                return await self._capture(live, cid)
        except TimeoutError:
            log.warning("assistant.observation_capture_timeout")
            return None

    async def _capture(self, live, cid):
        try:
            seen = self.clock()
            if not math.isfinite(seen) or seen < 0:
                return None
            async with self.sessions() as db:
                source = await self._source(db, live, cid)
            return ObservationStamp(source, seen, self.key(live, cid)) if source else None
        except Exception:
            log.warning("assistant.observation_capture_unavailable")
            return None

    async def record(self, live, cid, progress, stamp):
        try:
            async with asyncio.timeout(STEP_BUDGET):
                return await self._record(live, cid, progress, stamp)
        except TimeoutError:
            log.warning("assistant.observation_record_timeout")
            return False

    async def _record(self, live, cid, progress, stamp):
        try:
            if (
                not isinstance(stamp, ObservationStamp)
                or stamp.binding != self.key(live, cid)
                or not isinstance(progress, dict)
                or progress.get("cid") != str(cid)
                or progress.get("state") not in STAGES
                or "source_sha256" in progress
                and progress["source_sha256"] != stamp.source
            ):
                return False
            now = self.clock()
            if not math.isfinite(now) or not 0 <= now - stamp.seen <= TTL:
                return False
            async with self.sessions() as db:
                if await self._source(db, live, cid) != stamp.source:
                    return False
            value = {
                "v": 1,
                "principal_id": str(live.principal_id),
                "operator_id": str(live.operator_id),
                "run_id": str(live.run_id),
                "generation": live.generation,
                "cid": str(cid),
                "versions": list(live.versions),
                "source": stamp.source,
                "seen": stamp.seen,
                "stage": progress["state"],
            }
            return bool(await self.redis.set(self.key(live, cid), encode(value).decode(), ex=TTL))
        except Exception:
            # Observation failure cannot retry a model, stop a Run or alter an
            # original durable command. The UI gets unknown instead.
            log.warning("assistant.observation_record_unavailable")
            return False

    async def annotate(self, db, principal, page):
        assistant_dialogs.require_admin(principal)
        rows = page.get("items")
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError("An authorized bounded SQL dialogue page is required")
        output = []
        for row in rows:
            if not isinstance(row, dict) or row.get("principal_id") != str(principal.id):
                raise ValueError("Observation cannot cross the SQL page owner")
            output.append({**row, "observation": None})
        result = {**page, "items": output}
        try:
            async with asyncio.timeout(PAGE_BUDGET):
                return await self._annotate(db, principal, rows, result, output)
        except TimeoutError:
            log.warning("assistant.observation_page_timeout")
            return {**page, "items": [{**row, "observation": None} for row in rows]}

    async def _annotate(self, db, principal, rows, result, output):
        try:
            run = await db.get(AssistantRun, principal.id, populate_existing=True)
            if run is None or run.state != "running" or run.mode != "auto":
                return result
            live = await assistant_runs.authority(
                db, principal.id, run.run_id, run.generation, self.admission
            )
            selected = [
                (i, uuid.UUID(row["id"]))
                for i, row in enumerate(rows)
                if row.get("operator_id") == str(live.operator_id) and row.get("state") == "waiting"
            ]
            if not selected:
                return result
            # No SCAN, other-owner probe or unbounded history-key walk.
            values = await self.redis.mget([self.key(live, cid) for _, cid in selected])
            if not isinstance(values, list) or len(values) != len(selected):
                return result
            fields = {
                "v",
                "principal_id",
                "operator_id",
                "run_id",
                "generation",
                "cid",
                "versions",
                "source",
                "seen",
                "stage",
            }
            for (index, cid), raw in zip(selected, values, strict=True):
                try:
                    if not isinstance(raw, (str, bytes)):
                        continue
                    value = decode(raw.encode() if isinstance(raw, str) else raw, 4096)
                    if (
                        not isinstance(value, dict)
                        or set(value) != fields
                        or type(value["v"]) is not int
                        or value["v"] != 1
                        or value["principal_id"] != str(live.principal_id)
                        or value["operator_id"] != str(live.operator_id)
                        or value["run_id"] != str(live.run_id)
                        or type(value["generation"]) is not int
                        or value["generation"] != live.generation
                        or value["cid"] != str(cid)
                        or value["versions"] != list(live.versions)
                        or value["stage"] not in STAGES
                        or type(value["seen"]) not in (int, float)
                        or not math.isfinite(value["seen"])
                        or not 0 <= self.clock() - value["seen"] <= TTL
                        or await self._source(db, live, cid) != value["source"]
                    ):
                        continue
                    output[index]["observation"] = {
                        "stage": value["stage"],
                        "observed_at": value["seen"],
                        "source_sha256": value["source"],
                        "observation_only": True,
                    }
                except Exception:
                    continue
        except Exception:
            log.warning("assistant.observation_page_unavailable")
        return result
