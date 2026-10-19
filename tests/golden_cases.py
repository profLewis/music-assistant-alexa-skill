"""Golden-response cases: every Alexa request type the skill handles, across device kinds and locales.

Each case is pushed through the real lambda_handler and the WHOLE response envelope is captured, together with
the side effects the skill caused (Music Assistant commands, stream reachability probes). The fork's goal is
"exactly the same response as upstream" except where a change is deliberate, so tests/golden/*.json is recorded
from upstream (scripts/record_golden.py) and test_golden_responses.py replays and compares byte-for-byte.
"""

import json

STREAM_URL = "https://streams.example.com/music/flow/session/The%20moon.mp3"

# device kinds: what the Echo advertises, and whether the add-on has APL enabled
DEVICES = {
    "audio": ({"AudioPlayer": {}}, "false"),  # Echo Dot / speaker
    "show_apl": ({"AudioPlayer": {}, "Alexa.Presentation.APL": {}}, "true"),  # Echo Show, APL on
    "show_noapl": ({"AudioPlayer": {}, "Alexa.Presentation.APL": {}}, "false"),  # Echo Show, APL off
    "apl_only": ({"Alexa.Presentation.APL": {}}, "true"),  # screen without AudioPlayer
}
LOCALES = ("en-GB", "en-US")

# (name, request type, intent, extra request fields, session_new, stream pushed, device mapped, MA command ok)
REQUESTS = [
    ("launch", "LaunchRequest", None, {}, True, True, True, True),
    ("launch_nostream", "LaunchRequest", None, {}, True, False, True, True),
    ("play_audio", "IntentRequest", "PlayAudio", {}, True, True, True, True),
    ("play_audio_unmapped", "IntentRequest", "PlayAudio", {}, True, True, False, True),
    ("help", "IntentRequest", "AMAZON.HelpIntent", {}, True, True, True, True),
    ("fallback", "IntentRequest", "AMAZON.FallbackIntent", {}, False, True, True, True),
    ("stop", "IntentRequest", "AMAZON.StopIntent", {}, False, True, True, True),
    ("cancel", "IntentRequest", "AMAZON.CancelIntent", {}, False, True, True, True),
    ("pause", "IntentRequest", "AMAZON.PauseIntent", {}, False, True, True, True),
    ("pause_new_session", "IntentRequest", "AMAZON.PauseIntent", {}, True, True, True, True),
    ("pause_ma_fail", "IntentRequest", "AMAZON.PauseIntent", {}, False, True, True, False),
    ("resume", "IntentRequest", "AMAZON.ResumeIntent", {}, False, True, True, True),
    ("resume_nostream", "IntentRequest", "AMAZON.ResumeIntent", {}, False, False, True, True),
    ("next", "IntentRequest", "AMAZON.NextIntent", {}, False, True, True, True),
    ("next_unmapped", "IntentRequest", "AMAZON.NextIntent", {}, False, True, False, True),
    ("next_ma_fail", "IntentRequest", "AMAZON.NextIntent", {}, False, True, True, False),
    ("previous", "IntentRequest", "AMAZON.PreviousIntent", {}, False, True, True, True),
    ("start_over", "IntentRequest", "AMAZON.StartOverIntent", {}, False, True, True, True),
    ("loop_on", "IntentRequest", "AMAZON.LoopOnIntent", {}, False, True, True, True),
    ("shuffle_on", "IntentRequest", "AMAZON.ShuffleOnIntent", {}, False, True, True, True),
    ("playback_started", "AudioPlayer.PlaybackStarted", None, {"token": STREAM_URL, "offsetInMilliseconds": 0}, None, True, True, True),
    ("playback_finished", "AudioPlayer.PlaybackFinished", None, {"token": STREAM_URL, "offsetInMilliseconds": 1000}, None, True, True, True),
    ("playback_stopped", "AudioPlayer.PlaybackStopped", None, {"token": STREAM_URL, "offsetInMilliseconds": 1000}, None, True, True, True),
    ("playback_nearly_finished", "AudioPlayer.PlaybackNearlyFinished", None, {"token": STREAM_URL, "offsetInMilliseconds": 1000}, None, True, True, True),
    ("playback_failed", "AudioPlayer.PlaybackFailed", None, {"token": STREAM_URL, "error": {"type": "MEDIA_ERROR_UNKNOWN", "message": "x"}}, None, True, True, True),
    ("exception_encountered", "System.ExceptionEncountered", None, {"error": {"type": "INVALID_RESPONSE", "message": "x"}, "cause": {"requestId": "r"}}, None, True, True, True),
    ("apl_user_event", "Alexa.Presentation.APL.UserEvent", None, {"token": "playbackToken", "arguments": ["refresh"]}, False, True, True, True),
    ("cmd_play", "PlaybackController.PlayCommandIssued", None, {}, None, True, True, True),
    ("cmd_next", "PlaybackController.NextCommandIssued", None, {}, None, True, True, True),
    ("cmd_previous", "PlaybackController.PreviousCommandIssued", None, {}, None, True, True, True),
    ("cmd_pause", "PlaybackController.PauseCommandIssued", None, {}, None, True, True, True),
    ("session_ended", "SessionEndedRequest", None, {"reason": "USER_INITIATED"}, False, True, True, True),
    ("skill_enabled", "AlexaSkillEvent.SkillEnabled", None, {}, None, True, True, True),
]


