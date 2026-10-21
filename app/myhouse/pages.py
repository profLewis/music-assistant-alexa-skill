"""MyHouse pages: read the house (ha.states) and lay it out (apl). Temperatures to one decimal, as the dashboard."""

import time

from . import apl, ha
from .house import (BOILER, BOOST_HOURS, BOOSTS, CENTRAL, DAY_T, FORCE_OFF, GROUP, LEAD, NIGHT_T, OFF_TIME, ON_TIME, OVERRIDE, ROOMS,
                    TARGET, WINTER, WINTER_END, WINTER_START)


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
    return apl.document("home", "Cat Ballou", rows, _top())


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
        apl.pill("End boosts", "end_boost", "all", on=bool(bst)), apl.navpill("Settings", "hsettings")]}
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


def mode():
    """Normal / Boost / Override / Off - what the heating is doing as a whole."""
    if ha.state(FORCE_OFF) == "on":
        return "off"
    if ha.state(OVERRIDE) == "on":
        return "override"
    if CENTRAL in boosted():
        return "boost"
    return "normal"


def _row(label, value, minus, plus, act):
    return {"type": "Container", "direction": "row", "alignItems": "center", "width": "48%", "spacing": "2%", "paddingBottom": "1.6vh", "items": [
        apl._txt(label, 22, apl.DIM, "bold", width="40%"), apl._txt(value, 30, apl.TEXT, "bold", grow=1),
        apl.pill("−", act, minus), apl.pill("+", act, plus)]}


def _hm(t, d):
    try:
        h, m = (int(x) for x in str(t).split(":")[:2])
    except ValueError:
        h, m = 7, 0
    m = (h * 60 + m + d) % 1440
    return f"{m // 60:02d}:{m % 60:02d}:00"


def _day(dt, d):
    import datetime
    try:
        x = datetime.date.fromisoformat(str(dt)[:10])
    except ValueError:
        x = datetime.date.today()
    return (x + datetime.timedelta(days=d)).isoformat()


def _date(dt):
    import datetime
    try:
        return datetime.date.fromisoformat(str(dt)[:10]).strftime("%-d %b %Y")
    except ValueError:
        return "—"


def hsettings():
    """Heating settings: Central Control now, the mode, winter + its dates, boost length, morning / night."""
    cur, tgt, act = ha.attr(CENTRAL, "current_temperature"), ha.attr(CENTRAL, "temperature"), ha.attr(CENTRAL, "hvac_action") or ha.state(CENTRAL)
    md, win = mode(), ha.state(WINTER) == "on"
    hrs = _num(ha.state(BOOST_HOURS)) or 2
    head = {"type": "Container", "direction": "row", "alignItems": "center", "paddingBottom": "2vh", "items": [
        apl._txt(t1(cur), 64, apl.WARM, "bold"),
        {"type": "Container", "paddingLeft": "2vw", "grow": 1, "items": [apl._txt("CENTRAL CONTROL", 18, apl.DIM, "bold"),
                                                                       apl._txt(f"target {t1(tgt)} · {str(act).replace('_', ' ')}", 24, apl.TEXT)]},
        apl.pill("Normal", "hmode", "normal", on=md == "normal"), apl.pill("Boost", "hmode", "boost", on=md == "boost"),
        apl.pill("Override", "hmode", "override", on=md == "override"), apl.pill("Off", "hmode", "off", on=md == "off")]}
    day_t, night_t = _num(ha.state(DAY_T)) or 20, _num(ha.state(NIGHT_T)) or 10
    on_t, off_t = ha.state(ON_TIME, "07:00:00"), ha.state(OFF_TIME, "21:00:00")
    ws, we = ha.state(WINTER_START), ha.state(WINTER_END)
    rows = [
        {"type": "Container", "direction": "row", "alignItems": "center", "width": "48%", "spacing": "2%", "paddingBottom": "1.6vh", "items": [
            apl._txt("Winter", 22, apl.DIM, "bold", width="40%"), apl._txt("On" if win else "Off", 30, apl.TEXT, "bold", grow=1),
            apl.pill("Winter " + ("on" if win else "off"), "toggle", WINTER, on=win)]},
        _row("Boost length", f"{hrs:g} h", str(max(0.5, hrs - 0.5)), str(min(8, hrs + 0.5)), "set_boost_hours"),
        _row("Winter starts", _date(ws), _day(ws, -7), _day(ws, 7), "set_winter_start"),
        _row("Winter ends", _date(we), _day(we, -7), _day(we, 7), "set_winter_end"),
        _row("Morning on at", str(on_t)[:5], _hm(on_t, -15), _hm(on_t, 15), "set_on_time"),
        _row("Morning temp", f"{day_t:.1f}°", str(day_t - 0.5), str(day_t + 0.5), "set_day_t"),
        _row("Night from", str(off_t)[:5], _hm(off_t, -15), _hm(off_t, 15), "set_off_time"),
        _row("Night temp", f"{night_t:.1f}°", str(night_t - 0.5), str(night_t + 0.5), "set_night_t"),
    ]
    grid2 = [{"type": "Container", "direction": "row", "width": "100%", "items": rows[i:i + 2]} for i in range(0, len(rows), 2)]
    return apl.document("heating", "Heating settings", [head] + grid2, _top())


PAGES = {"home": home, "lights": lights, "heating": heating, "music": music, "hsettings": hsettings}


def render(page):
    return (PAGES.get(page) or home)()
