"""Fork: MyHouse - the house on the Echo Show. The skill draws pages, keeps the screen up without the microphone,
and turns taps / voice into Home Assistant calls."""

import json

import pytest

from golden_cases import build_event
from myhouse import actions, deploy, ha, handlers, model, pages

SHOW = {"Alexa.Presentation.APL": {"runtime": {"maxVersion": "2023.2"}}}
MOON = {**SHOW, "Alexa.Presentation.HTML": {"runtime": {"maxVersion": "1.1"}}}   # (the Moon: an Echo Show with the panel's web app)
DOT = {}
STATES = {
    "sensor.outside_temperature": "11.234", "sensor.house_temperature": "19.46", "input_number.target_temperature": "19.5",
    "sensor.lights_on": "3", "sensor.house_health_state": "ok", "weather.forecast_home": "partlycloudy",
    "sensor.boiler": "Heating now", "binary_sensor.boiler_heating": "on", "input_number.panel_boost_hours": "2",
    "light.angle": "on", "light.key": "off", "light.living_room_light_light_1": "off",
    "sensor.room_temperature_living_room": "18.94", "input_text.ma_player": "media_player.venus",
}


@pytest.fixture
def house(monkeypatch):
    calls = []
    st = {k: {"entity_id": k, "state": v, "attributes": {}} for k, v in STATES.items()}
    st["climate.radiator_living_room_thermostat"] = {"state": "heat", "attributes": {"temperature": 20, "current_temperature": 18.5}}
    st["media_player.venus"] = {"state": "playing", "attributes": {"media_title": "Hey Jude", "media_artist": "The Beatles", "volume_level": 0.4, "friendly_name": "Venus"}}
    st["sensor.heating_boosts"] = {"state": "0", "attributes": {"boosts": []}}
    monkeypatch.setattr(ha, "states", lambda max_age=2.0: st)
    monkeypatch.setattr(ha, "call", lambda d, s, data=None: calls.append((d, s, data)) or [])
    monkeypatch.setattr(deploy, "skill_id", lambda: "golden-skill")
    return calls


@pytest.fixture(autouse=True)
def _house_not_reached(monkeypatch):
    """These must never set a real timer: ha.alert goes to the house's own Home Assistant when run on it."""
    def refuse(*a, **k):
        raise RuntimeError("no house in tests")
    monkeypatch.setattr(ha, "alert", refuse)
    monkeypatch.setattr(ha, "ask_ai", refuse)
    monkeypatch.setattr(ha, "play_this", refuse)
    monkeypatch.setattr(ha, "good_morning", refuse)
    monkeypatch.setattr(ha, "room_bump", refuse)


def run(req_type, intent=None, extra=None, iface=SHOW, slots=None, new=True):
    ev = build_event(req_type, intent, extra or {}, new, iface, "en-GB")
    if slots:
        ev["request"]["intent"]["slots"] = {k: {"name": k, "value": v} for k, v in slots.items()}
    out = handlers.build().invoke(_env(ev), None)
    return json.loads(json.dumps(_ser(out)))


def _env(ev):
    from ask_sdk_core.serialize import DefaultSerializer
    from ask_sdk_model import RequestEnvelope
    return DefaultSerializer().deserialize(json.dumps(ev), RequestEnvelope)


def _ser(out):
    from ask_sdk_core.serialize import DefaultSerializer
    return DefaultSerializer().serialize(out)


def test_launch_draws_home_and_leaves_the_mic_off(house):
    r = run("LaunchRequest")["response"]
    d = r["directives"][0]
    assert d["type"] == "Alexa.Presentation.APL.RenderDocument"
    assert "shouldEndSession" not in r   # screen up, no microphone
    text = json.dumps(d["document"], ensure_ascii=False)
    assert "19.5°" in text and "11.2°" in text and "Hey Jude" in text


def test_every_page_draws(house):
    for p in pages.PAGES:
        doc = pages.render(p)
        assert doc["type"] == "APL" and json.dumps(doc)


def test_tap_room_lights_toggles_and_redraws(house):
    r = run("Alexa.Presentation.APL.UserEvent", extra={"arguments": ["act", "room_lights", "Living room"], "source": {}, "token": "myhouse"})["response"]
    assert house[-1] == ("light", "turn_off", {"entity_id": ["light.angle", "light.living_room_light_light_1", "light.key"]})   # one was on → off
    assert r["directives"][0]["type"] == "Alexa.Presentation.APL.RenderDocument" and "outputSpeech" not in r


@pytest.fixture
def bump(monkeypatch):
    """script.heating_room_bump stood in for: what was asked, and the house's answer (as the real script words it)."""
    asked = []

    def fake(room, by=None, dur=None, way="up"):
        asked.append({"room": room, "by": by, "dur": dur, "way": way})
        if room in ("bathroom",):
            return {"ok": False, "say": "The bathroom has no radiator I can control."}
        return {"ok": True, "say": f"Boosting the {room} by {by or 1} degrees.", "temps": [22.0]}
    monkeypatch.setattr(ha, "room_bump", fake)
    return asked


def _slots(**kw):
    """slots with Alexa's own resolution ("lounge" -> "living room"): {name: (said, resolved or None)}"""
    out = {}
    for k, (said, res) in kw.items():
        out[k] = {"name": k, "value": said}
        if res:
            out[k]["resolutions"] = {"resolutionsPerAuthority": [{"authority": "x", "status": {"code": "ER_SUCCESS_MATCH"},
                                                                  "values": [{"value": {"name": res, "id": res}}]}]}
    return out


