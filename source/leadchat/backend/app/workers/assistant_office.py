"""Observe original office authorization; no CRM HTTP or automatic physical issue."""

from app.core.observability import with_job_scope
from app.services.assistant_office import NativeOffice


@with_job_scope
async def native_office_step(ctx: dict, work_key: str):
    service = ctx.get("native_office")
    if not isinstance(service, NativeOffice) or not service.enabled:
        return {"state": "disabled", "execution_allowed": False}
    return await service.advance(work_key)
