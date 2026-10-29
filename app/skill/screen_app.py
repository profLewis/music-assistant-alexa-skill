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

  MUSIC ASSISTANT'S PAUSE / STOP take the screen: MA sends them to the Echo as voice requests ("ask music assistant to
  pause"), and Alexa ends the panel's session for each - the Show then fell back to Alexa's home screen. A pause or stop
  arriving within a few seconds of the panel's session ending is that: the panel opens again at once on its Music page,
  PAUSED (data.paused - the page doesn't send its stop-music, which would pause MA again and loop). A quit (Alexa, exit /
  another skill) has no pause behind it, so the panel stays closed.

  A PANEL THAT NEVER CAME UP (29 Oct: The moon silent - every play was handed to a panel that wasn't there): the page
  tells the skill it's up ({"type": "opened"}); a music hand-off whose session ends within FAIL_S without a word from the
  page didn't open, so for RETRY_S the Show's music goes to Alexa's own player instead (the music plays; the panel is
  tried again after). Each close is logged with Alexa's reason / error.

MUSIC_SCREEN_APP=false turns it off (the launch then plays the latest stream, as upstream)."""

import logging
import time

from ask_sdk_core.dispatch_components import AbstractRequestHandler, AbstractResponseInterceptor
from ask_sdk_core.utils import is_intent_name, is_request_type
from ask_sdk_model.interfaces.audioplayer import StopDirective

from app_settings import get_setting

log = logging.getLogger(__name__)
OPEN = {}   # device id → the session the control panel runs in
ENDED = {}  # device id → when Alexa last ended the panel's session (time.time())
REOPEN_S = 5   # a pause / stop this soon after the panel's session ended came from that same MA command
STARTED = {}   # device id → (session, time.time()) of the last panel opened there
SEEN = {}      # device id → the session the page last spoke from (it came up)
FAILED = {}    # device id → when a panel opened there never came up
FAIL_S = 20    # a panel's session ending this soon, the page silent: it didn't come up
RETRY_S = 900  # after one that didn't: Alexa's own player for this long
HANDOFF = {}   # device id → (session, time.time()) of the last music hand-off to the panel there
HANDOFF_S = 120   # a pause / stop this soon after a hand-off whose page came up is the hand-over's own (see ScreenAppReopen)


def _started(handler_input):
    dev = _dev(handler_input); OPEN[dev] = _sid(handler_input); STARTED[dev] = (_sid(handler_input), time.time())


def failed_lately(dev):
    return time.time() - FAILED.get(dev, 0) < RETRY_S


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
        _started(handler_input); FAILED.pop(_dev(handler_input), None)   # (asked for by hand: try it)
        log.info("Screen app: opened on a Show (session %s)", (_sid(handler_input) or "")[-8:])
        return r


class ScreenAppPlay(AbstractRequestHandler):
    """Music Assistant's play to a Show: open the control panel on the Music page; the page asks for the stream."""
    def can_handle(self, handler_input):
        return (enabled() and is_intent_name("PlayAudio")(handler_input) and _html(handler_input)
                and OPEN.get(_dev(handler_input)) != _sid(handler_input)   # (already open in this session: just play)
                and not self._skip(_dev(handler_input)))

    @staticmethod
    def _skip(dev):
        if failed_lately(dev):
            log.warning("Screen app: the panel didn't come up on this Show lately - Alexa's own player plays it")
            return True
        return False

    def handle(self, handler_input):
        from myhouse.handlers import _open_dashboard
        url, player = stream(handler_input)
        r = _open_dashboard(handler_input, "music", {"play": 1, "stream": url, "player": player}) if url else None
        if r is None:   # (no sign-in set up: Alexa's own player, as before)
            from . import lambda_function
            return lambda_function.LaunchRequestOrPlayAudioHandler().handle(handler_input)
        _started(handler_input); HANDOFF[_dev(handler_input)] = (_sid(handler_input), time.time())
        log.info("Screen app: music for a Show - opening the control panel's Music page (session %s)", (_sid(handler_input) or "")[-8:])
        return r


class ScreenAppReopen(AbstractRequestHandler):
    """MA's pause / stop just ended the panel's session: open it again, paused, on the Music page."""
    def can_handle(self, handler_input):
        dev = _dev(handler_input)
        return (enabled() and _html(handler_input) and OPEN.get(dev) != _sid(handler_input)
                and (is_intent_name("AMAZON.PauseIntent")(handler_input) or is_intent_name("AMAZON.StopIntent")(handler_input))
                and time.time() - ENDED.get(dev, 0) < REOPEN_S)

    def handle(self, handler_input):
        from myhouse.handlers import _open_dashboard
        try:
            _url, player = stream(handler_input)
        except Exception:
            player = None
        # THE HAND-OVER'S OWN PAUSE (29 Oct): once the panel is up, Home Assistant moves the music from "The moon" to the
        # screen's own speaker, and Music Assistant then stops "The moon" - by voice, which ends the panel's session.
        # Opened again PAUSED, the page's speaker came back stopped: silence. Soon after a hand-off whose page came up,
        # it opens with resume instead (the page reconnects its speaker and plays on).
        dev = _dev(handler_input); ho = HANDOFF.get(dev)
        resume = bool(ho and SEEN.get(dev) == ho[0] and time.time() - ho[1] < HANDOFF_S)
        r = _open_dashboard(handler_input, "music", {"resume": 1, "player": player} if resume else {"paused": 1, "player": player})
        if r is None:
            return handler_input.response_builder.response
        _started(handler_input); ENDED.pop(dev, None)
        if resume:
            HANDOFF.pop(dev, None)
            log.info("Screen app: the hand-over's pause took the screen - the control panel opened again, playing on (session %s)", (_sid(handler_input) or "")[-8:])
            return r
        log.info("Screen app: MA's pause took the screen - the control panel opened again, paused (session %s)", (_sid(handler_input) or "")[-8:])
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