def run_slots(intent, iface=SHOW, new=True, **kw):
    ev = build_event("IntentRequest", intent, {}, new, iface, "en-GB")
    ev["request"]["intent"]["slots"] = _slots(**kw)
    return json.loads(json.dumps(_ser(handlers.build().invoke(_env(ev), None))))


def test_voice_boost_living_room(house, bump):
    # (9 Nov 2026: one room, by n degrees, for a while - the house's script.heating_room_bump does it and words the answer)
    r = run("IntentRequest", "BoostIntent", slots={"room": "lounge"})["response"]
    assert bump == [{"room": "lounge", "by": None, "dur": None, "way": "up"}]
    assert "Boosting the lounge by 1 degrees." in r["outputSpeech"]["ssml"]
    assert not [c for c in house if c[1] == "heating_boost"]   # (never the radiators straight from the skill)


def test_boost_by_and_for(house, bump):
    run_slots("BoostIntent", room=("Beau's room", "beau bedroom"), by=("2", None), dur=("PT30M", None))
    assert bump[-1] == {"room": "beau bedroom", "by": "2", "dur": "PT30M", "way": "up"}
    run_slots("BoostIntent", room=("the kitchen", "kitchen"), dur=("PT1H", None), way=("increase", "up"))
    assert bump[-1] == {"room": "kitchen", "by": None, "dur": "PT1H", "way": "up"}


def test_turn_down(house, bump):
    run_slots("BoostIntent", room=("bedroom", "bedroom"), by=("1", None), way=("turn down", "down"))
    assert bump[-1]["way"] == "down" and bump[-1]["by"] == "1"
    run_slots("BoostIntent", room=("study", "lewis study"), way=("colder", None))   # (said, not resolved: still down)
    assert bump[-1] == {"room": "lewis study", "by": None, "dur": None, "way": "down"}


def test_boost_no_radiator_room_says_so(house, bump):
    r = run_slots("BoostIntent", room=("bathroom", "bathroom"))["response"]
    assert "no radiator" in r["outputSpeech"]["ssml"]


def test_boost_on_the_moon_keeps_the_panel(house, bump):
    # (inside the open panel: said, no page drawn over it, session kept - no shouldEndSession)
    r = run_slots("BoostIntent", iface=MOON, new=False, room=("kitchen", "kitchen"), by=("2", None))["response"]
    assert "Boosting the kitchen by 2 degrees." in r["outputSpeech"]["ssml"]
    assert r.get("shouldEndSession") is not True and not r.get("directives")
    # (no room said on the Moon: the Moon's own room, the kitchen)
    run_slots("BoostIntent", iface=MOON, new=False, way=("turn up", "up"))
    assert bump[-1]["room"] == "kitchen"


def test_boost_one_shot_ends(house, bump):
    # ("Alexa, ask Peach Banana to boost the living room by 2 degrees" on an Echo without a screen / with the panel shut: said, ended)
    r = run_slots("BoostIntent", iface=DOT, room=("living room", "living room"), by=("2", None))["response"]
    assert r["shouldEndSession"] is True and "living room" in r["outputSpeech"]["ssml"]
    r = run_slots("BoostIntent", iface=MOON, new=True, room=("library", "library"))["response"]
    assert r["shouldEndSession"] is True and "library" in r["outputSpeech"]["ssml"]
    # (no room on another Echo: "here" - the house takes the room of the Echo just spoken to)
    run_slots("BoostIntent", iface=DOT, way=("up", "up"))
    assert bump[-1]["room"] == "here"


