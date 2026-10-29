"""Fork: the control panel inside the music skill on an Echo Show (screen_app.py)."""

import base64

import pytest

from golden_cases import build_event
from skill import lambda_function as handlers
from skill import screen_app

AUTH = {"Authorization": "Basic " + base64.b64encode(b"test-user:test-password").decode()}
HTML = {"AudioPlayer": {}, "Alexa.Presentation.APL": {}, "Alexa.Presentation.HTML": {"runtime": {"maxVersion": "1.1"}}}


@pytest.fixture(autouse=True)
def _forget_screens():
    """(the module's per-device state is process-wide: a panel left 'open' here strips other files' AudioPlayer replies)"""
    yield
    for d in (screen_app.OPEN, screen_app.ENDED, screen_app.STARTED, screen_app.SEEN, screen_app.FAILED, screen_app.HANDOFF):
        d.clear()


def _signin(monkeypatch):
    from myhouse import signin
    monkeypatch.setattr(signin, "_opts", lambda: {"catballou_ha_password": "pw", "catballou_ha_url": "https://ha.example"})
    monkeypatch.setattr(signin, "code", lambda: "CODE1")


def test_launch_opens_the_control_panel_and_play_keeps_it_open(client, monkeypatch):
    _signin(monkeypatch); screen_app.OPEN.clear()
    r = handlers.lambda_handler(build_event("LaunchRequest", None, {}, True, HTML, "en-GB"), None)["response"]
    assert [d["type"] for d in r["directives"]] == ["Alexa.Presentation.HTML.Start"] and not r.get("shouldEndSession")
    # MA's play arrives in the same session: it plays, and the page stays up
    client.post("/ma/push-url", json={"streamUrl": "https://ma.example.com/flow/s/The%20moon/x/The%20moon.mp3", "title": "Trouble"}, headers=AUTH)
    r = handlers.lambda_handler(build_event("IntentRequest", "PlayAudio", {}, False, HTML, "en-GB"), None)["response"]
    assert not r.get("directives") and not r.get("shouldEndSession")   # (the page plays it - Alexa's player isn't used)
    # the page's first message quits the music
    r = handlers.lambda_handler(build_event("Alexa.Presentation.HTML.Message", None, {"message": {"type": "stop-music"}}, False, HTML, "en-GB"), None)["response"]
    assert [d["type"] for d in r["directives"]] == ["AudioPlayer.Stop"] and not r.get("shouldEndSession")
    # a user's Stop still ends it
    r = handlers.lambda_handler(build_event("IntentRequest", "AMAZON.StopIntent", {}, False, HTML, "en-GB"), None)["response"]
    assert r.get("shouldEndSession") is True and not screen_app.OPEN


def test_off_or_no_browser_launch_is_unchanged(client, monkeypatch):
    _signin(monkeypatch); screen_app.OPEN.clear()
    client.post("/ma/push-url", json={"streamUrl": "https://ma.example.com/flow/s/The%20moon/x/The%20moon.mp3", "title": "Trouble"}, headers=AUTH)
    r = handlers.lambda_handler(build_event("LaunchRequest", None, {}, True, {"AudioPlayer": {}}, "en-GB"), None)["response"]
    assert "AudioPlayer.Play" in [d["type"] for d in r["directives"]]
    monkeypatch.setenv("MUSIC_SCREEN_APP", "false")
    r = handlers.lambda_handler(build_event("LaunchRequest", None, {}, True, HTML, "en-GB"), None)["response"]
    assert "Alexa.Presentation.HTML.Start" not in [d["type"] for d in r["directives"]]


