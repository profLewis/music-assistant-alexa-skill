"""MyHouse: creating / updating its own Alexa skill with the add-on's existing Amazon sign-in (the same Login with
Amazon tokens the music skill's Setup uses). The skill id is kept in /data/myhouse.json.

    create (once) → manifest built → voice model uploaded per locale → built → enabled for testing on the account
"""

import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import quote

from skill_deployment import DeploymentError, https_url, manager
from app_settings import get_setting

from .model import interaction_model

STATE = Path(os.environ.get("MYHOUSE_STATE_PATH", "/data/myhouse.json"))
LOCALES = ("en-GB", "en-US")
_lock = threading.Lock()
_status = {"phase": "idle", "message": ""}


def _load():
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def _save(d):
    STATE.write_text(json.dumps(d))


def skill_id():
    return _load().get("skill_id")


# the screens it runs on (Amazon sends the skill only to devices whose screen is listed) - the music skill's list
VIEWPORTS = [
    {"mode": "HUB", "shape": "ROUND", "minWidth": 100, "maxWidth": 599, "minHeight": 100, "maxHeight": 599},
    {"mode": "HUB", "shape": "RECTANGLE", "minWidth": 600, "maxWidth": 959, "minHeight": 100, "maxHeight": 599},
    {"mode": "HUB", "shape": "RECTANGLE", "minWidth": 960, "maxWidth": 1279, "minHeight": 600, "maxHeight": 959},
    {"mode": "HUB", "shape": "RECTANGLE", "minWidth": 1280, "maxWidth": 1920, "minHeight": 600, "maxHeight": 1279},
    {"mode": "TV", "shape": "RECTANGLE", "minWidth": 960, "maxWidth": 960, "minHeight": 540, "maxHeight": 540},
]


def music_interfaces(m):
    sid = m.state.get("skill_id")
    if not sid:
        return []
    body = m.api("GET", f"/v1/skills/{quote(sid, safe='')}/stages/development/manifest").json()
    return ((body.get("manifest") or {}).get("apis") or {}).get("custom", {}).get("interfaces") or []


def music_endpoint(m):
    """The music skill's endpoint as Amazon has it (the one that's known to work): its certificate type is copied."""
    sid = m.state.get("skill_id")
    if not sid:
        return {}
    body = m.api("GET", f"/v1/skills/{quote(sid, safe='')}/stages/development/manifest").json()
    return ((body.get("manifest") or {}).get("apis") or {}).get("custom", {}).get("endpoint") or {}


def amazon_manifests():
    """Both skills' endpoint + interfaces as Amazon has them now (for checking)."""
    m = manager(); out = {}
    for name, sid in (("music", m.state.get("skill_id")), ("house", skill_id())):
        if sid:
            b = m.api("GET", f"/v1/skills/{quote(sid, safe='')}/stages/development/manifest").json().get("manifest", {})
            c = (b.get("apis") or {}).get("custom") or {}
            out[name] = {"endpoint": c.get("endpoint"), "regions": c.get("regions"), "interfaces": c.get("interfaces"),
                         "locales": list(((b.get("publishingInformation") or {}).get("locales") or {}).keys())}
            st = m.api("GET", f"/v1/skills/{quote(sid, safe='')}/status").json()
            out[name]["status"] = {k: (v.get("lastUpdateRequest", {}).get("status") if isinstance(v, dict) and "lastUpdateRequest" in v else
                                       {l: x.get("lastUpdateRequest", {}).get("status") for l, x in v.items()} if isinstance(v, dict) else v)
                                   for k, v in st.items()}
            try:
                out[name]["enablement"] = m.api("GET", f"/v1/skills/{quote(sid, safe='')}/stages/development/enablement").status_code
            except Exception as e:  # noqa: BLE001
                out[name]["enablement"] = str(e)[:80]
    return out


