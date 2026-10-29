"""MyHouse actions: what a tap or a spoken command does to the house. Each returns a short sentence to say (or None)."""

from . import ha
from .house import (BOOST_HOURS, CENTRAL, DAY_T, FORCE_OFF, GROUP, LEAD, NIGHT_T, OFF_TIME, ON_TIME, OVERRIDE, ROOMS, TARGET,
                    WINTER, WINTER_END, WINTER_START, room)
from .pages import _num, boosted, lights_on, t1


def room_lights(name, on=None):
    r = room(name)
    if not r:
        return f"I don't know a room called {name}."
    ents = ROOMS[r][0]
    if on is None:
        on = not lights_on(r)
    ha.call("light", "turn_on" if on else "turn_off", {"entity_id": ents})
    return f"{r} lights {'on' if on else 'off'}."


def all_lights(on):
    ha.call("script", "panel_all_lights", {"action": "on" if on else "off"})
    return f"All the lights {'on' if on else 'off'}."


def boost(name, toggle=True):
    r = room(name)
    if not r or not ROOMS[r][1]:
        return f"There's no radiator I can boost in {name}."
    rads, bst = ROOMS[r][1], boosted()
    if toggle and any(e in bst for e in rads):
        for e in rads:
            ha.call("script", "heating_end_boost", {"entity": e, "quick": True})
        return f"Boost ended in the {r.lower()}."
    cur = _num(ha.state(ROOMS[r][2])) if ROOMS[r][2] else None
    temp = min(28.0, round(((cur or _num(ha.state(TARGET)) or 19.0) + 1) * 2) / 2)
    hours = _num(ha.state(BOOST_HOURS)) or 2
    for e in rads:
        ha.call("script", "heating_boost", {"entity": e, "temp": temp, "hours": hours})
    return f"Boosting the {r.lower()} to {temp:.1f} degrees for {hours:g} hours."


def end_boost(name="all"):
    if (name or "all") == "all":
        ha.call("script", "heating_end_boost", {"entity": "all", "quick": True})
        return "All boosts ended."
    return boost(name, toggle=True) if any(e in boosted() for e in ROOMS.get(room(name) or "", ([], [], None, []))[1]) else "No boost running there."


def set_target(t):
    v = _num(t)
    if v is None or not 10 <= v <= 26:
        return "Pick a temperature between 10 and 26 degrees."
    v = round(v * 2) / 2
    ha.call("input_number", "set_value", {"entity_id": TARGET, "value": v})
    return f"The house target is now {v:.1f} degrees."


def temperature(name=None):
    if not name:
        return f"The house is {t1(ha.state('sensor.house_temperature'))[:-1]} degrees; outside it's {t1(ha.state('sensor.outside_temperature'))[:-1]}."
    r = room(name)
    if not r or not ROOMS[r][2]:
        return f"I don't have a thermometer in {name}."
    return f"The {r.lower()} is {t1(ha.state(ROOMS[r][2]))[:-1]} degrees."


def _players():
    lead = ha.state(LEAD) or "media_player.all_floors"
    extra = [x.strip() for x in (ha.state(GROUP) or "").split(",") if x.strip().startswith("media_player.")]
    return [lead] + extra if ha.state("input_select.ma_multi_mode") != "lead" else [lead]


def music(act):
    act = (act or "").lower()
    ps = _players()
    svc = {"pause": "media_pause", "stop": "media_pause", "play": "media_play", "resume": "media_play", "play_pause": "media_play_pause",
           "next": "media_next_track", "skip": "media_next_track", "previous": "media_previous_track", "back": "media_previous_track"}.get(act)
    if svc:
        ha.call("media_player", svc, {"entity_id": ps if svc != "media_next_track" and svc != "media_previous_track" else ps[0]})
        return None
    if act in ("louder", "quieter", "turn up", "turn down", "volume up", "volume down"):
        up = act in ("louder", "turn up", "volume up")
        for p in ps:
            v = _num(ha.attr(p, "volume_level"))
            if v is not None:
                ha.call("media_player", "volume_set", {"entity_id": p, "volume_level": max(0.0, min(1.0, round(v + (0.06 if up else -0.06), 2)))})
        return None
    return "I can pause, play, skip, go back, or make it louder or quieter."


def echo_volume(direction=None, level=None, alexa_device=None):
    """The Echo's own volume (script.echo_volume in Home Assistant): direction 'up' / 'down' a step, or level 0-10."""
    v = {"direction": direction or "", "level": level if level not in (None, "?") else "", "alexa_device": alexa_device or ""}
    ha.call("script", "turn_on", {"entity_id": "script.echo_volume", "variables": v})


def heating_mode(m):
    """Normal / Boost (Central Control up a degree for the boost length) / Override (on regardless) / Off (off regardless)."""
    if m in ("normal", "boost", "override", "off"):
        ha.call("input_boolean", "turn_on" if m == "override" else "turn_off", {"entity_id": OVERRIDE})
        ha.call("input_boolean", "turn_on" if m == "off" else "turn_off", {"entity_id": FORCE_OFF})
    if m == "normal" and CENTRAL in boosted():
        ha.call("script", "heating_end_boost", {"entity": CENTRAL, "quick": True})
    if m == "boost":
        cur = _num(ha.attr(CENTRAL, "current_temperature")) or _num(ha.state(TARGET)) or 19.0
        hours = _num(ha.state(BOOST_HOURS)) or 2
        ha.call("script", "heating_boost", {"entity": CENTRAL, "temp": min(28.0, round((cur + 1) * 2) / 2), "hours": hours})
        return f"Boosting the heating for {hours:g} hours."
    return {"normal": "Heating back to normal.", "override": "Heating on regardless.", "off": "Heating off."}.get(m)


def _num_set(entity, v, lo, hi):
    x = _num(v)
    if x is not None:
        ha.call("input_number", "set_value", {"entity_id": entity, "value": max(lo, min(hi, round(x * 2) / 2))})


def do(action, arg):
    """A tap on the screen: ["act", action, arg]."""
    if action == "room_lights":
        return room_lights(arg)
    if action == "all_lights":
        return all_lights(arg == "on")
    if action == "boost":
        return boost(arg)
    if action == "end_boost":
        return end_boost(arg)
    if action == "target":
        return set_target(arg)
    if action == "music":
        return music(arg)
    if action == "hmode":
        return heating_mode(arg)
    if action == "toggle" and arg in (WINTER,):
        return ha.call("input_boolean", "toggle", {"entity_id": arg}) and None
    if action == "set_boost_hours":
        return _num_set(BOOST_HOURS, arg, 0.5, 8)
    if action == "set_day_t":
        return _num_set(DAY_T, arg, 10, 26)
    if action == "set_night_t":
        return _num_set(NIGHT_T, arg, 10, 22)
    if action in ("set_on_time", "set_off_time"):
        return ha.call("input_datetime", "set_datetime", {"entity_id": ON_TIME if action == "set_on_time" else OFF_TIME, "time": arg}) and None
    if action in ("set_winter_start", "set_winter_end"):
        return ha.call("input_datetime", "set_datetime", {"entity_id": WINTER_START if action == "set_winter_start" else WINTER_END, "date": arg}) and None
    return None
