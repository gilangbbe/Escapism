import { useEffect, useRef, useState } from "react";
import type { GameEvent, WorldSnapshot } from "./types";

const WS_URL = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;

export function useGameSocket() {
  const [events, setEvents] = useState<GameEvent[]>([]);
  const [world, setWorld] = useState<WorldSnapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (msg) => {
      const data = JSON.parse(msg.data);
      if (data.kind === "history" && Array.isArray(data.events)) {
        setEvents(data.events);
        const latestWorld = [...data.events]
          .reverse()
          .find((e: GameEvent) => e.payload?.world)?.payload.world as WorldSnapshot | undefined;
        if (latestWorld) setWorld(latestWorld);
        return;
      }
      if (data.kind === "reset") {
        setEvents([]);
        return;
      }
      const ev = data as GameEvent;
      setEvents((prev) => [...prev, ev]);
      if (ev.payload?.world) setWorld(ev.payload.world as WorldSnapshot);
    };
    return () => ws.close();
  }, []);

  return { events, world, connected };
}

export async function resetSimulation() {
  await fetch("/api/reset", { method: "POST" });
}