def manifest(endpoint, cert=None, viewports=None):
    loc = {
        "name": "Cat Ballou",
        "summary": "The house on your Echo Show: lights, heating and music.",
        "description": "Cat Ballou shows the house on an Echo Show - rooms, lights, heating and music - with touch "
                       "controls, and answers by voice. Say \"Alexa, open Cat Ballou\".",
        "examplePhrases": ["Alexa, open Cat Ballou", "Alexa, ask Cat Ballou to show the heating",
                           "Alexa, ask Cat Ballou to turn on the kitchen lights"],
        "keywords": ["home", "lights", "heating"],
        "smallIconUri": "https://raw.githubusercontent.com/profLewis/music-assistant-alexa-skill/proflewis/assets/icons/myhouse_108.png",
        "largeIconUri": "https://raw.githubusercontent.com/profLewis/music-assistant-alexa-skill/proflewis/assets/icons/myhouse_512.png",
    }
    return {"manifest": {
        "manifestVersion": "1.0",
        "publishingInformation": {"locales": {l: loc for l in LOCALES}, "isAvailableWorldwide": False,
                                  "distributionCountries": ["GB"], "category": "SMART_HOME"},
        "apis": {"custom": {"endpoint": {"uri": endpoint, "sslCertificateType": cert or get_setting("SKILL_CERTIFICATE_TYPE", "Wildcard")},
                            "interfaces": [{"type": "ALEXA_PRESENTATION_APL", "supportedViewports": viewports or VIEWPORTS}]}},
        "privacyAndCompliance": {"allowsPurchases": False, "usesPersonalInfo": False, "isChildDirected": False,
                                 "isExportCompliant": True, "containsAds": False},
        "permissions": [],
    }}


def status():
    return {**_status, "skill_id": skill_id()}


def _say(phase, message):
    _status.update(phase=phase, message=message)


def _wait(m, path, what, locale=None):
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        body = m.api("GET", path + "/status", params=[("resource", what)]).json()
        node = body.get(what, {})
        if locale:
            node = node.get(locale, {})
        st = node.get("lastUpdateRequest", {}).get("status")
        if st == "SUCCEEDED":
            return
        if st == "FAILED":
            errs = node.get("lastUpdateRequest", {}).get("errors") or []
            raise DeploymentError(f"Amazon could not build the {what}{' ' + locale if locale else ''}: "
                                  + "; ".join(e.get("message", "") for e in errs)[:400])
        time.sleep(3)
    raise DeploymentError(f"Amazon's {what} build timed out")


def deploy(app):
    """Run in a thread: create or update the MyHouse skill. Needs an app context for the deployment manager."""
    if not _lock.acquire(blocking=False):
        raise DeploymentError("A MyHouse deployment is already running")

    def run():
        try:
            with app.app_context():
                m = manager()
                vendor = m.state.get("vendor_id")
                if not vendor:
                    raise DeploymentError("Deploy the music skill from Setup first (no Amazon account selected)")
                endpoint = https_url(get_setting("SKILL_HOSTNAME", "").strip(), "Skill endpoint").rstrip("/") + "/myhouse"
                d = _load(); sid = d.get("skill_id")
                ep = music_endpoint(m)   # the music skill's endpoint works: same host, same certificate type
                vp = next((i.get("supportedViewports") for i in music_interfaces(m) if i.get("type") == "ALEXA_PRESENTATION_APL" and i.get("supportedViewports")), None)
                body = manifest(endpoint, ep.get("sslCertificateType"), vp)
                if not sid:
                    _say("creating", "Creating the MyHouse skill at Amazon…")
                    sid = m.api("POST", "/v1/skills", json={"vendorId": vendor, **body}).json()["skillId"]
                    d["skill_id"] = sid; _save(d)
                else:
                    _say("updating", "Updating the MyHouse skill…")
                    m.api("PUT", f"/v1/skills/{quote(sid, safe='')}/stages/development/manifest", json=body)
                path = f"/v1/skills/{quote(sid, safe='')}"
                _wait(m, path, "manifest")
                for loc in LOCALES:
                    _say("model", f"Uploading the voice model ({loc})…")
                    m.api("PUT", f"{path}/stages/development/interactionModel/locales/{loc}", json=interaction_model())
                for loc in LOCALES:
                    _say("building", f"Amazon is building the voice model ({loc})…")
                    _wait(m, path, "interactionModel", loc)
                _say("enabling", "Enabling MyHouse for testing on your account…")
                m.api("PUT", f"{path}/stages/development/enablement")
                _say("done", "Cat Ballou is ready: say \"Alexa, open Cat Ballou\".")
        except Exception as e:  # noqa: BLE001 - reported on the status endpoint
            _say("failed", str(e)[:500])
        finally:
            _lock.release()

    threading.Thread(target=run, daemon=True).start()
