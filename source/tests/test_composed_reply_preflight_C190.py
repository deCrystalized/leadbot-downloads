"""Already used words can be reconsidered before the independent review."""

import json
from unittest.mock import patch

import test_owner_auto241 as owner_auto
import test_reviewed_reply_finalization_C189 as reply_bridge
from research_workflow import ResearchService
from test_unique_replies296 import accept, proposed

bridge = reply_bridge.bridge


def test_owner_auto_can_reword_a_composed_repeat_after_reopening_jobs():
    original_init = ResearchService.__init__

    def configure(service, *args, **kwargs):
        kwargs["unique_replies_enabled"] = True
        original_init(service, *args, **kwargs)

    case = owner_auto.OwnerAuto241Tests()
    try:
        with patch.object(ResearchService, "__init__", configure):
            case.setUp()
        first = case.finish()
        owner = owner_auto.fixture.OWNER
        service = case.sim.service
        original = json.loads(service.jobs._file(first, "result.json").read_bytes())
        full = original["candidate"]["reply"]
        assert full.startswith("Здравствуйте! ")
        raw = full.removeprefix("Здравствуйте! ")
        assert service.jobs.reply_available(owner, raw) is True
        assert service.jobs.reply_available(owner, full) is False

        reopened = ResearchService(
            case.sim.root / "research",
            shared_lock=service.jobs.lock,
            corpus_factory=service.corpus_factory,
            request=case.sim.provider,
            schedule=case.sim.work.append,
            native_context=service.native_context,
            proposal_enabled=True,
            unique_replies_enabled=True,
            owner_auto_enabled=True,
            auto_session_call_limit=8,
        )
        case.sim.app.research = case.sim.service = reopened
        case.next_context("authored-composed-repeat-after-restart")
        wording = "Здравствуйте! Из какого материала у Вас стена?"
        meaning = {
            "intent": "Клиент хочет повесить полку.",
            "meaning": "Просит повесить полку.",
            "note": "Материал стены ещё не указан.",
        }
        case.sim.scripted_candidates = [
            dict(meaning, reply=raw),
            dict(meaning, reply=wording),
        ]
        second = case.finish()
        saved = json.loads(reopened.jobs._file(second, "result.json").read_bytes())
        assert saved["candidate"]["reply"] == wording
        assert [x["role"] for x in saved["trace"]] == ["research", "research", "review"]
        final, code = case.research("research_finalize", second)
        assert code == 200 and final["cached"] is True
        assert final["validation"] == []
        assert final["reply"] == wording
        assert final["needs_operator"] is False
        audit = reopened.jobs.audit_read(owner, second)
        assert audit["chain_valid"]
        assert any(e["event"] == "reply_revision_required" for e in audit["events"])
        assert len(case.sim.requests) == 5 and len(case.jobs()) == 2
        status, code = case.sim.app.handle(dict(case.body, action="personal_status"))
        assert code == 200 and status["research_auto"]["reserved_calls"] == 8
        assert status["research_auto"]["remaining_calls"] == 0
    finally:
        case.doCleanups()


def test_two_calls_leave_no_budget_to_reword_a_composed_repeat(bridge):
    question = bridge.task["decision"]["next_question"]["question"]
    full = "Здравствуйте! " + question
    store = bridge.service.jobs
    prior = proposed(store, 1, "Что за материал использован для стены?", owner="owner")
    accept(store, prior)
    store.finalize(
        prior[0],
        prior[2],
        fresh=lambda: prior[2],
        finish=lambda _: {"reply": full, "needs_operator": False, "validation": []},
    )
    bridge.scripted_reply = question
    bridge.service.admit(bridge.app, bridge.body, max_calls=2, seconds=300)
    pending, code = bridge.call("research_start")
    assert code == 200 and pending["pending_research"]
    assert len(bridge.work) == 1
    bridge.work.pop(0)()
    job = pending["research_job_id"]
    rejected = json.loads(store._file(job, "result.json").read_bytes())
    assert rejected["approved"] is False and rejected["reply"] == ""
    assert "Repeated complete reply" in rejected["reason"]
    assert [x["role"] for x in rejected["trace"]] == ["research"]
    assert store.status("owner", job)["state"] == "rejected"
    assert len(bridge.requests) == 1
