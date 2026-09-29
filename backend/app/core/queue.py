from arq.connections import ArqRedis, RedisSettings
from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings

AUDIO_QUEUE = "audio"


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(settings.redis_url)


_pool: Redis | None = None


async def get_redis() -> Redis:
    """One shared Redis client for pub/sub and plain commands, per process."""
    global _pool
    if _pool is None:
        _pool = Redis.from_url(settings.redis_url, decode_responses=True)
    return _pool


async def enqueue_audio(message_id: str) -> None:
    """Hand a message id to the worker.

    arq keeps its pending jobs in a sorted set so it can order them by score
    and pull the most urgent first. Pushing with rpush would create a list
    under the same name and the worker dies with WRONGTYPE. Going through
    ArqRedis.enqueue_job keeps the API's data structure and the worker's in
    agreement, and the queue name has to match WorkerSettings.queue_name
    or the worker ends up polling a key nothing writes to.
    """
    pool = ConnectionPool.from_url(settings.redis_url)
    arq = ArqRedis(pool, default_queue_name=AUDIO_QUEUE)
    try:
        await arq.enqueue_job("process_audio", message_id)
    finally:
        await arq.aclose()