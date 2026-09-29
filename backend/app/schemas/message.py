import uuid
from datetime import datetime

from pydantic import BaseModel


class MessageOut(BaseModel):
    id: uuid.UUID
    channel_id: uuid.UUID
    sender_id: uuid.UUID
    sender_username: str
    status: str
    duration_seconds: float | None
    waveform_peaks: list[float] | None
    failure_reason: str | None
    created_at: datetime
    sequence: int