def test_music_played_to_a_show_opens_the_music_page_which_starts_it(client, monkeypatch):
    _signin(monkeypatch); screen_app.OPEN.clear()
    client.post("/ma/push-url", json={"streamUrl": "https://ma.example.com/flow/s/The%20moon/x/The%20moon.mp3", "title": "Trouble"}, headers=AUTH)
    r = handlers.lambda_handler(build_event("IntentRequest", "PlayAudio", {}, True, HTML, "en-GB"), None)["response"]
    d = r["directives"]
    assert [x["type"] for x in d] == ["Alexa.Presentation.HTML.Start"] and d[0]["data"]["page"] == "music" and d[0]["data"]["play"] == 1
    assert d[0]["data"]["stream"].endswith("/The%20moon.mp3") and d[0]["data"]["player"] == "The moon"
    assert not r.get("shouldEndSession")
    # while it's open, a pause (MA's, by voice) reaches MA but sends Alexa's player nothing, and keeps the panel open
    r = handlers.lambda_handler(build_event("IntentRequest", "AMAZON.PauseIntent", {}, False, HTML, "en-GB"), None)["response"]
    assert not r.get("directives") and not r.get("shouldEndSession")


def _ev(req_type, intent, extra, new, sid):
    e = build_event(req_type, intent, extra, new, HTML, "en-GB"); e["session"]["sessionId"] = sid; return e


def test_mas_pause_ending_the_panel_opens_it_again_paused(client, monkeypatch):
    _signin(monkeypatch); screen_app.OPEN.clear(); screen_app.ENDED.clear()
    client.post("/ma/push-url", json={"streamUrl": "https://ma.example.com/flow/s/The%20moon/x/The%20moon.mp3", "title": "Trouble"}, headers=AUTH)
    handlers.lambda_handler(_ev("IntentRequest", "PlayAudio", {}, True, "S.panel"), None)
    # MA's "ask music assistant to pause": Alexa ends the panel's session, then the pause comes in a new one
    handlers.lambda_handler(_ev("SessionEndedRequest", None, {"reason": "USER_INITIATED"}, False, "S.panel"), None)
    r = handlers.lambda_handler(_ev("IntentRequest", "AMAZON.PauseIntent", {}, True, "S.pause"), None)["response"]
    d = r["directives"]
    assert [x["type"] for x in d] == ["Alexa.Presentation.HTML.Start"] and d[0]["data"]["page"] == "music" and d[0]["data"]["paused"] == 1
    assert "stream" not in d[0]["data"] and not r.get("shouldEndSession") and screen_app.OPEN["echo-1"] == "S.pause"
    # MA's stop the same way
    handlers.lambda_handler(_ev("SessionEndedRequest", None, {"reason": "USER_INITIATED"}, False, "S.pause"), None)
    r = handlers.lambda_handler(_ev("IntentRequest", "AMAZON.StopIntent", {}, True, "S.stop"), None)["response"]
    assert [x["type"] for x in r["directives"]] == ["Alexa.Presentation.HTML.Start"] and not r.get("shouldEndSession")


def test_a_pause_long_after_the_panel_closed_does_not_reopen_it(client, monkeypatch):
    _signin(monkeypatch); screen_app.OPEN.clear(); screen_app.ENDED.clear()
    client.post("/ma/push-url", json={"streamUrl": "https://ma.example.com/flow/s/The%20moon/x/The%20moon.mp3", "title": "Trouble"}, headers=AUTH)
    handlers.lambda_handler(_ev("IntentRequest", "PlayAudio", {}, True, "S.panel"), None)
    handlers.lambda_handler(_ev("SessionEndedRequest", None, {"reason": "USER_INITIATED"}, False, "S.panel"), None)
    screen_app.ENDED["echo-1"] -= 60   # (closed a minute ago: a quit, not MA's pause)
    r = handlers.lambda_handler(_ev("IntentRequest", "AMAZON.PauseIntent", {}, True, "S.later"), None)["response"]
    assert "Alexa.Presentation.HTML.Start" not in [x["type"] for x in (r.get("directives") or [])]


