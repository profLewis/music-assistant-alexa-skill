"""MyHouse: the house it shows - rooms, their lights, radiators and thermometers (from the control-panel dashboard),
and what each page reads. Kept in one place so the voice model's room names and the screens agree."""

ROOMS = {   # name: lights, radiators (climate), room thermometer, other spoken names
    "Living room": (["light.angle", "light.living_room_light_light_1", "light.key"], ["climate.radiator_living_room_thermostat"], "sensor.room_temperature_living_room", ["lounge", "sitting room"]),
    "Library": (["light.library_light_light_1", "light.library_light_left", "light.owl", "light.pin", "light.library_right"], ["climate.radiator_library_thermostat"], "sensor.room_temperature_library", []),
    "Kitchen": (["light.ballpoint", "light.light_kitchen_light", "light.light_kitchen_light_3", "light.light_kitchen_light_2", "light.snitch"], ["climate.control_radiator_kitchen"], "sensor.room_temperature_kitchen", []),
    "Hallway": (["light.door", "light.hallway_lower", "light.a_upper_hallway_light"], ["climate.radiator_lower_hallway_thermostat", "climate.radiator_upper_hallway_thermostat"], "sensor.room_temperature_hallway", ["hall", "landing"]),
    "Downstairs bathroom": (["light.light_cellar_light", "light.light_loo_light"], ["climate.radiator_loo_thermostat"], "sensor.room_temperature_downstairs_bathroom", ["loo", "toilet", "cellar"]),
    "Bathroom": (["light.light_bathroom_light_2", "light.light_bathroom_light"], [], "sensor.room_temperature_bathroom", []),
    "Bedroom": (["light.bedroom"], ["climate.radiator_bedroom_left_thermostat", "climate.bedroom_radiator_bedroom_right_thermostat"], "sensor.room_temperature_bedroom", ["main bedroom"]),
    "Lewis study": (["light.smart_bulb"], ["climate.radiator_study_left_thermostat", "climate.radiator_study_right_thermostat"], "sensor.room_temperature_lewis_study", ["study", "lewis's study", "office"]),
    "Sian study": (["light.sian_rope_lamp"], ["climate.radiator_beau_bedroom_thermostat"], "sensor.room_temperature_sian_study", ["sian's study"]),
    "Beau bedroom": (["light.frodo"], ["climate.radiator_harry_bedroom_thermostat"], "sensor.room_temperature_beau_bedroom", ["beau's bedroom", "beau's room"]),
    "Back garden": (["light.back_door_light", "light.hue_outdoor_spot_1"], [], None, ["garden", "outside"]),
}

TARGET = "input_number.target_temperature"
BOOST_HOURS = "input_number.panel_boost_hours"
BOOSTS = "sensor.heating_boosts"
BOILER = "sensor.boiler"
LEAD = "input_text.ma_player"
GROUP = "input_text.ma_player_group"


def room(name):
    """The room for a spoken / tapped name (case-insensitive, synonyms too), or None."""
    n = (name or "").strip().lower()
    for key, (_l, _r, _t, alts) in ROOMS.items():
        if n == key.lower() or n in alts or n.rstrip("s") == key.lower():
            return key
    for key in ROOMS:   # "the kitchen", "kitchen lights"
        if key.lower() in n:
            return key
    return None
