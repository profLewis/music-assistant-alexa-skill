"""Fork: the display-only page follows the song via /now/ addresses (token-protected)."""

import base64

from golden_cases import build_event
from now_playing import token, urls
from skill import lambda_function as handlers

AUTH = {"Authorization": "Basic " + base64.b64encode(b"test-user:test-password").decode()}
SHOW = {"AudioPlayer": {}, "Alexa.Presentation.APL": {}}
FLOW = "https://ma.example.com/flow/s/The%20moon/x/The%20moon.mp3"


def push(client, title):
    client.post("/ma/push-url", json={"streamUrl": FLOW, "title": title, "artist": "Elvis", "album": "Sings",
                                      "imageUrl": "https://ma.example.com/art.jpg"}, headers=AUTH)


def test_now_addresses_follow_the_latest_push_and_need_the_token(client, monkeypatch):
    monkeypatch.setenv("SKILL_HOSTNAME", "https://alexa.example.com")
    push(client, "Trouble")
    cover, text = urls("The moon")
    path = text.replace("https://alexa.example.com", "")
    assert "Trouble" in client.get(path).get_data(as_text=True)
    push(client, "King Creole")   # the next song: same address, new title
    assert "King Creole" in client.get(path).get_data(as_text=True)
    r = client.get(cover.replace("https://alexa.example.com", ""))
    assert r.status_code == 302 and r.headers["Location"].startswith("https://") and r.headers["Location"].endswith("/art.jpg")
    assert client.get(path.replace(token("The moon"), "0" * 24)).status_code == 404


def test_display_only_page_reloads_from_now_without_sendevent(client, monkeypatch):
    monkeypatch.setenv("SKILL_HOSTNAME", "https://alexa.example.com")
    monkeypatch.setenv("ENABLE_APL", "true")
    monkeypatch.setenv("APL_DISPLAY_ONLY", "true")
    push(client, "Trouble")
    event = build_event("IntentRequest", "PlayAudio", {}, True, SHOW, "en-GB")
    r = handlers.lambda_handler(event, None)["response"]
    doc = str(next(d for d in r["directives"] if d["type"] == "Alexa.Presentation.APL.RenderDocument")["document"])
    assert "/now/" in doc and "nowTick" in doc and "VectorGraphic" in doc
    assert "SendEvent" not in doc and r["shouldEndSession"] is True
