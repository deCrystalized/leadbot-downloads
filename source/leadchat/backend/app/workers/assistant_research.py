"""One short ARQ observation step; explicit configuration, disabled by default."""

import uuid
from typing import Any

from app.core.observability import with_job_scope
from app.services.assistant_research import NativeResearchRelay


@with_job_scope
async def native_research_step(ctx: dict, work_id: str) -> dict[str, Any]:
    relay = ctx.get("native_research_relay")
    if not isinstance(relay, NativeResearchRelay) or not relay.enabled:
        return {"state": "disabled", "can_send_or_create": False}
    result = await relay.advance(work_id)
    delay, queue = result.get("next_poll_after_s"), ctx.get("arq")
    if delay is not None and queue is not None and ctx.get("native_driver_managed") is not True:
        # DB CAS is authoritative; a new queue ID cannot regenerate a reply.
        await queue.enqueue_job(
            "native_research_step",
            work_id,
            _defer_by=delay,
            _job_id="native-research:" + uuid.uuid4().hex,
        )
    return result


async def recover_native_research(ctx: dict) -> int:
    relay, queue = ctx.get("native_research_relay"), ctx.get("arq")
    if not isinstance(relay, NativeResearchRelay) or not relay.enabled or queue is None:
        return 0
    keys = await relay.due()
    for key in keys:
        await queue.enqueue_job(
            "native_research_step", key, _job_id="native-research:" + uuid.uuid4().hex
        )
    return len(keys)
