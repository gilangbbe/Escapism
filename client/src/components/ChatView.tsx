import { useEffect, useRef } from "react";
import type { GameEvent } from "../types";
import { MessageBubble } from "./MessageBubble";

interface Props {
  events: GameEvent[];
}

export function ChatView({ events }: Props) {
  const endRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length]);

  return (
    <div className="flex-1 overflow-y-auto px-6 py-4">
      <div className="max-w-3xl mx-auto space-y-1">
        {events.map((ev, i) => (
          <MessageBubble key={`${ev.tick}-${ev.kind}-${i}`} event={ev} />
        ))}
        <div ref={endRef} />
      </div>
    </div>
  );
}
