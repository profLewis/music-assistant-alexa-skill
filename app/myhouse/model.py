"""MyHouse voice model ("Alexa, open Peach Banana")."""

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
        # (ALEXA'S OWN JOBS while the panel is open: the open session hears everything said, so these are caught here and
        # handed back to Alexa - handlers.HandOff - instead of being lost to Help; anything else unknown: FallbackIntent)
        {"name": "AlarmIntent", "slots": [{"name": "time", "type": "AMAZON.TIME"}],
         "samples": ["set an alarm for {time}", "set alarm for {time}", "set an alarm at {time}", "set my alarm for {time}",
                     "wake me up at {time}", "wake me at {time}", "alarm for {time}", "set an alarm", "set alarm"]},
        {"name": "TimerIntent", "slots": [{"name": "dur", "type": "AMAZON.DURATION"}],
         "samples": ["set a timer for {dur}", "set timer for {dur}", "set a {dur} timer", "start a {dur} timer", "timer for {dur}",
                     "start a timer for {dur}", "set a timer", "start a timer"]},
        {"name": "AlarmOpIntent", "slots": [{"name": "op", "type": "ALERT_OP"}, {"name": "thing", "type": "ALERT_THING"}],
         "samples": ["{op} the {thing}", "{op} my {thing}", "{op} all {thing}", "{op} all my {thing}", "{op} all the {thing}"]},
        {"name": "TimerLeftIntent", "slots": [],
         "samples": ["how long is left on the timer", "how long left on the timer", "how much time is left", "how long is left",
                     "what time is the alarm", "what alarms do i have", "what timers do i have", "what time is it"]},
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
        {"name": "ALERT_OP", "values": [{"name": {"value": v, "synonyms": syn}} for v, syn in [
            ("cancel", ["delete", "remove", "turn off", "switch off"]), ("stop", ["silence"]), ("snooze", []), ("show", ["list"])]]},
        {"name": "ALERT_THING", "values": [{"name": {"value": v, "synonyms": syn}} for v, syn in [
            ("alarm", ["alarm clock"]), ("alarms", []), ("timer", []), ("timers", []), ("reminder", []), ("reminders", [])]]},
        {"name": "MUSIC_ACTION", "values": [{"name": {"value": v, "synonyms": s}} for v, s in [
            ("pause", ["stop", "hold"]), ("play", ["resume", "carry on", "continue"]), ("next", ["skip", "next song", "skip this"]),
            ("previous", ["back", "last song", "go back"]), ("louder", ["turn up", "volume up"]), ("quieter", ["turn down", "volume down"])]]},
    ]
    return {"interactionModel": {"languageModel": {"invocationName": "peach banana", "intents": intents, "types": types}}}
