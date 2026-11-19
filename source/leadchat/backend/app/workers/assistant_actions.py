"""Short native action steps; configured by trusted worker startup, default OFF."""

import uuid

from app.core.observability import with_job_scope
from app.services.assistant_actions import NativeActionCoordinator


@with_job_scope
async def native_action_step(ctx: dict, action_key: str):
    service = ctx.get("native_action_coordinator")
    if not isinstance(service, NativeActionCoordinator) or not service.enabled:
        return {"state": "disabled", "execution_allowed": False}
    result = await service.advance(action_key)
    delay, queue = result.get("next_poll_after_s"), ctx.get("arq")
    if delay is not None and queue is not None and ctx.get("native_driver_managed") is not True:
        await queue.enqueue_job(
            "native_action_step",
            action_key,
            _defer_by=delay,
            _job_id="native-action:" + uuid.uuid4().hex,
        )
    return result


async def recover_native_actions(ctx: dict) -> int:
    service, queue = ctx.get("native_action_coordinator"), ctx.get("arq")
    if not isinstance(service, NativeActionCoordinator) or not service.enabled or queue is None:
        return 0
    keys = await service.due()
    for key in keys:
        await queue.enqueue_job(
            "native_action_step", key, _job_id="native-action:" + uuid.uuid4().hex
        )
    return len(keys)
