"""Count stored LeadChat records without exporting histories or identities.

Run inside the authenticated LeadChat API environment with its existing DB
configuration. No account IDs, chat IDs, texts or attachment metadata leave
the database. Only a complete repeatable-read snapshot is printed.
"""
import asyncio
import json


SNAPSHOT = (
    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
    "SET LOCAL statement_timeout = '8s'",
    "SET LOCAL lock_timeout = '1s'",
    "SET LOCAL TIME ZONE 'UTC'",
)

CONVERSATIONS = """
WITH scoped AS (
    SELECT CASE WHEN channel IN ('avito', 'max_bot', 'max_user', 'jivo', 'telegram')
                THEN channel ELSE 'other' END AS channel_group,
           client_id, last_message_at, crm_request_id, outcome
    FROM public.conversations
)
SELECT channel_group, COUNT(*) AS conversations,
       COUNT(DISTINCT client_id) AS linked_client_cards,
       COUNT(*) FILTER (WHERE last_message_at IS NULL) AS no_last_message_timestamp,
       COUNT(*) FILTER (WHERE NULLIF(crm_request_id, '') IS NOT NULL) AS crm_id_present,
       COUNT(*) FILTER (WHERE outcome IS NOT NULL) AS stored_outcome_present
FROM scoped
GROUP BY channel_group
ORDER BY channel_group
"""

TOTALS = """
SELECT COUNT(*) AS conversations, COUNT(DISTINCT client_id) AS linked_client_cards
FROM public.conversations
"""

MESSAGES = """
WITH scoped AS (
    SELECT CASE
             WHEN direction = 'note' THEN 'note'
             WHEN direction = 'system' OR sender_type IN ('system', 'avito') THEN 'system'
             WHEN direction = 'in' AND sender_type = 'client' THEN 'client'
             WHEN direction = 'out' AND sender_type = 'operator' THEN 'operator'
             WHEN direction = 'out' AND sender_type = 'bot' THEN 'bot'
             ELSE 'other'
           END AS role_group,
           created_at,
           CASE WHEN jsonb_typeof(attachments) = 'array'
                THEN jsonb_array_length(attachments) > 0 ELSE false END AS has_attachment,
           voice_transcript_status
    FROM public.messages
)
SELECT role_group, COUNT(*) AS messages,
       DATE(MIN(created_at)) AS first_stored_date_utc,
       DATE(MAX(created_at)) AS last_stored_date_utc,
       COUNT(*) FILTER (WHERE has_attachment) AS with_attachments,
       COUNT(*) FILTER (WHERE voice_transcript_status = 'done') AS asr_done_status
FROM scoped
GROUP BY role_group
ORDER BY role_group
"""

CONVERSATION_LENGTHS = """
WITH message_presence AS (
    SELECT conversation_id, COUNT(*) AS message_rows,
           MAX(CASE WHEN direction = 'in' AND sender_type = 'client'
                    THEN 1 ELSE 0 END) AS has_client,
           MAX(CASE WHEN direction = 'out' AND sender_type = 'operator'
                         AND delivery_status = 'delivered' THEN 1 ELSE 0 END) AS has_operator,
           MAX(CASE WHEN direction = 'out' AND sender_type = 'bot'
                         AND delivery_status = 'delivered' THEN 1 ELSE 0 END) AS has_bot
    FROM public.messages
    GROUP BY conversation_id
), scoped AS (
    SELECT CASE WHEN m.message_rows IS NULL THEN 0
                WHEN m.message_rows <= 5 THEN 1
                WHEN m.message_rows <= 20 THEN 6
                WHEN m.message_rows <= 100 THEN 21
                ELSE 101 END AS minimum_messages,
           COALESCE(m.message_rows, 0) AS message_rows, m.has_client, m.has_operator, m.has_bot
    FROM public.conversations c
    LEFT JOIN message_presence m ON m.conversation_id = c.id
)
SELECT minimum_messages, COUNT(*) AS conversations, SUM(message_rows) AS messages,
       COUNT(*) FILTER (WHERE has_client = 1 AND has_operator = 1) AS client_and_delivered_operator,
       COUNT(*) FILTER (WHERE has_client = 1 AND has_bot = 1) AS client_and_delivered_bot,
       COUNT(*) FILTER (WHERE has_client = 1 AND has_operator = 1 AND has_bot = 1) AS client_and_both
FROM scoped
GROUP BY minimum_messages
ORDER BY minimum_messages
"""


async def census(session, statement):
    """The caller must supply a new transaction-capable LeadChat session."""
    async with session.begin():
        for query in SNAPSHOT:
            await session.execute(statement(query))
        totals = dict((await session.execute(statement(TOTALS))).mappings().one())
        channels = [dict(row) for row in
                    (await session.execute(statement(CONVERSATIONS))).mappings()]
        roles = [dict(row) for row in (await session.execute(statement(MESSAGES))).mappings()]
        lengths = [dict(row) for row in (await session.execute(statement(CONVERSATION_LENGTHS))).mappings()]
        for band in lengths:
            # PostgreSQL SUM(bigint) returns numeric. Keep exact integer counts in JSON.
            band["messages"] = int(band["messages"])
        if sum(row["conversations"] for row in channels) != totals["conversations"]:
            raise RuntimeError("Inconsistent conversation aggregates")
        if sum(row["conversations"] for row in lengths) != totals["conversations"]:
            raise RuntimeError("Inconsistent conversation length aggregates")
        totals["messages"] = sum(row["messages"] for row in roles)
        unlinked_messages = totals["messages"] - sum(row["messages"] for row in lengths)
        if unlinked_messages < 0:
            raise RuntimeError("Inconsistent message aggregates")
    return {
        "schema": 2,
        "scope": "stored_leadchat_records_not_training_corpus",
        "totals": totals,
        "conversation_channels": channels,
        "message_roles": roles,
        "conversation_lengths": lengths,
        "unlinked_messages": unlinked_messages,
    }


async def _main():
    from sqlalchemy import text

    from app.db.session import dispose_engine, get_session_factory, init_engine

    engine = init_engine(component="leadbot-archive-census")
    try:
        if engine.dialect.name != "postgresql":
            raise RuntimeError("PostgreSQL snapshot required")
        async with get_session_factory()() as session:
            return await census(session, text)
    finally:
        await dispose_engine()


if __name__ == "__main__":
    try:
        result = asyncio.run(_main())
    except Exception as exc:
        raise SystemExit(f"Archive census unavailable ({type(exc).__name__})") from None
    print(json.dumps(result, default=str, ensure_ascii=False))