def case_ids():
    return [f"{r[0]}__{d}__{loc}" for r in REQUESTS for d in DEVICES for loc in LOCALES]


def build_event(req_type, intent, extra, session_new, interfaces, locale, device="echo-1"):
    request = {"type": req_type, "requestId": "golden-request", "timestamp": "2026-10-19T20:00:00Z", "locale": locale}
    if intent:
        request["intent"] = {"name": intent, "confirmationStatus": "NONE", "slots": {}}
    request.update(extra)
    payload = {
        "version": "1.0",
        "context": {
            "System": {
                "application": {"applicationId": "golden-skill"},
                "user": {"userId": "golden-user"},
                "device": {"deviceId": device, "supportedInterfaces": interfaces},
                "apiEndpoint": "https://api.eu.amazonalexa.com",
            },
            "AudioPlayer": {"playerActivity": "PLAYING", "token": STREAM_URL, "offsetInMilliseconds": 0},
        },
        "request": request,
    }
    if session_new is not None:
        payload["session"] = {
            "new": session_new,
            "sessionId": "SessionId.golden",
            "application": {"applicationId": "golden-skill"},
            "user": {"userId": "golden-user"},
        }
    return payload


def run_case(case_id, monkeypatch):
    """Run one case in the (already isolated) test environment; return a JSON-able record of what happened."""
    import requests
    import shared_store
    from skill import device_mapping, ma_control
    from skill import lambda_function as handlers

    name, device_kind, locale = case_id.split("__")
    _, req_type, intent, extra, session_new, pushed, mapped, ma_ok = next(r for r in REQUESTS if r[0] == name)
    interfaces, apl = DEVICES[device_kind]
    monkeypatch.setenv("ENABLE_APL", apl)

    side_effects = []
    monkeypatch.setattr(ma_control, "_recent_ma_triggered", {})
    monkeypatch.setattr(
        ma_control, "send_player_command", lambda p, c: side_effects.append(["ma", p, c]) or ma_ok
    )

    class _Resp:
        status_code = 200
        headers = {"Content-Type": "audio/mpeg"}

        def close(self):
            pass

        def iter_content(self, *a, **k):
            return iter([b"\0"])

    def _net(method):
        def call(url, *a, **k):
            side_effects.append(["http", method, url])
            return _Resp()

        return call

    for method in ("get", "head", "post", "put"):
        monkeypatch.setattr(requests, method, _net(method))

    if pushed:
        shared_store.set_ma({"streamUrl": STREAM_URL, "title": "Planet Telex", "artist": "Radiohead",
                             "album": "The Bends", "imageUrl": "https://streams.example.com/art.jpg"})
    if mapped:
        device_mapping.set_player_for_device("echo-1", "The moon")

    event = build_event(req_type, intent, extra, session_new, interfaces, locale)
    try:
        envelope = handlers.lambda_handler(event, None)
        envelope = json.loads(json.dumps(envelope, sort_keys=True, default=str))
        envelope.pop("userAgent", None)  # names the local Python version, not skill behaviour
        result = {"envelope": envelope}
    except Exception as err:  # an exception is a behaviour too: record it rather than fail the run
        result = {"exception": f"{type(err).__name__}: {err}"}
    result["side_effects"] = side_effects
    return result
