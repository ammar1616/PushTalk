"""The arq job that turns an upload into a playable clip.

ffmpeg and ffprobe run for real here rather than being mocked. The things this
test cares about - that duration is measured from the bytes, that the output is
genuinely Opus, that peaks come back as 64 buckets - only have meaning if the
real tools produced them. A mock would only prove the mock works.

The pub/sub assertion subscribes for real on the compose Redis, so a passing
test means the event a connected client would receive actually went out.
"""

import json
import uuid

import pytest
from redis.asyncio import Redis
from sqlalchemy import text

from app.realtime.pubsub import EVENT_MESSAGE_FAILED, EVENT_MESSAGE_NEW, channel_topic
from app.services import audio_service, message_service
from app.worker.tasks import process_audio

pytestmark = pytest.mark.asyncio


@pytest.fixture
def worker_ctx():
    """The shape arq hands a job: a context dict with a redis client."""

    async def make():
        redis = Redis.from_url(
            __import__("app.core.config", fromlist=["settings"]).settings.redis_url,
            decode_responses=True,
        )
        return {"redis": redis}

    return make


async def _make_pending(db_session, user, channel, source: bytes):
    """Create the row and write the original blob, the way the upload route does."""
    message = await message_service.create_pending_message(
        db_session, channel.id, user.id, "recording.ogg"
    )
    await db_session.commit()
    audio_service.original_path(message.id).write_bytes(source)
    return message


async def _await_event(redis: Redis, topic: str, timeout: float = 5.0):
    """Wait for one message on a topic.

    A pub/sub read has to be set up before the publish, so this subscribes and
    then hands the subscription back; the caller triggers the job and awaits
    the read. Doing it the other way round would race and flake.
    """
    pubsub = redis.pubsub()
    await pubsub.subscribe(topic)
    # Drain the subscribe confirmation so the next read is the real event.
    async for _ in pubsub.listen():
        break
    return pubsub


async def test_process_audio_marks_ready_and_publishes(
    db_session, owner_setup, valid_audio, worker_ctx
):
    user, channel = await owner_setup()
    message = await _make_pending(db_session, user, channel, valid_audio.read_bytes())
    ctx = await worker_ctx()

    pubsub = await _await_event(ctx["redis"], channel_topic(str(channel.id)))
    try:
        await process_audio(ctx, str(message.id))
        raw = await pubsub.get_message(timeout=5.0)
    finally:
        await pubsub.unsubscribe()
        await ctx["redis"].aclose()

    await db_session.refresh(message)
    assert message.status == "ready"
    assert message.failure_reason is None
    assert message.duration_seconds is not None
    assert 0.8 < message.duration_seconds < 1.2

    # 64 peaks, each normalized to 0..1.
    assert len(message.waveform_peaks) == 64
    assert all(0.0 <= p <= 1.0 for p in message.waveform_peaks)

    assert raw is not None, "no event arrived on the channel topic"
    event = json.loads(raw["data"])
    assert event["type"] == EVENT_MESSAGE_NEW
    assert event["data"]["id"] == str(message.id)
    assert event["data"]["sequence"] == message.sequence
    assert event["data"]["sender_username"] == user.username
    assert event["data"]["duration_seconds"] == message.duration_seconds


async def test_normalized_file_is_real_opus(db_session, owner_setup, valid_audio, worker_ctx):
    """Check the produced file, not just the row that points at it."""
    user, channel = await owner_setup()
    message = await _make_pending(db_session, user, channel, valid_audio.read_bytes())
    ctx = await worker_ctx()
    try:
        await process_audio(ctx, str(message.id))
    finally:
        await ctx["redis"].aclose()

    target = audio_service.normalized_path(message.id)
    assert target.is_file()

    import subprocess

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_name,channels,sample_rate", "-of", "default=noprint_wrappers=1:nokey=1",
         str(target)],
        capture_output=True, check=True, text=True, timeout=30,
    )
    lines = [line.strip() for line in probe.stdout.splitlines() if line.strip()]
    assert "opus" in lines
    assert "1" in lines, f"expected mono, got {lines}"
    assert "48000" in lines


async def test_missing_source_file_fails_the_message(
    db_session, owner_setup, worker_ctx
):
    """No uploaded bytes must not look like success."""
    user, channel = await owner_setup()
    message = await message_service.create_pending_message(
        db_session, channel.id, user.id, "gone.ogg"
    )
    await db_session.commit()
    ctx = await worker_ctx()

    pubsub = await _await_event(ctx["redis"], channel_topic(str(channel.id)))
    try:
        await process_audio(ctx, str(message.id))
        raw = await pubsub.get_message(timeout=5.0)
    finally:
        await pubsub.unsubscribe()
        await ctx["redis"].aclose()

    await db_session.refresh(message)
    assert message.status == "failed"
    assert message.failure_reason

    event = json.loads(raw["data"])
    assert event["type"] == EVENT_MESSAGE_FAILED
    assert event["data"]["message_id"] == str(message.id)
    assert event["data"]["reason"]


