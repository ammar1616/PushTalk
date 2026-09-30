import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_membership
from app.core.errors import AppError
from app.db.models import User
from app.db.session import get_db
from app.realtime.manager import manager
from app.schemas.channel import ChannelCreate, ChannelOut, MemberOut
from app.services import channel_service

router = APIRouter(prefix="/channels", tags=["channels"])


@router.post("", response_model=ChannelOut, status_code=201)
async def create_channel(
    body: ChannelCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    channel = await channel_service.create_channel(
        session, body.name, current_user.id
    )
    if channel is None:
        raise AppError("CHANNEL_NAME_TAKEN", "That channel name is already taken.", 409)
    return channel


@router.get("", response_model=list[ChannelOut])
async def list_channels(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    return await channel_service.list_channels_for_user(session, current_user.id)


@router.post("/{channel_id}/join", status_code=204)
async def join_channel(
    channel_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    channel = await channel_service.get_channel(session, channel_id)
    if channel is None:
        raise AppError("CHANNEL_NOT_FOUND", "No such channel.", 404)
    await channel_service.join_channel(session, current_user.id, channel_id)
    return None


@router.get("/{channel_id}/members", response_model=list[MemberOut])
async def list_members(
    channel_id: uuid.UUID,
    _membership=Depends(require_membership),
    session: AsyncSession = Depends(get_db),
):
    rows = await channel_service.list_members(session, channel_id)
    # Presence lives in memory, not in the database. It is answered by this
    # process only, so with more than one API instance a member can be online
    # on another instance and still read as offline here. Redis presence would
    # fix that and is out of scope for this commit.
    return [
        MemberOut(
            id=user_id,
            username=username,
            joined_at=joined_at,
            online=manager.is_online(str(user_id)),
        )
        for user_id, username, joined_at in rows
    ]