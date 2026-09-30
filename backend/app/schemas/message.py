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
    # Per-recipient progress. Aggregated for the sender: everyone else has
    # played -> "played", everyone else has at least heard it -> "delivered",
    # otherwise "sent".
    delivered_count: int = 0
    played_count: int = 0
    recipient_count: int = 0
    aggregated_status: str = "sent"


class StatusAck(BaseModel):
    """Reply to POST /messages/{id}/delivered and .../played."""

    message_id: uuid.UUID
    user_id: uuid.UUID
    state: str
    aggregated_status: str