def test_the_page_asking_to_be_opened_again_gets_a_fresh_start_into_its_screensaver(client, monkeypatch):
    # (Alexa closes a web app after 30 minutes without a touch: the panel starts itself again a little before that)
    _signin(monkeypatch); screen_app.OPEN.clear()
    handlers.lambda_handler(build_event("LaunchRequest", None, {}, True, HTML, "en-GB"), None)
    r = handlers.lambda_handler(build_event("Alexa.Presentation.HTML.Message", None, {"message": {"type": "restart", "page": "home", "saver": True, "resume": True}}, False, HTML, "en-GB"), None)["response"]
    d = r["directives"]
    assert [x["type"] for x in d] == ["Alexa.Presentation.HTML.Start"] and not r.get("shouldEndSession")
    assert d[0]["data"]["page"] == "home" and d[0]["data"]["saver"] == 1 and d[0]["data"]["resume"] == 1
    assert d[0]["configuration"]["timeoutInSeconds"] == 1800
    # a page name that isn't one goes Home
    r = handlers.lambda_handler(build_event("Alexa.Presentation.HTML.Message", None, {"message": {"type": "restart", "page": "../x"}}, False, HTML, "en-GB"), None)["response"]
    assert r["directives"][0]["data"]["page"] == "home" and "saver" not in r["directives"][0]["data"]


def _clear():
    for d in (screen_app.OPEN, screen_app.ENDED, screen_app.STARTED, screen_app.SEEN, screen_app.FAILED, screen_app.HANDOFF):
        d.clear()


def test_a_closed_panel_is_forgotten(client, monkeypatch):
    """29 Oct: SkillEventHandler answered every SessionEndedRequest first - the panel stayed 'open' for ever."""
    _signin(monkeypatch); _clear()
    handlers.lambda_handler(_ev("LaunchRequest", None, {}, True, "S.launch"), None)
    handlers.lambda_handler(_ev("Alexa.Presentation.HTML.Message", None, {"message": {"type": "opened"}}, False, "S.launch"), None)
    assert screen_app.OPEN["echo-1"] == "S.launch"
    handlers.lambda_handler(_ev("SessionEndedRequest", None, {"reason": "USER_INITIATED"}, False, "S.launch"), None)
    assert "echo-1" not in screen_app.OPEN and not screen_app.FAILED


def test_a_panel_that_never_came_up_lets_alexa_play_the_music(client, monkeypatch):
    _signin(monkeypatch); _clear()
    client.post("/ma/push-url", json={"streamUrl": "https://ma.example.com/flow/s/The%20moon/x/The%20moon.mp3", "title": "Trouble"}, headers=AUTH)
    r = handlers.lambda_handler(_ev("IntentRequest", "PlayAudio", {}, True, "S.try"), None)["response"]
    assert [x["type"] for x in r["directives"]] == ["Alexa.Presentation.HTML.Start"]
    # Alexa ends it at once, the page never spoke: it didn't come up
    handlers.lambda_handler(_ev("SessionEndedRequest", None, {"reason": "ERROR", "error": {"type": "INVALID_RESPONSE", "message": "x"}}, False, "S.try"), None)
    assert "echo-1" in screen_app.FAILED and "echo-1" not in screen_app.OPEN
    # MA plays again: Alexa's own player plays it (not stripped - the panel isn't open)
    r = handlers.lambda_handler(_ev("IntentRequest", "PlayAudio", {}, True, "S.next"), None)["response"]
    assert "AudioPlayer.Play" in [x["type"] for x in r["directives"]]
    # asked for by hand ("open music assistant"), the panel is tried again
    r = handlers.lambda_handler(_ev("LaunchRequest", None, {}, True, "S.hand"), None)["response"]
    assert [x["type"] for x in r["directives"]] == ["Alexa.Presentation.HTML.Start"] and not screen_app.FAILED


def test_a_panel_that_came_up_is_used_again(client, monkeypatch):
    _signin(monkeypatch); _clear()
    client.post("/ma/push-url", json={"streamUrl": "https://ma.example.com/flow/s/The%20moon/x/The%20moon.mp3", "title": "Trouble"}, headers=AUTH)
    handlers.lambda_handler(_ev("IntentRequest", "PlayAudio", {}, True, "S.ok"), None)
    handlers.lambda_handler(_ev("Alexa.Presentation.HTML.Message", None, {"message": {"type": "opened"}}, False, "S.ok"), None)
    handlers.lambda_handler(_ev("SessionEndedRequest", None, {"reason": "USER_INITIATED"}, False, "S.ok"), None)
    assert not screen_app.FAILED
    r = handlers.lambda_handler(_ev("IntentRequest", "PlayAudio", {}, True, "S.again"), None)["response"]
    assert [x["type"] for x in r["directives"]] == ["Alexa.Presentation.HTML.Start"]


