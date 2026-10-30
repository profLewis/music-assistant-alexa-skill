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

from skill_deployment import DeploymentError, https_url, manager, pack
from app_settings import get_setting

from . import alerts, widgets
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
    """The music skill's endpoint as Amazon has it (the one that's known to work) - INCLUDING its per-region endpoints:
    the UK Echoes use the EU one, which is set to Wildcard (Cloudflare's certificate). Copying only the default
    ("Trusted") made Amazon refuse to call Peach Banana at all ("unable to reach the requested skill")."""
    sid = m.state.get("skill_id")
    if not sid:
        return {}
    body = m.api("GET", f"/v1/skills/{quote(sid, safe='')}/stages/development/manifest").json()
    custom = ((body.get("manifest") or {}).get("apis") or {}).get("custom", {})
    ep = dict(custom.get("endpoint") or {})
    regions = custom.get("regions") or {}
    eu = (regions.get("EU") or {}).get("endpoint") or {}
    if eu.get("sslCertificateType"):
        ep["sslCertificateType"] = eu["sslCertificateType"]
    ep["regions"] = regions
    return ep


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


def manifest(endpoint, cert=None, viewports=None, regions=None):
    loc = {
        "name": "Peach Banana",
        "summary": "The house on your Echo Show: lights, heating and music.",
        "description": "Peach Banana shows the house on an Echo Show - rooms, lights, heating and music - with touch "
                       "controls, and answers by voice. Say \"Alexa, open Peach Banana\".",
        "examplePhrases": ["Alexa, open Peach Banana", "Alexa, ask Peach Banana to show the heating",
                           "Alexa, ask Peach Banana to turn on the kitchen lights"],
        "keywords": ["home", "lights", "heating"],
        "smallIconUri": "https://raw.githubusercontent.com/profLewis/music-assistant-alexa-skill/proflewis/assets/icons/myhouse_108.png",
        "largeIconUri": "https://raw.githubusercontent.com/profLewis/music-assistant-alexa-skill/proflewis/assets/icons/myhouse_512.png",
    }
    return {"manifest": {
        "manifestVersion": "1.0",
        "publishingInformation": {"locales": {l: loc for l in LOCALES}, "isAvailableWorldwide": False,
                                  "distributionCountries": ["GB"], "category": "SMART_HOME"},
        "apis": {"custom": {"endpoint": {"uri": endpoint, "sslCertificateType": cert or get_setting("SKILL_CERTIFICATE_TYPE", "Wildcard")},
                            "interfaces": [{"type": "ALEXA_PRESENTATION_APL", "supportedViewports": viewports or VIEWPORTS},
                                           {"type": "ALEXA_PRESENTATION_HTML"}] + widgets.INTERFACES,   # (the web app: the whole control panel on the Show; the widgets)
                            **({"regions": regions} if regions else {})}},
        "privacyAndCompliance": {"allowsPurchases": False, "usesPersonalInfo": False, "isChildDirected": False,
                                 "isExportCompliant": True, "containsAds": False},
        "permissions": [{"name": n} for n in alerts.PERMISSIONS],
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
                ep = music_endpoint(m)   # the music skill's endpoint works: same address, same certificate type
                endpoint = ep.get("uri") or https_url(get_setting("SKILL_HOSTNAME", "").strip(), "Skill endpoint")   # the SAME address as the music skill (Amazon reaches it; /myhouse it never called) - requests are told apart by skill id
                d = _load(); sid = d.get("skill_id")
                vp = next((i.get("supportedViewports") for i in music_interfaces(m) if i.get("type") == "ALEXA_PRESENTATION_APL" and i.get("supportedViewports")), None)
                body = manifest(endpoint, ep.get("sslCertificateType") or "Wildcard", vp, ep.get("regions"))
                if not sid:
                    _say("creating", "Creating the skill at Amazon…")
                    sid = m.api("POST", "/v1/skills", json={"vendorId": vendor, **body}).json()["skillId"]
                    d["skill_id"] = sid; _save(d)
                path = f"/v1/skills/{quote(sid, safe='')}"
                # the WHOLE skill package (manifest, voice model, the widgets) - widgets only arrive this way
                files = {"skill-package/skill.json": json.dumps(body).encode()}
                for loc in LOCALES:
                    files[f"skill-package/interactionModels/custom/{loc}.json"] = json.dumps(interaction_model()).encode()
                files.update(widgets.packages(LOCALES))
                _say("uploading", "Uploading the skill package (with the widgets)…")
                up = m.api("POST", "/v1/skills/uploads").json()["uploadUrl"]
                m.transfer("PUT", up, data=pack(files), headers={"Content-Type": "application/zip"})
                job = m.api("POST", f"{path}/imports", json={"location": up})
                _say("importing", "Amazon is importing the package…")
                st = None
                for _ in range(200):
                    st = m.api("GET", m.job_path(job, "imports")).json()
                    if st.get("status") != "IN_PROGRESS":
                        break
                    time.sleep(3)
                if (st or {}).get("status") != "SUCCEEDED":
                    errs = []
                    for r in (st or {}).get("skill", {}).get("resources", []) or []:
                        errs += [f"{r.get('name')}: {e.get('message')}" for e in (r.get("errors") or [])]
                    raise DeploymentError("Amazon couldn't import the package: " + ("; ".join(errs) or json.dumps(st)[:400]))
                _wait(m, path, "manifest")
                for loc in LOCALES:
                    _say("building", f"Amazon is building the voice model ({loc})…")
                    _wait(m, path, "interactionModel", loc)
                _say("enabling", "Enabling MyHouse for testing on your account…")
                m.api("PUT", f"{path}/stages/development/enablement")
                _say("done", "Peach Banana is ready: say \"Alexa, open Peach Banana\".")
        except Exception as e:  # noqa: BLE001 - reported on the status endpoint
            _say("failed", str(e)[:500])
        finally:
            _lock.release()

    threading.Thread(target=run, daemon=True).start()


def music_html():
    """The control panel inside the MUSIC skill (skill/screen_app.py): its manifest at Amazon gets the web-app interface
    (Alexa.Presentation.HTML) added - nothing else changed. (The music skill's own Setup → Deploy rebuilds its manifest
    without it: run this again after one.)"""
    m = manager(); sid = m.state.get("skill_id")
    if not sid:
        raise DeploymentError("The music skill isn't deployed")
    path = f"/v1/skills/{quote(sid, safe='')}/stages/development/manifest"
    body = m.api("GET", path).json()
    ifs = body["manifest"]["apis"]["custom"].setdefault("interfaces", [])
    if any(i.get("type") == "ALEXA_PRESENTATION_HTML" for i in ifs):
        return {"changed": False, "interfaces": [i.get("type") for i in ifs]}
    ifs.append({"type": "ALEXA_PRESENTATION_HTML"})
    m.api("PUT", path, json={"manifest": body["manifest"]})
    _wait(m, f"/v1/skills/{quote(sid, safe='')}", "manifest")
    return {"changed": True, "interfaces": [i.get("type") for i in ifs]}


def music_volume(locales=("en-GB", "en-US")):
    """"Turn the volume down", alarms and timers for the MUSIC skill too (the user, 29 Oct): its voice model at Amazon gets
    VolumeIntent and Peach Banana's Alarm / Timer intents added (their types too) - nothing else changed - and is rebuilt (a failed build leaves the old
    model in use). The music skill's own Setup → Deploy rebuilds its model without it: run this again after one."""
    from .model import VOLUME_INTENT, interaction_model
    own = interaction_model()["interactionModel"]["languageModel"]
    add = [VOLUME_INTENT] + [i for i in own["intents"] if i["name"] in ("AlarmIntent", "TimerIntent", "AlarmOpIntent", "TimerLeftIntent")]
    add_types = [t for t in own["types"] if t["name"] in ("VOLUME_DIR", "ALERT_OP", "ALERT_THING")]
    m = manager(); sid = m.state.get("skill_id")
    if not sid:
        raise DeploymentError("The music skill isn't deployed")
    out = {}
    for loc in locales:
        path = f"/v1/skills/{quote(sid, safe='')}/stages/development/interactionModel/locales/{loc}"
        r = m.api("GET", path)
        if r.status_code >= 300:
            out[loc] = f"no model ({r.status_code})"; continue
        body = r.json(); lm = body["interactionModel"]["languageModel"]
        have = {i.get("name") for i in lm.get("intents", [])}
        new = [i for i in add if i["name"] not in have]
        if not new:
            out[loc] = "already there"; continue
        lm.setdefault("intents", []).extend(new)
        names = {t["name"] for t in add_types}
        lm["types"] = [t for t in lm.get("types", []) if t.get("name") not in names] + add_types
        m.api("PUT", path, json={"interactionModel": body["interactionModel"]})
        _wait(m, f"/v1/skills/{quote(sid, safe='')}", "interactionModel", loc)
        out[loc] = "added"
    return out


def _v2(m, method, path, **kw):
    """A call to Amazon's v2 API (the simulator) - the deployment manager only allows v1 paths."""
    r = m._send_once(method, path, 0, kw)
    return r.status_code, (r.json() if r.content else {})


def simulate(text, locale="en-GB"):
    """Ask Amazon to simulate saying `text` to the development skill and return what happened (for diagnosing)."""
    m, sid = manager(), skill_id()
    path = f"/v2/skills/{quote(sid, safe='')}/stages/development/simulations"
    code, r = _v2(m, "POST", path, json={"session": {"mode": "FORCE_NEW_SESSION"}, "input": {"content": text}, "device": {"locale": locale}})
    if code >= 300:
        return {"http": code, "body": r}
    sim = r.get("id")
    for _ in range(30):
        time.sleep(1.5)
        code, b = _v2(m, "GET", f"{path}/{sim}")
        if b.get("status") != "IN_PROGRESS":
            return b
    return {"status": "TIMEOUT"}