class ScreenAppVolume(AbstractRequestHandler):
    """"Turn the volume down" (VolumeIntent - myhouse/model.VOLUME_INTENT, added to this skill's model by POST
    /myhouse/music-volume): the Echo's own volume through Home Assistant; the panel and the music stay."""
    def can_handle(self, handler_input):
        return is_intent_name("VolumeIntent")(handler_input)

    def handle(self, handler_input):
        from myhouse.handlers import volume
        return volume(handler_input)


class ScreenAppHandOff(AbstractRequestHandler):
    """ALEXA'S OWN JOBS WITH THE PANEL OPEN (the user, 29 Oct: "if someone says to alexa to set an alarm or timer would
    that work when the app is playing? I want all such commands passed through if you don't recognise them"): alarms,
    timers (myhouse/model, added to this skill's model by POST /myhouse/music-volume) and anything this skill doesn't know
    (FallbackIntent) are handed to Alexa as Peach Banana does (myhouse.handlers.hand_off): the panel closes, Alexa does
    it, and the panel comes back on its Music page - the music on the screen's speaker carrying on (script.peach_banana_handoff)."""
    def can_handle(self, handler_input):
        from myhouse.handlers import HandOff
        dev = _dev(handler_input)
        return (enabled() and dev is not None and _sid(handler_input) is not None and OPEN.get(dev) == _sid(handler_input)
                and any(is_intent_name(n)(handler_input) for n in HandOff.NAMES))

    def handle(self, handler_input):
        from myhouse.handlers import HandOff
        handler_input.attributes_manager.session_attributes["page"] = "music"
        OPEN.pop(_dev(handler_input), None)   # (closing it is the point - KeepScreenOpen leaves it be)
        log.info("Screen app: %s - handed to Alexa", handler_input.request_envelope.request.intent.name)
        return HandOff().handle(handler_input)


class ScreenAppMessage(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("Alexa.Presentation.HTML.Message")(handler_input)

    def handle(self, handler_input):
        msg = getattr(handler_input.request_envelope.request, "message", None) or {}
        kind = msg.get("type") if isinstance(msg, dict) else None
        SEEN[_dev(handler_input)] = _sid(handler_input)   # (the page is up)
        log.info("Screen app: message %s (session %s)", kind, (_sid(handler_input) or "")[-8:])
        rb = handler_input.response_builder
        if kind == "restart":   # (opened again before Alexa's 30-minute idle limit closes it - myhouse.handlers.restart)
            from myhouse.handlers import restart
            r = restart(handler_input, msg)
            if r is not None:
                _started(handler_input)
                return r
        if kind == "stop-music":
            rb.add_directive(StopDirective())
            try:
                from . import lambda_function
                lambda_function._sync_to_ma_unless_echo(handler_input, "pause")
            except Exception:
                log.exception("Screen app: pausing Music Assistant failed")
        return rb.response


class ScreenAppEnded(AbstractRequestHandler):
    """(registered FIRST - before SkillEventHandler, which answers every SessionEndedRequest: registered after it, this
    never ran, so a closed panel stayed 'open' and every play was handed to it - 29 Oct)"""
    def can_handle(self, handler_input):
        if is_request_type("SessionEndedRequest")(handler_input) and OPEN.get(_dev(handler_input)) == _sid(handler_input):
            return True
        return False

    def handle(self, handler_input):
        r = handler_input.request_envelope.request
        dev, sid = _dev(handler_input), _sid(handler_input)
        reason, err = getattr(r, "reason", None), getattr(getattr(r, "error", None), "message", None)
        st = STARTED.get(dev)
        if st and st[0] == sid and SEEN.get(dev) != sid and time.time() - st[1] < FAIL_S:
            FAILED[dev] = time.time()
            log.warning("Screen app: the panel never came up (closed after %.0f s: %s %s) - Alexa's own player for the next %d min",
                        time.time() - st[1], reason, err, RETRY_S // 60)
        else:
            log.info("Screen app: closed (%s %s)", reason, err)
        ENDED[dev] = time.time()   # (MA's next voice request - a pause - may be what ended it: see ScreenAppReopen)
        OPEN.pop(dev, None)
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
        if (same and (is_intent_name("AMAZON.StopIntent")(handler_input) or is_intent_name("AMAZON.CancelIntent")(handler_input))
                and not any((getattr(d, "object_type", "") or "") == "Alexa.Presentation.HTML.Start" for d in (response.directives or []))):
            OPEN.pop(dev, None)
            return
        if response.should_end_session:
            response.should_end_session = None
