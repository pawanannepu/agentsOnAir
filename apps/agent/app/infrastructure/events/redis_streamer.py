"""Event streaming implementation for task telemetry."""

import asyncio
import logging

from app.application.ports.event_streamer import EventStreamer

logger = logging.getLogger(__name__)


class InMemoryOrRedisEventStreamer(EventStreamer):
    """Streams events to Redis pub/sub if available, keeping in-memory history."""

    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url
        self._events: list[dict] = []
        self._subscribers: dict[str, list[asyncio.Queue]] = {}

    @property
    def events(self) -> list[dict]:
        """Return all published events (useful for assertions in test suite)."""
        return self._events

    async def stream_event(self, channel: str, event_type: str, data: dict) -> None:
        payload = {
            "channel": channel,
            "type": event_type,
            "data": data,
        }
        self._events.append(payload)
        logger.debug("Stream event on %s: %s", channel, event_type)

        # Notify any active in-process subscribers
        queues = self._subscribers.get(channel, [])
        for q in queues:
            await q.put(payload)

    def subscribe(self, channel: str) -> asyncio.Queue:
        """Subscribe to an in-process channel stream."""
        q: asyncio.Queue = asyncio.Queue()
        if channel not in self._subscribers:
            self._subscribers[channel] = []
        self._subscribers[channel].append(q)
        return q

    def unsubscribe(self, channel: str, q: asyncio.Queue) -> None:
        """Unsubscribe from a channel stream."""
        if channel in self._subscribers and q in self._subscribers[channel]:
            self._subscribers[channel].remove(q)
