"""Redis Streams and in memory event streaming implementation."""

import asyncio
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from app.application.ports.event_streamer import EventStreamer

logger = logging.getLogger(__name__)


class InMemoryOrRedisEventStreamer(EventStreamer):
    """Streams events to Redis Streams or in memory buffer."""

    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url
        self._redis_client = None
        self._redis_disabled = False
        self._events: list[dict] = []
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        # In memory stream storage: task_id -> list of
        # (event_id, event_type, data, timestamp)
        self._streams: dict[str, list[tuple[str, str, dict, str]]] = {}
        self._stream_notifiers: dict[str, list[asyncio.Event]] = {}
        self._seq_counter = 0

    async def _get_client(self):
        if not self._redis_url or self._redis_disabled:
            return None
        if self._redis_client is not None:
            return self._redis_client
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=0.2,
                # Must exceed SSE XREAD BLOCK (1000ms) to avoid idle read timeouts.
                socket_timeout=5.0,
            )
            await client.ping()
            self._redis_client = client
        except Exception as exc:
            logger.info(
                "Redis unavailable at %s (%s), using in memory streamer",
                self._redis_url,
                exc,
            )
            self._redis_disabled = True
            self._redis_client = None
        return self._redis_client

    @property
    def events(self) -> list[dict]:
        """Return all published events."""
        return self._events

    async def stream_event(self, channel: str, event_type: str, data: dict) -> None:
        """Publish event to channel and append to stream if task channel."""
        payload = {
            "channel": channel,
            "type": event_type,
            "data": data,
        }
        self._events.append(payload)
        logger.debug("Stream event on %s: %s", channel, event_type)

        # Notify any active in process subscribers
        queues = self._subscribers.get(channel, [])
        for q in queues:
            await q.put(payload)

        # If channel format is task:{task_id} or task:{task_id}:events, append to stream
        parts = channel.split(":")
        if len(parts) >= 2 and parts[0] == "task":
            task_id = parts[1]
            await self.append_event(task_id, event_type, data)

    def subscribe(self, channel: str) -> asyncio.Queue:
        """Subscribe to an in process channel stream."""
        q: asyncio.Queue = asyncio.Queue()
        if channel not in self._subscribers:
            self._subscribers[channel] = []
        self._subscribers[channel].append(q)
        return q

    def unsubscribe(self, channel: str, q: asyncio.Queue) -> None:
        """Unsubscribe from a channel stream."""
        if channel in self._subscribers and q in self._subscribers[channel]:
            self._subscribers[channel].remove(q)

    async def append_event(
        self,
        task_id: uuid.UUID | str,
        event_type: str,
        data: dict,
        max_len: int = 10000,
    ) -> str:
        """Append event to task:{task_id}:stream."""
        str_task_id = str(task_id)
        stream_key = f"task:{str_task_id}:stream"
        timestamp = datetime.now(UTC).isoformat()
        client = await self._get_client()

        if client:
            try:
                payload: dict[Any, Any] = {
                    "event_type": event_type,
                    "data": json.dumps(data),
                    "timestamp": timestamp,
                }
                event_id = await client.xadd(
                    stream_key,
                    payload,
                    maxlen=max_len,
                    approximate=True,
                )
                # Set 24 hour TTL on key
                await client.expire(stream_key, 86400)
                return str(event_id)
            except Exception as exc:
                logger.warning(
                    "Redis xadd failed for %s, falling back to in memory: %s",
                    stream_key,
                    exc,
                )

        # In memory fallback
        self._seq_counter += 1
        now_ms = int(time.time() * 1000)
        event_id = f"{now_ms}-{self._seq_counter}"
        entry = (event_id, event_type, data, timestamp)

        if str_task_id not in self._streams:
            self._streams[str_task_id] = []
        self._streams[str_task_id].append(entry)

        # Trim in memory stream to max_len
        if len(self._streams[str_task_id]) > max_len:
            self._streams[str_task_id] = self._streams[str_task_id][-max_len:]

        # Wake up any waiting readers
        notifiers = self._stream_notifiers.get(str_task_id, [])
        for ev in notifiers:
            ev.set()

        return event_id

    async def read_events(
        self,
        task_id: uuid.UUID | str,
        last_event_id: str = "0-0",
        count: int | None = None,
        block_ms: int = 0,
    ) -> list[tuple[str, str, dict, str]]:
        """Read events from task:{task_id}:stream starting after last_event_id."""
        str_task_id = str(task_id)
        stream_key = f"task:{str_task_id}:stream"
        client = await self._get_client()

        if client:
            try:
                streams_dict: dict[Any, Any] = {
                    stream_key: last_event_id if last_event_id else "0-0"
                }
                read_res: Any = await client.xread(
                    streams_dict,
                    count=count,
                    block=block_ms if block_ms > 0 else None,
                )
                results: list[tuple[str, str, dict, str]] = []
                if read_res:
                    for _key, messages in read_res:
                        for msg_id, fields in messages:
                            event_type = str(fields.get("event_type", "unknown"))
                            raw_data = str(fields.get("data", "{}"))
                            try:
                                data_dict = json.loads(raw_data)
                            except Exception:
                                data_dict = {"raw": raw_data}
                            timestamp = str(
                                fields.get("timestamp", datetime.now(UTC).isoformat())
                            )
                            results.append(
                                (str(msg_id), event_type, data_dict, timestamp)
                            )
                return results
            except Exception as exc:
                logger.warning(
                    "Redis xread failed for %s, falling back to in memory: %s",
                    stream_key,
                    exc,
                )

        # In memory fallback
        stream = self._streams.get(str_task_id, [])
        filtered: list[tuple[str, str, dict, str]] = []

        def parse_id(eid: str) -> tuple[int, int]:
            try:
                parts = eid.split("-")
                return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
            except Exception:
                return (0, 0)

        cursor = parse_id(last_event_id)
        for item in stream:
            item_id = parse_id(item[0])
            if item_id > cursor:
                filtered.append(item)
                if count and len(filtered) >= count:
                    break

        if not filtered and block_ms > 0:
            # Wait for next event or timeout
            ev = asyncio.Event()
            if str_task_id not in self._stream_notifiers:
                self._stream_notifiers[str_task_id] = []
            self._stream_notifiers[str_task_id].append(ev)
            try:
                await asyncio.wait_for(ev.wait(), timeout=block_ms / 1000.0)
            except TimeoutError:
                pass
            finally:
                if (
                    str_task_id in self._stream_notifiers
                    and ev in self._stream_notifiers[str_task_id]
                ):
                    self._stream_notifiers[str_task_id].remove(ev)

            # Re check stream
            stream = self._streams.get(str_task_id, [])
            for item in stream:
                item_id = parse_id(item[0])
                if item_id > cursor:
                    filtered.append(item)
                    if count and len(filtered) >= count:
                        break

        return filtered

    async def get_stream_transcript(
        self, task_id: uuid.UUID | str
    ) -> tuple[str, list[dict], int]:
        """Read all accumulated stream events and consolidate terminal log text."""
        str_task_id = str(task_id)
        stream_key = f"task:{str_task_id}:stream"
        client = await self._get_client()

        raw_events: list[tuple[str, str, dict, str]] = []
        if client:
            try:
                # Read all items via xrange
                entries: Any = await client.xrange(stream_key, min="-", max="+")
                for msg_id, fields in entries:
                    event_type = str(fields.get("event_type", "unknown"))
                    raw_data = str(fields.get("data", "{}"))
                    try:
                        data_dict = json.loads(raw_data)
                    except Exception:
                        data_dict = {"raw": raw_data}
                    timestamp = str(
                        fields.get("timestamp", datetime.now(UTC).isoformat())
                    )
                    raw_events.append((str(msg_id), event_type, data_dict, timestamp))
            except Exception as exc:
                logger.warning("Redis xrange failed for %s: %s", stream_key, exc)

        if not raw_events:
            raw_events = self._streams.get(str_task_id, [])

        terminal_chunks: list[str] = []
        events_json: list[dict] = []
        line_count = 0

        for event_id, event_type, data, timestamp in raw_events:
            events_json.append(
                {
                    "event_id": event_id,
                    "event_type": event_type,
                    "data": data,
                    "timestamp": timestamp,
                }
            )
            if event_type == "task.log":
                chunk = data.get("chunk", "")
                terminal_chunks.append(chunk)
                line_count += chunk.count("\n")

        terminal_log = "".join(terminal_chunks)
        return terminal_log, events_json, line_count


_default_streamer: InMemoryOrRedisEventStreamer | None = None


def get_event_streamer() -> InMemoryOrRedisEventStreamer:
    """Get the application event streamer instance."""
    global _default_streamer
    if _default_streamer is None:
        from app.core.config import settings

        _default_streamer = InMemoryOrRedisEventStreamer(
            redis_url=getattr(settings, "REDIS_URL", None)
        )
    return _default_streamer
