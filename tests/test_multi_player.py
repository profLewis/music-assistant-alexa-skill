"""Several Echoes playing at once (fork change): each Echo must get the stream Music Assistant pushed for ITS player.

Upstream kept one stream slot, so when MA played on Mars and Venus together the second push overwrote the first and
both Echoes were handed the same stream. Pushes are now also kept per player (from the flow URL, or an explicit
playerId), and a request from an Echo mapped to a player (/devices) gets that player's stream.
"""

import base64

from golden_cases import build_event
from music_assistant_api.ma_routes import player_from_stream_url
from skill import device_mapping
from skill import lambda_function as handlers

AUTH = {"Authorization": "Basic " + base64.b64encode(b"test-user:test-password").decode()}
SPEAKER = ({"AudioPlayer": {}}, "en-GB")


def flow(player):
    return f"http://ma.local:8097/flow/2LZAtt6E/{player.replace(' ', '%20')}/0e1adf408a3b/{player.replace(' ', '%20')}.mp3"


def push(client, player, title, **extra):
    body = {"streamUrl": flow(player), "title": title, "artist": "A", "album": "B", **extra}
    assert client.post("/ma/push-url", json=body, headers=AUTH).status_code == 200


def play_url(device):
    event = build_event("IntentRequest", "PlayAudio", {}, True, SPEAKER[0], SPEAKER[1], device=device)
    directives = handlers.lambda_handler(event, None)["response"]["directives"]
    return next(d for d in directives if d["type"] == "AudioPlayer.Play")["audioItem"]["stream"]["url"]


def test_player_from_stream_url():
    assert player_from_stream_url(flow("Mars")) == "Mars"
    assert player_from_stream_url(flow("The moon")) == "The moon"
    assert player_from_stream_url("http://ma.local:8097/flow/queue/song.mp3") is None
    assert player_from_stream_url("http://ma.local:8097/other/path.mp3") is None


def test_each_mapped_echo_gets_its_own_stream(client):
    device_mapping.set_player_for_device("echo-mars", "Mars")
    device_mapping.set_player_for_device("echo-venus", "Venus")
    push(client, "Mars", "Song on Mars")
    push(client, "Venus", "Song on Venus")   # pushed last: upstream would hand this to BOTH Echoes
    assert "/Mars/" in play_url("echo-mars")
    assert "/Venus/" in play_url("echo-venus")


def test_order_of_requests_does_not_matter(client):
    device_mapping.set_player_for_device("echo-mars", "Mars")
    device_mapping.set_player_for_device("echo-venus", "Venus")
    push(client, "Venus", "v")
    push(client, "Mars", "m")
    assert "/Venus/" in play_url("echo-venus")
    assert "/Mars/" in play_url("echo-mars")


def test_unmapped_echo_still_gets_the_latest_push(client):
    device_mapping.set_player_for_device("echo-mars", "Mars")
    push(client, "Mars", "m")
    push(client, "Venus", "v")
    assert "/Venus/" in play_url("echo-unknown")


def test_mapped_echo_without_its_own_push_gets_the_latest(client):
    device_mapping.set_player_for_device("echo-moon", "The moon")
    push(client, "Venus", "v")
    assert "/Venus/" in play_url("echo-moon")


def test_explicit_player_id_wins(client):
    device_mapping.set_player_for_device("echo-mars", "Mars")
    body = {"streamUrl": "http://ma.local:8097/stream/x.mp3", "title": "t", "playerId": "Mars"}
    assert client.post("/ma/push-url", json=body, headers=AUTH).status_code == 200
    push(client, "Venus", "v")
    assert play_url("echo-mars").endswith("/stream/x.mp3")
