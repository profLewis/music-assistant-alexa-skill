"""TIMERS AND ALARMS WITHOUT LEAVING THE PANEL (the user, 30 Oct: "cant we avoid letting alexa take over"): set through
Alexa's own Timers and Reminders services for skills, so the session stays open - the panel and the music on its screen
speaker carry on. Alexa has no such service for alarms: an alarm here is a reminder, spoken at that time, and says so.
False = not possible here (the permission not given in the Alexa app, or the service failed): the caller hands over."""

import logging
import re
from datetime import datetime, timedelta

from dateutil import tz
import requests

log = logging.getLogger("myhouse")
ZONE = "Europe/London"
LOCALE = "en-GB"
PERMISSIONS = ["alexa::alerts:timers:skill:readwrite", "alexa::alerts:reminders:skill:readwrite"]


def _post(handler_input, path, body):
    system = handler_input.request_envelope.context.system
    try:
        r = requests.post(f"{system.api_endpoint}{path}", json=body, timeout=3,
                          headers={"Authorization": f"Bearer {system.api_access_token}"})
    except requests.RequestException:
        log.exception("Alerts: %s didn't answer", path)
        return False
    if r.status_code >= 300:
        log.warning("Alerts: %s said %s %s", path, r.status_code, r.text[:200])
        return False
    return True


def _call(handler_input, method, path):
    """A reading or a cancelling: the answer's JSON ({} when it has none), None if not possible."""
    system = handler_input.request_envelope.context.system
    try:
        r = requests.request(method, f"{system.api_endpoint}{path}", timeout=3,
                             headers={"Authorization": f"Bearer {system.api_access_token}"})
        if r.status_code >= 300:
            log.warning("Alerts: %s said %s %s", path, r.status_code, r.text[:200])
            return None
        return r.json() if r.content else {}
    except (requests.RequestException, ValueError):
        log.exception("Alerts: %s didn't answer", path)
        return None


def timers_left(handler_input, now=None):
    """Seconds left on each timer set from this skill, soonest first; None if Alexa won't say."""
    got = _call(handler_input, "GET", "/v1/alerts/timers")
    if got is None:
        return None
    now = now or datetime.now(tz.UTC)
    left = []
    for t in got.get("timers") or []:
        if t.get("status") == "ON" and t.get("triggerTime"):
            left.append(int((datetime.fromisoformat(t["triggerTime"].replace("Z", "+00:00")) - now).total_seconds()))
    return sorted(x for x in left if x > 0)


def alarms_set(handler_input):
    """[(token, "2026-10-31T07:30:00.000")] of the alarms set from this skill, soonest first; None if Alexa won't say."""
    got = _call(handler_input, "GET", "/v1/alerts/reminders")
    if got is None:
        return None
    return sorted(((a["alertToken"], a["trigger"]["scheduledTime"]) for a in got.get("alerts") or []
                   if a.get("status") == "ON" and (a.get("trigger") or {}).get("scheduledTime")), key=lambda x: x[1])


def cancel_timers(handler_input):
    """How many were cancelled; None if not possible."""
    left = timers_left(handler_input)
    if left is None:
        return None
    if left and _call(handler_input, "DELETE", "/v1/alerts/timers") is None:
        return None
    return len(left)


def cancel_alarms(handler_input):
    """How many were cancelled; None if not possible."""
    al = alarms_set(handler_input)
    if al is None:
        return None
    for token, _at in al:
        if _call(handler_input, "DELETE", f"/v1/alerts/reminders/{token}") is None:
            return None
    return len(al)


def timer(handler_input, iso_duration):
    """AMAZON.DURATION "PT5M" as it came (Alexa's timers take the same form)."""
    return _post(handler_input, "/v1/alerts/timers", {
        "duration": iso_duration,
        "timerLabel": "Timer",
        "creationBehavior": {"displayExperience": {"visibility": "VISIBLE"}},
        "triggeringBehavior": {"operation": {"type": "ANNOUNCE", "textToAnnounce": [{"locale": LOCALE, "text": "Your timer is up."}]},
                               "notificationConfig": {"playAudible": True}}})


def next_time(clock, now=None):
    """AMAZON.TIME "07:30" -> the next time it's 7:30 here; None for "MO" and the like, which name no time."""
    if not re.fullmatch(r"\d{1,2}:\d{2}", clock or ""):
        return None
    now = now or datetime.now(tz.gettz(ZONE))
    h, m = (int(x) for x in clock.split(":"))
    at = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return at if at > now else at + timedelta(days=1)


# ALARM OR TIMER? (the owner, 15 Nov 2026: "it is mostly things like 'Alexa set an alarm for 19 minutes' when we mean a timer
# really. Auto correct that" - "treat alarm and timer the same"). What was SAID (alarm / timer) matters less than HOW: a length
# ("in 19 minutes", "for 90 minutes") is a timer when it ends within SOON; a clock time ("for 7", "at 6:30") is an alarm. A long
# length said for an alarm ("an alarm in 8 hours") stays an alarm, at that time. The same rule is in the house:
# custom_templates/alarm_or_timer.jinja (Assist) and www/alarm-kind.js (the pages) - keep them alike.
SOON = 3 * 3600


def seconds(iso):
    """AMAZON.DURATION "PT1H30M" -> 5400; None if it names no length."""
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", iso or "")
    if not m or not any(m.groups()):
        return None
    return sum(int(v or 0) * u for v, u in zip(m.groups(), (86400, 3600, 60, 1))) or None


def iso(secs):
    """5400 -> "PT1H30M" (Alexa's timers take this form)."""
    h, m, s = secs // 3600, secs % 3600 // 60, secs % 60
    return "PT" + (f"{h}H" if h else "") + (f"{m}M" if m else "") + (f"{s}S" if s or not (h or m) else "")


def classify(said, clock=None, dur=None, now=None):
    """("timer", seconds) or ("alarm", local datetime) - or None when neither a time nor a length was heard.
    said: "alarm" or "timer" (the word used); clock: AMAZON.TIME "07:30"; dur: AMAZON.DURATION "PT19M"."""
    secs = seconds(dur)
    now = now or datetime.now(tz.gettz(ZONE))
    if secs:
        if said == "timer" or secs <= SOON:
            return ("timer", secs)
        return ("alarm", now + timedelta(seconds=secs))
    at = next_time(clock, now)
    return ("alarm", at) if at else None


def alarm(handler_input, clock, words, now=None):
    return alarm_at(handler_input, next_time(clock, now), words)


def alarm_at(handler_input, at, words):
    if at is None:
        return False
    return _post(handler_input, "/v1/alerts/reminders", {
        "requestTime": datetime.now(tz.UTC).strftime("%Y-%m-%dT%H:%M:%S.000"),
        "trigger": {"type": "SCHEDULED_ABSOLUTE", "scheduledTime": at.strftime("%Y-%m-%dT%H:%M:%S.000"), "timeZoneId": ZONE},
        "alertInfo": {"spokenInfo": {"content": [{"locale": LOCALE, "text": f"It's {words}. This is your alarm."}]}},
        "pushNotification": {"status": "ENABLED"}})
