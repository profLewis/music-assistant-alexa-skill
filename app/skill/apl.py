# -*- coding: utf-8 -*-

import json
import logging
import os
import sys

from ask_sdk_model.interfaces.alexa.presentation.apl import RenderDocumentDirective

from . import data

# Ensure /app/src is on the Python path so shared_store can be imported
_app_src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _app_src not in sys.path:
    sys.path.insert(0, _app_src)


def _load_apl_template():
    # type: () -> dict
    """Load the APL document template from JSON file."""
    template_path = os.path.join(os.path.dirname(__file__), "apl_document.json")
    with open(template_path, "r") as f:
        return json.load(f)


def add_apl(response_builder, start_paused=False):
    # type: (ResponseFactory, bool) -> None
    """Add the RenderDocumentDirective to the response with APL document."""
    metadata = _get_metadata()
    if not metadata:
        logging.warning("No metadata available for APL rendering")
        return

    # The MA API already normalizes local artwork and preserves provider hosts.
    cover_image = metadata.get("coverImageSource", "")
    background_image = metadata.get("backgroundImageSource", "")

    # Load the APL document template
    apl_document = _load_apl_template()

    # Set the dynamic autoplay value based on start_paused
    autoplay = not start_paused

    # Update autoplay in Video component and AlexaTransportControls
    try:
        video_component = apl_document["layouts"]["AudioPlayer"]["item"][0]["items"][2][
            "items"
        ][1]["items"][0]
        video_component["autoplay"] = autoplay
    except (KeyError, IndexError):
        logging.debug("Could not set video autoplay in APL template")

    try:
        transport_controls = apl_document["layouts"]["AudioPlayer"]["item"][0]["items"][
            2
        ]["items"][1]["items"][1]["items"][0]["item"][1]
        transport_controls["autoplay"] = autoplay
    except (KeyError, IndexError):
        logging.debug("Could not set transport autoplay in APL template")

    # Update mainTemplate with metadata values
    try:
        main_template_item = apl_document["mainTemplate"]["items"][0]
        main_template_item.update(
            {
                "audioSources": metadata.get("audioSources", ""),
                "backgroundImageSource": background_image,
                "coverImageSource": cover_image,
                "headerAttributionImage": metadata.get("headerAttributionImage", ""),
                "headerTitle": metadata.get("headerTitle", ""),
                "headerSubtitle": metadata.get("headerSubtitle", ""),
                "primaryText": metadata.get("primaryText", ""),
                "secondaryText": metadata.get("secondaryText", ""),
            }
        )
    except (KeyError, IndexError):
        logging.warning("Could not update mainTemplate in APL document")

    response_builder.add_directive(
        RenderDocumentDirective(
            token="playbackToken", document=apl_document, datasources={}
        )
    )


def _get_metadata():
    """Use the same request snapshot as AudioPlayer playback."""
    return data.get_info()


def add_apl_display(response_builder):
    # type: (ResponseFactory) -> None
    """Fork: the now-playing page as a DISPLAY ONLY - background, cover, title, artist - shown alongside Alexa's own
    AudioPlayer, which plays the music. No hidden Video player (it would play the stream a second time), no slider /
    transport controls (they drive that player) and no refresh timer (a SendEvent would reopen the skill session, and
    an open session is what keeps Alexa listening). The response can then end the session."""
    import copy

    metadata = _get_metadata()
    if not metadata:
        return
    doc = copy.deepcopy(_load_apl_template())
    root = doc["layouts"]["AudioPlayer"]["item"][0]
    root.pop("onMount", None)   # the MetadataRefresh polling loop
    # follow the song: re-load the cover and the title (as a vector graphic) every 10 s from this server's /now/
    # addresses - a page-local timer, no SendEvent, so the session stays closed
    try:
        from music_assistant_api.ma_routes import player_from_stream_url
        from now_playing import urls

        cover_url, text_url = urls(player_from_stream_url(metadata.get("audioSources", "")) or "_")
    except Exception:
        cover_url = text_url = None
    if cover_url:
        root.setdefault("bind", []).append({"name": "nowTick", "type": "number", "value": 0})
        root["onMount"] = [{"type": "Sequential", "repeatCount": -1, "commands": [
            {"type": "Idle", "delay": 10000}, {"type": "SetValue", "property": "nowTick", "value": "${nowTick + 1}"}]}]
        live = "${'" + cover_url + "?t=' + nowTick}"

        def follow(node):
            if isinstance(node, dict):
                if node.get("type") == "AlexaBackground":
                    node["backgroundImageSource"] = live
                if node.get("type") == "AlexaImage":
                    node["imageSource"] = live
                if node.get("type") == "Container" and any(
                        isinstance(x, dict) and x.get("id") == "Audio_PrimaryText" for x in node.get("items", [])):
                    node["items"] = [{"type": "VectorGraphic", "id": "Audio_LiveText", "width": "100%", "height": "16vh",
                                      "scale": "best-fit", "align": "left", "source": "${'" + text_url + "?t=' + nowTick}"}]
                for v in node.values():
                    follow(v)
            elif isinstance(node, list):
                for v in node:
                    follow(v)

        follow(root)
    try:
        body = root["items"][2]["items"]
        root["items"][2]["items"] = [c for c in body if c.get("id") != "Audio_AudioInfo"]   # video + slider + controls
    except (KeyError, IndexError):
        logging.debug("Could not trim the player out of the APL template")
    doc["mainTemplate"]["items"][0].update(
        {
            "audioSources": "",
            "backgroundImageSource": metadata.get("backgroundImageSource", ""),
            "coverImageSource": metadata.get("coverImageSource", ""),
            "headerAttributionImage": metadata.get("headerAttributionImage", ""),
            "headerTitle": metadata.get("headerTitle", ""),
            "headerSubtitle": metadata.get("headerSubtitle", ""),
            "primaryText": metadata.get("primaryText", ""),
            "secondaryText": metadata.get("secondaryText", ""),
        }
    )
    response_builder.add_directive(
        RenderDocumentDirective(token="displayToken", document=doc, datasources={})
    )

