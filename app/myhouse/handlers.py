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


def _open_dashboard(handler_input, page="home"):
    """THE WHOLE CONTROL PANEL on the Show: open /control-panel/<page> signed in as the Echo Show user with a one-time
    code (signin.py - the Show's browser keeps nothing, so no stored sign-in). The front-door page (www/catballou.html)
    turns the code into the frontend's own sign-in. None when the Show can't (no web app support / no password set):
    the drawn screens are used instead."""
    from . import signin
    if not signin.configured() or not _html(handler_input):
        return None
    try:
        data = {"code": signin.code(), "state": signin.state(), "page": page}
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


class Launch(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("LaunchRequest")(handler_input) or is_intent_name("AMAZON.NavigateHomeIntent")(handler_input)

    def handle(self, handler_input):
        if not _screen(handler_input):
            return _reply(handler_input, actions.temperature())
        return _open_dashboard(handler_input, "home") or _reply(handler_input, None, "home")


class ShowPage(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("ShowPageIntent")(handler_input)

    def handle(self, handler_input):
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


class Help(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.HelpIntent")(handler_input) or is_intent_name("AMAZON.FallbackIntent")(handler_input)

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
    for h in (OurSkillOnly(), Launch(), ShowPage(), Command(), Touch(), Help(), Stop(), Ended()):
        sb.add_request_handler(h)
    sb.add_exception_handler(Oops())
    return sb.create()
