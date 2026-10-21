"""Fork: the control panel inside the music skill on an Echo Show (screen_app.py)."""

import base64

from golden_cases import build_event
from skill import lambda_function as handlers
from skill import screen_app

AUTH = {"Authorization": "Basic " + base64.b64encode(b"test-user:test-password").decode()}
HTML = {"AudioPlayer": {}, "Alexa.Presentation.APL": {}, "Alexa.Presentation.HTML": {"runtime": {"maxVersion": "1.1"}}}


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
    assert "AudioPlayer.Play" in [d["type"] for d in r["directives"]] and not r.get("shouldEndSession")
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
    assert not r.get("shouldEndSession")
    r = handlers.lambda_handler(build_event("Alexa.Presentation.HTML.Message", None, {"message": {"type": "play"}}, False, HTML, "en-GB"), None)["response"]
    assert [x["type"] for x in r["directives"]] == ["AudioPlayer.Play"] and not r.get("shouldEndSession")
