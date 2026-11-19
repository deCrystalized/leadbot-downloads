"""Actual listing SQL over an isolated SQLite model, no production connections."""
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as Obj
from unittest.mock import patch
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from app.core.errors import ApiError
from app.services import assistant_dialogs as service


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "listing_conversation"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String)
    crm_request_id: Mapped[str | None] = mapped_column(String)
    assignee_id: Mapped[str | None] = mapped_column(String)
    transfer_to_id: Mapped[str | None] = mapped_column(String, default=None)
    bot_active: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    last_message_at: Mapped[datetime] = mapped_column(DateTime)


class Job(Base):
    __tablename__ = "listing_job"
    conversation_id: Mapped[str] = mapped_column(ForeignKey(Conversation.id), primary_key=True)
    principal_id: Mapped[str] = mapped_column(String)
    operator_id: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class ListingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.session.close)
        for name, value in [("AssistantDialog", Job), ("Conversation", Conversation)]:
            p = patch.object(service, name, value);p.start();self.addCleanup(p.stop)
        p = patch.object(service.inbox, "is_waiting", lambda conv: False)
        p.start();self.addCleanup(p.stop)
        session = self.session
        class DB:
            async def execute(self, stmt):return session.execute(stmt)
            async def scalar(self, stmt):return session.scalar(stmt)
            async def commit(self):raise AssertionError("Observation cannot write")
            async def flush(self):raise AssertionError("Observation cannot write")
        self.db = DB()
        self.principal = Obj(id="owner", role="admin", is_active=True, deleted_at=None, is_service=False)

    def add(self, cid, status="in_progress", crm=None, actor="author", owner="owner", state="waiting"):
        now = datetime.now(UTC)
        conv = Conversation(id=cid, status=status, crm_request_id=crm, assignee_id=actor,
                            updated_at=now, last_message_at=now-timedelta(hours=11))
        job = Job(conversation_id=cid, principal_id=owner, operator_id=actor, version=1,
                  state=state, updated_at=now)
        self.session.add_all([conv, job]);self.session.commit()
        return job, conv

    async def test_fourteen_closed_jobs_do_not_remain_active_or_get_mutated(self):
        for i in range(14):self.add(str(i), status="closed", state="paused")
        active = await service.list_jobs(self.db, self.principal, 25, 0)
        self.assertEqual(active["total"], 0);self.assertEqual(active["items"], [])
        archive = await service.list_jobs(self.db, self.principal, 25, 0, "archive")
        self.assertEqual(archive["total"], 14)
        self.assertTrue(all(r["state"] == "closed" and not r["auto_started"] for r in archive["items"]))
        self.assertEqual(set(self.session.scalars(select(Job.state))), {"paused"})

    async def test_filtering_precedes_pagination_and_exact_total(self):
        for i in range(40):self.add("old"+str(i), status="closed")
        for i in range(27):self.add("live"+str(i))
        first = await service.list_jobs(self.db, self.principal, 25, 0)
        last = await service.list_jobs(self.db, self.principal, 25, 25)
        self.assertEqual(first["total"], 27);self.assertEqual(len(first["items"]), 25)
        self.assertTrue(first["more"]);self.assertFalse(last["more"])
        self.assertEqual(len(last["items"]), 2)
        self.assertEqual(len({r["id"] for r in first["items"]+last["items"]}), 27)

    async def test_manual_close_is_visible_without_a_job_or_message_version_change(self):
        job, conv = self.add("same")
        before = service.snapshot(job, conv)
        conv.status = "closed";conv.updated_at += timedelta(minutes=1)
        after = service.snapshot(job, conv)
        self.assertEqual(after["version"], before["version"])
        self.assertEqual(after["last_message_at"], before["last_message_at"])
        self.assertNotEqual(after["source_revision"], before["source_revision"])
        self.assertEqual(after["state"], "closed")

    async def test_linked_order_is_archived_and_never_counted_as_active(self):
        self.add("created", crm="9000001")
        self.assertEqual((await service.list_jobs(self.db,self.principal,25,0))["total"], 0)
        rows = (await service.list_jobs(self.db,self.principal,25,0,"archive"))["items"]
        self.assertEqual(rows[0]["state"], "completed")

    async def test_principal_and_selected_author_are_isolated(self):
        self.add("a", actor="a");self.add("b", actor="b");self.add("foreign", actor="a", owner="other")
        rows = (await service.list_jobs(self.db,self.principal,25,0,"active","a"))["items"]
        self.assertEqual([r["id"] for r in rows], ["a"])

    async def test_reassignment_unassignment_transfer_and_other_bot_are_not_active(self):
        for cause in ("assignee", "unassigned", "transfer", "bot"):
            job, conv = self.add(cause)
            if cause == "assignee":conv.assignee_id = "other"
            elif cause == "unassigned":conv.assignee_id = None
            elif cause == "transfer":conv.transfer_to_id = "other"
            else:conv.bot_active = True
        self.session.commit()
        self.assertEqual((await service.list_jobs(self.db,self.principal,25,0))["total"], 0)
        rows=(await service.list_jobs(self.db,self.principal,25,0,"archive"))["items"]
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(r["state"] == "released" for r in rows))

    async def test_invalid_view_and_nonadmin_are_rejected(self):
        with self.assertRaises(ApiError):await service.list_jobs(self.db,self.principal,25,0,"anything")
        self.principal.role = "manager"
        with self.assertRaises(ApiError):await service.list_jobs(self.db,self.principal,25,0)
