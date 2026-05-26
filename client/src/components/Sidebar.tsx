import type { WorldSnapshot } from "../types";

interface Props {
  world: WorldSnapshot | null;
  connected: boolean;
  onReset: () => void;
}

export function Sidebar({ world, connected, onReset }: Props) {
  return (
    <aside className="w-80 border-l border-brass/30 bg-ink/60 p-5 overflow-y-auto flex flex-col gap-5">
      <header className="border-b border-brass/30 pb-3">
        <div className="text-xs uppercase tracking-widest text-brass">The Black Vesper</div>
        <div className="text-lg leading-tight">The Last Voyage</div>
        <div className="text-xs text-brass/60 mt-1">
          {connected ? "● live" : "○ disconnected"}
        </div>
      </header>

      {world ? (
        <>
          <Section title="Time">
            <div className="text-3xl tracking-wider">{world.in_game_time}</div>
            <div className="text-xs text-brass/70">
              {world.minutes_until_port_royal} min until Port Royal
            </div>
          </Section>

          <Section title="Location">
            <div>{world.current_location}</div>
            {world.scene_id && (
              <div className="text-xs text-brass/60 italic">{world.scene_id}</div>
            )}
          </Section>

          <Section title="Alarm">
            <Meter value={world.alarm_meter} max={world.alarm_max ?? 10} />
          </Section>

          <Section title="Inventory">
            <ul className="space-y-1 text-sm">
              {world.inventory.map((i) => (
                <li key={i} className="flex items-center gap-2">
                  <span className="text-brass">◆</span>
                  <span>{i.replace(/_/g, " ")}</span>
                </li>
              ))}
              {world.inventory.length === 0 && (
                <li className="text-brass/60 italic text-xs">empty</li>
              )}
            </ul>
          </Section>

          <Section title="Objectives">
            <ul className="space-y-1 text-sm">
              {Object.entries(world.objectives).map(([id, status]) => (
                <li key={id} className="flex items-center justify-between gap-2">
                  <span className={status === "complete" ? "line-through text-brass/50" : ""}>
                    {id.replace(/_/g, " ")}
                  </span>
                  <span
                    className={[
                      "text-xs uppercase tracking-wide",
                      status === "complete"
                        ? "text-brass"
                        : status === "active"
                          ? "text-ember"
                          : "text-brass/40",
                    ].join(" ")}
                  >
                    {status}
                  </span>
                </li>
              ))}
            </ul>
          </Section>

          {world.known_facts && world.known_facts.length > 0 && (
            <Section title="Known facts">
              <ul className="space-y-1 text-xs text-brass/80">
                {world.known_facts.slice(-6).map((f, i) => (
                  <li key={i}>• {f}</li>
                ))}
              </ul>
            </Section>
          )}
        </>
      ) : (
        <div className="text-brass/60 italic">Waiting for the world to wake...</div>
      )}

      <button
        onClick={onReset}
        className="mt-auto rounded border border-ember/70 bg-ember/20 hover:bg-ember/40 text-parchment py-2 text-sm uppercase tracking-widest"
      >
        Restart run
      </button>
    </aside>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <div className="text-xs uppercase tracking-widest text-brass/70 mb-1">{title}</div>
      <div>{children}</div>
    </section>
  );
}

function Meter({ value, max }: { value: number; max: number }) {
  const pct = Math.min(100, Math.round((value / Math.max(1, max)) * 100));
  return (
    <div className="w-full h-2 rounded bg-ink border border-brass/40 overflow-hidden">
      <div className="h-full bg-ember" style={{ width: `${pct}%` }} />
    </div>
  );
}
