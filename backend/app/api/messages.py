import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_membership
from app.core.errors import AppError
from app.core.queue import enqueue_audio, get_redis
from app.db.models import Membership, Message, User
from app.db.session import get_db
from app.realtime.pubsub import EVENT_MESSAGE_STATUS, channel_topic
from app.schemas.message import MessageOut, StatusAck
from app.services import audio_service, message_service

router = APIRouter(tags=["messages"])


def to_out(message: Message, username: str, stats: dict[str, int], recipients: int) -> MessageOut:
    delivered = stats.get("delivered", 0)
    played = stats.get("played", 0)
    return MessageOut(
        id=message.id,
        channel_id=message.channel_id,
        sender_id=message.sender_id,
        sender_username=username,
        status=message.status,
        duration_seconds=message.duration_seconds,
        waveform_peaks=message.waveform_peaks,
        failure_reason=message.failure_reason,
        created_at=message.created_at,
        sequence=message.sequence,
        delivered_count=delivered,
        played_count=played,
        recipient_count=recipients,
        aggregated_status=message_service.aggregate(delivered, played, recipients),
    )


async def load_message(session: AsyncSession, message_id: uuid.UUID) -> Message:
    message = await session.get(Message, message_id)
    if message is None:
        raise AppError("MESSAGE_NOT_FOUND", "That message does not exist.", 404)
    return message


async def require_channel_member(session: AsyncSession, channel_id, user_id) -> None:
    """Membership check for a route with no channel in the URL.

    The message endpoints learn the channel by loading the message first, so
    they cannot use the channel_id path parameter that require_membership
    reads.
    """
    result = await session.execute(
        select(Membership).where(
            Membership.channel_id == channel_id,
            Membership.user_id == user_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise AppError("NOT_A_MEMBER", "Join the channel first.", 403)


async def _usernames_for(
    session: AsyncSession, messages: list[Message]
) -> dict[uuid.UUID, str]:
    """id -> username for a page of messages, in one query.

    Touching message.sender for each row would be a lazy load, and lazy
    loads inside async SQLAlchemy have to be awaited explicitly - one lazy
    load per message is also one query per message.
    """
    ids = {message.sender_id for message in messages}
    if not ids:
        return {}
    result = await session.execute(select(User.id, User.username).where(User.id.in_(ids)))
    return {user_id: username for user_id, username in result.all()}


@router.post(
    "/channels/{channel_id}/messages",
    response_model=MessageOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_message(
    channel_id: uuid.UUID,
    audio: UploadFile = File(...),
    membership: Membership = Depends(require_membership),
    session: AsyncSession = Depends(get_db),
):
    # Cheap early reject on the declared type. Not trusted, just a fast way to
    # turn away an obvious mistake before writing anything to disk.
    if not audio.content_type or not audio.content_type.startswith("audio/"):
        raise AppError("UNSUPPORTED_MEDIA_TYPE", "Send an audio file.", 415)

    # Loading membership.user here would be a lazy load, and lazy loads raise
    # inside async SQLAlchemy unless awaited explicitly. One extra query now
    # is cheaper than debugging that.
    sender = await session.get(User, membership.user_id)

    message = await message_service.create_pending_message(
        session, channel_id, membership.user_id, audio.filename or "recording.webm"
    )
    message_id = message.id

    try:
        await audio_service.save_upload(audio, message_id)
        await audio_service.validate_audio(audio_service.original_path(message_id))
    except audio_service.AudioInvalid as exc:
        # Nothing usable was created, so do not leave a row or a file behind.
        audio_service.delete_message_files(message_id)
        raise AppError("AUDIO_REJECTED", str(exc), 400)

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        audio_service.delete_message_files(message_id)
        raise

    try:
        await enqueue_audio(str(message_id))
    except Exception as exc:
        # The row exists but nothing will ever process it. Mark it failed so it
        # does not sit in pending forever looking like it is about to arrive.
        message.status = "failed"
        message.failure_reason = "Could not queue for processing."
        await session.commit()
        raise AppError("QUEUE_UNAVAILABLE", "Recording could not be queued.", 503) from exc

    return MessageOut(
        id=message.id,
        channel_id=message.channel_id,
        sender_id=message.sender_id,
        sender_username=sender.username,
        status=message.status,
        duration_seconds=message.duration_seconds,
        waveform_peaks=message.waveform_peaks,
        failure_reason=message.failure_reason,
        created_at=message.created_at,
        sequence=message.sequence,
    )


@router.get("/channels/{channel_id}/messages", response_model=list[MessageOut])
async def list_messages(
    channel_id: uuid.UUID,
    before: datetime | None = Query(None),
    before_sequence: int | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    membership: Membership = Depends(require_membership),
    session: AsyncSession = Depends(get_db),
):
    rows = await message_service.list_history(
        session, channel_id, before, before_sequence, limit
    )
    # Two queries for the whole page: the usernames, and every status row for
    # these messages at once. Not one query per message.
    usernames = await _usernames_for(session, rows)
    counts = await message_service.status_counts(session, [row.id for row in rows])
    recipients = await message_service.recipient_count(session, channel_id) - 1
    return [
        to_out(row, usernames.get(row.sender_id, ""), counts.get(row.id, {}), recipients)
        for row in rows
    ]


@router.get("/messages/{message_id}", response_model=MessageOut)
async def get_message(
    message_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    message = await load_message(session, message_id)
    await require_channel_member(session, message.channel_id, user.id)
    usernames = await _usernames_for(session, [message])
    counts = await message_service.status_counts(session, [message.id])
    recipients = await message_service.recipient_count(session, message.channel_id) - 1
    return to_out(
        message, usernames.get(message.sender_id, ""), counts.get(message.id, {}), recipients
    )


async def _record_status(
    message_id: uuid.UUID,
    state: str,
    user: User,
    session: AsyncSession,
) -> StatusAck:
    message = await load_message(session, message_id)
    await require_channel_member(session, message.channel_id, user.id)

    recipients = await message_service.recipient_count(session, message.channel_id) - 1
    stored = await message_service.mark_status(session, message, user.id, state)
    await session.commit()

    counts = await message_service.status_counts(session, [message.id])
    aggregated = message_service.aggregate(
        counts.get(message.id, {}).get("delivered", 0),
        counts.get(message.id, {}).get("played", 0),
        recipients,
    )

    # Tell the channel so the sender's other devices update without polling.
    redis = await get_redis()
    await redis.publish(
        channel_topic(str(message.channel_id)),
        json.dumps(
            {
                "type": EVENT_MESSAGE_STATUS,
                "data": {
                    "message_id": str(message.id),
                    "aggregated": aggregated,
                },
            }
        ),
    )

    return StatusAck(
        message_id=message.id,
        user_id=user.id,
        state=stored,
        aggregated_status=aggregated,
    )


@router.post("/messages/{message_id}/delivered", response_model=StatusAck)
async def mark_delivered(
    message_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    return await _record_status(message_id, "delivered", user, session)


@router.post("/messages/{message_id}/played", response_model=StatusAck)
async def mark_played(
    message_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    return await _record_status(message_id, "played", user, session)