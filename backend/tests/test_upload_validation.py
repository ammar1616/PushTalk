"""Upload validation.

The route is the only place that decides whether a blob becomes a message, so
these tests are about the rejects as much as the accept.

Two things get checked on every path: the HTTP status, and that a rejected
upload leaves nothing behind. A 400 that still leaves a row and a file on disk
is a slow disk leak, and the message would sit in `pending` forever looking
like it was about to arrive.
"""

import pytest

from app.db.models import Message
from app.services import audio_service

pytestmark = pytest.mark.asyncio


async def _upload(client, channel, user, path, content_type="audio/ogg"):
    return await client.post(
        f"/channels/{channel.id}/messages",
        files={"audio": (path.name, path.read_bytes(), content_type)},
        headers={"Authorization": f"Bearer {_token(user)}"},
    )


def _token(user):
    from app.core.security import create_access_token

    return create_access_token(str(user.id))


async def _no_rows():
    """True when nothing was committed.

    Read on a separate connection on purpose. The route runs inside the same
    session the test holds, so a rejected upload's row is still sitting in
    that session's uncommitted transaction. Production gives each request its
    own session and rolls it back, which is exactly what "separate connection"
    reproduces here - asking the shared session would report a row that no
    other process can see.
    """
    from sqlalchemy import func, select

    from app.db.session import engine

    async with engine.connect() as conn:
        count = (
            await conn.execute(select(func.count()).select_from(Message))
        ).scalar_one()
    return count == 0


async def test_accepts_valid_audio(client, db_session, owner_setup, valid_audio):
    user, channel = await owner_setup()

    resp = await _upload(client, channel, user, valid_audio)

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "pending"
    assert body["sequence"] == 1
    assert body["sender_username"] == "owner"
    # Nothing is known about duration or waveform until the worker runs.
    assert body["duration_seconds"] is None
    assert body["waveform_peaks"] is None


async def test_rejects_non_audio_mime(client, db_session, owner_setup, valid_audio):
    user, channel = await owner_setup()

    resp = await _upload(client, channel, user, valid_audio, content_type="text/plain")

    assert resp.status_code == 415
    assert resp.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"
    assert await _no_rows()


async def test_rejects_a_file_that_is_not_audio(client, db_session, owner_setup, text_file):
    """A .txt sent with an audio MIME type still has to be refused.

    The declared type is attacker-controlled. The duration check reads the real
    bytes with ffprobe, which is the only reason this is caught.
    """
    user, channel = await owner_setup()

    resp = await _upload(client, channel, user, text_file, content_type="audio/ogg")

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "AUDIO_REJECTED"
    assert await _no_rows()


async def test_rejects_oversize_upload(
    client, db_session, owner_setup, valid_audio, monkeypatch
):
    """The cap is enforced while streaming, so the bytes are written and then
    deleted rather than read into memory and checked.

    The limit is lowered instead of shipping an 11 MB fixture: the cap is a
    running byte total, so a tiny cap over a small real file exercises exactly
    the same code path and finishes in milliseconds. Encoding a genuine 11 MB
    clip would take far longer and assert nothing extra.
    """
    from app.core.config import settings

    user, channel = await owner_setup()
    monkeypatch.setattr(settings, "max_audio_mb", 0)

    resp = await _upload(client, channel, user, valid_audio)

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "AUDIO_REJECTED"
    assert "too large" in resp.json()["error"]["message"]
    assert await _no_rows()


async def test_oversize_cap_still_allows_a_small_file(
    client, db_session, owner_setup, valid_audio
):
    """Guard against the cap being wired up to always reject."""
    user, channel = await owner_setup()
    resp = await _upload(client, channel, user, valid_audio)
    assert resp.status_code == 202


async def test_rejects_too_short(client, db_session, owner_setup, short_audio):
    user, channel = await owner_setup()

    resp = await _upload(client, channel, user, short_audio)

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "AUDIO_REJECTED"
    assert "little longer" in resp.json()["error"]["message"]
    assert await _no_rows()


async def test_rejects_too_long(client, db_session, owner_setup, long_audio):
    user, channel = await owner_setup()

    resp = await _upload(client, channel, user, long_audio)

    assert resp.status_code == 400
    assert "longer than" in resp.json()["error"]["message"]
    assert await _no_rows()


async def test_rejected_upload_leaves_no_file_on_disk(
    client, db_session, owner_setup, short_audio
):
    """The bytes must be cleaned up, not just the row."""
    user, channel = await owner_setup()

    resp = await _upload(client, channel, user, short_audio)
    assert resp.status_code == 400

    originals = list((audio_service.media_root() / audio_service.ORIGINAL_DIR).iterdir())
    assert originals == [], f"left behind: {originals}"


async def test_upload_requires_membership(client, db_session, user_factory, valid_audio):
    """A stranger cannot post into a channel they never joined."""
    owner = await user_factory(username="channelowner")
    from app.services import channel_service

    channel = await channel_service.create_channel(db_session, "general", owner.id)
    await db_session.commit()

    stranger = await user_factory(username="stranger")
    resp = await _upload(client, channel, stranger, valid_audio)

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "NOT_A_MEMBER"
    assert await _no_rows()


async def test_upload_requires_auth(client, owner_setup, valid_audio):
    _, channel = await owner_setup()

    resp = await client.post(
        f"/channels/{channel.id}/messages",
        files={"audio": (valid_audio.name, valid_audio.read_bytes(), "audio/ogg")},
    )

    assert resp.status_code == 401


async def test_sequences_increment_per_channel(
    client, db_session, owner_setup, valid_audio
):
    """Sequence numbers order the channel, so they must not collide."""
    user, channel = await owner_setup()

    first = await _upload(client, channel, user, valid_audio)
    second = await _upload(client, channel, user, valid_audio)

    assert first.json()["sequence"] == 1
    assert second.json()["sequence"] == 2


async def test_missing_file_field_is_a_validation_error(client, owner_setup):
    user, channel = await owner_setup()

    resp = await client.post(
        f"/channels/{channel.id}/messages",
        headers={"Authorization": f"Bearer {_token(user)}"},
    )

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"