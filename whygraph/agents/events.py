"""In-process event bus for agent events: live SSE fan-out + JSONL recording.

Every event is appended to `scenarios/recordings/live/<incident>.jsonl` in the same format the replay endpoint
serves, so a good live run can be copied into `scenarios/recordings/` and replayed in the demo.
"""

import asyncio
import time
from collections import defaultdict
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from whygraph.config import get_settings
from whygraph.models.events import AgentEvent, AgentName, EventType

_CLOSE = None  # sentinel pushed to subscribers when an investigation finishes


def now_ms() -> int:
    return int(time.time() * 1000)


def to_sse(event: AgentEvent) -> str:
    return f"data: {event.model_dump_json()}\n\n"


class EventBus:
    def __init__(self, record_dir: Path | None = None) -> None:
        self._record_dir = record_dir
        self._history: dict[str, list[AgentEvent]] = {}
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._closed: set[str] = set()

    def _path(self, incident_id: str) -> Path | None:
        return self._record_dir / f"{incident_id}.jsonl" if self._record_dir else None

    def history(self, incident_id: str) -> list[AgentEvent]:
        """Events so far; reloaded from the recording after an API restart."""
        if incident_id not in self._history:
            path = self._path(incident_id)
            events = []
            if path and path.exists():
                events = [
                    AgentEvent.model_validate_json(x) for x in path.read_text().splitlines() if x.strip()
                ]
                self._closed.add(incident_id)
            self._history[incident_id] = events
        return self._history[incident_id]

    async def publish(
        self, incident_id: str, type: EventType, agent: AgentName | None = None, **payload: Any
    ) -> AgentEvent:
        history = self.history(incident_id)
        event = AgentEvent(
            seq=len(history) + 1,
            ts=now_ms(),
            incident_id=incident_id,
            type=type,
            agent=agent,
            payload=payload,
        )
        history.append(event)
        self._closed.discard(incident_id)
        path = self._path(incident_id)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a") as f:
                f.write(event.model_dump_json() + "\n")
        for q in self._subs[incident_id]:
            q.put_nowait(event)
        return event

    def close(self, incident_id: str) -> None:
        """Mark the stream finished; subscribers receive the end of the stream."""
        self._closed.add(incident_id)
        for q in self._subs[incident_id]:
            q.put_nowait(_CLOSE)

    def is_closed(self, incident_id: str) -> bool:
        return incident_id in self._closed

    async def subscribe(self, incident_id: str, follow: bool = True) -> AsyncIterator[AgentEvent]:
        """Yield the history, then live events until the investigation closes (stop early if not follow)."""
        q: asyncio.Queue = asyncio.Queue()
        self._subs[incident_id].add(q)  # register before reading history so nothing slips between
        try:
            last = 0
            for event in list(self.history(incident_id)):
                last = event.seq
                yield event
            if not follow or self.is_closed(incident_id):
                return
            while True:
                event = await q.get()
                if event is _CLOSE:
                    return
                if event.seq > last:
                    last = event.seq
                    yield event
        finally:
            self._subs[incident_id].discard(q)


_bus: EventBus | None = None


def get_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus(get_settings().recordings_dir / "live")
    return _bus
