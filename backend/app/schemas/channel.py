import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ChannelCreate(BaseModel):
    name: str = Field(min_length=3, max_length=64)


class ChannelOut(BaseModel):
    id: uuid.UUID
    name: str
    created_by: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class MemberOut(BaseModel):
    id: uuid.UUID
    username: str
    joined_at: datetime
    # Always False until the realtime layer lands in commit 7.
    online: bool = False