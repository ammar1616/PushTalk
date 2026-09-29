from arq.connections import RedisSettings
from redis.asyncio import Redis

from app.core.config import settings

AUDIO_QUEUE = "audio"


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(settings.redis_url)


_pool: Redis | None = None


async def get_redis() -> Redis:
    """One shared Redis connection pool per process."""
    global _pool
    if _pool is None:
        _pool = Redis.from_url(settings.redis_url, decode_responses=True)
    return _pool


async def enqueue_audio(message_id: str) -> None:
    redis = await get_redis()
    await redis.rpush(AUDIO_QUEUE, message_id)