"""MyHouse skill handlers. On a screen: draw the page, leave the session open WITHOUT a reprompt (no microphone),
redraw after each tap / every 30 s. Without a screen: just say it."""

import logging
import time

from ask_sdk_core.dispatch_components import AbstractExceptionHandler, AbstractRequestHandler
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.utils import get_slot_value, is_intent_name, is_request_type
from ask_sdk_model.interfaces.alexa.presentation.apl import RenderDocumentDirective
from ask_sdk_model.interfaces.alexa.presentation.html import Configuration, StartDirective, StartRequest, StartRequestMethod

from . import actions, apl, deploy, pages, widgets

log = logging.getLogger("myhouse")
INTENT_PAGE = {"LightsOnIntent": "lights", "LightsOffIntent": "lights", "BoostIntent": "heating", "EndBoostIntent": "heating",
               "SetTargetIntent": "heating", "TemperatureIntent": "heating", "MusicIntent": "music"}


def _screen(handler_input):
    try:
        si = handler_input.request_envelope.context.system.device.supported_interfaces
        return getattr(si, "alexa_presentation_apl", None) is not None
    except Exception:
        return False


def _html(handler_input):
    try:
        si = handler_input.request_envelope.context.system.device.supported_interfaces
        return getattr(si, "alexa_presentation_html", None) is not None
    except Exception:
        return False


def _open_dashboard(handler_input, page="home", extra=None):
    """THE WHOLE CONTROL PANEL on the Show: open /control-panel/<page> signed in as the Echo Show user with a one-time
    code (signin.py - the Show's browser keeps nothing, so no stored sign-in). The front-door page (www/catballou.html)
    turns the code into the frontend's own sign-in. None when the Show can't (no web app support / no password set):
    the drawn screens are used instead."""
    from . import signin
    if not signin.configured() or not _html(handler_input):
        return None
    try:
        data = {"code": signin.code(), "state": signin.state(), "page": page, **(extra or {})}
    except Exception:
        log.exception("Peach Banana: signing the Show in failed")
        return None
    base = signin._cfg()["url"]
    rb = handler_input.response_builder
    rb.add_directive(StartDirective(data=data, request=StartRequest(uri=f"{base}/local/catballou.html?v={int(time.time())}", method=StartRequestMethod.GET),
                                    configuration=Configuration(timeout_in_seconds=1800)))
    return rb.response


def _page(handler_input, page=None):
    at = handler_input.attributes_manager.session_attributes
    if page:
        at["page"] = page
    return at.get("page", "home")


def _reply(handler_input, say=None, page=None, keep=True):
    rb = handler_input.response_builder
    if say:
        rb.speak(say)
    if _screen(handler_input):
        p = _page(handler_input, page)
        try:
            rb.add_directive(RenderDocumentDirective(token=apl.TOKEN, document=pages.render(p), datasources={}))
        except Exception:
            log.exception("MyHouse: drawing %s failed", p)
            if not say:
                rb.speak("Sorry, I couldn't read the house just now.")
        if not keep:
            rb.set_should_end_session(True)
        # (keep: shouldEndSession left unset - the page stays up, the microphone stays off)
    else:
        rb.set_should_end_session(True)
    return rb.response


class OurSkillOnly(AbstractRequestHandler):
    """Requests for any other skill id are refused (the endpoint is public)."""
    def can_handle(self, handler_input):
        sid = deploy.skill_id()
        try:
            app = handler_input.request_envelope.context.system.application.application_id
        except Exception:
            app = None
        return bool(sid) and app != sid

    def handle(self, handler_input):
        return handler_input.response_builder.set_should_end_session(True).response


def remember_user(handler_input):
    """The widgets' live data goes to this user (the skill-scoped Alexa user id), so it's kept from every request."""
    try:
        uid = handler_input.request_envelope.context.system.user.user_id
        d = deploy._load()
        if uid and d.get("user_id") != uid:
            d["user_id"] = uid
            deploy._save(d)
    except Exception:
        pass


class Widgets(AbstractRequestHandler):
    """Amazon's widget messages (installed / removed / update / errors): note the user and send the data straight away."""
    def can_handle(self, handler_input):
        t = getattr(handler_input.request_envelope.request, "object_type", "") or ""
        return t.startswith("Alexa.DataStore")

    def handle(self, handler_input):
        remember_user(handler_input)
        t = handler_input.request_envelope.request.object_type
        log.info("Peach Banana widgets: %s", t)
        if t.endswith("UsagesInstalled"):
            try:
                widgets.push(deploy._load().get("user_id"), force=True)
            except Exception:
                log.exception("Peach Banana widget push failed")
        return handler_input.response_builder.response


