"""Fork: MyHouse - the house on the Echo Show. The skill draws pages, keeps the screen up without the microphone,
and turns taps / voice into Home Assistant calls."""

import json

import pytest

from golden_cases import build_event
from myhouse import actions, deploy, ha, handlers, model, pages

SHOW = {"Alexa.Presentation.APL": {"runtime": {"maxVersion": "2023.2"}}}
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


def run(req_type, intent=None, extra=None, iface=SHOW, slots=None):
    ev = build_event(req_type, intent, extra or {}, True, iface, "en-GB")
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


def test_voice_boost_living_room(house):
    r = run("IntentRequest", "BoostIntent", slots={"room": "lounge"})["response"]
    assert ("script", "heating_boost", {"entity": "climate.radiator_living_room_thermostat", "temp": 20.0, "hours": 2.0}) in house
    assert "living room" in r["outputSpeech"]["ssml"].lower()


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
    assert {"name": {"value": "living room", "synonyms": ["lounge", "sitting room"]}} in rooms


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
    monkeypatch.setattr(signin, "_opts", lambda: {})   # no password set: the drawn screens instead
    assert run("LaunchRequest", iface=iface)["response"]["directives"][0]["type"] == "Alexa.Presentation.APL.RenderDocument"


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


def _op(op, thing):
    ev = build_event("IntentRequest", "AlarmOpIntent", {}, True, SHOW, "en-GB")
    ev["request"]["intent"]["slots"] = {k: {"name": k, "value": v, "resolutions": {"resolutionsPerAuthority": [{"authority": "x", "status": {"code": "ER_SUCCESS_MATCH"}, "values": [{"value": {"name": v, "id": v}}]}]}} for k, v in (("op", op), ("thing", thing))}
    return json.loads(json.dumps(_ser(handlers.build().invoke(_env(ev), None))))["response"]


def test_cancel_our_alarm_here_and_alexas_goes_to_alexa(house, monkeypatch):
    deleted = _alerts(monkeypatch, al=[("tok", "2026-10-31T07:30:00.000")])
    r = _op("cancel", "alarm")
    assert "cancelled 1 alarm" in r["outputSpeech"]["ssml"] and ("DELETE", "/v1/alerts/reminders/tok") in deleted and not _handoff(house)
    _alerts(monkeypatch)
    assert _op("cancel", "alarm")["shouldEndSession"] is True and _handoff(house)[0]["text"] == "cancel my alarm"


def test_time_answered_here(house):
    r = run("IntentRequest", "TimeIntent")["response"]
    assert "It's" in r["outputSpeech"]["ssml"] and not r.get("shouldEndSession")


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


def test_fallback_hands_over_and_asks_to_say_it_again(house):
    r = run("IntentRequest", "AMAZON.FallbackIntent")["response"]
    assert r["shouldEndSession"] is True and "say that again" in r["outputSpeech"]["ssml"]
    v = _handoff(house)
    assert v[0]["text"] == "" and v[0]["back_after"] == 60


def test_unmatched_page_is_not_ours(house):
    ev = build_event("IntentRequest", "ShowPageIntent", {}, True, SHOW, "en-GB")
    ev["request"]["intent"]["slots"] = {"page": {"name": "page", "value": "an alarm", "resolutions": {"resolutionsPerAuthority": [
        {"authority": "x", "status": {"code": "ER_SUCCESS_NO_MATCH"}}]}}}
    out = json.loads(json.dumps(_ser(handlers.build().invoke(_env(ev), None))))
    assert out["response"]["shouldEndSession"] is True and _handoff(house)


def test_model_has_the_alexa_jobs():
    names = {i["name"] for i in model.interaction_model()["interactionModel"]["languageModel"]["intents"]}
    assert {"AlarmIntent", "TimerIntent", "AlarmOpIntent", "AMAZON.FallbackIntent"} <= names