def test_boost_house_down(house, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(ha, "room_bump", broken)
    r = run_slots("BoostIntent", iface=DOT, room=("kitchen", "kitchen"))["response"]
    assert "didn't answer" in r["outputSpeech"]["ssml"] and r["shouldEndSession"] is True


def test_boost_model_samples():
    I = {i["name"]: i for i in model.interaction_model()["interactionModel"]["languageModel"]["intents"]}
    b = I["BoostIntent"]
    assert [x["name"] for x in b["slots"]] == ["room", "by", "dur", "way"]
    said = set(b["samples"])
    for s in ["boost the {room}", "boost the {room} by {by} degrees for {dur}", "{way} the temperature in the {room} by {by} degrees",
              "make it {way} in the {room}", "make the {room} {way} for {dur}", "turn the heating {way} in the {room} by {by} degree",
              "boost the heating"]:
        assert s in said, s
    # (9 Nov 11:18 "increase the temperature in the living room by two degrees" went to TemperatureIntent; "make it hotter in the
    #  living room" to EndBoostIntent - both now have their own BoostIntent sample)
    assert "{way} the temperature in the {room} by {by} degrees" in said and "make it {way} in the {room}" in said
    ways = next(t for t in model.interaction_model()["interactionModel"]["languageModel"]["types"] if t["name"] == "HEAT_WAY")["values"]
    assert {v["name"]["value"] for v in ways} == {"up", "down"}
    from myhouse.house import room
    assert room("upstairs") == "Upper hallway" and room("downstairs loo") == "Downstairs bathroom" and room("beau room") == "Beau bedroom"


def test_hallway_is_two_rooms_and_hallway_means_both(house):
    # (8 Nov 2026: the hallway split into Lower and Upper hallway, each its own radiator and thermometer)
    from myhouse.house import room, rooms
    assert room("landing") == "Upper hallway" and room("hall") == "Lower hallway" and room("downstairs hall") == "Lower hallway"
    assert room("upstairs hall") == "Upper hallway" and room("front hall") == "Lower hallway"
    assert rooms("hallway") == ["Lower hallway", "Upper hallway"] and rooms("the hallway lights") == ["Lower hallway", "Upper hallway"]
    assert rooms("lower hallway") == ["Lower hallway"]
    st = ha.states()
    st["sensor.room_temperature_lower_hallway"] = {"state": "18.1", "attributes": {}}
    st["sensor.room_temperature_upper_hallway"] = {"state": "17.8", "attributes": {}}
    # (a tap on the screen's Boost still boosts both halves, each 1 degree above its own temperature)
    actions.boost("hallway", toggle=False)
    assert ("script", "heating_boost", {"entity": "climate.radiator_lower_hallway_thermostat", "temp": 19.0, "hours": 2.0}) in house
    assert ("script", "heating_boost", {"entity": "climate.radiator_upper_hallway_thermostat", "temp": 19.0, "hours": 2.0}) in house
    house.clear()
    actions.boost("landing", toggle=False)
    assert [c[2]["entity"] for c in house if c[1] == "heating_boost"] == ["climate.radiator_upper_hallway_thermostat"]
    assert actions.temperature("hallway") == "The lower hallway is 18.1 degrees. The upper hallway is 17.8 degrees."
    actions.room_lights("hallway", on=False)
    assert house[-1] == ("light", "turn_off", {"entity_id": ["light.door", "light.hallway_lower", "light.a_upper_hallway_light"]})
    vals = [v["name"]["value"] for v in next(t for t in model.interaction_model()["interactionModel"]["languageModel"]["types"] if t["name"] == "ROOM")["values"]]
    assert "lower hallway" in vals and "upper hallway" in vals and "hallway" in vals


def test_set_target_and_music(house):
    run("IntentRequest", "SetTargetIntent", slots={"temp": "21"})
    assert ("input_number", "set_value", {"entity_id": "input_number.target_temperature", "value": 21.0}) in house
    run("IntentRequest", "MusicIntent", slots={"act": "pause"})
    assert house[-1][1] == "media_pause"


def test_no_screen_just_speaks_and_ends(house):
    r = run("LaunchRequest", iface=DOT)["response"]
    assert r["shouldEndSession"] is True and "19.5" in r["outputSpeech"]["ssml"] and not r.get("directives")


def test_other_skills_are_refused(house, monkeypatch):
    monkeypatch.setattr(deploy, "skill_id", lambda: "amzn1.ask.skill.someone-else")
    r = run("LaunchRequest")["response"]
    assert r["shouldEndSession"] is True and not r.get("directives")


def test_voice_model_rooms_and_invocation():
    m = model.interaction_model()["interactionModel"]["languageModel"]
    assert m["invocationName"] == "peach banana"
    rooms = next(t for t in m["types"] if t["name"] == "ROOM")["values"]
    assert {"name": {"value": "living room", "synonyms": ["lounge", "sitting room", "front room"]}} in rooms


def test_root_endpoint_hands_cat_ballou_requests_to_it(client, house, monkeypatch):
    # Peach Banana shares the music skill's address: a request with its skill id goes to the house skill
    from app import app as flask_app
    monkeypatch.setitem(flask_app.config, "ASK_VERIFY_REQUEST_SIGNATURE", False)
    monkeypatch.setitem(flask_app.config, "ASK_VERIFY_REQUEST_TIMESTAMP", False)
    seen = []
    adapter = flask_app.extensions["myhouse_adapter"]
    monkeypatch.setattr(adapter, "dispatch_request", lambda: seen.append(1) or "{}")
    ev = build_event("LaunchRequest", None, {}, True, SHOW, "en-GB")
    ev["context"]["System"]["application"]["applicationId"] = "golden-skill"
    client.post("/", json=ev)
    assert seen == [1]


def test_heating_settings_page_and_its_controls(house):
    doc = json.dumps(pages.render("hsettings"), ensure_ascii=False)
    assert "Heating settings" in doc and "Winter" in doc and "Boost length" in doc and "Morning temp" in doc
    actions.do("hmode", "off")
    assert ("input_boolean", "turn_on", {"entity_id": "input_boolean.heating_force_off"}) in house
    actions.do("set_day_t", "20.5")
    assert ("input_number", "set_value", {"entity_id": "input_number.core_heating_temperature", "value": 20.5}) in house
    actions.do("set_on_time", "06:45:00")
    assert ("input_datetime", "set_datetime", {"entity_id": "input_datetime.heating_on_time", "time": "06:45:00"}) in house
    actions.do("set_winter_start", "2026-11-08")
    assert house[-1] == ("input_datetime", "set_datetime", {"entity_id": "input_datetime.winter_start", "date": "2026-11-08"})


def test_launch_opens_the_whole_control_panel_when_the_show_can(house, monkeypatch):
    from myhouse import signin
    monkeypatch.setattr(signin, "_opts", lambda: {"catballou_ha_password": "pw", "catballou_ha_url": "https://ha.example"})
    monkeypatch.setattr(signin, "code", lambda: "CODE1")
    iface = {**SHOW, "Alexa.Presentation.HTML": {"runtime": {"maxVersion": "1.1"}}}
    r = run("LaunchRequest", iface=iface)["response"]
    d = r["directives"][0]
    assert d["type"] == "Alexa.Presentation.HTML.Start" and d["request"]["uri"].startswith("https://ha.example/local/catballou.html?v=")
    assert d["data"]["code"] == "CODE1" and d["data"]["page"] == "home" and d["data"]["state"]
    monkeypatch.setattr(signin, "_opts", lambda: {})   # no password set: the drawn screens instead (a Show without the web app)
    assert run("LaunchRequest", iface=SHOW)["response"]["directives"][0]["type"] == "Alexa.Presentation.APL.RenderDocument"


def test_widget_packages_and_install_message(house, monkeypatch):
    from myhouse import widgets
    files = widgets.packages(["en-GB"])
    for wid in ("CentralControl", "PeachBanana"):
        m = json.loads(files[f"skill-package/dataStorePackages/{wid}/manifest.json"])
        assert m["manifest"]["id"] == wid and m["publishingInformation"]["locales"]["en-GB"][0]["targetViewport"] == "WIDGET_M"
        doc = json.loads(files[f"skill-package/dataStorePackages/{wid}/documents/document.json"])
        assert doc["extensions"][0]["uri"] == "alexaext:datastore:10" and "openPage" in json.dumps(doc)
    pushed = []
    monkeypatch.setattr(widgets, "push", lambda uid, force=False: pushed.append((uid, force)))
    saved = {}
    monkeypatch.setattr(deploy, "_load", lambda: dict(saved))
    monkeypatch.setattr(deploy, "_save", lambda d: saved.update(d))
    ev = build_event("Alexa.DataStore.PackageManager.UsagesInstalled", None,
                     {"payload": {"packageId": "CentralControl", "packageVersion": "1.0.0", "usages": [{"instanceId": "x", "location": "FAVORITE"}]}}, True, SHOW, "en-GB")
    run_ev = handlers.build().invoke(_env(ev), None)
    assert saved.get("user_id") == "golden-user" and pushed == [("golden-user", True)]
    # a widget tap opens the page (drawn screens when no web app)
    r = run("Alexa.Presentation.APL.UserEvent", extra={"arguments": ["openPage", "hsettings"], "source": {}, "token": "x"})["response"]
    assert "Heating settings" in json.dumps(r, ensure_ascii=False)


def _handoff(calls):
    return [c[2]["variables"] for c in calls if c[:2] == ("script", "turn_on") and c[2]["entity_id"] == "script.peach_banana_handoff"]


@pytest.fixture
def alerts_refused(monkeypatch):
    from myhouse import alerts
    monkeypatch.setattr(alerts, "_post", lambda *a: False)


@pytest.fixture
def alerts_ok(monkeypatch):
    from myhouse import alerts
    sent = []
    monkeypatch.setattr(alerts, "_post", lambda h, path, body: sent.append((path, body)) or True)
    return sent


def test_timer_set_directly_keeps_the_panel_open(house, alerts_ok):
    r = run("IntentRequest", "TimerIntent", slots={"dur": "PT5M"})["response"]
    assert not r.get("shouldEndSession") and "5 minutes" in r["outputSpeech"]["ssml"] and not _handoff(house)
    assert alerts_ok[0][0] == "/v1/alerts/timers" and alerts_ok[0][1]["duration"] == "PT5M"


def test_alarm_set_directly_says_it_wont_ring(house, alerts_ok):
    r = run("IntentRequest", "AlarmIntent", slots={"time": "07:30"})["response"]
    assert not r.get("shouldEndSession") and "rather than ring" in r["outputSpeech"]["ssml"] and not _handoff(house)
    assert alerts_ok[0][1]["trigger"]["timeZoneId"] == "Europe/London" and "T07:30:00" in alerts_ok[0][1]["trigger"]["scheduledTime"]


def _alerts(monkeypatch, left=(), al=()):
    from myhouse import alerts
    deleted = []
    monkeypatch.setattr(alerts, "timers_left", lambda h, now=None: list(left))
    monkeypatch.setattr(alerts, "alarms_set", lambda h: list(al))
    monkeypatch.setattr(alerts, "_call", lambda h, m, p: deleted.append((m, p)) or {})
    return deleted


def test_how_long_is_left_answered_here(house, monkeypatch):
    _alerts(monkeypatch, left=[250], al=[("a", "2026-10-31T07:30:00.000")])
    r = run("IntentRequest", "TimerLeftIntent")["response"]
    assert "5 minutes left on a timer" in r["outputSpeech"]["ssml"] and "7:30 am" in r["outputSpeech"]["ssml"]
    assert not r.get("shouldEndSession") and not _handoff(house)


def _op(op, thing, ses=None):
    ev = build_event("IntentRequest", "AlarmOpIntent", {}, True, SHOW, "en-GB")
    ev["session"]["attributes"] = ses or {}
    ev["request"]["intent"]["slots"] = {k: {"name": k, "value": v, "resolutions": {"resolutionsPerAuthority": [{"authority": "x", "status": {"code": "ER_SUCCESS_MATCH"}, "values": [{"value": {"name": v, "id": v}}]}]}} for k, v in (("op", op), ("thing", thing))}
    return json.loads(json.dumps(_ser(handlers.build().invoke(_env(ev), None))))["response"]


def test_cancel_our_alarm_here_and_alexas_goes_to_alexa(house, monkeypatch):
    deleted = _alerts(monkeypatch, al=[("tok", "2026-10-31T07:30:00.000")])
    r = _op("cancel", "alarm")
    assert "cancelled 1 alarm" in r["outputSpeech"]["ssml"] and ("DELETE", "/v1/alerts/reminders/tok") in deleted and not _handoff(house)
    _alerts(monkeypatch)
    r = _op("cancel", "alarm")
    assert "no alarm set here" in r["outputSpeech"]["ssml"] and not r.get("shouldEndSession") and not _handoff(house)
    assert _op("cancel", "alarm", {"no_alert": True})["shouldEndSession"] is True and _handoff(house)[0]["text"] == "cancel my alarm"


def test_time_answered_here(house):
    r = run("IntentRequest", "TimeIntent")["response"]
    assert "It's" in r["outputSpeech"]["ssml"] and not r.get("shouldEndSession")


def test_time_goes_to_the_ai(house, monkeypatch):
    asked = []
    monkeypatch.setattr(ha, "ask_ai", lambda t, c="": asked.append(t) or {"ok": True, "answer": "It's twenty past seven.", "conversation_id": "c1"})
    r = run("IntentRequest", "TimeIntent")["response"]
    assert asked == ["what time is it"] and "twenty past seven" in r["outputSpeech"]["ssml"]


def test_alarm_time_is_the_next_one(house):
    from datetime import datetime
    from myhouse import alerts
    now = datetime(2026, 10, 30, 19, 0)
    assert alerts.next_time("19:02", now) == datetime(2026, 10, 30, 19, 2)
    assert alerts.next_time("07:30", now) == datetime(2026, 10, 31, 7, 30)
    assert alerts.next_time("MO", now) is None


def test_alarm_said_with_the_panel_open_goes_to_alexa_and_comes_back(house, alerts_refused):
    r = run("IntentRequest", "AlarmIntent", slots={"time": "07:30"})["response"]
    assert r["shouldEndSession"] is True   # (the web app closes - Alexa has the Echo)
    v = _handoff(house)
    assert v and v[0]["text"] == "set an alarm for 7:30 am" and v[0]["back_after"] == 12


def test_timer_duration_in_words(house, alerts_refused):
    run("IntentRequest", "TimerIntent", slots={"dur": "PT1H5M"})
    assert _handoff(house)[0]["text"] == "set a timer for 1 hour 5 minutes"
    assert handlers._duration("PT30S") == "30 seconds" and handlers._duration("nonsense") is None
    assert handlers._clock("19:00") == "7 pm" and handlers._clock("00:15") == "12:15 am"


def test_fallback_asks_again_once_then_hands_over(house):
    r = run("IntentRequest", "AMAZON.FallbackIntent")
    assert not r["response"].get("shouldEndSession") and r["sessionAttributes"]["asked_again"] and not _handoff(house)
    ev = build_event("IntentRequest", "AMAZON.FallbackIntent", {}, True, SHOW, "en-GB")
    ev["session"]["attributes"] = {"asked_again": True}
    r = json.loads(json.dumps(_ser(handlers.build().invoke(_env(ev), None))))["response"]
    assert r["shouldEndSession"] is True and "say that again" in r["outputSpeech"]["ssml"]
    v = _handoff(house)
    assert v[0]["text"] == "" and v[0]["back_after"] == 60


def test_unmatched_page_tries_the_ai_first(house, monkeypatch):
    asked = []
    monkeypatch.setattr(ha, "ask_ai", lambda t, c="": asked.append(t) or {"ok": True, "answer": "Yes", "conversation_id": ""})
    ev = build_event("IntentRequest", "ShowPageIntent", {}, True, SHOW, "en-GB")
    ev["request"]["intent"]["slots"] = {"page": {"name": "page", "value": "some bananas", "resolutions": {"resolutionsPerAuthority": [
        {"authority": "x", "status": {"code": "ER_SUCCESS_NO_MATCH"}}]}}}
    out = json.loads(json.dumps(_ser(handlers.build().invoke(_env(ev), None))))
    assert asked == ["some bananas"] and not out["response"].get("shouldEndSession") and not _handoff(house)


def test_model_has_the_alexa_jobs():
    names = {i["name"] for i in model.interaction_model()["interactionModel"]["languageModel"]["intents"]}
    assert {"AlarmIntent", "TimerIntent", "AlarmOpIntent", "AMAZON.FallbackIntent"} <= names


def _said(r):
    return r["response"]["outputSpeech"]["ssml"]


def test_ask_ai_puts_the_opening_back_and_stays_open(house, monkeypatch):
    asked = []
    monkeypatch.setattr(ha, "ask_ai", lambda t, c="": asked.append(t) or {"ok": True, "answer": "**Fish** & chips", "conversation_id": "chat1"})
    r = run("IntentRequest", "AskTellIntent", slots={"q": "a joke"})
    assert asked == ["tell me a joke"]
    assert "Fish &amp; chips" in _said(r)
    assert not r["response"].get("shouldEndSession")
    assert r["sessionAttributes"]["ai_chat"] == "chat1"


def test_ask_ai_off_gives_alexa_the_words(house, monkeypatch):
    monkeypatch.setattr(ha, "ask_ai", lambda t, c="": {"ok": False, "why": "off", "answer": ""})
    said = []
    monkeypatch.setattr(handlers, "hand_off", lambda hi, text=None: said.append(text) or hi.response_builder.response)
    run("IntentRequest", "AskWhyIntent", slots={"q": "is the sky blue"})
    assert said == ["why is the sky blue"]


def test_ask_ai_too_slow_keeps_the_panel(house, monkeypatch):
    def slow(t, c=""):
        raise TimeoutError
    monkeypatch.setattr(ha, "ask_ai", slow)
    r = run("IntentRequest", "AskIntent", slots={"q": "anything"})
    assert "didn't answer" in _said(r).replace("&#x27;", "'")
    assert not r["response"].get("shouldEndSession")


def test_model_has_the_ask_intents():
    names = {i["name"]: i for i in model.interaction_model()["interactionModel"]["languageModel"]["intents"]}
    for n in model.ASK_INTENTS:
        assert names[n]["slots"][0]["type"] == "AMAZON.SearchQuery"


def test_every_question_opening_reaches_the_ai():
    said = [s for _w, samples in model.ASK_INTENTS.values() for s in samples]
    for s in ["what {q}", "does {q}", "is {q}", "can {q}", "give me {q}"]:
        assert s in said
    assert len(said) == len(set(said))


def test_house_keeps_the_timer_when_alexa_refuses(house, alerts_refused, monkeypatch):
    got = []
    monkeypatch.setattr(ha, "alert", lambda action, kind="", at=0, secs=0: got.append((action, kind, at, secs)) or {"ok": True, "count": 1, "items": []})
    r = run("IntentRequest", "TimerIntent", slots={"dur": "PT12M"})["response"]
    assert "12 minutes" in r["outputSpeech"]["ssml"] and not r.get("shouldEndSession") and not _handoff(house)
    assert got[0][:2] == ("set", "timer") and got[0][2] > 1e9 and got[0][3] == 720
    assert "cancelled 1 timer" in _op("cancel", "timer")["outputSpeech"]["ssml"] and not _handoff(house)


def test_a_timer_with_no_length_is_asked_about(house):
    r = run("IntentRequest", "TimerIntent")["response"]
    assert "How long" in r["outputSpeech"]["ssml"] and not r.get("shouldEndSession") and not _handoff(house)
    r = run("IntentRequest", "AlarmIntent")["response"]
    assert "What time" in r["outputSpeech"]["ssml"] and not _handoff(house)


def test_play_this_goes_to_the_house_and_stays_open(house, monkeypatch):
    asked = []
    monkeypatch.setattr(ha, "play_this", lambda t, ma_player_id=None: asked.append(t) or {"ok": True, "name": "Born to Run", "kind": "album"})
    r = run("IntentRequest", "PlayThisIntent", slots={"what": "born to run"}, iface=MOON, new=False)["response"]   # (the panel open)
    assert asked == ["born to run"] and "Playing Born to Run" in r["outputSpeech"]["ssml"] and not r.get("shouldEndSession") and not _handoff(house)


def test_stop_stops_the_music_and_keeps_the_panel(house, monkeypatch):
    done = []
    monkeypatch.setattr(handlers, "_music_playing", lambda: True)
    monkeypatch.setattr(actions, "music", lambda a: done.append(a))
    r = run("IntentRequest", "AMAZON.StopIntent")["response"]
    assert done == ["pause"] and not r.get("shouldEndSession")
    monkeypatch.setattr(handlers, "_music_playing", lambda: False)
    # (9 Nov 2026: said again with nothing playing, it no longer closes - only "close Peach Banana" does)
    assert "shouldEndSession" not in run("IntentRequest", "AMAZON.StopIntent")["response"]


# "ALEXA, STOP" TRAPPED (the user, 9 Nov 2026: "can't you trap that and interpret better?") - golden responses on the Moon
# (an Echo Show with the panel's web app): stop / cancel / pause / be quiet stop what the house is sounding, the panel stays.
HUSH = ["AMAZON.StopIntent", "AMAZON.CancelIntent", "AMAZON.PauseIntent", "QuietIntent"]


@pytest.fixture
def journal(monkeypatch):
    lines = []
    monkeypatch.setattr(ha, "journal", lambda body: lines.append(body))
    monkeypatch.setattr(ha, "hush", lambda: {"stopped": False, "what": "nothing"})
    return lines


@pytest.mark.parametrize("intent", HUSH)
def test_stop_with_music_playing_pauses_it_and_keeps_the_panel(house, monkeypatch, journal, intent):
    done = []
    monkeypatch.setattr(handlers, "_music_playing", lambda: True)
    monkeypatch.setattr(actions, "music", lambda a: done.append(a))
    out = run("IntentRequest", intent, iface=MOON, new=False)
    assert out["response"] == {}   # (golden: no words, no directives, no shouldEndSession - the panel up, the microphone off)
    assert done == ["pause"] and journal == [{"type": "stop-trapped", "intent": intent, "did": "music"}]


@pytest.mark.parametrize("intent", HUSH)
def test_stop_with_nothing_playing_does_nothing_and_keeps_the_panel(house, monkeypatch, journal, intent):
    monkeypatch.setattr(handlers, "_music_playing", lambda: False)
    monkeypatch.setattr(actions, "music", lambda a: pytest.fail("nothing to pause"))
    out = run("IntentRequest", intent, iface=MOON, new=False)
    assert out["response"] == {}
    assert not [c for c in house if c[0] == "media_player"] and journal[-1]["did"] == "nothing"


def test_stop_stops_the_house_s_timer_or_alarm_first(house, monkeypatch, journal):
    monkeypatch.setattr(ha, "hush", lambda: {"stopped": True, "what": "alert"})
    monkeypatch.setattr(handlers, "_music_playing", lambda: True)
    monkeypatch.setattr(actions, "music", lambda a: pytest.fail("the music carries on after the alarm"))
    out = run("IntentRequest", "AMAZON.StopIntent", iface=MOON, new=False)
    assert out["response"] == {} and journal[-1]["did"] == "alert"


def test_stop_pauses_an_announcement_on_the_moon_screen(house, monkeypatch, journal):
    monkeypatch.setattr(handlers, "_music_playing", lambda: False)
    st = ha.states()
    st["media_player.the_moon_screen"] = {"entity_id": "media_player.the_moon_screen", "state": "playing", "attributes": {}}
    out = run("IntentRequest", "AMAZON.StopIntent", iface=MOON, new=False)
    assert out["response"] == {} and ("media_player", "media_pause", {"entity_id": "media_player.the_moon_screen"}) in house
    assert journal[-1]["did"] == "screen"


def test_stop_survives_the_house_not_answering(house, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(ha, "hush", boom)
    monkeypatch.setattr(ha, "journal", boom)
    monkeypatch.setattr(handlers, "_music_playing", lambda: False)
    assert run("IntentRequest", "AMAZON.StopIntent", iface=MOON, new=False)["response"] == {}


def test_stop_the_alarm_while_the_house_s_is_sounding(house, monkeypatch, journal):
    monkeypatch.setattr(ha, "hush", lambda: {"stopped": True, "what": "alert"})
    res = {"status": {"code": "ER_SUCCESS_MATCH"}}
    ev_slots = {"op": {"name": "op", "value": "stop", "resolutions": {"resolutionsPerAuthority": [{**res, "values": [{"value": {"name": "stop", "id": "stop"}}]}]}},
                "thing": {"name": "thing", "value": "alarm", "resolutions": {"resolutionsPerAuthority": [{**res, "values": [{"value": {"name": "alarm", "id": "alarm"}}]}]}}}
    ev = build_event("IntentRequest", "AlarmOpIntent", {}, False, MOON, "en-GB")
    ev["request"]["intent"]["slots"] = ev_slots
    r = json.loads(json.dumps(_ser(handlers.build().invoke(_env(ev), None))))["response"]
    assert r == {} and journal[-1] == {"type": "stop-trapped", "intent": "AlarmOpIntent stop", "did": "alert"}


def test_close_peach_banana_ends_it(house, journal):
    r = run("IntentRequest", "ExitIntent", iface=MOON, new=False)["response"]
    assert r["shouldEndSession"] is True and "Closing Peach Banana" in r["outputSpeech"]["ssml"]
    assert journal == [{"type": "exit", "intent": "ExitIntent"}]


def test_stop_on_an_echo_without_a_screen_still_ends(house, monkeypatch, journal):
    monkeypatch.setattr(handlers, "_music_playing", lambda: False)
    assert run("IntentRequest", "AMAZON.StopIntent", iface={})["response"]["shouldEndSession"] is True


def test_quiet_and_exit_are_in_the_model():
    I = model.interaction_model()["interactionModel"]["languageModel"]["intents"]
    names = {i["name"]: i for i in I}
    assert "be quiet" in names["QuietIntent"]["samples"] and "close peach banana" in names["ExitIntent"]["samples"]
    assert not any("exit" in x.split() for x in names["ExitIntent"]["samples"])   # (Amazon keeps "exit" itself)
    seen = {}
    for i in I:   # (Amazon refuses a model with the same sample in two intents)
        for x in i.get("samples", []):
            assert seen.setdefault(x.lower(), i["name"]) == i["name"], (x, seen[x.lower()], i["name"])


def test_good_morning_is_the_house_s_and_stays_open(house, monkeypatch):
    monkeypatch.setattr(ha, "good_morning", lambda: {"say": "Good morning. It's twenty past seven. Here's Radio 4."})
    r = run("IntentRequest", "GoodMorningIntent")["response"]
    assert "Here's Radio 4" in r["outputSpeech"]["ssml"] and not r.get("shouldEndSession") and not _handoff(house)


def test_good_morning_without_the_house_still_says_the_time(house, monkeypatch):
    def boom():
        raise OSError("no")
    monkeypatch.setattr(ha, "good_morning", boom)
    r = run("IntentRequest", "GoodMorningIntent")["response"]
    assert "Good morning" in r["outputSpeech"]["ssml"] and "didn't answer" in r["outputSpeech"]["ssml"]


def test_good_morning_is_in_the_model():
    from myhouse import model as m
    names = [i["name"] for i in m.interaction_model()["interactionModel"]["languageModel"]["intents"]]
    assert "GoodMorningIntent" in names


def test_turn_on_the_lights_is_not_music(house, monkeypatch):
    monkeypatch.setattr(ha, "play_this", lambda t: (_ for _ in ()).throw(AssertionError("played music")))
    monkeypatch.setattr(actions, "room_lights", lambda r, on=None: "Kitchen lights on.")
    r = run("IntentRequest", "PlayThisIntent", slots={"what": "the kitchen lights"})["response"]
    assert "Kitchen lights on" in r["outputSpeech"]["ssml"]


def test_turn_on_radio_is_played(house, monkeypatch):
    asked = []
    monkeypatch.setattr(ha, "play_this", lambda t, ma_player_id=None: asked.append(t) or {"ok": True, "name": "BBC Radio 4", "kind": "radio"})
    r = run("IntentRequest", "PlayThisIntent", slots={"what": "radio four"}, iface=MOON, new=False)["response"]
    assert asked == ["radio four"] and "Playing BBC Radio 4" in r["outputSpeech"]["ssml"]


def test_turn_on_is_in_the_model():
    from myhouse import model as m
    pt = [i for i in m.interaction_model()["interactionModel"]["languageModel"]["intents"] if i["name"] == "PlayThisIntent"][0]
    assert "turn on {what}" in pt["samples"] and "tune in to {what}" in pt["samples"]


def test_full_panel_is_never_covered(house, monkeypatch):
    """on an HTML device (the web-app panel open) an answer speaks and turns the panel's page - no APL RenderDocument"""
    from myhouse import handlers as H
    monkeypatch.setattr(H, "_html", lambda hi: True)
    monkeypatch.setattr(actions, "room_lights", lambda r, on=None: "Kitchen lights on.")
    r = run("IntentRequest", "LightsOnIntent", slots={"room": "kitchen"})["response"]
    assert not any((d.get("type") or "").startswith("Alexa.Presentation.APL") for d in (r.get("directives") or []))


def test_listening_window_only_when_quiet(house, monkeypatch):
    from myhouse import handlers as H
    states = {"input_boolean.peach_listen": "on", "media_player.the_moon_screen": "idle"}
    monkeypatch.setattr(ha, "state", lambda e, d=None: states.get(e, d))
    r = run("IntentRequest", "TimeIntent")["response"]
    assert r.get("shouldEndSession") is False
    assert not r.get("reprompt")   # (a silent reprompt is refused by Amazon: "SSML does not contain any speech content")
    states["media_player.the_moon_screen"] = "playing"
    r = run("IntentRequest", "TimeIntent")["response"]
    assert not r.get("reprompt") and r.get("shouldEndSession") is not False


def test_good_morning_no_listening_window(house, monkeypatch):
    """6 Nov 2026: "Alexa, good morning" -> "a problem with the requested skill's response" (the silent reprompt). Radio 4 is
    starting, so no listening window at all - and never a reprompt."""
    states = {"input_boolean.peach_listen": "on", "media_player.the_moon_screen": "idle"}
    monkeypatch.setattr(ha, "state", lambda e, d=None: states.get(e, d))
    r = run("IntentRequest", "GoodMorningIntent")["response"]
    assert "Good morning" in r["outputSpeech"]["ssml"]
    assert not r.get("reprompt") and r.get("shouldEndSession") is not False


def test_shopping_add_goes_to_alexas_list(house, monkeypatch):
    got = []
    monkeypatch.setattr(ha, "shopping", lambda op, item: got.append((op, item)) or {"ok": True, "item": item})
    r = run("IntentRequest", "ShoppingAddIntent", slots={"item": "vegetarian suet"})["response"]
    assert got == [("add", "vegetarian suet")] and "put vegetarian suet on your shopping list" in r["outputSpeech"]["ssml"]


def test_shopping_remove_not_there(house, monkeypatch):
    monkeypatch.setattr(ha, "shopping", lambda op, item: {"ok": False, "item": item})
    r = run("IntentRequest", "ShoppingRemoveIntent", slots={"item": "milk"})["response"]
    assert "isn't on your shopping list" in r["outputSpeech"]["ssml"]


def test_shopping_in_the_model():
    from myhouse import model as m
    names = {i["name"]: i for i in m.interaction_model()["interactionModel"]["languageModel"]["intents"]}
    assert "put {item} on the shopping list" in names["ShoppingAddIntent"]["samples"]
    assert "take {item} off my shopping list" in names["ShoppingRemoveIntent"]["samples"]


def test_more_things_go_to_the_ai(house, monkeypatch):
    """6 Nov 2026: "as many things as possible handled by the Peach Banana AI"."""
    asked = []
    monkeypatch.setattr(ha, "ask_ai", lambda t, c="": asked.append(t) or {"ok": True, "answer": "Here you go.", "conversation_id": "c"})
    run("IntentRequest", "AskWhoOpenIntent", slots={"q": "invented the telephone"})
    run("IntentRequest", "AskThingIntent", slots={"asked": "joke"})
    run("IntentRequest", "AskThingIntent", slots={"asked": "news"})
    assert asked == ["who invented the telephone", "tell me a joke", "what's in the news today"]


def test_model_fits():
    I = model.interaction_model()["interactionModel"]["languageModel"]["intents"]
    assert len(I) + sum(len(i.get("slots", [])) for i in I) <= 345   # (Amazon's limit: 350 intents + slots)
    kinds = {}
    for i in I:
        for sl in i.get("slots", []):
            kinds.setdefault(sl["name"], set()).add(sl["type"])
    assert all(len(v) == 1 for v in kinds.values())   # (a slot name may have only one type across the model)
    said = [s.lower() for i in I for s in i.get("samples", [])]
    assert len(said) == len(set(said))


# (a number on its own sets the house target, clamped to the radiators' limits, and says so - the user, 8 Nov 2026)
@pytest.mark.parametrize("said,want", [("21", 21.0), ("22.5", 22.5), ("40", 30.0), ("9", 10.0), ("10", 10.0)])
def test_a_number_sets_the_target_clamped(house, monkeypatch, said, want):
    st = ha.states()
    st["input_number.target_temperature"] = {"state": "20", "attributes": {"min": 10, "max": 32}}
    st["climate.radiator_living_room_thermostat"]["attributes"].update({"min_temp": 5, "max_temp": 30})
    r = run("IntentRequest", "SetTargetIntent", slots={"temp": said})["response"]
    assert ("input_number", "set_value", {"entity_id": "input_number.target_temperature", "value": want}) in house
    assert f"setting the house temperature target to {want:.1f} degrees" in r["outputSpeech"]["ssml"].lower()


@pytest.mark.parametrize("said", ["5", "41", "100"])
def test_a_number_out_of_range_is_refused(house, said):
    r = run("IntentRequest", "SetTargetIntent", slots={"temp": said})["response"]
    assert not [c for c in house if c[:2] == ("input_number", "set_value")]
    assert "between 9 and 40" in r["outputSpeech"]["ssml"]


def test_voice_model_takes_a_bare_number():
    from myhouse import model
    it = next(i for i in model.interaction_model()["interactionModel"]["languageModel"]["intents"] if i["name"] == "SetTargetIntent")
    assert "{temp}" in it["samples"]


# (halves too - the user, 8 Nov 2026: "all numbers from 9 to 40 (integers and 0.5)")
@pytest.mark.parametrize("slots,want", [({"temp": "20", "tenth": "5"}, 20.5), ({"temp": "19", "half": "and a half"}, 19.5),
                                        ({"temp": "21", "tenth": "2"}, 21.0)])
def test_halves_set_the_target(house, slots, want):
    st = ha.states()
    st["input_number.target_temperature"] = {"state": "20", "attributes": {"min": 10, "max": 32}}
    r = run("IntentRequest", "SetTargetIntent", slots=slots)["response"]
    assert ("input_number", "set_value", {"entity_id": "input_number.target_temperature", "value": want}) in house
    assert f"setting the house temperature target to {want:.1f} degrees" in r["outputSpeech"]["ssml"].lower()
