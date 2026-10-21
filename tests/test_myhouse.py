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
