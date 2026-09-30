import json
import logging
from collections import defaultdict

from fastapi import WebSocket
from redis.asyncio import Redis
from sqlalchemy import select

from app.db.models import Membership, Message
from app.db.session import SessionLocal

log = logging.getLogger("realtime")

# Subscribe to every channel with one pattern instead of one topic per
# channel. A channel created after the API starts would otherwise never
# get its events.
CHANNEL_PATTERN = "pushtalk:channel:*"

# Never replay an unbounded backlog to a client that has been away for days.
REPLAY_LIMIT = 200


class ConnectionManager:
    """Tracks live sockets so a message reaches everyone in a channel.

    Two maps are kept. by_channel answers "who needs this event" and
    by_user answers "is this user online", which is what makes presence
    correct when someone has two tabs open.
    """

    def __init__(self) -> None:
        self.by_channel: dict[str, set[WebSocket]] = defaultdict(set)
        self.by_user: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, channel_id: str, user_id: str, websocket: WebSocket) -> None:
        self.by_channel[channel_id].add(websocket)
        self.by_user[user_id].add(websocket)

    def disconnect(self, channel_id: str, user_id: str, websocket: WebSocket) -> None:
        self.by_channel.get(channel_id, set()).discard(websocket)
        self.by_user.get(user_id, set()).discard(websocket)

    def is_online(self, user_id: str) -> bool:
        # A user with two tabs stays online until the last one closes.
        return bool(self.by_user.get(user_id))

    async def broadcast(self, channel_id: str, payload: dict) -> None:
        """Send one payload to every socket watching a channel.

        A dead socket is dropped instead of raising, otherwise one closed
        tab stops delivery for everyone else in the channel.
        """
        text = json.dumps(payload)
        for websocket in list(self.by_channel.get(channel_id, set())):
            try:
                await websocket.send_text(text)
            except Exception:
                self.by_channel[channel_id].discard(websocket)
                self.logout(websocket)


    def logout(self, websocket: WebSocket) -> None:
        for sockets in self.by_user.values():
            sockets.discard(websocket)


manager = ConnectionManager()


def message_payload(message: Message) -> dict:
    return {
        "id": str(message.id),
        "channel_id": str(message.channel_id),
        "sender_id": str(message.sender_id),
        "status": message.status,
        "duration_seconds": message.duration_seconds,
        "waveform_peaks": message.waveform_peaks,
        "failure_reason": message.failure_reason,
        "created_at": message.created_at.isoformat(),
        "sequence": message.sequence,
        # Replayed messages carry no per-recipient counts. The client refetches
        # history when it needs them, and guessing here would show a sender
        # "sent" for a message everyone has already played.
        "delivered_count": 0,
        "played_count": 0,
        "recipient_count": 0,
        "aggregated_status": "sent",
    }


async def replay(channel_id: str, since_sequence: int) -> list[Message]:
    """Load the messages a reconnecting client missed.

    Ordered by sequence, not timestamp. Two uploads in the same
    millisecond can share a created_at, which would replay out of order.
    """
    async with SessionLocal() as session:
        result = await session.execute(
            select(Message)
            .where(Message.channel_id == channel_id, Message.sequence > since_sequence)
            .order_by(Message.sequence)
            .limit(REPLAY_LIMIT)
        )
        return list(result.scalars().all())


async def is_member(channel_id: str, user_id: str) -> bool:
    async with SessionLocal() as session:
        result = await session.execute(
            select(Membership).where(
                Membership.channel_id == channel_id,
                Membership.user_id == user_id,
            )
        )
        return result.scalar_one_or_none() is not None


async def listen(redis: Redis) -> None:
    """Forward worker events to the local sockets, until cancelled."""
    pubsub = redis.pubsub()
    await pubsub.psubscribe(CHANNEL_PATTERN)

    async for raw in pubsub.listen():
        if raw.get("type") != "pmessage":
            continue
        channel_id = raw["channel"].rsplit(":", 1)[-1]
        try:
            payload = json.loads(raw["data"])
        except json.JSONDecodeError:
            continue
        await manager.broadcast(channel_id, payload)


async def serve(websocket: WebSocket, channel_id: str, user_id: str, since_sequence: int) -> None:
    """One client's connection: check access, catch up, then stay live."""
    # Accept before the membership check so a refusal can carry a close code
    # instead of being flattened into an HTTP 403 by the handshake.
    await websocket.accept()
    if not await is_member(channel_id, user_id):
        # 4403 is our own code, mirroring the HTTP 403.
        await websocket.close(code=4403)
        return

    await manager.connect(channel_id, user_id, websocket)
    try:
        # Replay before going live. Doing it the other way round lets a
        # message arrive live and then again from the replay, so the client
        # renders it twice.
        for message in await replay(channel_id, since_sequence):
            await websocket.send_text(
                json.dumps({"type": "message.replay", "data": message_payload(message)})
            )

        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            # Keeps proxies from closing an idle connection.
            if data.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except Exception:
        pass
    finally:
        manager.disconnect(channel_id, user_id, websocket)