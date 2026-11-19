"""Real SQLAlchemy expiration after commit; implicit response reads are forbidden.

SQLite and an async facade replace only the database transport. Production
MissingGreenlet evidence comes from the retained native claim traceback.
"""
import unittest
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace as Obj
from unittest.mock import AsyncMock, patch

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, create_engine, event, func, inspect
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from app.core.errors import ApiError
from app.services import assistant_dialogs as service


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "commit_conversation"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, default="in_progress")
    crm_request_id: Mapped[str | None] = mapped_column(String)
    assignee_id: Mapped[str | None] = mapped_column(String)
    claimed_by_id: Mapped[str | None] = mapped_column(String)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime)
    transfer_to_id: Mapped[str | None] = mapped_column(String)
    bot_active: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp())
    last_message_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class Job(Base):
    __tablename__ = "commit_job"
    conversation_id: Mapped[str] = mapped_column(ForeignKey(Conversation.id), primary_key=True)
    principal_id: Mapped[str] = mapped_column(String)
    operator_id: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer)


class CommitTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine, expire_on_commit=False)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.session.close)
        self.in_awaited_io = False
        self.commits = 0
        self.refreshed = []
        self.expired_after_commit = []
        self.owner = Obj(id="owner", role="admin", is_active=True, deleted_at=None, is_service=False)
        self.author = Obj(id="author")
        for name, value in [("Conversation", Conversation), ("AssistantDialog", Job)]:
            p = patch.object(service, name, value);p.start();self.addCleanup(p.stop)
        for target, name, value in [(service.inbox, "is_waiting", lambda conv: False),
                                   (service, "check_conversation", AsyncMock()),
                                   (service, "write_audit", AsyncMock())]:
            p = patch.object(target, name, value);p.start();self.addCleanup(p.stop)
        case = self
        class DB:
            async def get(self, model, key):
                with case.awaited_io():return case.session.get(model, key)
            def add(self, value):case.session.add(value)
            async def commit(self):
                with case.awaited_io():
                    case.session.commit();case.commits += 1
                    case.expired_after_commit.append(set(inspect(case.conv).expired_attributes))
            async def refresh(self, value):
                with case.awaited_io():case.session.refresh(value);case.refreshed.append(type(value).__name__)
        self.db = DB()
        async def locked(db, cid):return await db.get(Conversation, cid)
        p = patch.object(service.conversations, "get_conversation_for_update", locked)
        p.start();self.addCleanup(p.stop)
        @event.listens_for(self.engine, "before_cursor_execute")
        def reject_hidden_select(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT") and not case.in_awaited_io:
                raise AssertionError("Implicit SQL during snapshot after commit: equivalent async MissingGreenlet")

    @contextmanager
    def awaited_io(self):
        old = self.in_awaited_io;self.in_awaited_io = True
        try:yield
        finally:self.in_awaited_io = old

    def seed(self, job=False, state="waiting", assignee=None, crm=None):
        with self.awaited_io():
            self.conv = Conversation(id="chat", status="in_progress", assignee_id=assignee,
                                     claimed_by_id=assignee, crm_request_id=crm)
            self.session.add(self.conv)
            if job:self.session.add(Job(conversation_id="chat", principal_id="owner", operator_id="author", state=state, version=1))
            self.session.commit()

    async def test_new_claim_refreshes_database_generated_revision_after_commit(self):
        self.seed()
        result = await service.enroll(self.db,self.owner,self.author,"chat",expected_assignee_id=None,manual=False)
        self.assertIn("updated_at", self.expired_after_commit[0])
        self.assertEqual(self.commits, 1);self.assertEqual(result["state"], "waiting")
        self.assertEqual(result["assignee_id"], "author");self.assertIsNotNone(result["source_revision"])
        self.assertEqual(set(self.refreshed), {"Conversation", "Job"})

    async def test_manual_handoff_refreshes_existing_job_and_version(self):
        self.seed(job=True,state="paused",assignee="owner")
        result = await service.enroll(self.db,self.owner,self.author,"chat",expected_assignee_id="owner",manual=True)
        self.assertEqual(result["version"], 2);self.assertEqual(result["state"], "waiting")
        self.assertEqual(self.commits, 1);self.assertIsNotNone(result["source_revision"])

    async def test_expire_on_commit_for_job_and_conversation_is_also_supported(self):
        self.seed();self.session.expire_on_commit = True
        result = await service.enroll(self.db,self.owner,self.author,"chat",expected_assignee_id=None,manual=False)
        self.assertEqual(result["version"], 1);self.assertEqual(result["operator_id"], "author")
        self.assertIsNotNone(result["source_revision"])

    async def test_takeover_acknowledges_pause_after_return_to_its_principal(self):
        self.seed(job=True,assignee="author")
        result = await service.pause(self.db,self.owner,"chat","author",1)
        self.assertEqual(result["state"], "paused");self.assertEqual(result["assignee_id"], "owner")
        self.assertEqual(result["version"], 2);self.assertEqual(self.commits, 1)

    async def test_complete_reads_committed_card_without_an_implicit_select(self):
        self.seed(job=True,assignee="author")
        async def link(db, conv, principal, crm):conv.crm_request_id = crm
        async def close(db, conv, new_status, actor):conv.status = new_status
        with patch.object(service.conversations,"set_crm_request",link), \
             patch.object(service.conversations,"change_status",close), \
             patch.object(service.conversations,"crm_request_twins",AsyncMock(return_value=[])):
            result = await service.complete(self.db,self.owner,"chat","author",1,"9000001",telegram_confirmed=True)
        self.assertEqual(result["state"], "completed");self.assertEqual(result["conversation_status"], "closed")
        self.assertEqual(result["crm_request_id"], "9000001");self.assertEqual(self.commits, 1)

    async def test_no_telegram_confirmation_still_prevents_commit(self):
        self.seed(job=True,assignee="author")
        with self.assertRaises(ApiError):await service.complete(self.db,self.owner,"chat","author",1,"9000001")
        self.assertEqual(self.commits, 0);self.assertEqual(self.refreshed, [])

    async def test_wrong_author_version_still_prevents_takeover_commit(self):
        self.seed(job=True,assignee="author")
        with self.assertRaises(ApiError):await service.pause(self.db,self.owner,"chat","other",1)
        self.assertEqual(self.commits, 0)

    async def test_real_third_party_reassignment_still_has_released_state(self):
        self.seed(job=True,state="paused",assignee="other")
        with self.awaited_io():job = self.session.get(Job,"chat")
        result = service.snapshot(job,self.conv)
        self.assertEqual(result["state"], "released");self.assertEqual(self.commits, 0)
