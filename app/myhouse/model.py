"""MyHouse voice model ("Alexa, open Cat Ballou")."""

from .house import ROOMS


def _room_values():
    return [{"name": {"value": k.lower(), "synonyms": alts}} for k, (_l, _r, _t, alts) in ROOMS.items()]


def interaction_model():
    R = "{room}"
    intents = [
        {"name": "ShowPageIntent", "slots": [{"name": "page", "type": "PAGE"}],
         "samples": ["show {page}", "show me {page}", "show the {page}", "go to {page}", "open {page}", "{page}"]},
        {"name": "LightsOnIntent", "slots": [{"name": "room", "type": "ROOM"}],
         "samples": [f"turn on the {R} lights", f"turn the {R} lights on", f"{R} lights on", f"switch on the {R} lights",
                     f"turn on the lights in the {R}", "turn on all the lights", "all lights on"]},
        {"name": "LightsOffIntent", "slots": [{"name": "room", "type": "ROOM"}],
         "samples": [f"turn off the {R} lights", f"turn the {R} lights off", f"{R} lights off", f"switch off the {R} lights",
                     f"turn off the lights in the {R}", "turn off all the lights", "all lights off"]},
        {"name": "BoostIntent", "slots": [{"name": "room", "type": "ROOM"}],
         "samples": [f"boost the {R}", f"boost {R}", f"boost the {R} radiator", f"warm up the {R}", f"heat the {R}"]},
        {"name": "EndBoostIntent", "slots": [{"name": "room", "type": "ROOM"}],
         "samples": [f"stop the boost in the {R}", f"end the {R} boost", "stop the boosts", "end all boosts"]},
        {"name": "SetTargetIntent", "slots": [{"name": "temp", "type": "AMAZON.NUMBER"}],
         "samples": ["set the house to {temp} degrees", "set the heating to {temp}", "make it {temp} degrees", "target {temp}"]},
        {"name": "TemperatureIntent", "slots": [{"name": "room", "type": "ROOM"}],
         "samples": [f"what's the temperature in the {R}", f"how warm is the {R}", "how warm is the house", "what's the temperature"]},
        {"name": "MusicIntent", "slots": [{"name": "act", "type": "MUSIC_ACTION"}],
         "samples": ["{act} the music", "{act} music", "music {act}", "{act} track", "{act}"]},
        {"name": "AMAZON.HelpIntent", "samples": []}, {"name": "AMAZON.StopIntent", "samples": []},
        {"name": "AMAZON.CancelIntent", "samples": []}, {"name": "AMAZON.FallbackIntent", "samples": []},
        {"name": "AMAZON.NavigateHomeIntent", "samples": []},
    ]
    types = [
        {"name": "ROOM", "values": _room_values()},
        {"name": "PAGE", "values": [{"name": {"value": "home", "synonyms": ["the house", "summary", "front page"]}},
                                    {"name": {"value": "lights", "synonyms": ["the lights", "lighting"]}},
                                    {"name": {"value": "heating", "synonyms": ["radiators", "the heating", "rads", "temperatures"]}},
                                    {"name": {"value": "music", "synonyms": ["the music", "the player", "what's playing"]}}]},
        {"name": "MUSIC_ACTION", "values": [{"name": {"value": v, "synonyms": s}} for v, s in [
            ("pause", ["stop", "hold"]), ("play", ["resume", "carry on", "continue"]), ("next", ["skip", "next song", "skip this"]),
            ("previous", ["back", "last song", "go back"]), ("louder", ["turn up", "volume up"]), ("quieter", ["turn down", "volume down"])]]},
    ]
    return {"interactionModel": {"languageModel": {"invocationName": "cat ballou", "intents": intents, "types": types}}}
