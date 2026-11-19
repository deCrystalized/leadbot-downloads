"""Bounded server-owned dialog cycle. No observer tab or browser lease is needed.

Only existing durable services dispatch private commands or delivery. This
driver schedules their observation steps; it never repeats an unknown send,
chooses a model, repairs a response or fabricates a CRM/Telegram receipt.
"""

import json
import math
import time
from collections.abc import Callable
from datetime import UTC

from sqlalchemy import exists, func, select

from app.core.errors import ApiError
from app.models import AssistantDialog, AssistantRun, AvitoAccount, Conversation, User
from app.models import AssistantNativeAction as Action
from app.models import AssistantResearchWork as Research
from app.services import assistant_actions, assistant_dialogs, assistant_runs, inbox, leadbot_reader
from app.services.assistant_research import TERMINAL as RESEARCH_TERMINAL
from app.services.assistant_research import NativeResearchRelay, ready_visual, visual_source_review
from app.services.leadbot_execution_protocol import decode


def _object(raw):
    value = decode((raw or "{}").encode(), 1000000)
    if not isinstance(value, dict):
        raise ValueError("Original native result object required")
    return value


class NativeDialogDriver:
    def __init__(
        self,
        sessions,
        *,
        admission: assistant_runs.RuntimeAdmission,
        actions: assistant_actions.NativeActionCoordinator,
        research: NativeResearchRelay,
        redis,
        arq,
        enabled: bool = False,
        max_dialogs: int = 20,
        scan_batch: int = 20,
        settle_seconds: float = 2,
        clock: Callable[[], float] = time.time,
        observer=None,
        office=None,
    ):
        from app.services.assistant_observation import NativeObservation
        from app.services.assistant_office import NativeOffice

        if (
            not isinstance(admission, assistant_runs.RuntimeAdmission)
            or not isinstance(actions, assistant_actions.NativeActionCoordinator)
            or not isinstance(research, NativeResearchRelay)
            or type(enabled) is not bool
            or type(max_dialogs) is not int
            or not 1 <= max_dialogs <= 100
            or type(scan_batch) is not int
            or not 1 <= scan_batch <= 100
            or type(settle_seconds) not in (int, float)
            or not math.isfinite(settle_seconds)
            or not 0 <= settle_seconds <= 10
            or not callable(clock)
            or enabled
            and (not actions.enabled or not research.enabled or arq is None)
            or observer is not None
            and (
                not isinstance(observer, NativeObservation)
                or observer.sessions is not sessions
                or observer.redis is not redis
                or observer.admission != admission
            )
            or office is not None
            and (
                not isinstance(office, NativeOffice)
                or office.sessions is not sessions
                or office.redis is not redis
                or office.admission != admission
                or not office.enabled
            )
        ):
            raise ValueError("Trusted bounded native driver dependencies required")
        self.sessions, self.admission = sessions, admission
        self.actions, self.research, self.redis, self.arq = actions, research, redis, arq
        self.enabled, self.max_dialogs, self.scan_batch = enabled, max_dialogs, scan_batch
        self.settle_seconds, self.clock = settle_seconds, clock
        self.observer = observer
        self.office = office

    async def schedule_existing(self):
        """One deterministic observer job at a time; never a vendor-job retry.

        Managed callbacks do not create parallel self-polling chains. A queue
        restart can only call advance() on already persisted work. Its command
        journal, not the ARQ observer ID, decides whether dispatch is new.
        """
        if not self.enabled:
            return 0
        count = 0
        for service, name, prefix in (
            (self.actions, "native_action_step", "native-action-observe:"),
            (self.research, "native_research_step", "native-research-observe:"),
        ):
            for key in await service.due():
                await self.arq.enqueue_job(name, key, _job_id=prefix + key)
                count += 1
        if self.office is not None:
            for key in await self.office.due():
                await self.arq.enqueue_job(
                    "native_office_step", key, _job_id="native-office-observe:" + key
                )
                count += 1
        return count

    async def _block(self, live, code):
        async with self.sessions() as db:
            result = await assistant_runs.block(db, live, code)
            await db.commit()
            return result

    async def _source(self, live, cid):
        async with self.sessions() as db:
            current = await assistant_runs.authority(
                db, live.principal_id, live.run_id, live.generation, self.admission
            )
            if current != live:
                raise ValueError("Original native Run changed")
            result = await leadbot_reader._snapshot(
                db,
                str(cid),
                {"principal_id": str(live.principal_id), "operator_id": str(live.operator_id)},
            )
            if result is None:
                raise ValueError("Current authorized native source required")
            return result

    async def _snapshot(self, live, cid):
        return (await self._source(live, cid))[0]["source_sha256"]

    @staticmethod
    def _audio_state(header, source):
        if "unfinished_ASR" not in header.get("pending_reasons", ()):
            return None
        unfinished = []
        for message in source["messages"]:
            status = message.get("voice_transcript_status")
            audio = any(
                (a.get("kind") or a.get("type") or a.get("avito_type")) in ("voice", "audio")
                for a in message.get("attachments", ())
            )
            if (
                status
                and status != "done"
                or audio
                and (status != "done" or not message.get("voice_transcript"))
            ):
                unfinished.append(message)
        if (
            set(header.get("pending_reasons", ())) == {"unfinished_ASR"}
            and unfinished
            and all(
                m.get("direction") == "in"
                and m.get("sender_type") == "client"
                and m.get("voice_transcript_status")
                in ("pending", "queued", "processing", "transcribing")
                for m in unfinished
            )
        ):
            return "waiting_transcription"
        # Failed/unknown empty audio and mixed unresolved media remain review,
        # not an invented client fact or an indefinite transcription wait.
        return "source_review"

    async def _block_if_current(self, live, cid, source_hash, code):
        # An ordinary new inbound or same-ID ASR correction is not by itself
        # a technical incident that revokes the whole launch.
        if await self._snapshot(live, cid) == source_hash:
            await self._block(live, code)
            return {"cid": str(cid), "state": "technical_stop", "reason_code": code}
        return {"cid": str(cid), "state": "source_changed"}

    async def _handoff_if_current(self, live, cid, source, reason):
        if await self._snapshot(live, cid) != source:
            return {"cid": str(cid), "state": "source_changed"}
        async with self.sessions() as db:
            # Serialize with start/stop before locking the affected conversation.
            principal = await assistant_runs._principal(db, live.principal_id, lock=True)
            await assistant_runs.authority(
                db, live.principal_id, live.run_id, live.generation, self.admission
            )
            job = await db.get(AssistantDialog, cid)
            if job is None:
                return {"cid": str(cid), "state": "source_changed"}
            await assistant_dialogs.locked_job(db, principal, cid, live.operator_id, job.version)
            current = await leadbot_reader._snapshot(
                db,
                str(cid),
                {"principal_id": str(live.principal_id), "operator_id": str(live.operator_id)},
            )
            if current is None or current[0]["source_sha256"] != source:
                return {"cid": str(cid), "state": "source_changed"}
            await assistant_dialogs.pause(db, principal, cid, live.operator_id, job.version)
        return {"cid": str(cid), "state": "needs_operator", "reason": reason}

    async def _quiet(self, cid):
        async with self.sessions() as db:
            stamp = await db.scalar(
                select(Conversation.last_message_at).where(Conversation.id == cid)
            )
        if stamp is None:
            return True
        stamp = stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp
        return self.clock() - stamp.timestamp() >= self.settle_seconds

    async def _visual(self, live, cid, source, *, preclaim=False):
        work = await self.research.enqueue(live, cid, source, "visual", preclaim=preclaim)
        if work["state"] == "waiting_model_capacity":
            return {"cid": str(cid), **work}
        if work["state"] == "ready":
            async with self.sessions() as db:
                original = await db.get(Research, work["work_id"])
                if ready_visual(original, live, cid, source):
                    return {"cid": str(cid), "state": "media_observed", "source_sha256": source}
            return await self._block_if_current(live, cid, source, "native_model")
        if work["state"] in RESEARCH_TERMINAL:
            async with self.sessions() as db:
                original = await db.get(Research, work["work_id"])
                result = _object(original.result)
            if work["state"] == "parked" and result.get("code") == "research_prior_attempt":
                return {
                    "cid": str(cid),
                    "state": "prior_attempt_review",
                    "needs_operator": True,
                    "retry_started": False,
                }
            if (
                work["state"] == "parked"
                and original.purpose == "visual"
                and visual_source_review(result)
                and original.principal_id == live.principal_id
                and original.operator_id == live.operator_id
                and original.conversation_id == cid
                and original.source_hash == source
            ):
                current = (
                    original.run_id == live.run_id
                    and original.generation == live.generation
                    and json.loads(original.versions) == list(live.versions)
                )
                return {
                    "cid": str(cid),
                    "state": "source_review" if current else "prior_attempt_review",
                    "needs_operator": True,
                    "retry_started": False,
                }
            return await self._block_if_current(live, cid, source, "native_model")
        return {"cid": str(cid), "state": "research_pending", "source_sha256": source}

    async def _media_intake(self, live, cid, source):
        work = await self.actions.intake_screen(live, cid, source)
        async with self.sessions() as db:
            original = await db.get(Action, work["action_key"])
            if original.stage in ("blocked", "stopped", "expired"):
                return await self._block_if_current(live, cid, source, "native_source")
            if original.stage != "screened":
                return {"cid": str(cid), "state": "screening"}
            planned = _object(original.result)
        if planned.get("eligible") is True and planned["step"] == "claim":
            return None  # The ordinary claim still obtains its own fresh permit.
        if planned.get("eligible") is True and planned["step"] == "inspect_media":
            progress = await self._visual(live, cid, source, preclaim=True)
            if progress["state"] == "media_observed" and original.research_key:
                return {"cid": str(cid), "state": "source_review", "needs_operator": True}
            return progress
        return {
            "cid": str(cid),
            "state": "wait" if planned["step"] in ("wait", "paused") else "source_review",
            "needs_operator": planned["step"] == "handoff",
        }

    async def _drive_owned(self, live, cid):
        if self.office is not None:
            office = await self.office.observe_owned(live, cid)
            if office is not None:
                return {"cid": str(cid), **office}
        async with self.sessions() as db:
            # Own pending output never becomes a new client turn. An old Run
            # may have left an original effect to observe, not to adopt/send.
            unresolved = await db.scalar(
                select(Action)
                .where(
                    Action.conversation_id == cid,
                    Action.kind != "screen",
                    Action.stage.not_in(assistant_actions.TERMINAL),
                )
                .order_by(Action.deadline)
                .limit(1)
            )
            # Effect uncertainty belongs to the conversation, not to its
            # former author/controller. This metadata-only fence exposes no
            # old customer's text or receipt to a new actor.
            if unresolved is not None:
                if unresolved.stage == "queue_unknown":
                    await self._block(live, "native_delivery")
                    return {
                        "cid": str(cid),
                        "state": "technical_stop",
                        "reason_code": "native_delivery",
                    }
                return {"cid": str(cid), "state": "waiting_original_delivery"}
            pending = await db.scalar(
                select(Research)
                .where(
                    Research.principal_id == live.principal_id,
                    Research.operator_id == live.operator_id,
                    Research.conversation_id == cid,
                    Research.stage.not_in(("ready", "parked", "blocked", "stopped", "expired")),
                )
                .order_by(Research.deadline)
                .limit(1)
            )
            if pending is not None:
                return {
                    "cid": str(cid),
                    "state": "research_pending",
                    "source_sha256": pending.source_hash,
                }
        if not await self._quiet(cid):
            return {"cid": str(cid), "state": "collecting_messages"}
        header, raw = await self._source(live, cid)
        audio = self._audio_state(header, raw)
        if audio:
            return {"cid": str(cid), "state": audio, "needs_operator": audio == "source_review"}
        source = header["source_sha256"]
        screen = await self.actions.screen(live, cid, source)
        async with self.sessions() as db:
            row = await db.get(Action, screen["action_key"])
            if row.stage in ("blocked", "stopped", "expired"):
                return await self._block_if_current(live, cid, source, "native_source")
            if row.stage != "screened":
                return {"cid": str(cid), "state": "screening"}
            planned = _object(row.result)
        step = planned["step"]
        if step in ("wait", "paused"):
            return {"cid": str(cid), "state": "wait", "reason": planned.get("reason", "")}
        if step == "handoff":
            return await self._handoff_if_current(live, cid, source, planned.get("reason", ""))
        if step == "inspect_media":
            if row.research_key:
                return {"cid": str(cid), "state": "source_review", "needs_operator": True}
            return await self._visual(live, cid, source)
        purpose = "intake_form" if step == "prepare_crm" else "reply"
        if purpose == "intake_form" and self.office is not None:
            if await self.research.pending():
                # Do not start the separate original CRM resource deadline
                # while another CID is still using the shared model slot.
                return {
                    "cid": str(cid),
                    "state": "waiting_model_capacity",
                    "model_started": False,
                    "needs_operator": False,
                    "execution_allowed": False,
                    "can_send_or_create": False,
                }
            capacity = await self.office.capacity(live, cid, source)
            if capacity.get("capacity") is not True:
                return {"cid": str(cid), **capacity}
        work = await self.research.enqueue(live, cid, source, purpose)
        if work["state"] == "waiting_model_capacity":
            return {"cid": str(cid), **work}
        if work["state"] in ("parked", "blocked", "stopped", "expired"):
            if work["state"] == "parked":
                async with self.sessions() as db:
                    prior = await db.get(Research, work["work_id"])
                    result = _object(prior.result)
                if result.get("code") == "research_prior_attempt":
                    return {
                        "cid": str(cid),
                        "state": "prior_attempt_review",
                        "needs_operator": True,
                        "retry_started": False,
                    }
                if (
                    purpose == "reply"
                    and result.get("ok") is True
                    and result.get("action") == "handoff"
                    and result.get("needs_operator") is True
                    and result.get("reply") == ""
                    and result.get("draft_id")
                    and result.get("response_source") == "model"
                    and result.get("context_review_status") == "provided"
                    and result.get("validation")
                    == ["empty_or_long_reply", "model_context_mismatch"]
                    and result.get("code") is None
                    and result.get("execution_allowed") in (None, False)
                    and result.get("can_send_or_create") in (None, False)
                ):
                    return await self._handoff_if_current(
                        live, cid, source, "Ответ не прошёл проверку контекста"
                    )
            return await self._block_if_current(live, cid, source, "native_model")
        if work["state"] != "ready":
            return {
                "cid": str(cid),
                "state": "research_pending",
                "purpose": purpose,
                "source_sha256": source,
            }
        async with self.sessions() as db:
            original = await db.get(Research, work["work_id"])
            result = _object(original.result)
        if purpose == "intake_form":
            if self.office is not None:
                return {
                    "cid": str(cid),
                    **await self.office.offer(
                        live,
                        cid,
                        source,
                        research_key=work["work_id"],
                        screen_key=screen["action_key"],
                    ),
                }
            return {
                "cid": str(cid),
                "state": "waiting_executor",
                "form_ready": True,
                "work_id": work["work_id"],
                "created": False,
                "telegram_confirmed": False,
            }
        if not isinstance(result.get("reply"), str) or not result["reply"].strip():
            if result.get("action") == "wait" and result.get("needs_operator") is not True:
                return {"cid": str(cid), "state": "wait"}
            return await self._block_if_current(live, cid, source, "native_model")
        effect = await self.actions.enqueue(live, cid, source, research_key=work["work_id"])
        if effect["state"] in ("blocked", "stopped", "expired", "delivery_stopped"):
            return await self._block_if_current(live, cid, source, "native_delivery")
        return {"cid": str(cid), "state": effect["state"]}

    async def _headers(self, live, offset):
        async with self.sessions() as db:
            await assistant_runs.authority(
                db, live.principal_id, live.run_id, live.generation, self.admission
            )
            author = await db.get(User, live.operator_id)
            conditions = [
                inbox.visible_queue_condition(db, author),
                inbox.queue_condition(),
                Conversation.channel == "avito",
                AvitoAccount.channel == "avito",
                Conversation.crm_request_id.is_(None),
                Conversation.transfer_to_id.is_(None),
                ~exists().where(AssistantDialog.conversation_id == Conversation.id),
            ]
            query = select(Conversation.id).join(
                AvitoAccount, AvitoAccount.id == Conversation.account_id
            )
            total = await db.scalar(
                select(func.count()).select_from(query.where(*conditions).subquery())
            )
            ids = list(
                await db.scalars(
                    query.where(*conditions)
                    .order_by(Conversation.offered_at, Conversation.id)
                    .offset(offset)
                    .limit(self.scan_batch)
                )
            )
            return ids, total

    async def _run(self, live):
        own_cursor_key = "assistant-native:owned-scan:" + str(live.run_id)
        saved = await self.redis.get(own_cursor_key)
        offset = int(saved) if saved and str(saved).isdigit() else 0
        async with self.sessions() as db:
            owned_query = (
                select(AssistantDialog.conversation_id)
                .join(Conversation, Conversation.id == AssistantDialog.conversation_id)
                .where(
                    AssistantDialog.principal_id == live.principal_id,
                    AssistantDialog.operator_id == live.operator_id,
                    AssistantDialog.state == "waiting",
                    Conversation.status != "closed",
                    Conversation.crm_request_id.is_(None),
                    Conversation.assignee_id == live.operator_id,
                    Conversation.claimed_by_id == live.operator_id,
                )
            )
            owned_count = await db.scalar(select(func.count()).select_from(owned_query.subquery()))
            offset = offset if 0 <= offset < owned_count else 0
            owned = list(
                await db.scalars(
                    owned_query.order_by(Conversation.last_message_at, Conversation.id)
                    .offset(offset)
                    .limit(self.scan_batch)
                )
            )
            pending_claims = await db.scalar(
                select(func.count(func.distinct(Action.conversation_id))).where(
                    Action.principal_id == live.principal_id,
                    Action.operator_id == live.operator_id,
                    Action.kind == "claim",
                    Action.stage.not_in(assistant_actions.TERMINAL),
                    ~exists().where(
                        AssistantDialog.conversation_id == Action.conversation_id,
                        AssistantDialog.principal_id == live.principal_id,
                        AssistantDialog.operator_id == live.operator_id,
                        AssistantDialog.state == "waiting",
                    ),
                )
            )
            pending_visuals = await db.scalar(
                select(func.count(func.distinct(Research.conversation_id))).where(
                    Research.principal_id == live.principal_id,
                    Research.operator_id == live.operator_id,
                    Research.run_id == live.run_id,
                    Research.generation == live.generation,
                    Research.purpose == "visual",
                    Research.dialog_version == 0,
                    Research.stage.not_in(RESEARCH_TERMINAL),
                )
            )
        await self.redis.set(
            own_cursor_key,
            0 if offset + len(owned) >= owned_count else offset + len(owned),
            ex=3600,
        )
        progress = []
        for cid in owned[: self.scan_batch]:
            try:
                stamp = await self.observer.capture(live, cid) if self.observer else None
                progress.append(await self._drive_owned(live, cid))
                if self.observer:
                    await self.observer.record(live, cid, progress[-1], stamp)
                if progress[-1]["state"] == "technical_stop":
                    return progress
            except ApiError as error:
                if error.code not in (
                    "assistant_run_stale",
                    "assistant_stale",
                    "assistant_completed",
                    "assistant_assignment_changed",
                    "assistant_unavailable",
                ):
                    raise
                return progress
            except leadbot_reader.SourcePending:
                progress.append(
                    {
                        "cid": str(cid),
                        "state": "source_review",
                        "needs_operator": True,
                        "reason_code": "source_incomplete",
                    }
                )
        slots = self.max_dialogs - owned_count - pending_claims - pending_visuals
        if slots <= 0:
            return progress
        # Root admits one global model job. Finish already taken work before
        # taking another batch whose independent deadlines would just expire.
        # This never limits the panel page size or abandons waiting clients.
        if await self.research.pending():
            return progress
        async with self.sessions() as db:
            claim_pending = await db.scalar(
                select(Action.key)
                .where(
                    Action.kind == "claim",
                    Action.stage.not_in(assistant_actions.TERMINAL),
                    Action.deadline > self.clock(),
                )
                .limit(1)
            )
        if claim_pending is not None:
            return progress
        slots = min(slots, 1)
        cursor_key = "assistant-native:scan:" + str(live.run_id)
        old = await self.redis.get(cursor_key)
        offset = int(old) if old and str(old).isdigit() else 0
        ids, total = await self._headers(live, offset)
        if not ids and offset:
            ids, total = await self._headers(live, 0)
            offset = 0
        await self.redis.set(
            cursor_key, 0 if offset + len(ids) >= total else offset + len(ids), ex=3600
        )
        for cid in ids:
            if slots <= 0:
                break
            if not await self._quiet(cid):
                continue
            try:
                header, raw = await self._source(live, cid)
                audio = self._audio_state(header, raw)
                if audio:
                    progress.append(
                        {
                            "cid": str(cid),
                            "state": audio,
                            "needs_operator": audio == "source_review",
                        }
                    )
                    continue  # No incomplete-ASR claim or model call.
                source = header["source_sha256"]
                if "original_media_identity_pending" in header.get("pending_reasons", ()):
                    media_progress = await self._media_intake(live, cid, source)
                    if media_progress is not None:
                        progress.append(media_progress)
                        if media_progress["state"] == "technical_stop":
                            break
                        if media_progress["state"] == "research_pending":
                            slots -= 1
                        continue
                action = await self.actions.enqueue(live, cid, source)
            except ApiError as error:
                if error.code in (
                    "assistant_assignment_changed",
                    "assistant_existing_job",
                    "assistant_completed",
                    "assistant_unavailable",
                ):
                    continue
                raise
            except leadbot_reader.SourcePending:
                progress.append(
                    {
                        "cid": str(cid),
                        "state": "source_review",
                        "needs_operator": True,
                        "reason_code": "source_incomplete",
                    }
                )
                continue
            if action["state"] == "blocked":
                async with self.sessions() as db:
                    prior = await db.get(Action, action["action_key"])
                    result = _object(prior.result)
                if not result:
                    await self._block(live, "native_transport")
                    break
                continue  # Source-bound ineligible candidate stays unclaimed.
            progress.append({"cid": str(cid), "state": action["state"]})
            if action["state"] not in assistant_actions.TERMINAL:
                slots -= 1
        return progress

    async def tick(self):
        if not self.enabled:
            return {"state": "disabled", "runs": []}
        if not math.isfinite(self.clock()):
            raise ValueError("Finite native clock required")
        async with self.sessions() as db:
            rows = list(
                await db.scalars(
                    select(AssistantRun)
                    .where(AssistantRun.state == "running", AssistantRun.mode == "auto")
                    .order_by(AssistantRun.principal_id)
                    .limit(100)
                )
            )
        results = []
        for run in rows:
            try:
                async with self.sessions() as db:
                    live = await assistant_runs.authority(
                        db, run.principal_id, run.run_id, run.generation, self.admission
                    )
                progress = await self._run(live)
                results.append({"run_id": str(live.run_id), "progress": progress})
            except ApiError:
                # Current authority denied: no replacement launch or retake.
                stale = assistant_runs.RunAuthority(
                    run.principal_id,
                    run.operator_id,
                    run.run_id,
                    run.generation,
                    run.mode,
                    (run.policy_version, run.runtime_version, run.map_version, run.memory_version),
                )
                await self._block(stale, "native_runtime")
                continue
        await self.schedule_existing()
        return {"state": "observed", "runs": results}
