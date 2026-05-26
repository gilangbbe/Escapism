"""Action validation + dispatch.

The validator is the single chokepoint where agent intent meets world
rules. It returns an `ActionResult` describing what happened, which the
turn tracker logs and the renderer displays.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .ontology import ObjectType, Ontology
from .state import DIRECTIONS, Action, WorldState


@dataclass
class ActionResult:
    ok: bool
    summary: str
    side_effects: list = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.side_effects is None:
            self.side_effects = []


class ActionValidator:
    def __init__(self, world: WorldState, ontology: Ontology) -> None:
        self.world = world
        self.ontology = ontology

    # ---------- public ----------

    def apply(self, action: Action) -> ActionResult:
        if action.verb not in self.ontology.actions:
            return ActionResult(False, f"Unknown verb '{action.verb}'.")
        handler = getattr(self, f"_do_{action.verb.lower()}", None)
        if handler is None:
            return ActionResult(False, f"No handler for '{action.verb}'.")
        return handler(action)

    # ---------- handlers ----------

    def _do_wait(self, action: Action) -> ActionResult:
        return ActionResult(True, f"{action.actor_id} waits.")

    def _do_say(self, action: Action) -> ActionResult:
        text = str(action.args.get("text", action.say or "")).strip()
        if not text:
            return ActionResult(False, "SAY requires non-empty 'text'.")
        return ActionResult(True, f"{action.actor_id} says: \"{text}\"")

    def _do_move(self, action: Action) -> ActionResult:
        direction = str(action.args.get("direction", "")).upper()
        if direction not in DIRECTIONS:
            return ActionResult(False, f"MOVE direction must be one of {list(DIRECTIONS)}.")
        body = self.world.bodies[action.actor_id]
        dr, dc = DIRECTIONS[direction]
        target = (body.position[0] + dr, body.position[1] + dc)
        if not self.world.in_bounds(target):
            return ActionResult(False, f"Cannot move {direction.lower()}: out of bounds.")
        if not self.world.is_passable(target):
            reason = "wall" if self.world.tile_at(target).value == "#" else "blocked"
            return ActionResult(False, f"Cannot move {direction.lower()}: {reason}.")
        self.world.move(action.actor_id, direction)
        # Did the agent step onto an unlocked door?
        for obj in self.world.objects_at(target):
            if obj.type == ObjectType.DOOR and not obj.properties.get("locked", True):
                self.world.mark_escaped(action.actor_id)
                return ActionResult(
                    True,
                    f"{action.actor_id} steps through the door and escapes!",
                    side_effects=["escaped"],
                )
        return ActionResult(True, f"{action.actor_id} moves {direction.lower()}.")

    def _do_pickup(self, action: Action) -> ActionResult:
        obj_id = str(action.args.get("object_id", ""))
        obj = self.world.objects.get(obj_id)
        if obj is None:
            return ActionResult(False, f"No object '{obj_id}'.")
        body = self.world.bodies[action.actor_id]
        if obj.position != body.position:
            return ActionResult(False, f"Cannot pick up '{obj_id}': not on your tile.")
        self.world.pickup(action.actor_id, obj_id)
        return ActionResult(True, f"{action.actor_id} picks up the {obj.type.value}.")

    def _do_use(self, action: Action) -> ActionResult:
        item = str(action.args.get("item", ""))
        target = str(action.args.get("target", ""))
        body = self.world.bodies[action.actor_id]
        if item not in body.inventory:
            return ActionResult(False, f"Cannot use '{item}': not in inventory.")
        tgt_obj = self.world.objects.get(target)
        if tgt_obj is None:
            return ActionResult(False, f"Unknown target '{target}'.")
        # Must be on or adjacent to the target.
        dist = abs(tgt_obj.position[0] - body.position[0]) + abs(
            tgt_obj.position[1] - body.position[1]
        )
        if dist > 1:
            return ActionResult(False, f"Cannot use '{item}' on '{target}': too far away.")
        item_obj = self.world.objects[item]
        # Key + Door rule
        if item_obj.type == ObjectType.KEY and tgt_obj.type == ObjectType.DOOR:
            if not tgt_obj.properties.get("locked", True):
                return ActionResult(False, f"Door '{target}' is already unlocked.")
            self.world.unlock_door(target)
            return ActionResult(
                True,
                f"{action.actor_id} unlocks the door with the {item_obj.type.value}.",
                side_effects=["door_unlocked"],
            )
        return ActionResult(False, f"Nothing happens when you use '{item}' on '{target}'.")

    def _do_examine(self, action: Action) -> ActionResult:
        obj_id = str(action.args.get("object_id", ""))
        obj = self.world.objects.get(obj_id)
        if obj is None:
            return ActionResult(False, f"No object '{obj_id}'.")
        desc = f"{obj.type.value} (id={obj.obj_id})"
        if obj.properties:
            props = ", ".join(f"{k}={v}" for k, v in obj.properties.items())
            desc += f" [{props}]"
        return ActionResult(True, f"{action.actor_id} examines {desc}.")
