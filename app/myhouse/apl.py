"""MyHouse screens in APL (Alexa's screen format) - built for the Echo Show 8 (1280 × 800) and laid out in % so other
Shows scale. One document per draw: a top bar (title, time, outside), the page, and tabs along the bottom.
Every button is a TouchWrapper whose onPress sends ["act", <action>, <arg>] back to the skill, which does it and
redraws. The document keeps the screen up for 10 minutes without the microphone (the response leaves the session
open WITHOUT a reprompt), and asks for a quiet refresh every 30 s so the numbers stay current."""

TOKEN = "myhouse"
BG, CARD, CARD_ON, TEXT, DIM, ACCENT, WARM, COOL = "#101318", "#1d222b", "#3a3220", "#eef1f6", "#8b93a5", "#9fa8da", "#ffb347", "#6fb7ff"
TABS = [("home", "Home", "🏠"), ("lights", "Lights", "💡"), ("heating", "Heating", "🔥"), ("music", "Music", "🎵")]


def _txt(text, size=28, color=TEXT, weight="normal", **kw):
    return {"type": "Text", "text": text, "fontSize": f"{size}dp", "color": color, "fontWeight": weight, **kw}


def button(label, action, arg="", sub="", on=False, width="23%", height="150dp", icon=""):
    """A big touch square (like the dashboard's room buttons): icon, label, a small second line."""
    items = []
    if icon:
        items.append(_txt(icon, 40, textAlign="center"))
    items.append(_txt(label, 26, TEXT if not on else "#fff4d6", "bold", textAlign="center", maxLines=2))
    if sub:
        items.append(_txt(sub, 20, DIM if not on else "#ffd89a", textAlign="center", maxLines=1))
    return {"type": "TouchWrapper", "width": width, "height": height, "spacing": "1.5%",
            "onPress": [{"type": "SendEvent", "arguments": ["act", action, arg]}],
            "item": {"type": "Frame", "width": "100%", "height": "100%", "borderRadius": "18dp",
                     "backgroundColor": CARD_ON if on else CARD, "borderWidth": "2dp", "borderColor": WARM if on else "#2b313c",
                     "item": {"type": "Container", "width": "100%", "height": "100%", "justifyContent": "center",
                              "alignItems": "center", "items": items}}}


def pill(label, action, arg="", on=False, width="auto"):
    return {"type": "TouchWrapper", "width": width, "spacing": "12dp",
            "onPress": [{"type": "SendEvent", "arguments": ["act", action, arg]}],
            "item": {"type": "Frame", "borderRadius": "40dp", "backgroundColor": ACCENT if on else CARD,
                     "paddingLeft": "28dp", "paddingRight": "28dp", "paddingTop": "14dp", "paddingBottom": "14dp",
                     "item": _txt(label, 26, "#15171d" if on else TEXT, "bold")}}


def navpill(label, page):
    """A pill that opens another page."""
    return {"type": "TouchWrapper", "spacing": "12dp", "onPress": [{"type": "SendEvent", "arguments": ["page", page]}],
            "item": {"type": "Frame", "borderRadius": "40dp", "backgroundColor": CARD, "borderWidth": "2dp", "borderColor": ACCENT,
                     "paddingLeft": "28dp", "paddingRight": "28dp", "paddingTop": "14dp", "paddingBottom": "14dp",
                     "item": _txt(label + "  ›", 26, ACCENT, "bold")}}


def grid(items, per_row=4):
    """Rows of buttons, wrapping (APL Containers don't wrap on older Shows, so rows are built here)."""
    rows = [items[i:i + per_row] for i in range(0, len(items), per_row)]
    return {"type": "ScrollView", "width": "100%", "grow": 1, "item": {"type": "Container", "width": "100%",
            "items": [{"type": "Container", "direction": "row", "width": "100%", "spacing": "1.5%", "items": r} for r in rows]}}


def tile(title, value, sub="", color=TEXT, width="31%"):
    return {"type": "Frame", "width": width, "spacing": "2%", "borderRadius": "18dp", "backgroundColor": CARD,
            "paddingLeft": "22dp", "paddingTop": "16dp", "paddingBottom": "16dp",
            "item": {"type": "Container", "items": [_txt(title.upper(), 18, DIM, "bold"), _txt(value, 46, color, "bold"),
                                                    _txt(sub, 20, DIM, maxLines=2) if sub else {"type": "Container"}]}}


def document(page, title, body, top_right=""):
    tabs = [{"type": "TouchWrapper", "grow": 1, "onPress": [{"type": "SendEvent", "arguments": ["page", key]}],
             "item": {"type": "Container", "alignItems": "center", "paddingTop": "8dp", "paddingBottom": "8dp",
                      "items": [_txt(icon, 30, textAlign="center"),
                                _txt(name, 22, ACCENT if key == page else DIM, "bold", textAlign="center")]}}
            for key, name, icon in TABS]
    return {
        "type": "APL", "version": "2023.2", "theme": "dark",
        "settings": {"idleTimeout": 600000},
        "onMount": [{"type": "Sequential", "repeatCount": 20,
                     "commands": [{"type": "Idle", "delay": 30000}, {"type": "SendEvent", "arguments": ["tick", page]}]}],
        "mainTemplate": {"items": [{"type": "Container", "width": "100vw", "height": "100vh", "backgroundColor": BG,
            "paddingLeft": "3vw", "paddingRight": "3vw", "paddingTop": "2.5vh",
            "items": [
                {"type": "Container", "direction": "row", "alignItems": "center", "items": [
                    _txt(title, 40, TEXT, "bold", grow=1), _txt(top_right, 26, DIM)]},
                {"type": "Container", "grow": 1, "shrink": 1, "paddingTop": "2vh", "items": body},
                {"type": "Container", "direction": "row", "width": "100%", "items": tabs},
            ]}]},
    }


def render_directive(doc):
    return {"type": "Alexa.Presentation.APL.RenderDocument", "token": TOKEN, "document": doc, "datasources": {}}
