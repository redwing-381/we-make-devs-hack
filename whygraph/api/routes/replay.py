"""Replay recorded AgentEvent streams (scenarios/recordings/*.jsonl, live runs as live/<incident>) over SSE.

Same wire format as the live stream, so the UI can be built and demoed without agents or a database.
"""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from whygraph.config import get_settings
from whygraph.models.events import AgentEvent

router = APIRouter(prefix="/replay", tags=["replay"])
NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # live runs are named by incident id, e.g. INC-1031
LIVE = "live"  # the event bus records live runs into recordings_dir/live
MAX_GAP_S = 2.0


def _path(name: str, live: bool = False) -> Path:
    if not NAME.fullmatch(name):
        raise HTTPException(400, "invalid recording name")
    root = get_settings().recordings_dir
    p = (root / LIVE if live else root) / f"{name}.jsonl"
    if not p.is_file():
        raise HTTPException(404, f"no recording {name!r}")
    return p


def load_recording(path: Path) -> list[AgentEvent]:
    return [
        AgentEvent.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@router.get("")
def list_recordings() -> list[str]:
    root = get_settings().recordings_dir
    names = [p.stem for p in root.glob("*.jsonl") if NAME.fullmatch(p.stem)]
    live = [f"{LIVE}/{p.stem}" for p in (root / LIVE).glob("*.jsonl") if NAME.fullmatch(p.stem)]
    return sorted(names) + sorted(live)


# declared before /{name}/stream so a live recording named "stream" still resolves here
@router.get("/live/{name}")
def get_live_recording(name: str) -> list[dict]:
    return [e.model_dump() for e in load_recording(_path(name, live=True))]


@router.get("/live/{name}/stream")
async def stream_live_recording(name: str, speed: float = Query(2.0, gt=0, le=20)) -> StreamingResponse:
    return _stream(_path(name, live=True), f"{LIVE}/{name}", speed)


@router.get("/{name}")
def get_recording(name: str) -> list[dict]:
    return [e.model_dump() for e in load_recording(_path(name))]


@router.get("/{name}/stream")
async def stream_recording(name: str, speed: float = Query(2.0, gt=0, le=20)) -> StreamingResponse:
    return _stream(_path(name), name, speed)


def _stream(path: Path, name: str, speed: float) -> StreamingResponse:
    events = load_recording(path)

    async def gen() -> AsyncIterator[str]:
        prev_ts = events[0].ts if events else 0
        for e in events:
            await asyncio.sleep(min(max(e.ts - prev_ts, 0) / 1000 / speed, MAX_GAP_S))
            prev_ts = e.ts
            yield f"data: {e.model_dump_json()}\n\n"
        yield f"event: end\ndata: {json.dumps({'name': name})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
