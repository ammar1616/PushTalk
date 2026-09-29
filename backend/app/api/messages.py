import uuid

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_membership
from app.core.errors import AppError
from app.core.queue import enqueue_audio
from app.db.models import Membership, User
from app.db.session import get_db
from app.schemas.message import MessageOut
from app.services import audio_service, message_service

router = APIRouter(tags=["messages"])


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