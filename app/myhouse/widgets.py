"""Peach Banana WIDGETS on the Echo Show home screen (Alexa widgets: an APL package in the skill package, live data
through Amazon's Data Store):

  CentralControl - the Central Control (Library Nest) temperature, its target and what it's doing; a tap opens the
                   Heating settings page.
  CatBallou      - opens Peach Banana.

The numbers are pushed to the Data Store (namespace "house", key "central") whenever they change, using the skill's
own Alexa Client Id / Secret (console: Build > Tools > Permissions), set in the add-on's Configuration as
myhouse_client_id / myhouse_client_secret. The user id to push to is saved from Peach Banana's own requests."""

import json
import logging
import threading
import time
from pathlib import Path

import requests

from . import ha
from .house import CENTRAL

log = logging.getLogger("myhouse")
NS, KEY = "house", "central"
DS_API = "https://api.eu.amazonalexa.com/v1/datastore/commands"
ICON = "https://raw.githubusercontent.com/profLewis/music-assistant-alexa-skill/proflewis/assets/icons/"
_tok = {"t": None, "exp": 0}
_last = {"sig": None, "at": 0}


def _opts():
    try:
        return json.loads(Path("/data/options.json").read_text())
    except Exception:
        return {}


def configured():
    o = _opts()
    return bool(o.get("myhouse_client_id") and o.get("myhouse_client_secret"))


def _token():
    if _tok["t"] and _tok["exp"] > time.time() + 60:
        return _tok["t"]
    o = _opts()
    r = requests.post("https://api.amazon.com/auth/o2/token", timeout=15, data={
        "grant_type": "client_credentials", "client_id": o["myhouse_client_id"], "client_secret": o["myhouse_client_secret"],
        "scope": "alexa::datastore"})
    r.raise_for_status()
    b = r.json()
    _tok.update(t=b["access_token"], exp=time.time() + int(b.get("expires_in", 3600)))
    return _tok["t"]


def central_now():
    cur, tgt = ha.attr(CENTRAL, "current_temperature"), ha.attr(CENTRAL, "temperature")
    act = str(ha.attr(CENTRAL, "hvac_action") or ha.state(CENTRAL) or "").replace("_", " ")
    f = lambda v: f"{float(v):.1f}°" if v not in (None, "") else "—"   # noqa: E731
    mode = "Off (forced)" if ha.state("input_boolean.heating_force_off") == "on" else "Override" if ha.state("input_boolean.heating_override") == "on" else ""
    return {"temp": f(cur), "target": f"target {f(tgt)}" if tgt is not None else "no target", "state": (mode or act or "—").capitalize(),
            "heating": act == "heating", "house": f(ha.state("sensor.house_temperature")), "at": time.strftime("%H:%M")}


def push(user_id, force=False):
    """PUT the Central Control reading to the user's widgets (only when it has changed, or every 15 min)."""
    if not configured() or not user_id:
        return False
    data = central_now()
    sig = json.dumps({k: v for k, v in data.items() if k != "at"})
    if not force and sig == _last["sig"] and time.time() - _last["at"] < 900:
        return True
    r = requests.post(DS_API, timeout=15, headers={"Authorization": f"Bearer {_token()}"}, json={
        "commands": [{"type": "PUT_OBJECT", "namespace": NS, "key": KEY, "content": data}],
        "target": {"type": "USER", "id": user_id}})
    if r.status_code >= 300:
        log.warning("Peach Banana widget push: %s %s", r.status_code, r.text[:200])
        return False
    _last.update(sig=sig, at=time.time())
    return True


def start(get_user):
    """Keep the widgets current: check every 60 s."""
    def loop():
        while True:
            try:
                push(get_user())
            except Exception:
                log.exception("Peach Banana widget push failed")
            time.sleep(60)
    threading.Thread(target=loop, daemon=True, name="catballou-widgets").start()


# ---------- the widget packages (files in the skill package's dataStorePackages/) ----------
_BIND = {"extensions": [{"name": "DataStore", "uri": "alexaext:datastore:10"}],
         "settings": {"DataStore": {"dataBindings": [{"namespace": NS, "key": KEY, "dataBindingName": "dsCentral", "dataType": "OBJECT"}]}}}


