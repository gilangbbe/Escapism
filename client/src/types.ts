export type EventKind =
  | "history"
  | "reset"
  | "scene_start"
  | "player_thought"
  | "player_say"
  | "player_action"
  | "gm_narration"
  | "gm_state_delta"
  | "system_hint"
  | "reflection"
  | "game_over";

export interface GameEvent {
  tick: number;
  ts?: string;
  kind: EventKind;
  actor: "system" | "mira" | "gm" | string;
  payload: Record<string, unknown> & { world?: WorldSnapshot };
}

export interface WorldSnapshot {
  tick: number;
  in_game_time: string;
  minutes_until_port_royal: number;
  current_location: string;
  alarm_meter: number;
  alarm_max?: number;
  inventory: string[];
  discovered_items?: string[];
  known_facts?: string[];
  npc_state?: Record<string, string>;
  object_state?: Record<string, string>;
  objectives: Record<string, string>;
  scene_id?: string;
  game_over?: string;
}
