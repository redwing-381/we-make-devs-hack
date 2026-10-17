import asyncio

from whygraph.agents.events import EventBus


def test_subscribe_replays_history_then_follows_until_close():
    async def scenario():
        bus = EventBus()
        await bus.publish("INC-1", "incident.opened", "orchestrator", incident={"id": "INC-1"})
        seen = []

        async def reader():
            async for e in bus.subscribe("INC-1"):
                seen.append((e.seq, e.type))

        task = asyncio.create_task(reader())
        await asyncio.sleep(0)
        await bus.publish("INC-1", "agent.started", "triage")
        await bus.publish("INC-1", "agent.done", "triage", summary="ok")
        bus.close("INC-1")
        await asyncio.wait_for(task, 1)
        return seen

    assert asyncio.run(scenario()) == [(1, "incident.opened"), (2, "agent.started"), (3, "agent.done")]


def test_closed_stream_ends_after_history():
    async def scenario():
        bus = EventBus()
        await bus.publish("INC-2", "agent.started", "cause")
        bus.close("INC-2")
        return [e.seq async for e in bus.subscribe("INC-2")]

    assert asyncio.run(asyncio.wait_for(scenario(), 1)) == [1]


def test_recording_survives_restart(tmp_path):
    async def write():
        bus = EventBus(tmp_path)
        await bus.publish("INC-3", "agent.started", "memory")
        await bus.publish("INC-3", "agent.done", "memory", summary="no match")

    asyncio.run(write())
    reborn = EventBus(tmp_path)  # a fresh process: history comes back from the JSONL file
    history = reborn.history("INC-3")
    assert [e.type for e in history] == ["agent.started", "agent.done"]
    assert reborn.is_closed("INC-3")
    assert (tmp_path / "INC-3.jsonl").read_text().count("\n") == 2
