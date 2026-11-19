"""The reserved, separately reviewed wording is the only publishable draft."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import pytest
import test_research_bridge203 as sources
from research_workflow import ResearchService
from test_unique_replies296 import accept, jobs, proposed


class ScriptedBridge(sources.ResearchBridgeTests):
    __test__ = False
    scripted_reply: str

    def provider(self, payload, timeout):
        result = json.loads(super().provider(payload, timeout))
        content = result["output"][0]["content"][0]
        model_output = json.loads(content["text"])
        if model_output["kind"] == "draft":
            model_output["reply"] = self.scripted_reply
            model_output["candidate"]["reply"] = self.scripted_reply
            model_output["claims"][0]["text"] = self.scripted_reply
            content["text"] = json.dumps(model_output, ensure_ascii=False)
        return json.dumps(result, ensure_ascii=False).encode()


@pytest.fixture
def bridge():
    case = ScriptedBridge()
    original = ResearchService.__init__

    def configure(service, *args, **kwargs):
        kwargs["unique_replies_enabled"] = True
        original(service, *args, **kwargs)

    try:
        with patch.object(ResearchService, "__init__", configure):
            case.setUp()
        yield case
    finally:
        case.doCleanups()


def finalize_reviewed(bridge, reply, *, before_finalize=None):
    bridge.scripted_reply = reply
    job = bridge.start()
    status, code = bridge.call("research_status", research_job_id=job)
    assert code == 200, status
    assert status["research_state"] == "awaiting_root"
    original = json.loads(bridge.service.jobs._file(job, "result.json").read_bytes())
    assert original["candidate"]["reply"] == reply
    assert [step["role"] for step in original["trace"]] == ["research", "review"]
    bridge.service.jobs.decide(
        job, status["result_sha256"], accepted=True, reviewer="authored-control"
    )
    if before_finalize is not None:
        before_finalize()
    result, code = bridge.call("research_finalize", research_job_id=job)
    assert code == 200
    return job, result


@pytest.mark.parametrize("prior_claimed_complete_text", [True, False])
def test_collision_after_composition_stops_the_draft(
    bridge, prior_claimed_complete_text
):
    question = bridge.task["decision"]["next_question"]["question"]
    public = "Здравствуйте! " + question

    def competing_finalize():
        prior = proposed(
            bridge.service.jobs,
            1,
            public
            if prior_claimed_complete_text
            else "Что за материал использован для стены?",
            owner="owner",
        )
        accept(bridge.service.jobs, prior)
        bridge.service.jobs.finalize(
            prior[0],
            prior[2],
            fresh=lambda: prior[2],
            finish=lambda _: {
                "ok": True,
                "reply": public,
                "needs_operator": False,
                "validation": [],
            },
        )

    job, result = finalize_reviewed(
        bridge, question, before_finalize=competing_finalize
    )
    assert result["reply"] == ""
    assert result["needs_operator"] is True
    assert "reply_already_used" in result["validation"]
    status = bridge.service.jobs.status("owner", job)
    assert status["state"] == "done"
    _, saved = bridge.app.store.request(bridge.scope, bridge.prepared["request_id"])
    assert saved["reply"] == "" and saved["needs_operator"] is True
    assert len(bridge.requests) == 2


def test_composed_text_is_reserved_and_recovered_as_the_same_result(bridge):
    question = bridge.task["decision"]["next_question"]["question"]
    reply = "Здравствуйте! " + question
    job, result = finalize_reviewed(bridge, question)
    assert result["reply"] == reply
    assert result["validation"] == []
    assert result["needs_operator"] is False
    assert result["draft_id"]
    assert bridge.service.jobs.reply_available("owner", reply) is False
    cached, code = bridge.call("research_finalize", research_job_id=job)
    assert code == 200 and cached["cached"] is True
    assert cached["reply"] == reply and cached["draft_id"] == result["draft_id"]
    assert len(bridge.requests) == 2


def test_two_finalizations_cannot_reserve_the_same_complete_text(tmp_path):
    stores = [jobs(tmp_path), jobs(tmp_path)]
    items = [
        proposed(stores[0], 1, "Вопрос в первом диалоге."),
        proposed(stores[0], 2, "Вопрос во втором диалоге."),
    ]
    for item in items:
        accept(stores[0], item)
    both_finalizing = Barrier(2, timeout=5)
    complete = "Здравствуйте! Из какого материала стены?"

    def finalize(store, item):
        job, _, binding = item

        def finish(_):
            both_finalizing.wait()
            reserved = store.reserve_final_reply(job, binding, complete)
            return {
                "reply": complete if reserved else "",
                "needs_operator": not reserved,
            }

        return store.finalize(job, binding, fresh=lambda: binding, finish=finish)

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(finalize, stores[0], items[0])
        second = pool.submit(finalize, stores[1], items[1])
        outcomes = [first.result(timeout=10), second.result(timeout=10)]
    assert sorted(item["reply"] for item in outcomes) == ["", complete]
    reopened = jobs(tmp_path)
    assert reopened.reply_available("bot-owner", complete) is False


def test_lost_finalization_response_keeps_the_complete_reply_claim(tmp_path):
    store = jobs(tmp_path)
    question = "Из какого материала стены?"
    complete = "Здравствуйте! " + question
    item = proposed(store, 1, question)
    accept(store, item)
    job, _, binding = item
    saved: list[dict[str, object]] = []

    def finish(_):
        assert store.reserve_final_reply(job, binding, complete) is True
        saved.append({"reply": complete, "needs_operator": False})
        raise SystemExit("authored response loss after saving the draft")

    with pytest.raises(SystemExit, match="response loss"):
        store.finalize(job, binding, fresh=lambda: binding, finish=finish)
    reopened = jobs(tmp_path)
    assert reopened.reply_available("bot-owner", complete) is False
    recovered = reopened.reconcile(
        job,
        binding,
        fresh=lambda: binding,
        read=lambda: {"done": True, "result": saved[0]},
    )
    assert recovered["reply"] == complete
    assert len(saved) == 1
    assert reopened.audit_read("bot-owner", job)["chain_valid"] is True


def test_guarded_finalization_cannot_substitute_a_server_template(bridge):
    candidate = {
        "reply": "Какой материал стен в помещении кухни или ванной?",
        "needs_operator": False,
        "context_review": {
            "last_intent": "Клиент просит повесить полку.",
            "latest_client_meaning": "Нужно повесить полку.",
            "selected_step_fits": True,
            "evidence_ids": ["client"],
            "note": "Материал стены ещё не указан.",
        },
    }

    def reserve(reply):
        pytest.fail(f"Unexpected reservation of a template: {reply}")

    out = bridge.app.finalize(
        bridge.scope, dict(bridge.body, candidate=candidate), reserve_reply=reserve
    )
    assert out["reply"] == ""
    assert out["needs_operator"] is True
    assert "reviewed_reply_changed" in out["validation"]
