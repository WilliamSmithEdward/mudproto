from dataclasses import dataclass, field

from assets import get_gear_template_by_id, get_item_template_by_id, load_rooms, load_zones


@dataclass
class Room:
    room_id: str
    title: str
    description: str
    zone_id: str = ""
    exits: dict[str, str] = field(default_factory=dict)
    npcs: list[dict] = field(default_factory=list)
    items: list[dict] = field(default_factory=list)
    keyword_actions: list[dict] = field(default_factory=list)
    room_objects: list[dict] = field(default_factory=list)
    exit_details: list[dict] = field(default_factory=list)


@dataclass
class Zone:
    zone_id: str
    name: str
    repopulate_game_hours: int = 0
    reset_player_flags: list[str] = field(default_factory=list)
    reset_container_template_ids: list[str] = field(default_factory=list)
    room_ids: list[str] = field(default_factory=list)
    pending_repopulation: bool = False
    game_hours_since_repopulation: int = 0


@dataclass
class WorldState:
    rooms: dict[str, Room] = field(default_factory=dict)
    zones: dict[str, Zone] = field(default_factory=dict)


def build_default_world() -> WorldState:
    world = WorldState()

    for zone_data in load_zones():
        zone = Zone(
            zone_id=zone_data["zone_id"],
            name=zone_data["name"],
            repopulate_game_hours=max(0, int(zone_data.get("repopulate_game_hours", 0))),
            reset_player_flags=[str(flag).strip().lower() for flag in zone_data.get("reset_player_flags", []) if str(flag).strip()],
            reset_container_template_ids=[str(template_id).strip().lower() for template_id in zone_data.get("reset_container_template_ids", []) if str(template_id).strip()],
        )
        world.zones[zone.zone_id] = zone

    for room_data in load_rooms():
        room = Room(
            room_id=room_data["room_id"],
            title=room_data["title"],
            description=room_data["description"],
            zone_id=room_data.get("zone_id", ""),
            exits=room_data["exits"],
            npcs=room_data.get("npcs", []),
            items=room_data.get("items", []),
            keyword_actions=room_data.get("keyword_actions", []),
            room_objects=room_data.get("room_objects", []),
            exit_details=room_data.get("exit_details", []),
        )
        world.rooms[room.room_id] = room

    for room in world.rooms.values():
        if room.zone_id not in world.zones:
            raise ValueError(f"Room '{room.room_id}' belongs to unknown zone '{room.zone_id}'.")
        world.zones[room.zone_id].room_ids.append(room.room_id)

        for direction, destination_room_id in room.exits.items():
            if destination_room_id not in world.rooms:
                raise ValueError(
                    f"Room '{room.room_id}' has exit '{direction}' to unknown room '{destination_room_id}'."
                )

        for exit_detail in room.exit_details:
            exit_direction = str(exit_detail.get("direction", "")).strip().lower()
            if exit_direction not in room.exits:
                raise ValueError(
                    f"Room '{room.room_id}' exit detail references unknown direction '{exit_direction}'."
                )

        for room_item in room.items:
            template_id = str(room_item.get("template_id", "")).strip()
            if not template_id:
                raise ValueError(f"Room '{room.room_id}' item entries must include template_id.")
            if get_gear_template_by_id(template_id) is None and get_item_template_by_id(template_id) is None:
                raise ValueError(
                    f"Room '{room.room_id}' item '{template_id}' references an unknown gear or item template."
                )

        for keyword_action in room.keyword_actions:
            for action in keyword_action.get("actions", []):
                action_type = str(action.get("type", "")).strip().lower()
                if action_type not in {"set_exit", "reveal_exit", "show_exit", "teleport_player"}:
                    continue
                destination_room_id = str(action.get("destination_room_id", "")).strip()
                if destination_room_id not in world.rooms:
                    raise ValueError(
                        f"Room '{room.room_id}' keyword action points to unknown room '{destination_room_id}'."
                    )

    return world


WORLD = build_default_world()


def get_room(room_id: str) -> Room | None:
    return WORLD.rooms.get(room_id)