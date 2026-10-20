"""A display left on screen with APL switched off (fork change): its refresh must END the session.

On a screen Echo the APL display polls the skill (Alexa.Presentation.APL.UserEvent "MetadataRefresh"). Upstream kept the
session open on every refresh even with enable_apl=false, so a display left on screen from before kept the session alive:
Alexa kept listening, and Alexa+ said "say 'Alexa, exit' to go back". With APL off the refresh now ends the session (no
APL directives); with APL on it is unchanged.
"""

import base64

from golden_cases import build_event
from skill import lambda_function as handlers

AUTH = {"Authorization": "Basic " + base64.b64encode(b"test-user:test-password").decode()}
SHOW = {"AudioPlayer": {}, "Alexa.Presentation.APL": {}}


def refresh(client, monkeypatch, apl):
    monkeypatch.setenv("ENABLE_APL", apl)
    client.post("/ma/push-url", json={"streamUrl": "http://ma.local:8097/flow/s/The%20moon/x/The%20moon.mp3",
                                      "title": "T", "artist": "A", "album": "B"}, headers=AUTH)
    event = build_event("Alexa.Presentation.APL.UserEvent", None, {"token": "playbackToken", "arguments": ["MetadataRefresh"]},
                        False, SHOW, "en-GB")
    return handlers.lambda_handler(event, None)["response"]


def test_apl_off_refresh_ends_the_session(client, monkeypatch):
    r = refresh(client, monkeypatch, "false")
    assert r.get("shouldEndSession") is True
    assert not any(d["type"].startswith("Alexa.Presentation.APL") for d in r.get("directives") or [])


def test_apl_on_refresh_keeps_the_session(client, monkeypatch):
    r = refresh(client, monkeypatch, "true")
    assert r.get("shouldEndSession") is False
