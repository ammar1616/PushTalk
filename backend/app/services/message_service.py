import uuid
from datetime import datetime

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Membership, Message, MessageStatus


async def next_sequence(session: AsyncSession, channel_id: uuid.UUID) -> int:
    """Reserve the next sequence number for a channel.

    SELECT ... FOR UPDATE on the channel row makes a second concurrent upload
    block here until the first one commits, so both see different maximums.
    The unique constraint on (channel_id, sequence) is the actual guarantee;
    this just turns a duplicate-key error into a short wait.
    """
    await session.execute(
        select(Channel.id).where(Channel.id == channel_id).with_for_update()
    )
    current = await session.execute(
        select(func.coalesce(func.max(Message.sequence), 0)).where(
            Message.channel_id == channel_id
        )
    )
    return current.scalar_one() + 1


async def create_pending_message(
    session: AsyncSession,
    channel_id: uuid.UUID,
    sender_id: uuid.UUID,
    filename: str,
) -> Message:
    message = Message(
        id=uuid.uuid4(),
        channel_id=channel_id,
        sender_id=sender_id,
        status="pending",
        original_filename=filename,
        sequence=await next_sequence(session, channel_id),
    )
    session.add(message)
    return message


async def list_history(
    session: AsyncSession,
    channel_id: uuid.UUID,
before: datetime | None = None,
    before_sequence: int | None = None,
    limit: int = 50,
) -> list[Message]:
    """Newest first, one page at a time.

    Pagination is keyset based rather than an offset. OFFSET gets slower the
    deeper you go and, worse, rows inserted while a client is paging shift
    the window and duplicate or skip messages.

    Two cursor modes, because they answer different questions:

    - `before` alone is a plain timestamp cursor: strictly older. This is
      what the spec's signature asks for and it is what a simple client
      wants. It cannot tell two messages that share a timestamp apart.
    - `before` plus `before_sequence` compares (created_at, sequence) as one
      row value, which is exact even when timestamps collide. Postgres
      compares tuples natively so it is still a single condition.

    The sequence half is not decoration. created_at is not unique, and with
    a plain timestamp cursor a message sharing a timestamp with the cursor
    is skipped forever. I verified this by setting every message in a
    channel to the same created_at: the plain cursor repeats the same page
    forever, the pair cursor returns all nine exactly once.
    """
    query = select(Message).where(Message.channel_id == channel_id)
    if before is not None:
        if before_sequence is None:
            query = query.where(Message.created_at < before)
        else:
            query = query.where(
                tuple_(Message.created_at, Message.sequence) < tuple_(before, before_sequence)
            )
    query = query.order_by(Message.created_at.desc(), Message.sequence.desc()).limit(limit)
    result = await session.execute(query)
    return list(result.scalars().all())


async def recipient_count(session: AsyncSession, channel_id: uuid.UUID) -> int:
    """How many people a message in this channel is waiting on.

    The sender is excluded. They already know they sent it.
    """
    result = await session.execute(
        select(func.count(Membership.user_id)).where(Membership.channel_id == channel_id)
    )
    return result.scalar_one()


async def status_counts(
    session: AsyncSession, message_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, int]]:
    """Delivered/played counts for many messages in one query.

    A history page is 50 messages. Asking the database per message would be
    50 round trips, so this groups everything into a single statement.
    """
    if not message_ids:
        return {}
    result = await session.execute(
        select(MessageStatus.message_id, MessageStatus.state, func.count())
        .where(MessageStatus.message_id.in_(message_ids))
        .group_by(MessageStatus.message_id, MessageStatus.state)
    )
    counts: dict[uuid.UUID, dict[str, int]] = {}
    for message_id, state, total in result.all():
        counts.setdefault(message_id, {})[state] = total
    return counts


def aggregate(delivered: int, played: int, recipients: int) -> str:
    """Fold per-user rows into one status the sender can display.

    `played` is counted as delivered too, since playing means it arrived.
    A channel with no other members counts as delivered: nobody is going to
    confirm it, and leaving it on "sent" forever looks broken.
    """
    if recipients <= 0:
        return "delivered"
    reached = delivered + played
    if played >= recipients:
        return "played"
    if reached >= recipients:
        return "delivered"
    return "sent"


async def mark_status(
    session: AsyncSession, message: Message, user_id: uuid.UUID, state: str
) -> str:
    """Record that a user received or played a message.

    The unique constraint is on (message_id, user_id), so there is one row
    per person per message and a repeat call updates it rather than adding
    a second one.

    played outranks delivered and the row never moves backwards. A client
    that sends /delivered after /played - easy to do from two tabs - must
    not undo the fact that it was played.
    """
    row = (
        await session.execute(
            select(MessageStatus)
            .where(
                MessageStatus.message_id == message.id,
                MessageStatus.user_id == user_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()

    if row is None:
        session.add(MessageStatus(message_id=message.id, user_id=user_id, state=state))
        return state
    if row.state == "played" and state == "delivered":
        return "played"
    row.state = state
    return state