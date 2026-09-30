"""Redis pub/sub event names, shared by the worker and the API.

A message is only broadcast once processing has finished, so the worker
publishes to the channel's topic and the WebSocket manager fans it out.
"""

EVENT_MESSAGE_NEW = "message.new"
EVENT_MESSAGE_FAILED = "message.failed"
EVENT_MESSAGE_STATUS = "message.status"


def channel_topic(channel_id: str) -> str:
    return f"pushtalk:channel:{channel_id}"