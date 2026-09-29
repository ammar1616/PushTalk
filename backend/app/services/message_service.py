import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Message


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