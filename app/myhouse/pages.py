"""MyHouse pages: read the house (ha.states) and lay it out (apl). Temperatures to one decimal, as the dashboard."""

import time

from . import apl, ha
from .house import BOILER, BOOST_HOURS, BOOSTS, GROUP, LEAD, ROOMS, TARGET


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def t1(x):
    v = _num(x)
    return f"{v:.1f}°" if v is not None else "—"


def _clock():
    return time.strftime("%H:%M")


def _top():
    return f"{t1(ha.state('sensor.outside_temperature'))} outside   ·   {_clock()}"


def lights_on(room):
    return [e for e in ROOMS[room][0] if ha.state(e) == "on"]


def boosted():
    """{climate entity: info} for the boosts running now."""
    b = ha.attr(BOOSTS, "boosts") or []
    out = {}
    for x in b if isinstance(b, list) else []:
        if isinstance(x, dict) and x.get("entity"):
            out[x["entity"]] = x
    return out


def home():
    st = ha.states()
    n_on = ha.state("sensor.lights_on", "0")
    health = ha.state("sensor.house_health_state", "ok")
    weather = (st.get("weather.forecast_home") or {}).get("state", "").replace("partlycloudy", "partly cloudy").replace("-", " ")
    lead = ha.state(LEAD) or ""
    m = st.get(lead) or {}
    ma = m.get("attributes") or {}
    playing = m.get("state") == "playing"
    tiles = [
        apl.tile("House", t1(ha.state("sensor.house_temperature")), f"target {t1(ha.state(TARGET))}", apl.WARM),
        apl.tile("Outside", t1(ha.state("sensor.outside_temperature")), weather.capitalize(), apl.COOL),
        apl.tile("Heating", ha.state(BOILER, "—"), ha.state("sensor.heating_activity", "") or "", apl.WARM if ha.state("binary_sensor.boiler_heating") == "on" else apl.TEXT),
        apl.tile("Lights", f"{n_on} on", "tap Lights to change"),
        apl.tile("Music", "Playing" if playing else (m.get("state") or "—").capitalize(),
                 " · ".join(x for x in [ma.get("media_title"), ma.get("media_artist")] if x) or "nothing playing"),
        apl.tile("House health", "All well" if health == "ok" else ("Needs a look" if health == "problem" else health.capitalize()),
                 "", "#7ee08a" if health == "ok" else "#ff8a65"),
    ]
    rows = [{"type": "Container", "direction": "row", "width": "100%", "items": tiles[i:i + 3], "spacing": "2%"} for i in (0, 3)]
    return apl.document("home", "MyHouse", rows, _top())


def lights():
    btns = []
    for r in ROOMS:
        on = lights_on(r)
        n = len(ROOMS[r][0])
        btns.append(apl.button(r, "room_lights", r, f"{len(on)} of {n} on" if on else "off", on=bool(on), icon="💡"))
    bar = {"type": "Container", "direction": "row", "paddingBottom": "2vh",
           "items": [apl.pill("All on", "all_lights", "on"), apl.pill("All off", "all_lights", "off")]}
    return apl.document("lights", "Lights", [bar, apl.grid(btns, 4)], _top())


def heating():
    bst = boosted()
    btns = []
    for r, (_l, rads, thermo, _a) in ROOMS.items():
        if not rads:
            continue
        cur = ha.state(thermo) if thermo else ha.attr(rads[0], "current_temperature")
        setp = ha.attr(rads[0], "temperature")
        hot = any(e in bst for e in rads)
        sub = f"→ {t1(setp)}" + ("   BOOST" if hot else "")
        btns.append(apl.button(f"{r}\n{t1(cur)}", "boost", r, sub, on=hot, icon="🔥" if hot else "🌡️"))
    tgt = _num(ha.state(TARGET)) or 19.0
    bar = {"type": "Container", "direction": "row", "alignItems": "center", "paddingBottom": "2vh", "items": [
        apl._txt(f"House {t1(ha.state('sensor.house_temperature'))}   target {t1(tgt)}", 28, apl.TEXT, "bold", grow=1),
        apl.pill("− 0.5°", "target", str(tgt - 0.5)), apl.pill("+ 0.5°", "target", str(tgt + 0.5)),
        apl.pill("End boosts", "end_boost", "all", on=bool(bst))]}
    hint = apl._txt(f"Tap a room to boost it for {ha.state(BOOST_HOURS, '2')} h (again to end)  ·  heating: {ha.state(BOILER, '—')}", 20, apl.DIM, paddingTop="1vh")
    return apl.document("heating", "Heating", [bar, apl.grid(btns, 4), hint], _top())


def music():
    lead = ha.state(LEAD) or ""
    m = ha.states().get(lead) or {}
    a = m.get("attributes") or {}
    art = a.get("entity_picture") or ""
    if art.startswith("/"):
        art = ""   # (a Home Assistant-relative picture isn't reachable by the Echo - left blank)
    vol = _num(a.get("volume_level"))
    left = ({"type": "Image", "source": art, "width": "34vw", "height": "34vw", "scale": "best-fill", "borderRadius": "18dp"}
            if art else {"type": "Frame", "width": "34vw", "height": "34vw", "borderRadius": "18dp", "backgroundColor": apl.CARD,
                         "item": {"type": "Container", "width": "100%", "height": "100%", "justifyContent": "center", "alignItems": "center",
                                  "items": [apl._txt("🎵", 96)]}})
    right = {"type": "Container", "grow": 1, "paddingLeft": "4vw", "justifyContent": "center", "items": [
        apl._txt((m.get("state") or "—").upper(), 20, apl.DIM, "bold"),
        apl._txt(a.get("media_title") or "Nothing playing", 40, apl.TEXT, "bold", maxLines=2),
        apl._txt(a.get("media_artist") or "", 28, apl.ACCENT, maxLines=1),
        apl._txt(a.get("media_album_name") or "", 24, apl.DIM, maxLines=1, fontStyle="italic"),
        apl._txt(f"on {a.get('friendly_name') or lead}" + (f"   ·   volume {round(vol * 100)}" if vol is not None else ""), 22, apl.DIM, paddingTop="2vh"),
        {"type": "Container", "direction": "row", "paddingTop": "4vh", "items": [
            apl.pill("⏮", "music", "previous"), apl.pill("⏯", "music", "play_pause", on=m.get("state") == "playing"),
            apl.pill("⏭", "music", "next"), apl.pill("🔉", "music", "quieter"), apl.pill("🔊", "music", "louder")]}]}
    return apl.document("music", "Music", [{"type": "Container", "direction": "row", "alignItems": "center", "items": [left, right]}], _top())


PAGES = {"home": home, "lights": lights, "heating": heating, "music": music}


def render(page):
    return (PAGES.get(page) or home)()