def _txt(text, size, color="#eef1f6", weight="normal", **kw):
    return {"type": "Text", "text": text, "fontSize": f"{size}dp", "color": color, "fontWeight": weight, "textAlign": "center", **kw}


def _central_doc():
    return {"type": "APL", "version": "2023.1", **_BIND, "mainTemplate": {"parameters": ["payload"], "items": [
        {"type": "TouchWrapper", "width": "100vw", "height": "100vh",
         "onPress": [{"type": "SendEvent", "arguments": ["openPage", "hsettings"], "flags": {"interactionMode": "STANDARD"}}],
         "item": {"type": "Container", "width": "100vw", "height": "100vh", "justifyContent": "center", "alignItems": "center",
                  "backgroundColor": "${dsCentral.heating ? '#3a2412' : '#141821'}", "items": [
                      _txt("CENTRAL CONTROL", 16, "#8b93a5", "bold"),
                      _txt("${dsCentral.temp ?? '—'}", 72, "${dsCentral.heating ? '#ffb347' : '#eef1f6'}", "bold"),
                      _txt("${dsCentral.target ?? ''}", 22),
                      _txt("${dsCentral.state ?? 'Open Peach Banana to start'}", 22, "#ffb347"),
                      _txt("${dsCentral.house ? 'house ' + dsCentral.house + ' · ' + dsCentral.at : ''}", 16, "#8b93a5", paddingTop="12dp"),
                      _txt("tap for heating settings", 14, "#8b93a5", paddingTop="8dp")]}}]}}


def _open_doc():
    return {"type": "APL", "version": "2023.1", **_BIND, "mainTemplate": {"parameters": ["payload"], "items": [
        {"type": "TouchWrapper", "width": "100vw", "height": "100vh",
         "onPress": [{"type": "SendEvent", "arguments": ["openPage", "home"], "flags": {"interactionMode": "STANDARD"}}],
         "item": {"type": "Container", "width": "100vw", "height": "100vh", "justifyContent": "center", "alignItems": "center",
                  "backgroundColor": "#141821", "items": [
                      {"type": "Image", "source": ICON + "myhouse_512.png", "width": "45vw", "height": "45vw"},
                      _txt("Peach Banana", 34, "#eef1f6", "bold", paddingTop="12dp"),
                      _txt("${dsCentral.house ? 'house ' + dsCentral.house : 'lights · heating · music'}", 18, "#8b93a5")]}}]}}


def packages(locales):
    """{path in the skill package: bytes} for both widgets."""
    out = {}
    for wid, name, desc, doc, preview in (
            ("CentralControl", "Central Control", "The Central Control temperature; tap for the heating settings.", _central_doc(), "widget_central.png"),
            ("PeachBanana", "Peach Banana", "Opens Peach Banana - lights, heating and music.", _open_doc(), "widget_open.png")):
        base = f"skill-package/dataStorePackages/{wid}/"
        meta = {"name": name, "description": desc, "keywords": ["house", "heating"], "iconUri": ICON + "widget_icon_450.png", "previews": [ICON + preview]}
        out[base + "manifest.json"] = {"packageVersion": "1.0", "packageType": "APL_PACKAGE", "manifest": {
            "id": wid, "version": "1.0.0", "installStateChanges": "INFORM", "updateStateChanges": "INFORM",
            "presentationDefinitions": [{"url": "presentations/default.tpl"}], "appliesTo": "${viewport.mode == 'HUB'}"},
            "publishingInformation": {"schemaVersion": "1.0", "locales": {l: [{"targetViewport": "WIDGET_M", "metadata": meta}] for l in locales}}}
        out[base + "presentations/default.tpl"] = {"type": "APL_PRESENTATION", "documentUrl": "documents/document.json", "datasourceUrl": "datasources/default.json"}
        out[base + "documents/document.json"] = doc
        out[base + "datasources/default.json"] = {"payload": {}}
    return {k: json.dumps(v).encode() for k, v in out.items()}


INTERFACES = [{"type": "ALEXA_DATASTORE_PACKAGEMANAGER", "packages": [{"id": "CentralControl"}, {"id": "PeachBanana"}]},
              {"type": "ALEXA_DATA_STORE"},
              {"type": "ALEXA_EXTENSION", "requestedExtensions": [{"uri": "alexaext:datastore:10"}]}]
