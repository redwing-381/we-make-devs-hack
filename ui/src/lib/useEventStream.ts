import { useEffect, useState } from "react";
import { subscribe } from "../api/client";
import type { AgentEvent } from "../types/events";

/** Collects every AgentEvent from an SSE url (live or replay). Re-subscribes when url changes. */
export function useEventStream(url: string | null) {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [done, setDone] = useState(false);

  useEffect(() => {
    setEvents([]);
    setDone(false);
    if (!url) return;
    return subscribe(
      url,
      (e) => setEvents((prev) => [...prev, e]),
      () => setDone(true),
    );
  }, [url]);

  return { events, done };
}
