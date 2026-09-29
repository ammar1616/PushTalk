import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Membership, User


async def create_channel(session: AsyncSession, name: str, creator_id) -> Channel | None:
    """Create a channel and join the creator to it. None if the name is taken."""
    channel = Channel(name=name, created_by=creator_id)
    session.add(channel)
    try:
        # The INSERT happens here, so this is where a duplicate name blows up.
        # flush() sends the SQL but leaves the transaction open.
        await session.flush()
        session.add(Membership(user_id=creator_id, channel_id=channel.id))
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return None
    return channel


async def list_channels_for_user(session: AsyncSession, user_id) -> list[Channel]:
    result = await session.execute(
        select(Channel)
        .join(Membership, Membership.channel_id == Channel.id)
        .where(Membership.user_id == user_id)
        .order_by(Channel.name)
    )
    return list(result.scalars().all())


async def get_channel(session: AsyncSession, channel_id: uuid.UUID) -> Channel | None:
    return await session.get(Channel, channel_id)


async def join_channel(session: AsyncSession, user_id, channel_id) -> Membership:
    """Idempotent: joining twice returns the existing membership."""
    existing = await get_membership(session, user_id, channel_id)
    if existing is not None:
        return existing

    membership = Membership(user_id=user_id, channel_id=channel_id)
    session.add(membership)
    try:
        await session.commit()
    except IntegrityError:
        # Lost a race with another join from the same user. Not a problem.
        await session.rollback()
    return await get_membership(session, user_id, channel_id)


async def get_membership(
    session: AsyncSession, user_id, channel_id
) -> Membership | None:
    result = await session.execute(
        select(Membership).where(
            Membership.user_id == user_id,
            Membership.channel_id == channel_id,
        )
    )
    return result.scalar_one_or_none()


async def list_members(session: AsyncSession, channel_id) -> list[tuple]:
    """Return (user_id, username, joined_at) for a channel, oldest join first."""
    result = await session.execute(
        select(User.id, User.username, Membership.joined_at)
        .join(User, User.id == Membership.user_id)
        .where(Membership.channel_id == channel_id)
        .order_by(Membership.joined_at)
    )
    return list(result.all())