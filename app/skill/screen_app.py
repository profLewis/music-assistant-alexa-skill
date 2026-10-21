"""Fork: the control panel INSIDE the music skill ("Alexa, open music assistant" on an Echo Show), so the music and the
screen are one skill - Alexa lets only one skill have the screen, and when the music was the other skill it took the
screen from Peach Banana every time a song started.

  LaunchRequest on a device with a web browser (Alexa.Presentation.HTML) → the whole control panel (Peach Banana's front
  door, myhouse.handlers._open_dashboard), the session kept open for it.
  The page's first message {"type": "stop-music"} → AudioPlayer.Stop (and Music Assistant paused): opening it quits
  any music playing.
  MUSIC PLAYED TO A SHOW (MA's "ask music assistant to play audio", a new session) → the control panel opens on its
  Music page instead of Alexa's own player, with the stream: THE PAGE PLAYS IT ITSELF (an audio element), following
  Music Assistant's play / pause. (Tried first: the page asking the skill for AudioPlayer.Play - Alexa then froze the
  web app the moment its own player started, so the panel stopped updating.) While the panel is open on a device no
  AudioPlayer directive is sent there (it would take over again) - pause / resume / next reach Music Assistant, whose
  state the page follows.
  While it's open on a device, nothing the music skill answers there ends the session (MA's own play / pause reach this
  skill as voice requests) - unless the request is a user's Stop / Cancel. What happens is logged (session new / same),
  as this is a test of whether the Show keeps the page up while the same skill plays.

MUSIC_SCREEN_APP=false turns it off (the launch then plays the latest stream, as upstream)."""

import logging

from ask_sdk_core.dispatch_components import AbstractRequestHandler, AbstractResponseInterceptor
from ask_sdk_core.utils import is_intent_name, is_request_type
from ask_sdk_model.interfaces.audioplayer import StopDirective

from app_settings import get_setting

log = logging.getLogger(__name__)
OPEN = {}   # device id → the session the control panel runs in


def enabled():
    return get_setting("MUSIC_SCREEN_APP", "true").lower() in ("true", "1", "yes")


def _dev(handler_input):
    try:
        return handler_input.request_envelope.context.system.device.device_id
    except Exception:
        return None


def _sid(handler_input):
    s = getattr(handler_input.request_envelope, "session", None)
    return getattr(s, "session_id", None) if s else None


def _html(handler_input):
    try:
        return getattr(handler_input.request_envelope.context.system.device.supported_interfaces, "alexa_presentation_html", None) is not None
    except Exception:
        return False


class ScreenAppLaunch(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return enabled() and is_request_type("LaunchRequest")(handler_input) and _html(handler_input)

    def handle(self, handler_input):
        from myhouse.handlers import _open_dashboard
        r = _open_dashboard(handler_input, "home")
        if r is None:
            log.warning("Screen app: couldn't open the control panel (sign-in not set up?)")
            return handler_input.response_builder.speak("Sorry, I couldn't open the house.").set_should_end_session(True).response
        OPEN[_dev(handler_input)] = _sid(handler_input)
        log.info("Screen app: opened on a Show (session %s)", (_sid(handler_input) or "")[-8:])
        return r


class ScreenAppPlay(AbstractRequestHandler):
    """Music Assistant's play to a Show: open the control panel on the Music page; the page asks for the stream."""
    def can_handle(self, handler_input):
        return (enabled() and is_intent_name("PlayAudio")(handler_input) and _html(handler_input)
                and OPEN.get(_dev(handler_input)) != _sid(handler_input))   # (already open in this session: just play)

    def handle(self, handler_input):
        from myhouse.handlers import _open_dashboard
        url, player = stream(handler_input)
        r = _open_dashboard(handler_input, "music", {"play": 1, "stream": url, "player": player}) if url else None
        if r is None:   # (no sign-in set up: Alexa's own player, as before)
            from . import lambda_function
            return lambda_function.LaunchRequestOrPlayAudioHandler().handle(handler_input)
        OPEN[_dev(handler_input)] = _sid(handler_input)
        log.info("Screen app: music for a Show - opening the control panel's Music page (session %s)", (_sid(handler_input) or "")[-8:])
        return r


def stream(handler_input):
    """(the public stream URL Music Assistant pushed for this Echo - refreshed if it has gone stale -, its MA player name)"""
    from urllib.parse import unquote
    from . import lambda_function as lf, util
    url, _a = lf._get_stream_url(None)
    if url and not util.skip_url_validation() and not util.validate_stream_url(url):
        from . import device_mapping
        dev = _dev(handler_input); pid = device_mapping.get_player_for_device(dev)
        url = (lf._refresh_stream_url(dev, pid) if pid else None) or url
    if not url:
        return None, None
    try:
        url = util.replace_ip_in_url(url, util.get_ma_hostname(raise_on_http_scheme=True))
    except Exception:
        log.exception("Screen app: no public music address")
        return None, None
    parts = url.split("/flow/", 1)[-1].split("/")
    return url, (unquote(parts[1]) if len(parts) > 2 else None)


class ScreenAppMessage(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("Alexa.Presentation.HTML.Message")(handler_input)

    def handle(self, handler_input):
        msg = getattr(handler_input.request_envelope.request, "message", None) or {}
        kind = msg.get("type") if isinstance(msg, dict) else None
        log.info("Screen app: message %s (session %s)", kind, (_sid(handler_input) or "")[-8:])
        rb = handler_input.response_builder
        if kind == "stop-music":
            rb.add_directive(StopDirective())
            try:
                from . import lambda_function
                lambda_function._sync_to_ma_unless_echo(handler_input, "pause")
            except Exception:
                log.exception("Screen app: pausing Music Assistant failed")
        return rb.response


class ScreenAppEnded(AbstractRequestHandler):
    """(registered first: only notes the end, then lets nothing else run)"""
    def can_handle(self, handler_input):
        if is_request_type("SessionEndedRequest")(handler_input) and OPEN.get(_dev(handler_input)) == _sid(handler_input):
            return True
        return False

    def handle(self, handler_input):
        r = handler_input.request_envelope.request
        log.info("Screen app: closed (%s %s)", getattr(r, "reason", None), getattr(getattr(r, "error", None), "message", None))
        OPEN.pop(_dev(handler_input), None)
        return handler_input.response_builder.response


class KeepScreenOpen(AbstractResponseInterceptor):
    def process(self, handler_input, response):
        dev = _dev(handler_input)
        if dev not in OPEN or response is None:
            return
        req = handler_input.request_envelope.request
        same = OPEN[dev] == _sid(handler_input)
        name = getattr(getattr(req, "intent", None), "name", None) or req.object_type
        log.info("Screen app: %s while open - %s session", name, "SAME" if same else "a NEW" if _sid(handler_input) else "no")
        if is_request_type("Alexa.Presentation.HTML.Message")(handler_input):
            pass   # (its own answer: stop-music's AudioPlayer.Stop stops Alexa's player from before the panel opened)
        elif response.directives:   # Alexa's audio player would take the screen (and freeze the panel): the page plays
            response.directives = [d for d in response.directives if not (getattr(d, "object_type", "") or "").startswith("AudioPlayer.")
                                   and not (getattr(d, "object_type", "") or "").startswith("Alexa.Presentation.APL")] or None
        if same and (is_intent_name("AMAZON.StopIntent")(handler_input) or is_intent_name("AMAZON.CancelIntent")(handler_input)):
            OPEN.pop(dev, None)
            return
        if response.should_end_session:
            response.should_end_session = None
