"""Peach Banana: signing the Echo Show into Home Assistant WITHOUT storage. The Show's browser (Alexa Web API) won't
let pages keep anything, so Home Assistant's frontend can't store a sign-in. Instead, each time Peach Banana opens, the
add-on signs in as the Echo Show user (Home Assistant's own login flow, like the login page does) and gets a
ONE-TIME authorization code (valid ~10 minutes). The Show opens the control panel with that code, and the frontend
exchanges it for a sign-in it keeps in memory for as long as the page is open."""

import base64
import json

import requests

from .widgets import _opts


def _cfg():
    o = _opts()
    return {"url": (o.get("catballou_ha_url") or "https://ha.proflewis.stream").rstrip("/"),
            "inner": (o.get("catballou_ha_internal") or "http://homeassistant:8123").rstrip("/"),
            "user": o.get("catballou_ha_username") or "echoshow", "password": o.get("catballou_ha_password") or ""}


def configured():
    return bool(_cfg()["password"])


def code():
    """A one-time authorization code for the Echo Show user, for the Show's address (client id = that site)."""
    c = _cfg()
    client, redirect = c["url"] + "/", c["url"] + "/?auth_callback=1"
    s = requests.Session()
    r = s.post(c["inner"] + "/auth/login_flow", timeout=10,
               json={"client_id": client, "handler": ["homeassistant", None], "redirect_uri": redirect})
    r.raise_for_status()
    flow = r.json()["flow_id"]
    r = s.post(f"{c['inner']}/auth/login_flow/{flow}", timeout=10,
               json={"client_id": client, "username": c["user"], "password": c["password"]})
    r.raise_for_status()
    b = r.json()
    if b.get("type") != "create_entry":
        raise RuntimeError(f"Home Assistant didn't sign the Echo Show in: {b.get('errors') or b.get('type')}")
    return b["result"]


def state():
    """What the frontend expects back from its own login page (where it came from, who it is)."""
    c = _cfg()
    return base64.b64encode(json.dumps({"hassUrl": c["url"], "clientId": c["url"] + "/"}).encode()).decode()
