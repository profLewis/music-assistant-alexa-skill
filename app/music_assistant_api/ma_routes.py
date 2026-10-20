"""Music Assistant stream push and snapshot endpoints."""

from urllib.parse import unquote, urlsplit

import shared_store
from app_settings import get_setting
from flask import jsonify, request
from public_urls import rewrite_url


def player_from_stream_url(url):
    """The MA player a flow stream is for: /flow/<session>/<queue_id>/<item_id>/<queue_id>.<ext> -> queue_id."""
    try:
        parts = urlsplit(url).path.split("/")
        i = parts.index("flow")
        if len(parts) > i + 4 and parts[i + 2]:
            return unquote(parts[i + 2])
    except (ValueError, AttributeError):
        pass
    return None


def register_routes(bp):
    @bp.route("/push-url", methods=["POST"])
    def push_url():
        payload = request.get_json(silent=True)
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("streamUrl"), str)
            or not payload["streamUrl"]
        ):
            return jsonify({"error": "Missing required fields"}), 400
        raw_url = payload["streamUrl"]
        base = get_setting("MA_HOSTNAME", "").strip()
        try:
            stream_url = rewrite_url(raw_url, base)
            image_url = payload.get("imageUrl")
            if image_url:
                if not isinstance(image_url, str):
                    raise ValueError("imageUrl must be a string")
                # Provider artwork already hosted elsewhere must retain its own host.
                image_base = (
                    base
                    if urlsplit(image_url).hostname == urlsplit(raw_url).hostname
                    else ""
                )
                image_url = rewrite_url(image_url, image_base)
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        version = shared_store.set_ma(
            {
                "streamUrl": stream_url,
                "title": payload.get("title"),
                "artist": payload.get("artist"),
                "album": payload.get("album"),
                "imageUrl": image_url,
            },
            player_id=payload.get("playerId") or player_from_stream_url(raw_url),
        )
        return jsonify({"status": "ok", "version": version})

    @bp.route("/latest-url", methods=["GET"])
    def latest_url():
        payload = shared_store.get_ma()
        if not payload:
            return jsonify({"error": "No URL available"}), 404
        return jsonify(payload)