def test_the_hand_overs_own_pause_reopens_the_panel_playing_on(client, monkeypatch):
    """29 Oct: MA stopping 'The moon' once its music moved to the screen's speaker reopened the panel paused - silence."""
    _signin(monkeypatch); _clear(); screen_app.HANDOFF.clear()
    client.post("/ma/push-url", json={"streamUrl": "https://ma.example.com/flow/s/The%20moon/x/The%20moon.mp3", "title": "Trouble"}, headers=AUTH)
    handlers.lambda_handler(_ev("IntentRequest", "PlayAudio", {}, True, "S.play"), None)
    handlers.lambda_handler(_ev("Alexa.Presentation.HTML.Message", None, {"message": {"type": "opened"}}, False, "S.play"), None)
    handlers.lambda_handler(_ev("SessionEndedRequest", None, {"reason": "USER_INITIATED"}, False, "S.play"), None)
    r = handlers.lambda_handler(_ev("IntentRequest", "AMAZON.PauseIntent", {}, True, "S.pause"), None)["response"]
    d = r["directives"]
    assert [x["type"] for x in d] == ["Alexa.Presentation.HTML.Start"] and d[0]["data"].get("resume") == 1 and "paused" not in d[0]["data"]
    # a later pause (MA's, the panel's session ending again) is a real one: paused
    handlers.lambda_handler(_ev("SessionEndedRequest", None, {"reason": "USER_INITIATED"}, False, "S.pause"), None)
    r = handlers.lambda_handler(_ev("IntentRequest", "AMAZON.PauseIntent", {}, True, "S.pause2"), None)["response"]
    assert r["directives"][0]["data"].get("paused") == 1


def test_volume_said_with_the_panel_open_sets_the_echo_and_keeps_the_panel(client, monkeypatch):
    """29 Oct: "turn the volume down" with the panel open was lost - it's the Echo's volume, set through Home Assistant."""
    _signin(monkeypatch); _clear()
    from myhouse import actions
    calls = []
    monkeypatch.setattr(actions.ha, "call", lambda *a, **k: calls.append(a))
    handlers.lambda_handler(_ev("LaunchRequest", None, {}, True, "S.vol"), None)
    ev = _ev("IntentRequest", "VolumeIntent", {}, False, "S.vol")
    ev["request"]["intent"]["slots"] = {"dir": {"name": "dir", "value": "quieter", "resolutions": {"resolutionsPerAuthority": [
        {"status": {"code": "ER_SUCCESS_MATCH"}, "values": [{"value": {"name": "down", "id": "down"}}]}]}}, "level": {"name": "level"}}
    r = handlers.lambda_handler(ev, None)["response"]
    assert not r.get("shouldEndSession") and not r.get("outputSpeech") and screen_app.OPEN["echo-1"] == "S.vol"
    assert calls and calls[0][:2] == ("script", "turn_on") and calls[0][2]["variables"]["direction"] == "down"


def test_an_alarm_or_anything_unknown_with_the_panel_open_goes_to_alexa(client, monkeypatch):
    """29 Oct: "I want all such commands passed through if you don't recognise them"."""
    _signin(monkeypatch); _clear()
    from myhouse import handlers as mh
    said = []
    monkeypatch.setattr(mh, "hand_off", lambda hi, text=None: said.append((text, hi.attributes_manager.session_attributes.get("page")))
                        or hi.response_builder.set_should_end_session(True).response)
    handlers.lambda_handler(_ev("LaunchRequest", None, {}, True, "S.al"), None)
    r = handlers.lambda_handler(_ev("IntentRequest", "AMAZON.FallbackIntent", {}, False, "S.al"), None)["response"]
    assert r.get("shouldEndSession") is True and said == [(None, "music")] and "echo-1" not in screen_app.OPEN
