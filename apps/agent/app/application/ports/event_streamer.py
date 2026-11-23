"""Event streamer port for real-time task telemetry."""

from typing import Protocol


class EventStreamer(Protocol):
    """Stream execution logs and events to pub/sub channels."""

    async def stream_event(self, channel: str, event_type: str, data: dict) -> None:
        """Publish a structured event payload to the given channel."""
        ...
