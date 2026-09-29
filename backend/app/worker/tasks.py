import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from arq.connections import ArqRedis
from redis.asyncio import Redis
from sqlalchemy import select

from app.db.models import Message, User
from app.db.session import SessionLocal
from app.realtime.pubsub import EVENT_MESSAGE_FAILED, EVENT_MESSAGE_NEW, channel_topic
from app.services import audio_service

log = logging.getLogger("worker")

# A job killed mid-transcode must not strand the row in processing, so
# anything older than this is treated as abandoned and put back to pending.
STALE_AFTER = timedelta(minutes=10)


async def _publish(redis: Redis, channel_id, kind: str, data: dict) -> None:
    await redis.publish(
        channel_topic(str(channel_id)),
        json.dumps({"type": kind, "data": data}),
    )


async def process_audio(ctx: dict, message_id: str) -> None:
    """Normalize one uploaded recording, then publish it.

    arq passes the worker context as the first argument. The message_id is
    the second, because the API pushes it onto the queue as a plain string.
    """
    redis: Redis = ctx["redis"]
    log.info("job.start", extra={"job": "process_audio", "message_id": message_id})
    channel_id = None

    async with SessionLocal() as session:
        message = await session.get(Message, uuid.UUID(message_id))
        if message is None:
            log.warning("job.missing", extra={"job": "process_audio", "message_id": message_id})
            return
        if message.status == "ready":
            # arq retries on failure, so a job can arrive twice. Re-processing
            # a finished message would publish it a second time.
            log.info("job.already_ready", extra={"job": "process_audio", "message_id": message_id})
            return

        channel_id = message.channel_id
        message.status = "processing"
        await session.commit()

        try:
            source = audio_service.original_path(message.id)
            if not source.exists():
                raise audio_service.AudioInvalid("Uploaded file is missing.")

            target = await audio_service.normalize_audio(source, message.id)
            duration = await audio_service.probe_duration(target)
            peaks = await audio_service.waveform_peaks(target)

            message.audio_path = str(target)
            message.duration_seconds = duration
            message.waveform_peaks = peaks
            message.status = "ready"
            await session.commit()

            sender = await session.get(User, message.sender_id)
            await _publish(
                redis,
                channel_id,
                EVENT_MESSAGE_NEW,
                {
                    "id": str(message.id),
                    "channel_id": str(channel_id),
                    "sender_id": str(message.sender_id),
                    "sender_username": sender.username if sender else "",
                    "status": "ready",
                    "duration_seconds": duration,
                    "waveform_peaks": peaks,
                    "failure_reason": None,
                    "created_at": message.created_at.isoformat(),
                    "sequence": message.sequence,
                },
            )
            log.info("job.done", extra={"job": "process_audio", "message_id": message_id})

        except Exception as exc:
            reason = str(exc)[:250]
            await session.rollback()
            failed = await session.get(Message, message.id)
            if failed is not None:
                failed.status = "failed"
                failed.failure_reason = reason
                await session.commit()
            log.exception("job.failed", extra={"job": "process_audio", "message_id": message_id})
            await _publish(
                redis,
                channel_id,
                EVENT_MESSAGE_FAILED,
                {"message_id": message_id, "reason": reason},
            )


async def reap_stale_processing(ctx: dict) -> None:
    """Return messages abandoned mid-transcode back to pending.

    Only rows older than STALE_AFTER are touched, otherwise this would fight
    the worker on every message currently being processed.
    """
    redis: ArqRedis = ctx["redis"]
    cutoff = datetime.now(timezone.utc) - STALE_AFTER
    async with SessionLocal() as session:
        result = await session.execute(
            select(Message).where(
                Message.status == "processing",
                Message.created_at < cutoff,
            )
        )
        stale = list(result.scalars().all())
        for message in stale:
            message.status = "pending"
        if stale:
            await session.commit()
            for message in stale:
                await redis.enqueue_job("process_audio", str(message.id))
            log.warning("reaper.reset", extra={"count": len(stale)})