class Launch(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("LaunchRequest")(handler_input) or is_intent_name("AMAZON.NavigateHomeIntent")(handler_input)

    def handle(self, handler_input):
        remember_user(handler_input)
        if not _screen(handler_input):
            return _reply(handler_input, actions.temperature())
        return _open_dashboard(handler_input, "home") or _reply(handler_input, None, "home")


class ShowPage(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("ShowPageIntent")(handler_input)

    def handle(self, handler_input):
        if _unmatched(handler_input, "page"):
            return hand_off(handler_input)   # (not one of our pages - something for Alexa)
        p = (get_slot_value(handler_input, "page") or "home").lower()
        p = {"radiators": "heating", "rads": "heating", "the heating": "heating", "the lights": "lights", "the music": "music"}.get(p, p)
        dash = {"home": "home", "lights": "lights", "heating": "energy", "music": "music"}.get(p)
        return (_open_dashboard(handler_input, dash) if dash else None) or \
            _reply(handler_input, None if _screen(handler_input) else "Peach Banana needs a screen for that.", p if p in pages.PAGES else "home")


class Command(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return any(is_intent_name(n)(handler_input) for n in INTENT_PAGE)

    def handle(self, handler_input):
        name = handler_input.request_envelope.request.intent.name
        if name == "MusicIntent" and _unmatched(handler_input, "act"):
            return hand_off(handler_input)   # ("{act}" on its own catches all sorts)
        rm = get_slot_value(handler_input, "room")
        try:
            say = {
                "LightsOnIntent": lambda: actions.room_lights(rm, True) if rm else actions.all_lights(True),
                "LightsOffIntent": lambda: actions.room_lights(rm, False) if rm else actions.all_lights(False),
                "BoostIntent": lambda: actions.boost(rm or "", toggle=False),
                "EndBoostIntent": lambda: actions.end_boost(rm or "all"),
                "SetTargetIntent": lambda: actions.set_target(get_slot_value(handler_input, "temp")),
                "TemperatureIntent": lambda: actions.temperature(rm),
                "MusicIntent": lambda: actions.music(get_slot_value(handler_input, "act")) or "OK.",
            }[name]()
        except Exception:
            log.exception("MyHouse: %s failed", name)
            say = "Sorry, the house didn't answer."
        return _reply(handler_input, say, INTENT_PAGE[name])


class Touch(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("Alexa.Presentation.APL.UserEvent")(handler_input)

    def handle(self, handler_input):
        args = list(getattr(handler_input.request_envelope.request, "arguments", None) or [])
        kind = args[0] if args else ""
        if kind == "openPage":   # a widget: open Peach Banana (the control panel) on that page
            p = args[1] if len(args) > 1 else "home"
            return _open_dashboard(handler_input, {"hsettings": "settings-heating"}.get(p, p)) or _reply(handler_input, None, p)
        if kind == "page" and len(args) > 1:
            return _reply(handler_input, None, args[1])
        if kind == "tick":
            return _reply(handler_input, None, args[1] if len(args) > 1 else None)
        if kind == "act" and len(args) > 1:
            try:
                actions.do(args[1], args[2] if len(args) > 2 else "")
            except Exception:
                log.exception("MyHouse: tap %s failed", args)
                return _reply(handler_input, "Sorry, that didn't work.")
            return _reply(handler_input)   # (a tap answers with the redrawn page, quietly)
        return _reply(handler_input)


def restart(handler_input, msg):
    """The page asks to be OPENED AGAIN ({"type": "restart", "page", "saver", "resume"}): Alexa closes a web app after 30
    minutes without a touch (the longest it allows) and the Show then goes to its own home screen and slideshow, so the
    panel - showing its screensaver, the house movie - starts itself afresh a little before that. saver: straight back
    into the screensaver; resume: the music that was playing on the screen's own speaker carries on."""
    extra = {k: 1 for k in ("saver", "resume") if msg.get(k)}
    page = msg.get("page") if isinstance(msg.get("page"), str) and msg.get("page").isidentifier() else "home"
    log.info("Peach Banana: the page asked to be opened again (%s %s)", page, extra)
    return _open_dashboard(handler_input, page, extra)


class PageMessage(AbstractRequestHandler):
    """Messages from the control panel's front door. "stop-music": opening Peach Banana quits any music playing on this
    Echo (Music Assistant paused for its player - the music is the music skill's, so Peach Banana can't stop it itself)."""
    def can_handle(self, handler_input):
        return is_request_type("Alexa.Presentation.HTML.Message")(handler_input)

    def handle(self, handler_input):
        msg = getattr(handler_input.request_envelope.request, "message", None) or {}
        if isinstance(msg, dict) and msg.get("type") == "restart":
            r = restart(handler_input, msg)
            if r is not None:
                return r
        if isinstance(msg, dict) and msg.get("type") == "stop-music":
            try:
                from skill import lambda_function
                lambda_function._sync_to_ma_unless_echo(handler_input, "pause")
            except Exception:
                log.exception("Peach Banana: pausing the music failed")
        return handler_input.response_builder.response


def _resolved(handler_input, name):
    """The slot's value when it matched one of ours (ER_SUCCESS_MATCH), else None - "{page}" and "{act}" on their own
    otherwise catch whatever else is said ("set an alarm" heard as a page)."""
    try:
        slot = handler_input.request_envelope.request.intent.slots.get(name)
        for r in (slot.resolutions.resolutions_per_authority or []):
            if str(getattr(r.status.code, "value", r.status.code)) == "ER_SUCCESS_MATCH":
                return r.values[0].value.name
    except Exception:
        pass
    return None


def _unmatched(handler_input, name):
    """Said, but Alexa found it isn't one of the slot's values (ER_SUCCESS_NO_MATCH)."""
    try:
        slot = handler_input.request_envelope.request.intent.slots.get(name)
        return bool(slot and slot.value) and any(
            str(getattr(r.status.code, "value", r.status.code)) == "ER_SUCCESS_NO_MATCH"
            for r in (slot.resolutions.resolutions_per_authority or []))
    except Exception:
        return False


def _clock(t):
    """AMAZON.TIME "07:30" -> "7:30 am"; "MO"/"EV"... and anything else as it came."""
    try:
        h, m = (int(x) for x in t.split(":")[:2])
        return f"{h % 12 or 12}{':%02d' % m if m else ''} {'am' if h < 12 else 'pm'}"
    except Exception:
        return {"MO": "morning", "AF": "afternoon", "EV": "evening", "NI": "night"}.get(t, t)


def _duration(d):
    """AMAZON.DURATION "PT1H30M" -> "1 hour 30 minutes" (None if it isn't one)."""
    import re
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", d or "")
    if not m or not any(m.groups()):
        return None
    parts = [(int(v), u) for v, u in zip(m.groups(), ("day", "hour", "minute", "second")) if v]
    return " ".join(f"{n} {u}{'s' if n != 1 else ''}" for n, u in parts)


def hand_off(handler_input, text=None):
    """LET ALEXA DO IT, THEN COME BACK (the user, 24 Oct: with the panel open, "set an alarm" went to Peach Banana and was
    lost - "must be able to get back to my app after"). The session ends - the web app closes, so Alexa has the Echo
    again - and Home Assistant's script.peach_banana_handoff then says the request to this Echo as a text command (when
    it's one we understood: an alarm, a timer...) and opens Peach Banana again on the page it was on, once Alexa's
    done (a few seconds; a minute when the user has to say it again themselves)."""
    at = handler_input.attributes_manager.session_attributes
    page = {"heating": "energy"}.get(at.get("page"), at.get("page")) or "home"
    try:
        dev = handler_input.request_envelope.context.system.device.device_id
    except Exception:
        dev = None
    try:
        from . import ha
        ha.call("script", "turn_on", {"entity_id": "script.peach_banana_handoff",
                                      "variables": {"text": text or "", "page": page, "alexa_device": dev or "",
                                                    "back_after": 12 if text else 60}})
    except Exception:
        log.exception("Peach Banana: handing over to Alexa failed")
    log.info("Peach Banana: handing over to Alexa (%s)", text or "said again by the user")
    rb = handler_input.response_builder
    if not text:
        rb.speak("Over to Alexa - say that again. The panel comes back in a minute, or say: Alexa, open Peach Banana.")
    return rb.set_should_end_session(True).response


class HandOff(AbstractRequestHandler):
    """Alexa's own jobs said while the panel is open (alarms, timers...) and anything else Peach Banana doesn't know."""
    NAMES = ("AlarmIntent", "TimerIntent", "AlarmOpIntent", "TimerLeftIntent", "AMAZON.FallbackIntent")

    def can_handle(self, handler_input):
        return any(is_intent_name(n)(handler_input) for n in self.NAMES)

    def handle(self, handler_input):
        name = handler_input.request_envelope.request.intent.name
        text = None
        if name == "AlarmIntent":
            t = get_slot_value(handler_input, "time")
            text = f"set an alarm for {_clock(t)}" if t else None
        elif name == "TimerIntent":
            d = _duration(get_slot_value(handler_input, "dur"))
            text = f"set a timer for {d}" if d else None
        elif name == "AlarmOpIntent":
            op, thing = _resolved(handler_input, "op"), _resolved(handler_input, "thing")
            text = f"{op} my {thing}" if op and thing else None
        # (TimerLeftIntent / Fallback: the words said aren't sent to a skill - the user says it again to Alexa)
        return hand_off(handler_input, text)


class Help(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
        return _reply(handler_input, "Try: show the heating, turn on the kitchen lights, boost the living room, "
                          "set the house to 20 degrees, or pause the music.")


class Stop(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.StopIntent")(handler_input) or is_intent_name("AMAZON.CancelIntent")(handler_input)

    def handle(self, handler_input):
        return handler_input.response_builder.set_should_end_session(True).response


class Ended(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input):
        return handler_input.response_builder.response


class Oops(AbstractExceptionHandler):
    def can_handle(self, handler_input, exception):
        return True

    def handle(self, handler_input, exception):
        log.exception("MyHouse: unhandled", exc_info=exception)
        return handler_input.response_builder.speak("Sorry, something went wrong in MyHouse.").set_should_end_session(True).response


def build():
    sb = SkillBuilder()
    for h in (OurSkillOnly(), Widgets(), Launch(), ShowPage(), Command(), HandOff(), Touch(), PageMessage(), Help(), Stop(), Ended()):
        sb.add_request_handler(h)
    sb.add_exception_handler(Oops())
    return sb.create()