async def test_undecodable_source_fails_the_message(
    db_session, owner_setup, text_file, worker_ctx
):
    """Bytes that exist but are not audio must end up failed, not stuck."""
    user, channel = await owner_setup()
    message = await _make_pending(db_session, user, channel, text_file.read_bytes())
    ctx = await worker_ctx()

    pubsub = await _await_event(ctx["redis"], channel_topic(str(channel.id)))
    try:
        await process_audio(ctx, str(message.id))
        raw = await pubsub.get_message(timeout=5.0)
    finally:
        await pubsub.unsubscribe()
        await ctx["redis"].aclose()

    await db_session.refresh(message)
    assert message.status == "failed"
    assert json.loads(raw["data"])["type"] == EVENT_MESSAGE_FAILED


async def test_rerunning_a_ready_message_publishes_nothing(
    db_session, owner_setup, valid_audio, worker_ctx
):
    """arq retries failed jobs, so the same id can arrive twice.

    Reprocessing a finished message would broadcast it again and every client
    would show a duplicate.
    """
    user, channel = await owner_setup()
    message = await _make_pending(db_session, user, channel, valid_audio.read_bytes())
    ctx = await worker_ctx()

    first = await _await_event(ctx["redis"], channel_topic(str(channel.id)))
    try:
        await process_audio(ctx, str(message.id))
        assert await first.get_message(timeout=5.0) is not None
    finally:
        await first.unsubscribe()

    second = await _await_event(ctx["redis"], channel_topic(str(channel.id)))
    try:
        await process_audio(ctx, str(message.id))
        assert await second.get_message(timeout=1.0) is None, "published a second time"
    finally:
        await second.unsubscribe()
        await ctx["redis"].aclose()

    await db_session.refresh(message)
    assert message.status == "ready"


async def test_unknown_message_id_is_ignored(db_session, owner_setup, worker_ctx):
    """A job for a row that no longer exists must not raise.

    This happens in practice: a message can be deleted while its job is still
    queued, and a worker that crashed on it would retry forever.
    """
    ctx = await worker_ctx()
    try:
        await process_audio(ctx, str(uuid.uuid4()))
    finally:
        await ctx["redis"].aclose()


class _FakeQueue:
    """Stands in for arq's Redis so the reaper's re-enqueue can be asserted.

    Using the real queue would push jobs that the dev worker would pick up
    mid-test, which makes the suite depend on what else is running.
    """

    def __init__(self):
        self.enqueued: list[tuple[str, str]] = []

    async def enqueue_job(self, name: str, message_id: str, *args, **kwargs):
        self.enqueued.append((name, message_id))


async def _age_row(db_session, message_id, *, hours: int):
    """Push created_at into the past with raw SQL.

    The reaper decides staleness from created_at, and the column is a server
    default, so it has to be written directly. Assigning it on the ORM object
    and committing would not survive the flush.
    """
    await db_session.execute(
        text(
            "UPDATE messages SET created_at = now() - make_interval(hours => :h) "
            "WHERE id = :id"
        ),
        {"h": hours, "id": message_id},
    )
    await db_session.commit()


async def test_reaper_returns_stale_processing_rows_to_pending(
    db_session, owner_setup
):
    """A job killed mid-transcode must not strand the row in processing."""
    from app.worker.tasks import reap_stale_processing

    user, channel = await owner_setup()
    message = await _make_pending(db_session, user, channel, b"x")
    message.status = "processing"
    await db_session.commit()
    await _age_row(db_session, message.id, hours=1)

    queue = _FakeQueue()
    await reap_stale_processing({"redis": queue})

    await db_session.refresh(message)
    assert message.status == "pending"
    # Resetting the row without re-queueing it would leave it pending forever.
    assert queue.enqueued == [("process_audio", str(message.id))]


async def test_reaper_leaves_recent_rows_alone(db_session, owner_setup):
    """A job that is genuinely still running must not be reset."""
    from app.worker.tasks import reap_stale_processing

    user, channel = await owner_setup()
    message = await _make_pending(db_session, user, channel, b"x")
    message.status = "processing"
    await db_session.commit()

    queue = _FakeQueue()
    await reap_stale_processing({"redis": queue})

    await db_session.refresh(message)
    assert message.status == "processing"
    assert queue.enqueued == []


async def test_reaper_does_not_touch_failed_or_ready_rows(db_session, owner_setup):
    """Only abandoned `processing` rows are candidates for retry."""
    from app.worker.tasks import reap_stale_processing

    user, channel = await owner_setup()
    rows = {}
    for status in ("ready", "failed", "pending"):
        msg = await _make_pending(db_session, user, channel, b"x")
        msg.status = status
        await db_session.commit()
        await _age_row(db_session, msg.id, hours=1)
        rows[status] = msg

    queue = _FakeQueue()
    await reap_stale_processing({"redis": queue})

    for status, msg in rows.items():
        await db_session.refresh(msg)
        assert msg.status == status
    assert queue.enqueued == []