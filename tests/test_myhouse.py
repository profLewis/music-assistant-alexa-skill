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
    assert m["invocationName"] == "cat ballou"
    rooms = next(t for t in m["types"] if t["name"] == "ROOM")["values"]
    assert {"name": {"value": "living room", "synonyms": ["lounge", "sitting room"]}} in rooms


def test_root_endpoint_hands_cat_ballou_requests_to_it(client, house, monkeypatch):
    # Cat Ballou shares the music skill's address: a request with its skill id goes to the house skill
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
