"""Fork: APL_DISPLAY_ONLY - Alexa's AudioPlayer plays, the page is display-only, and the session ends."""

import base64

from golden_cases import build_event
from skill import lambda_function as handlers

AUTH = {"Authorization": "Basic " + base64.b64encode(b"test-user:test-password").decode()}
SHOW = {"AudioPlayer": {}, "Alexa.Presentation.APL": {}}


def play(client, monkeypatch, display_only):
    monkeypatch.setenv("ENABLE_APL", "true")
    monkeypatch.setenv("APL_DISPLAY_ONLY", display_only)
    client.post("/ma/push-url", json={"streamUrl": "https://ma.example.com/flow/s/The%20moon/x/The%20moon.mp3",
                                      "title": "Trouble", "artist": "Elvis", "album": "Sings", "imageUrl": "https://ma.example.com/art.jpg"}, headers=AUTH)
    event = build_event("IntentRequest", "PlayAudio", {}, True, SHOW, "en-GB")
    return handlers.lambda_handler(event, None)["response"]


def test_display_only_plays_through_audioplayer_and_ends_the_session(client, monkeypatch):
    r = play(client, monkeypatch, "true")
    types = [d["type"] for d in r["directives"]]
    assert "AudioPlayer.Play" in types and "Alexa.Presentation.APL.RenderDocument" in types
    assert r["shouldEndSession"] is True
    doc = next(d for d in r["directives"] if d["type"] == "Alexa.Presentation.APL.RenderDocument")["document"]
    text = str(doc)
    assert "'Video'" not in text and "SendEvent" not in text and "AlexaTransportControls" not in text
    assert "Trouble" in text


def test_without_display_only_the_full_apl_player_is_unchanged(client, monkeypatch):
    r = play(client, monkeypatch, "false")
    types = [d["type"] for d in r["directives"]]
    assert "AudioPlayer.Play" not in types and "Alexa.Presentation.APL.RenderDocument" in types


def _pause(client, monkeypatch, display_only, new_session):
    monkeypatch.setenv("ENABLE_APL", "true")
    monkeypatch.setenv("APL_DISPLAY_ONLY", display_only)
    event = build_event("IntentRequest", "AMAZON.PauseIntent", {}, new_session, SHOW, "en-GB")
    return handlers.lambda_handler(event, None)["response"]


def test_display_only_pause_stops_and_ends_the_session(client, monkeypatch):
    # a pause (MA's own pause arrives as one) left the session open on a Show: the Echo then sat listening
    for new in (True, False):
        r = _pause(client, monkeypatch, "true", new)
        assert [d["type"] for d in r.get("directives", [])] == ["AudioPlayer.Stop"]
        assert r["shouldEndSession"] is True


def test_display_only_display_event_ends_the_session(client, monkeypatch):
    monkeypatch.setenv("ENABLE_APL", "true")
    monkeypatch.setenv("APL_DISPLAY_ONLY", "true")
    event = build_event("Alexa.Presentation.APL.UserEvent", None, {"token": "playbackToken", "arguments": ["MetadataRefresh"]}, False, SHOW, "en-GB")
    r = handlers.lambda_handler(event, None)["response"]
    assert r["shouldEndSession"] is True
