import uuid

from fastapi import APIRouter, Query, WebSocket

from app.core.security import decode_access_token
from app.realtime.manager import serve

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
    channel_id: str = Query(...),
    since_sequence: int = Query(0),
) -> None:
    """Authenticated realtime feed for one channel.

    The token is a query parameter because a browser WebSocket API cannot
    send an Authorization header. That is why the handshake closes with
    4401 when it is missing or invalid instead of returning 401 - there is
    no HTTP response at that point.

    4403 means the token was fine but the user never joined the channel.
    """
    try:
        user_id = decode_access_token(token)
        channel = uuid.UUID(channel_id)
        if not user_id:
            raise ValueError("bad token")
    except Exception:
        # Accept, then close. Closing before accepting makes Starlette reject
        # the handshake with a plain HTTP 403 and the close code never reaches
        # the client, which defeats the point of having 4401.
        await websocket.accept()
        await websocket.close(code=4401)
        return

    await serve(websocket, str(channel), user_id, since_sequence)