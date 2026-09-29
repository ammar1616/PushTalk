from arq import cron

from app.core.logging import setup_logging
from app.core.queue import AUDIO_QUEUE, redis_settings
from app.worker.tasks import process_audio, reap_stale_processing

setup_logging()


class WorkerSettings:
    functions = [process_audio, reap_stale_processing]
    redis_settings = redis_settings()
    queue_name = AUDIO_QUEUE
    # Long enough for a 60s recording to transcode without arq killing it
    # mid-ffmpeg. The reaper resets anything stranded by a crash.
    job_timeout = 180
    max_jobs = 4
    keep_result = 0
    cron_jobs = [cron(reap_stale_processing, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55})]