"""MyHouse skill handlers. On a screen: draw the page, leave the session open WITHOUT a reprompt (no microphone),
redraw after each tap / every 30 s. Without a screen: just say it."""

import html
import logging
import re
import time

from ask_sdk_core.dispatch_components import AbstractExceptionHandler, AbstractRequestHandler, AbstractResponseInterceptor
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.utils import get_slot_value, is_intent_name, is_request_type
from ask_sdk_model.interfaces.alexa.presentation.apl import RenderDocumentDirective
from ask_sdk_model.interfaces.alexa.presentation.html import Configuration, StartDirective, StartRequest, StartRequestMethod

from . import actions, alerts, apl, deploy, ha, model, pages, widgets

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
    # THE FULL PANEL OPEN (an Echo Show with the web app - HTML): never draw the old built-in screens over it (the user, 4 Nov 2026:
    # "a weird version of Peach Banana is running on the Moon" - a lights / heating answer replaced the panel with them). Speak,
    # and turn the panel itself to that page (input_text.show_remote, read by the panel); the session stays open.
    if _html(handler_input):
        dash = {"heating": "rads", "lights": "lights", "music": "music", "home": "home"}.get(page or "")
        if dash:
            try:
                import time as _t
                ha.call("input_text", "set_value", {"entity_id": "input_text.show_remote", "value": f"{int(_t.time())} {dash}"})
            except Exception:
                log.exception("Peach Banana: turning the panel to %s", dash)
        return rb.response
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
            # (not one of our pages: the words were heard, so the AI helper tries first)
            said = get_slot_value(handler_input, "page")
            return ask_ai_said(handler_input, said) if said else hand_off(handler_input)
        p = (get_slot_value(handler_input, "page") or "home").lower()
        p = {"radiators": "heating", "rads": "heating", "the heating": "heating", "the lights": "lights", "the music": "music"}.get(p, p)
        if p in ("apesma", "a pesma", "ape smart", "apes ma", "a pes ma", "music app", "the music app", "music assistant", "the music assistant app"):
            p = "apesma"
        dash = {"home": "home", "lights": "lights", "heating": "energy", "music": "music", "apesma": "apesma"}.get(p)
        return (_open_dashboard(handler_input, dash) if dash else None) or \
            _reply(handler_input, None if _screen(handler_input) else "Peach Banana needs a screen for that.", p if p in pages.PAGES else "home")


