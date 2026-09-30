import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_allow_query_token
from app.api.messages import require_channel_member
from app.core.errors import AppError
from app.db.models import Message, User
from app.db.session import get_db
from app.services import audio_service

router = APIRouter(tags=["media"])

AUDIO_MIME = "audio/ogg"


@router.get("/media/{message_id}")
async def get_audio(
    message_id: uuid.UUID,
    user: User = Depends(get_current_user_allow_query_token),
    session: AsyncSession = Depends(get_db),
):
    """Serve the normalized clip, but only to somebody in the channel.

    Order matters here. Membership is checked before the file is touched, so
    a stranger cannot even learn whether a message id exists by comparing a
    403 against a 404, and cannot use the endpoint to probe which ids are
    real.
    """
    message = await session.get(Message, message_id)
    if message is None:
        raise AppError("MESSAGE_NOT_FOUND", "That message does not exist.", 404)

    await require_channel_member(session, message.channel_id, user.id)

    # A pending or failed message has no normalized file yet. Saying so
    # plainly beats a 404 that looks like the id was wrong.
    if message.status != "ready":
        raise AppError(
            "AUDIO_NOT_READY",
            "That recording is not ready yet.",
            409,
            {"status": message.status},
        )

    path = audio_service.normalized_path(message.id)
    if not path.is_file():
        # Row says ready but the file is gone. That is a server-side problem,
        # not a client mistake, so it gets a 5xx rather than a 404.
        raise AppError("AUDIO_UNAVAILABLE", "That recording is unavailable.", 503)

    # FileResponse streams from disk instead of loading the clip into memory,
    # and on this Starlette version it also answers Range requests with a 206
    # and Content-Range, which is what makes seeking work in the player.
    return FileResponse(path, media_type=AUDIO_MIME)