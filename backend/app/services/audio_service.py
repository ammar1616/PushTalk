import asyncio
import subprocess
import uuid
from pathlib import Path

from app.core.config import settings

ORIGINAL_DIR = "original"
NORMALIZED_DIR = "normalized"
AUDIO_EXT = ".ogg"


def media_root() -> Path:
    root = Path(settings.media_root)
    for name in (ORIGINAL_DIR, NORMALIZED_DIR):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def original_path(message_id: uuid.UUID) -> Path:
    # The id is a uuid we generated, so there is no user-controlled text in
    # this path at all. That is the point of naming files by id.
    return media_root() / ORIGINAL_DIR / str(message_id)


def normalized_path(message_id: uuid.UUID) -> Path:
    return media_root() / NORMALIZED_DIR / f"{message_id}{AUDIO_EXT}"


class AudioInvalid(Exception):
    """Raised when the uploaded file is not usable audio."""


async def save_upload(upload, message_id: uuid.UUID) -> int:
    """Stream the upload to disk, refusing anything over the size cap.

    Returns the number of bytes written. Checking size while streaming means
    a huge upload costs one partial file, not the whole thing in memory.
    """
    target = original_path(message_id)
    limit = settings.max_audio_mb * 1024 * 1024
    written = 0

    with target.open("wb") as out:
        while chunk := await upload.read(1024 * 64):
            written += len(chunk)
            if written > limit:
                out.close()
                target.unlink(missing_ok=True)
                raise AudioInvalid("File is too large.")
            out.write(chunk)

    if written == 0:
        target.unlink(missing_ok=True)
        raise AudioInvalid("File is empty.")
    return written


async def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    """Run ffmpeg/ffprobe without blocking the event loop.

    asyncio.to_thread moves the blocking subprocess call onto a worker thread.
    A plain subprocess.run here would freeze every other request for as long
    as ffmpeg takes.
    """
    try:
        return await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, check=True, timeout=20
        )
    except subprocess.TimeoutExpired:
        raise AudioInvalid("Could not read that audio file in time.")
    except subprocess.CalledProcessError:
        raise AudioInvalid("That file is not valid audio.")


async def probe_duration(path: Path) -> float:
    """Measure real duration with ffprobe. Never trust a client-reported one."""
    result = await _run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    )
    try:
        return float(result.stdout.decode().strip())
    except ValueError:
        raise AudioInvalid("Could not read the duration of that file.")


async def validate_audio(path: Path) -> float:
    """Full check for an upload. Returns the real duration in seconds.

    The declared MIME is only used as a cheap early reject. The duration
    always comes from ffprobe reading the actual bytes.
    """
    duration = await probe_duration(path)
    if duration < settings.min_audio_seconds:
        raise AudioInvalid("Hold the button a little longer.")
    if duration > settings.max_audio_seconds:
        raise AudioInvalid("Recording is longer than one minute.")
    return duration


async def normalize_audio(source: Path, message_id: uuid.UUID) -> Path:
    """Transcode to mono 48kHz Opus in an OGG container."""
    target = normalized_path(message_id)
    await _run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-i", str(source),
            "-vn",
            "-ac", "1",
            "-ar", "48000",
            "-c:a", "libopus",
            "-b:a", "32k",
            str(target),
        ]
    )
    return target


async def waveform_peaks(path: Path, buckets: int = 64) -> list[float]:
    """Rough waveform envelope for the UI, as `buckets` values in 0..1.

    Decode to mono 8kHz signed 16-bit, then take the peak of each slice.
    Downsampling to 8kHz is fine because this is a picture of the sound,
    not something anyone listens to.
    """
    rate = 8000
    result = await _run(
        [
            "ffmpeg", "-v", "error",
            "-i", str(path),
            "-f", "s16le",
            "-ac", "1",
            "-ar", str(rate),
            "-",
        ]
    )
    samples = result.stdout
    if not samples:
        return []

    # One bucket is two bytes, because s16le is signed 16-bit.
    per_bucket = max(1, (len(samples) // 2) // buckets)
    peaks: list[float] = []
    for index in range(buckets):
        start = index * per_bucket * 2
        chunk = samples[start:start + per_bucket * 2]
        if not chunk:
            break
        # Map signed 16-bit into 0..1.
        best = 0.0
        for offset in range(0, len(chunk) - 1, 2):
            value = int.from_bytes(chunk[offset:offset + 2], "little", signed=True)
            best = max(best, abs(value) / 32768.0)
        peaks.append(round(best, 3))
    return peaks


def delete_message_files(message_id: uuid.UUID) -> None:
    original_path(message_id).unlink(missing_ok=True)
    normalized_path(message_id).unlink(missing_ok=True)