class Command(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return any(is_intent_name(n)(handler_input) for n in INTENT_PAGE)

    def handle(self, handler_input):
        name = handler_input.request_envelope.request.intent.name
        if name == "MusicIntent" and _unmatched(handler_input, "act"):
            # ("{act}" on its own catches all sorts: the AI helper tries first)
            said = get_slot_value(handler_input, "act")
            return ask_ai_said(handler_input, said) if said else hand_off(handler_input)
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


def volume(handler_input):
    """VolumeIntent (model.VOLUME_INTENT) in either skill: the Echo's volume set; with a panel open nothing is said and
    the session is left as it was (the page stays, the music plays on); otherwise a short OK."""
    d, lvl = _resolved(handler_input, "dir"), get_slot_value(handler_input, "level")
    try:
        dev = handler_input.request_envelope.context.system.device.device_id
    except Exception:
        dev = None
    try:
        actions.echo_volume(d, lvl, dev)
    except Exception:
        log.exception("Volume: Home Assistant didn't answer")
    log.info("Volume: %s", d or f"to {lvl}")
    rb = handler_input.response_builder
    if _html(handler_input):
        return rb.response
    return rb.speak("OK.").set_should_end_session(True).response


class Volume(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("VolumeIntent")(handler_input)

    def handle(self, handler_input):
        return volume(handler_input)


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


def _alexa_at(entity):
    """Alexa's own next alarm / timer on The moon (Home Assistant reads them): a local datetime if it's still to come."""
    from datetime import datetime
    from dateutil import tz
    from . import ha
    try:
        at = datetime.fromisoformat(ha.state(entity) or "")
        at = at if at.tzinfo else at.replace(tzinfo=tz.UTC)
        return at.astimezone(tz.gettz(alerts.ZONE)) if at > datetime.now(tz.UTC) else None
    except Exception:
        return None


def _left_words(secs):
    h, m = secs // 3600, (secs % 3600 + 59) // 60
    if not h and secs < 60:
        return f"{secs} seconds"
    return _duration(f"PT{h}H{m}M" if h else f"PT{m}M")


# (the user, 31 Oct: "set a timer" went to Alexa because the skill hasn't the permission: the house keeps them instead - script.peach_alert)
def _house_set(kind, at, secs=0):
    try:
        return bool(ha.alert("set", kind, int(at), secs).get("ok"))
    except Exception:
        log.exception("Peach Banana: the house couldn't set the %s", kind)
        return False


def _house_cancel(kind):
    try:
        return int(ha.alert("cancel", kind).get("count") or 0)
    except Exception:
        log.exception("Peach Banana: the house couldn't cancel the %s", kind)
        return 0


def _house_list():
    try:
        return ha.alert("list").get("items") or []
    except Exception:
        log.exception("Peach Banana: the house couldn't list its timers")
        return None


def _seconds(d):
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", d)
    return sum(int(v or 0) * u for v, u in zip(m.groups(), (86400, 3600, 60, 1)))


def alerts_said(handler_input):
    """What's set, in words: from this skill and Alexa's own. None if Alexa won't say (no permission)."""
    left, al = alerts.timers_left(handler_input) or [], alerts.alarms_set(handler_input) or []
    words = [f"{_left_words(x)} left on a timer" for x in left]
    from datetime import datetime
    from dateutil import tz
    kept = _house_list()
    if kept is None and not left and not al:
        return None
    for it in kept or []:
        when = datetime.fromtimestamp(it["a"], tz.gettz(alerts.ZONE))
        words.append(f"{_left_words(int(it['a'] - time.time()))} left on a timer" if it["k"] == "timer" else f"an alarm at {_clock(when.strftime('%H:%M'))}")
    words += [f"an alarm at {_clock(at[11:16])}" for _t, at in al]
    own_t, own_a = _alexa_at("sensor.the_moon_next_timer"), _alexa_at("sensor.the_moon_next_alarm")
    if own_t and not left:
        words.append(f"a timer ending at {_clock(own_t.strftime('%H:%M'))}")
    if own_a and not any(at[11:16] == own_a.strftime("%H:%M") for _t, at in al):
        words.append(f"an alarm at {_clock(own_a.strftime('%H:%M'))}")
    return "You have " + ", and ".join(words) + "." if words else "You have no alarms or timers."


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
        rb = handler_input.response_builder
        # (done from here when Alexa's services allow it: the session stays open, as for the volume)
        if name == "AlarmIntent":
            t = get_slot_value(handler_input, "time")
            if not alerts.next_time(t):
                return rb.speak("What time?").response
            if alerts.alarm(handler_input, t, _clock(t)) or _house_set("alarm", alerts.next_time(t).timestamp()):
                log.info("Peach Banana: alarm set here (%s)", t)
                return rb.speak(f"OK, {_clock(t)}. I'll say it, rather than ring.").response
            text = f"set an alarm for {_clock(t)}"
        elif name == "TimerIntent":
            raw = get_slot_value(handler_input, "dur")
            d = _duration(raw)
            if not d:
                return rb.speak("How long for?").response
            if alerts.timer(handler_input, raw) or _house_set("timer", time.time() + _seconds(raw), _seconds(raw)):
                log.info("Peach Banana: timer set here (%s)", raw)
                return rb.speak(f"OK, {d}.").response
            text = f"set a timer for {d}"
        elif name == "AlarmOpIntent":
            op, thing = _resolved(handler_input, "op"), _resolved(handler_input, "thing")
            if op == "show":
                said = alerts_said(handler_input)
                if said:
                    return rb.speak(said).response
            elif op == "cancel" and thing:
                timers = thing.startswith("timer")
                n = (alerts.cancel_timers(handler_input) if timers else alerts.cancel_alarms(handler_input)) or 0
                n += _house_cancel("timer" if timers else "alarm")
                if n:
                    log.info("Peach Banana: cancelled %s %s here", n, thing)
                    return rb.speak(f"OK, cancelled {n} {thing.rstrip('s')}{'s' if n != 1 else ''}.").response
                # (none here: it may be one set with Alexa, which only Alexa can cancel - so only if it's asked for twice)
                ses = handler_input.attributes_manager.session_attributes
                if not ses.get("no_alert"):
                    ses["no_alert"] = True
                    return rb.speak(f"There's no {thing.rstrip('s')} set here. If Alexa set it, say that again and I'll pass it on.").response
            text = f"{op} my {thing}" if op and thing else None
        elif name == "TimerLeftIntent":
            said = alerts_said(handler_input)
            if said:
                return rb.speak(said).response
        # (Fallback: the words said aren't sent to a skill. Once, ask again and keep the panel; then the user says it again to Alexa)
        at = handler_input.attributes_manager.session_attributes
        if name == "AMAZON.FallbackIntent" and not at.get("asked_again"):
            at["asked_again"] = True
            return rb.speak("Sorry, I didn't catch that. Try again, starting with: ask.").response
        return hand_off(handler_input, text)


class AskAI(AbstractRequestHandler):
    """Free questions go to the AI helper, so the session stays open; with it off, Alexa is given the words (the panel closes)."""

    def can_handle(self, handler_input):
        return any(is_intent_name(n)(handler_input) for n in model.ASK_INTENTS)

    def handle(self, handler_input):
        word = model.ASK_INTENTS[handler_input.request_envelope.request.intent.name][0]
        q = get_slot_value(handler_input, "q")
        text = f"{word} {q}".strip() if q else None
        if not text:
            return hand_off(handler_input)
        # ("Alexa, ask peach banana to play radio four" said WITH the panel open lands here as a question - 5 Nov 2026 the AI
        #  answered "I'm not quite sure what you'd like me to do". The skill's own name is dropped, and play / turn on goes to
        #  the player, as "play {what}" does.)
        rest = re.sub(r"^(ask|tell)?\s*(the\s+)?peach(es)?\s*bananas?\s*(to\s+|and\s+)?", "", text.strip(), flags=re.I).strip()
        if rest != text.strip():
            if not rest:
                return _reply(handler_input, "Yes?")
            m = re.match(r"^(please\s+)?(play|put on|turn on|switch on|start|listen to|tune (?:in )?to)\s+(.+)$", rest, re.I)
            if m:
                return play_this(handler_input, m.group(3))
        return ask_ai_said(handler_input, rest or text)


class AskThing(AbstractRequestHandler):
    """"A joke", "another riddle", "the news" said on their own (the user, 6 Nov 2026: as much as possible to the AI)."""
    def can_handle(self, handler_input):
        return is_intent_name("AskThingIntent")(handler_input)

    def handle(self, handler_input):
        thing = get_slot_value(handler_input, "asked")
        try:   # (the list's own word, not the synonym heard)
            rs = handler_input.request_envelope.request.intent.slots["asked"].resolutions.resolutions_per_authority[0]
            thing = rs.values[0].value.name or thing
        except Exception:
            pass
        if not thing:
            return _reply(handler_input, "What would you like to know?")
        text = {"news": "what's in the news today", "weather": "what's the weather going to be like",
                "conversation": "let's have a chat"}.get(thing, f"tell me a {thing}")
        return ask_ai_said(handler_input, text)


def ask_ai_said(handler_input, text):
    rb = handler_input.response_builder
    at = handler_input.attributes_manager.session_attributes
    try:
        got = ha.ask_ai(text, at.get("ai_chat", ""))
    except Exception:
        log.exception("Peach Banana: the AI helper didn't answer")
        return rb.speak("Sorry, the AI helper didn't answer in time.").response
    if got.get("why") == "off":
        return hand_off(handler_input, text)
    if not got.get("ok"):
        log.warning("Peach Banana: the AI helper failed: %s", got)
        return rb.speak("Sorry, the AI helper couldn't answer that.").response
    # (kept so a follow-up continues the same conversation)
    at["ai_chat"] = got.get("conversation_id", "")
    return rb.speak(_spoken(got["answer"])).response


def _spoken(answer):
    return html.escape(re.sub(r"[*_#`]", "", answer), quote=False)


class Time(AbstractRequestHandler):
    """"What time is it" / "what's the time": the AI helper answers (the user, 6 Nov 2026: "does 'Alexa what is the time' or
    similar phrases go to my AI in Peach Banana? if not then make it so" - it is told the time at home with every question).
    The AI off / not answering: the clock said here, as before (never "sorry" for the time)."""
    def can_handle(self, handler_input):
        return is_intent_name("TimeIntent")(handler_input)

    def handle(self, handler_input):
        from datetime import datetime
        from dateutil import tz
        at = handler_input.attributes_manager.session_attributes
        try:
            got = ha.ask_ai("what time is it", at.get("ai_chat", ""))
            if got.get("ok") and got.get("answer"):
                at["ai_chat"] = got.get("conversation_id", "")
                return handler_input.response_builder.speak(_spoken(got["answer"])).response
        except Exception:
            log.exception("Peach Banana: the AI helper didn't answer the time")
        return handler_input.response_builder.speak(f"It's {_clock(datetime.now(tz.gettz(alerts.ZONE)).strftime('%H:%M'))}.").response


class GoodMorning(AbstractRequestHandler):
    """"Alexa, good morning": what the house says it does (script.peach_good_morning - the time, then Radio 4 on the panel).
    The house failing still gets a good morning and the time."""
    def can_handle(self, handler_input):
        return is_intent_name("GoodMorningIntent")(handler_input)

    def handle(self, handler_input):
        from datetime import datetime
        from dateutil import tz
        now = _clock(datetime.now(tz.gettz(alerts.ZONE)).strftime('%H:%M'))
        handler_input.attributes_manager.request_attributes["music_starting"] = True   # (Radio 4 starts: no listening window over it)
        try:
            say = ha.good_morning().get("say") or f"Good morning. It's {now}."
        except Exception:
            log.exception("Peach Banana: good morning didn't reach the house")
            say = f"Good morning. It's {now}. Sorry, the house didn't answer, so there's no radio."
        return handler_input.response_builder.speak(_spoken(say)).response


class Help(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
        return _reply(handler_input, "Try: show the heating, turn on the kitchen lights, boost the living room, "
                          "set the house to 20 degrees, or pause the music.")


class PlayThis(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("PlayThisIntent")(handler_input)

    def handle(self, handler_input):
        return play_this(handler_input, get_slot_value(handler_input, "what"))


class Load(AbstractRequestHandler):
    """LOAD it ready to play (the user, 5 Nov 2026) - the house plays it and pauses it the moment it starts."""
    def can_handle(self, handler_input):
        return is_intent_name("LoadIntent")(handler_input)

    def handle(self, handler_input):
        what = get_slot_value(handler_input, "what")
        return play_this(handler_input, ("load " + what) if what else None)


class PlayerControl(AbstractRequestHandler):
    """Unload, shuffle on / off, repeat on / off - the player that's playing (script.peach_play does it)."""
    def can_handle(self, handler_input):
        return is_intent_name("PlayerControlIntent")(handler_input)

    def handle(self, handler_input):
        rb = handler_input.response_builder
        ctl = (_resolved(handler_input, "ctl") or get_slot_value(handler_input, "ctl") or "").lower()
        if not ctl:
            return rb.speak("Shuffle, repeat or unload?").response
        try:
            got = ha.play_this(ctl)
        except Exception:
            log.exception("Peach Banana: player control %s", ctl)
            return rb.speak("Sorry, Music Assistant didn't answer.").response
        handler_input.attributes_manager.request_attributes["music_starting"] = True   # (no listening window over the music)
        return rb.speak(f"OK, {got.get('name') or ctl}.").response


class Shopping(AbstractRequestHandler):
    """THE SHOPPING LIST (the user, 5 Nov 2026: "if i say 'put xxx on the shopping list' to alexa I want it passed through to
    the alexa shopping list" - at 18:29 "put vegetarian suet on the shopping list" was heard as a radio station and Peach Banana
    said "Playing Shopping List"). Alexa's own list, changed by the house (script.peach_shopping); the panel and music left alone."""
    def can_handle(self, handler_input):
        return is_intent_name("ShoppingAddIntent")(handler_input) or is_intent_name("ShoppingRemoveIntent")(handler_input)

    def handle(self, handler_input):
        rb = handler_input.response_builder
        add = is_intent_name("ShoppingAddIntent")(handler_input)
        item = (get_slot_value(handler_input, "item") or "").strip()
        if not item:
            return rb.speak("What shall I " + ("put on" if add else "take off") + " the shopping list?").ask("What is it?").response
        try:
            got = ha.shopping("add" if add else "remove", item)
        except Exception:
            log.exception("Peach Banana: shopping list %s", item)
            return rb.speak("Sorry, I couldn't reach the shopping list.").response
        name = got.get("item") or item
        if add:
            return rb.speak(f"I've put {name} on your shopping list.").response
        if got.get("ok"):
            return rb.speak(f"I've taken {name} off your shopping list.").response
        return rb.speak(f"{name} isn't on your shopping list.").response


class Radio(AbstractRequestHandler):
    """A BBC station by name (RadioIntent - the station list in model.STATIONS): as "play {what}", with the station's own name."""
    def can_handle(self, handler_input):
        return is_intent_name("RadioIntent")(handler_input)

    def handle(self, handler_input):
        said = get_slot_value(handler_input, "station") or "the radio"
        try:   # (the station's own name when Alexa matched one of its ways of saying it)
            slot = handler_input.request_envelope.request.intent.slots.get("station")
            for r in (slot.resolutions.resolutions_per_authority or []):
                if str(getattr(r.status.code, "value", r.status.code)) == "ER_SUCCESS_MATCH" and r.values:
                    said = r.values[0].value.name
                    break
        except Exception:
            pass
        return play_this(handler_input, said)


class Books(AbstractRequestHandler):
    """Audible books and podcasts by voice (MyBookIntent / BookIntent / PodcastIntent): the house's peach_play knows "my book" (the
    last one), "audiobook <title>" (one of your books) and "podcast <name>"."""
    def can_handle(self, handler_input):
        return any(is_intent_name(n)(handler_input) for n in ("MyBookIntent", "BookIntent", "PodcastIntent"))

    def handle(self, handler_input):
        name = handler_input.request_envelope.request.intent.name
        title = (get_slot_value(handler_input, "title") or "").strip()
        what = "my book" if name == "MyBookIntent" or not title else ("audiobook " if name == "BookIntent" else "podcast ") + title
        return play_this(handler_input, what)


def play_this(handler_input, what):
    rb = handler_input.response_builder
    if not what:
        return rb.speak("What would you like to play?").response
    # ("turn on the kitchen lights" is the LIGHTS, not music to play - "turn on {what}" catches it too)
    import re as _re
    if _re.search(r"\blights?\b|\blamps?\b", what.lower()):
        rm = _re.sub(r"\b(the|lights?|lamps?|on|in|all)\b", " ", what.lower()).strip()
        try:
            say = actions.room_lights(rm, True) if rm else actions.all_lights(True)
        except Exception:
            log.exception("Peach Banana: lights from turn on")
            say = "Sorry, the house didn't answer."
        return _reply(handler_input, say, "lights")
    # THE PANEL SHUT, ON THE SHOW (the user, 5 Nov 2026: "I can't have it starting in the R4 player" - the routines send
    # "ask peach banana to play …" before Alexa's own player can start): open the panel on the Music page, and the house
    # plays it there as soon as the panel's own speaker is connected (script.peach_play_when_ready) - in the valve radio.
    env = handler_input.request_envelope
    if _html(handler_input) and env.session is not None and env.session.new:
        try:
            ha.call("script", "turn_on", {"entity_id": "script.peach_play_when_ready", "variables": {"text": what}})
        except Exception:
            log.exception("Peach Banana: play when ready %s", what)
        opened = _open_dashboard(handler_input, "music")
        if opened is not None:
            handler_input.attributes_manager.request_attributes["music_starting"] = True
            return opened
    # ON AN ECHO WITHOUT THE PANEL: on that Echo (its Music Assistant player, from the add-on's device mapping)
    mine = None
    if not _html(handler_input):
        try:
            from skill.device_mapping import get_player_for_device
            mine = get_player_for_device(env.context.system.device.device_id)
        except Exception:
            log.exception("Peach Banana: which player is this Echo")
    if not _html(handler_input) and not mine:
        # (which Echo this is, the house can tell from its voice logs: script.peach_play_here plays it there)
        try:
            ha.call("script", "turn_on", {"entity_id": "script.peach_play_here", "variables": {"text": what}})
        except Exception:
            log.exception("Peach Banana: play here %s", what)
            return rb.speak("Sorry, the house didn't answer.").set_should_end_session(True).response
        return rb.speak("OK.").set_should_end_session(True).response
    try:
        got = ha.play_this(what, mine)
    except Exception:
        log.exception("Peach Banana: couldn't play %s", what)
        return rb.speak("Sorry, Music Assistant didn't answer.").response
    if not got.get("ok"):
        return rb.speak(f"Sorry, I couldn't find {_spoken(what)}.").response
    # (music is starting: no listening window after this answer - 5 Nov 2026, "play radio four" with the panel open was
    #  answered "there was a problem with the requested skill's response" while the music began under an open microphone)
    handler_input.attributes_manager.request_attributes["music_starting"] = True
    if what.lower().startswith("load "):
        return rb.speak(f"{_spoken(got.get('name', what))} is loaded, ready to play.").response
    return rb.speak(f"Playing {_spoken(got.get('name', what))}.").response


def _music_playing():
    try:
        sh = actions._shift()
        if sh and not sh.get("p"):
            return True   # (the rewound radio, played by the panel itself)
        return any(ha.state(p) == "playing" for p in actions._players())
    except Exception:
        log.exception("Peach Banana: couldn't see the music")
        return False


class PauseResume(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.PauseIntent")(handler_input) or is_intent_name("AMAZON.ResumeIntent")(handler_input)

    def handle(self, handler_input):
        actions.music("pause" if is_intent_name("AMAZON.PauseIntent")(handler_input) else "play")
        return handler_input.response_builder.response


class Stop(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.StopIntent")(handler_input) or is_intent_name("AMAZON.CancelIntent")(handler_input)

    def handle(self, handler_input):
        # (the user, 31 Oct: "if they say pause or stop it should refer to that": the music stops and the panel stays; said again, it closes)
        if _music_playing():
            actions.music("pause")
            return handler_input.response_builder.response
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


class ListeningWindow(AbstractResponseInterceptor):
    """THE LISTENING WINDOW (the user, 4 Nov 2026: "can't you do it in Peach Banana - so I needn't say Alexa" - "go on, but make sure
    it doesn't interfere with what's playing"): after Peach Banana SPEAKS an answer, the microphone stays open about 8 s (the
    blue ring) so the next thing can be said without "Alexa" - each answer opens a new window. Only when NOTHING is playing on
    the Moon (its Peach Banana speaker, or the Echo itself): listening would duck the music. Never on a reply that ends the
    session or starts music; no reprompt at all (no "anything else?" - and a silent one is refused by Amazon). input_boolean.peach_listen switches it off."""
    def process(self, handler_input, response):
        try:
            if response is None or response.output_speech is None or response.should_end_session is True or response.reprompt is not None:
                return
            if handler_input.attributes_manager.request_attributes.get("music_starting"):
                return
            if (response.directives or []) and any("AudioPlayer" in type(d).__name__ for d in response.directives):
                return
            if ha.state("input_boolean.peach_listen", "on") == "off":
                return
            if any(ha.state(p) == "playing" for p in ("media_player.the_moon_screen", "media_player.the_moon", "media_player.kitchen_the_moon")):
                return
            # (NO reprompt: a silent one - <break time="1ms"/> - is refused by Amazon, "SSML does not contain any speech content",
            # and the whole answer with it: "a problem with the requested skill's response" and Peach Banana closed - the user,
            # 6 Nov 2026, "Alexa, good morning". shouldEndSession false alone opens the microphone after the answer.)
            response.should_end_session = False
        except Exception:
            log.exception("Peach Banana: listening window")


def PeachJournal(base):
    """The music skill's SkillJournal, its events marked skill: peach banana."""
    class _J(base):
        @staticmethod
        def _send(body):
            base._send({**body, "skill": "peach banana"})
    return _J()


def build():
    sb = SkillBuilder()
    for h in (OurSkillOnly(), Widgets(), Launch(), ShowPage(), Volume(), Command(), Time(), GoodMorning(), AskThing(), Radio(), Books(), Shopping(), Load(), PlayerControl(), PlayThis(), PauseResume(), AskAI(), HandOff(), Touch(), PageMessage(), Help(), Stop(), Ended()):
        sb.add_request_handler(h)
    sb.add_global_response_interceptor(ListeningWindow())
    try:   # (every request and answer noted in Home Assistant, as the music skill does - event skill_journal, skill "peach banana")
        from skill.lambda_function import SkillJournal
        j = PeachJournal(SkillJournal)
        sb.add_global_request_interceptor(j)
        sb.add_global_response_interceptor(j)
    except Exception:
        log.exception("Peach Banana: no skill journal")
    sb.add_exception_handler(Oops())
    return sb.create()
