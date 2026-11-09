"""MyHouse: talking to Home Assistant from inside the add-on (Supervisor proxy, the add-on's own token -
config.yaml has homeassistant_api: true). Small, synchronous, with a short-lived cache of all states so one
screen draw costs one request."""

import os
import time

import requests

BASE = os.environ.get("MYHOUSE_HA_URL", "http://supervisor/core/api")
_cache = {"at": 0.0, "states": {}}


def _headers():
    token = os.environ.get("SUPERVISOR_TOKEN") or os.environ.get("MYHOUSE_HA_TOKEN", "")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def states(max_age=2.0):
    """{entity_id: state dict} - re-read when older than max_age seconds."""
    if time.time() - _cache["at"] > max_age:
        r = requests.get(f"{BASE}/states", headers=_headers(), timeout=8)
        r.raise_for_status()
        _cache["states"] = {s["entity_id"]: s for s in r.json()}
        _cache["at"] = time.time()
    return _cache["states"]


def state(entity_id, default=None):
    s = states().get(entity_id)
    return s["state"] if s else default


def attr(entity_id, name, default=None):
    s = states().get(entity_id)
    return (s.get("attributes") or {}).get(name, default) if s else default


def call(domain, service, data=None):
    """Call a service; the next read sees fresh states."""
    r = requests.post(f"{BASE}/services/{domain}/{service}", headers=_headers(), json=data or {}, timeout=15)
    r.raise_for_status()
    _cache["at"] = 0.0
    return r.json()


def alert(action, kind="", at=0, secs=0):
    """script.peach_alert: timers and alarms kept by the house ({ok, count, items: [{k, a}]}), so no Alexa permission is needed. Raises if it fails."""
    r = requests.post(f"{BASE}/services/script/peach_alert?return_response", headers=_headers(), json={"action": action, "kind": kind, "at": at, "secs": secs}, timeout=3)
    r.raise_for_status()
    return r.json().get("service_response") or {}


def play_this(text, ma_player_id=None):
    """script.peach_play: the best match for the words starts playing ({ok, name, kind}) - on that Music Assistant player
    when given (the Echo that was asked), else on the house's chosen one. Raises if it fails."""
    body = {"text": text, **({"ma_player_id": ma_player_id} if ma_player_id else {})}
    r = requests.post(f"{BASE}/services/script/peach_play?return_response", headers=_headers(), json=body, timeout=6.5)
    r.raise_for_status()
    return r.json().get("service_response") or {}


def shopping(op, item):
    """script.peach_shopping: add to / take off ALEXA'S OWN shopping list ({ok, item}). Raises if it fails."""
    r = requests.post(f"{BASE}/services/script/peach_shopping?return_response", headers=_headers(), json={"op": op, "item": item}, timeout=6.5)
    r.raise_for_status()
    return r.json().get("service_response") or {}


def good_morning():
    """script.peach_good_morning: what "Alexa, good morning" does, kept by the house ({say}) - the time, Radio 4 on the panel. Raises if it fails."""
    r = requests.post(f"{BASE}/services/script/peach_good_morning?return_response", headers=_headers(), json={}, timeout=6.5)
    r.raise_for_status()
    return r.json().get("service_response") or {}


def ask_ai(text, conversation_id="", timeout=6.5):
    """script.ai_ask's answer ({ok, why, answer, conversation_id}), inside the time Alexa waits for a skill. Raises if too slow or it fails."""
    r = requests.post(f"{BASE}/services/script/ai_ask?return_response", headers=_headers(), json={"text": text, "conversation_id": conversation_id}, timeout=timeout)
    r.raise_for_status()
    return r.json().get("service_response") or {}


def hush():
    """script.peach_hush: a timer or alarm the house is sounding on the Moon is stopped ({stopped, what}). Raises if it fails."""
    r = requests.post(f"{BASE}/services/script/peach_hush?return_response", headers=_headers(), json={}, timeout=3)
    r.raise_for_status()
    _cache["at"] = 0.0
    return r.json().get("service_response") or {}


def journal(body):
    """A line in the skill journal (event skill_journal, skill "peach banana"), in the background - never slows an answer."""
    import threading

    def go():
        try:
            requests.post(f"{BASE}/events/skill_journal", headers=_headers(), json={**body, "skill": "peach banana"}, timeout=4)
        except Exception:
            pass
    threading.Thread(target=go, daemon=True).start()
