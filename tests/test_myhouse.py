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


@pytest.fixture(autouse=True)
def _house_not_reached(monkeypatch):
    """These must never set a real timer: ha.alert goes to the house's own Home Assistant when run on it."""
    def refuse(*a, **k):
        raise RuntimeError("no house in tests")
    monkeypatch.setattr(ha, "alert", refuse)
    monkeypatch.setattr(ha, "ask_ai", refuse)
    monkeypatch.setattr(ha, "play_this", refuse)
    monkeypatch.setattr(ha, "good_morning", refuse)


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
    monkeypatch.setattr(ha, "play_this", lambda t: asked.append(t) or {"ok": True, "name": "Born to Run", "kind": "album"})
    r = run("IntentRequest", "PlayThisIntent", slots={"what": "born to run"})["response"]
    assert asked == ["born to run"] and "Playing Born to Run" in r["outputSpeech"]["ssml"] and not r.get("shouldEndSession") and not _handoff(house)


def test_stop_stops_the_music_and_keeps_the_panel(house, monkeypatch):
    done = []
    monkeypatch.setattr(handlers, "_music_playing", lambda: True)
    monkeypatch.setattr(actions, "music", lambda a: done.append(a))
    r = run("IntentRequest", "AMAZON.StopIntent")["response"]
    assert done == ["pause"] and not r.get("shouldEndSession")
    monkeypatch.setattr(handlers, "_music_playing", lambda: False)
    assert run("IntentRequest", "AMAZON.StopIntent")["response"]["shouldEndSession"] is True


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
    monkeypatch.setattr(ha, "play_this", lambda t: asked.append(t) or {"ok": True, "name": "BBC Radio 4", "kind": "radio"})
    r = run("IntentRequest", "PlayThisIntent", slots={"what": "radio four"})["response"]
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
    from app.myhouse import model
    it = next(i for i in model.interaction_model()["interactionModel"]["languageModel"]["intents"] if i["name"] == "SetTargetIntent")
    assert "{temp}" in it["samples"]
