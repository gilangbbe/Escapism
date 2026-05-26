import type { GameEvent } from "../types";

interface Props {
  event: GameEvent;
}

export function MessageBubble({ event }: Props) {
  const { kind, actor, payload } = event;
  const text = (payload?.text as string) || "";

  if (kind === "scene_start") {
    return (
      <div className="mx-auto my-6 max-w-2xl text-center text-sm italic text-brass/80">
        <div className="mb-2 tracking-widest uppercase text-xs text-brass">— Scene —</div>
        <div className="border-t border-b border-brass/40 py-3 px-4 bg-ink/30 rounded">
          {(payload?.message as string) || text}
        </div>
      </div>
    );
  }

  if (kind === "game_over") {
    return (
      <div className="mx-auto my-8 max-w-md text-center">
        <div className="rounded-lg border-2 border-ember bg-ember/10 p-6">
          <div className="text-xs uppercase tracking-widest text-ember mb-2">End of Scene</div>
          <div className="text-lg">{(payload?.outcome as string) || "Game over."}</div>
        </div>
      </div>
    );
  }

  if (kind === "gm_state_delta") {
    const notes = (payload?.notes as string[]) || [];
    return (
      <div className="mx-auto my-2 max-w-xl text-xs text-brass/70 font-mono">
        <div className="flex flex-wrap gap-1 justify-center">
          {notes.map((n, i) => (
            <span key={i} className="rounded bg-ink/60 border border-brass/30 px-2 py-0.5">
              {n}
            </span>
          ))}
        </div>
      </div>
    );
  }

  if (kind === "system_hint") {
    return (
      <div className="mx-auto my-3 max-w-xl">
        <div className="rounded-md border border-ember/60 bg-ember/10 px-3 py-2 text-xs text-ember/90">
          <span className="uppercase tracking-widest mr-2 text-[10px] text-ember">hint</span>
          {text}
        </div>
      </div>
    );
  }

  if (actor === "mira") {
    const isThought = kind === "player_thought";
    const isAction = kind === "player_action";
    const action = isAction ? (payload?.action as { verb?: string; target?: string; args?: Record<string, unknown> }) : null;
    return (
      <div className="flex justify-end my-1">
        <div className="max-w-[75%] flex flex-col items-end">
          <div className="text-xs text-brass/70 mb-1">Mira · t{event.tick}</div>
          <div
            className={[
              "rounded-2xl rounded-br-md px-4 py-2",
              isThought
                ? "bg-sea/30 border border-sea/60 italic text-parchment/70"
                : isAction
                  ? "bg-brass/20 border border-brass/60 font-mono text-sm text-brass"
                  : "bg-ember/80 text-parchment",
            ].join(" ")}
          >
            {isThought && <span className="opacity-60 mr-1">💭</span>}
            {isAction && action ? (
              <span>
                <span className="opacity-60 mr-1">▸</span>
                <span className="font-semibold">{action.verb}</span>
                {action.target ? <span className="ml-1">{action.target}</span> : null}
                {action.args && Object.keys(action.args).length > 0 ? (
                  <span className="ml-1 opacity-70">{JSON.stringify(action.args)}</span>
                ) : null}
              </span>
            ) : (
              text
            )}
          </div>
        </div>
      </div>
    );
  }

  if (actor === "gm") {
    return (
      <div className="flex justify-start my-1">
        <div className="max-w-[75%]">
          <div className="text-xs text-brass/70 mb-1">Game Master · t{event.tick}</div>
          <div className="rounded-2xl rounded-bl-md bg-ink/70 border border-brass/40 px-4 py-3 text-parchment/90 leading-relaxed">
            {text}
          </div>
        </div>
      </div>
    );
  }

  // system fallback
  return (
    <div className="text-center text-xs text-brass/50 my-2 italic">[{kind}] {text}</div>
  );
}
