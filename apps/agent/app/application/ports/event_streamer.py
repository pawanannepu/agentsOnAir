"""Event streamer port for real time task telemetry."""

import uuid
from typing import Protocol


class EventStreamer(Protocol):
    """Stream execution logs and events to Redis Streams and channels."""

    async def stream_event(self, channel: str, event_type: str, data: dict) -> None:
        """Publish a structured event payload to the given channel."""
        ...

    async def append_event(
        self,
        task_id: uuid.UUID | str,
        event_type: str,
        data: dict,
        max_len: int = 10000,
    ) -> str:
        """Append an event to the task stream in Redis Streams with a MAXLEN cap.

        Returns the monotonic event ID string (e.g. 1732450000000-0).
        """
        ...

    async def read_events(
        self,
        task_id: uuid.UUID | str,
        last_event_id: str = "0-0",
        count: int | None = None,
        block_ms: int = 0,
    ) -> list[tuple[str, str, dict, str]]:
        """Read events from the task stream starting after last_event_id.

        Returns a list of tuples: (event_id, event_type, data_dict, timestamp_iso).
        """
        ...

    async def get_stream_transcript(
        self, task_id: uuid.UUID | str
    ) -> tuple[str, list[dict], int]:
        """Read accumulated events from the stream for in flight fallback or archiving.

        Returns (terminal_log_text, events_list, total_lines).
        """
        ...
