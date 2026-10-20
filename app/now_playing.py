"""Fork: what's playing NOW, for the display-only page on screen Echoes.

The display-only page (APL_DISPLAY_ONLY) can't ask the skill for updates - that reopens the session, and an open
session keeps Alexa listening. Instead it re-loads two addresses on a timer:
  /now/<token>/<player>/cover      -> redirect to the cover of the song MA last pushed for that player
  /now/<token>/<player>/text.json  -> the title and "artist - album" as an AVG vector graphic (APL pages can't fetch text)
<token> is an HMAC of the player with the API password, so the addresses can't be guessed; anything else is a 404.
"""

import hashlib
import hmac
import json
from urllib.parse import quote

from flask import Blueprint, Response, abort, redirect

import shared_store
from app_settings import get_setting

bp = Blueprint("now_playing", __name__)


def token(player):
    key = (get_setting("APP_PASSWORD") or "ma-alexa-skill").encode()
    return hmac.new(key, (player or "_").encode(), hashlib.sha256).hexdigest()[:24]


def base_url():
    return (get_setting("SKILL_HOSTNAME") or "").strip().rstrip("/")


def urls(player):
    """(cover, text) addresses for a player ("_" = the latest push), or (None, None) without a public skill URL."""
    base, p = base_url(), player or "_"
    if not base.startswith("https://"):
        return None, None
    root = f"{base}/now/{token(p)}/{quote(p, safe='')}"
    return root + "/cover", root + "/text.json"


def _payload(tok, player):
    if not hmac.compare_digest(tok, token(player)):
        abort(404)
    return shared_store.get_ma(None if player == "_" else player) or {}


def _no_cache(resp):
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@bp.route("/now/<tok>/<path:player>/cover")
def cover(tok, player):
    url = _payload(tok, player).get("imageUrl") or ""
    if not url.startswith("https://"):
        abort(404)
    return _no_cache(redirect(url, 302))


@bp.route("/now/<tok>/<path:player>/text.json")
def text(tok, player):
    p = _payload(tok, player)
    title = (p.get("title") or "")[:48]
    sub = " - ".join(str(x) for x in (p.get("artist"), p.get("album")) if x)[:64]
    avg = {
        "type": "AVG",
        "version": "1.2",
        "width": 1200,
        "height": 190,
        "items": [
            {"type": "text", "text": title, "fill": "#FFFFFF", "fontSize": 72, "fontWeight": "bold", "x": 0, "y": 82},
            {"type": "text", "text": sub, "fill": "#E6E6E6", "fontSize": 44, "x": 0, "y": 160},
        ],
    }
    return _no_cache(Response(json.dumps(avg), mimetype="application/json"))
