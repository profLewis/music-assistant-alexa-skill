"""MyHouse voice model ("Alexa, open Peach Banana")."""

from .house import ROOMS


def _room_values():
    return [{"name": {"value": k.lower(), "synonyms": alts}} for k, (_l, _r, _t, alts) in ROOMS.items()]


# THE ECHO'S OWN VOLUME while a panel is open (the user, 29 Oct: "when my app is playing on the echo it doesn't allow
# other alexa commands like turn the volume down - let them pass through"): the open session hears everything said, so
# "turn the volume down" reached the skill as unknown and was lost. Both skills (Peach Banana and the music skill's
# panel) take it and set the Echo's volume through Home Assistant (script.echo_volume) - the panel and music stay.
VOLUME_TYPE = {"name": "VOLUME_DIR", "values": [
    {"name": {"value": "up", "synonyms": ["louder", "higher", "turn up", "increase", "raise", "a bit louder"]}},
    {"name": {"value": "down", "synonyms": ["quieter", "lower", "softer", "turn down", "decrease", "a bit quieter"]}}]}
VOLUME_INTENT = {"name": "VolumeIntent", "slots": [{"name": "dir", "type": "VOLUME_DIR"}, {"name": "level", "type": "AMAZON.NUMBER"}],
                 "samples": ["turn the volume {dir}", "turn volume {dir}", "turn it {dir}", "volume {dir}", "{dir} the volume",
                             "make the volume {dir}", "make it {dir}", "set the volume to {level}", "set volume to {level}",
                             "volume to {level}", "volume {level}", "turn the volume to {level}", "change the volume to {level}"]}


# QUESTIONS FOR THE AI HELPER (the user, 31 Oct): Alexa only passes on free words after fixed ones, and the fixed ones are
# lost, so each opening is its own intent; handlers.AskAI puts them back. Exact samples above still win ("what's the time").
ASK_INTENTS = {"AskIntent": ("", ["ask {q}", "ask about {q}", "question {q}"]),
               "AskTellIntent": ("tell me", ["tell me {q}"]),
               "AskWhatIntent": ("what is", ["what is {q}", "what's {q}"]),
               "AskWhoIntent": ("who is", ["who is {q}", "who's {q}"]),
               "AskWhyIntent": ("why", ["why {q}"]),
               "AskHowIntent": ("how", ["how {q}"]),
               "AskWhereIntent": ("where", ["where {q}"]),
               "AskWhenIntent": ("when", ["when {q}"])}
# (the user, 31 Oct: "what does a banana look like" went to Alexa, who doesn't tell a skill what it can't place; "a much wider range
# of phrases"): a skill can't catch just anything, each needs its own opening. Words that start a job the panel does itself aren't here.
OPENINGS = ["what", "which", "whose", "who are", "who was", "how's", "where's", "when's", "why's", "is", "are", "am", "was", "were", "can", "could",
            "do", "does", "did", "will", "would", "should", "shall", "has", "have", "had", "may", "might", "must", "explain", "describe", "define",
            "translate", "convert", "calculate", "compare", "summarise", "spell", "pronounce", "recommend", "suggest", "name", "list", "find", "search for",
            "look up", "google", "say", "give me", "teach me", "help me", "write", "make up", "i", "i'm", "i'd", "my", "we", "you", "your", "let's", "please", "hey", "okay"]
for _w in OPENINGS:
    ASK_INTENTS["Ask" + "".join(x.capitalize() for x in _w.replace("'", " ").split()) + "OpenIntent"] = (_w, [_w + " {q}"])


# the BBC stations as script.peach_play knows them (packages/peach_play.yaml), each with the ways it's said
STATIONS = [
    ("radio one", ["radio 1", "bbc radio one", "radio one please", "r one"]),
    ("radio two", ["radio 2", "bbc radio two", "r two"]),
    ("radio three", ["radio 3", "bbc radio three", "r three"]),
    ("radio four", ["radio 4", "bbc radio four", "bbc radio 4", "r four", "radio four fm", "bbc four radio"]),
    ("radio four extra", ["radio 4 extra", "four extra", "bbc radio four extra"]),
    ("five live", ["radio five live", "5 live", "radio 5 live", "radio five", "bbc five live", "bbc radio five live"]),
    ("six music", ["radio six music", "6 music", "radio 6 music", "radio six", "bbc six music", "bbc radio six music"]),
    ("world service", ["the world service", "bbc world service", "world service radio"]),
    ("radio london", ["bbc london", "bbc radio london"]),
    ("the archers", ["archers", "the archers omnibus", "the latest archers", "the archers on radio four"]),
    ("the radio", ["radio", "bbc radio", "the bbc", "the wireless", "some radio"]),
]


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
                     "wake me up at {time}", "wake me at {time}", "alarm for {time}", "set an alarm", "set alarm", "for {time}", "{time}"]},
        {"name": "TimerIntent", "slots": [{"name": "dur", "type": "AMAZON.DURATION"}],
         "samples": ["set a timer for {dur}", "set timer for {dur}", "set a {dur} timer", "start a {dur} timer", "timer for {dur}",
                     "start a timer for {dur}", "set a timer", "start a timer", "for {dur}", "{dur}"]},
        {"name": "AlarmOpIntent", "slots": [{"name": "op", "type": "ALERT_OP"}, {"name": "thing", "type": "ALERT_THING"}],
         "samples": ["{op} the {thing}", "{op} my {thing}", "{op} all {thing}", "{op} all my {thing}", "{op} all the {thing}"]},
        {"name": "TimerLeftIntent", "slots": [],
         "samples": ["how long is left on the timer", "how long left on the timer", "how much time is left", "how long is left",
                     "what time is the alarm", "what alarms do i have", "what timers do i have"]},
        {"name": "TimeIntent", "slots": [], "samples": ["what time is it", "what's the time", "what is the time", "tell me the time"]},
        # (the user, 4 Nov 2026: "when I say 'alexa good morning' in the morning that should all happen in Peach Banana too" -
        # with the panel open, Peach Banana hears it before any Alexa routine; it took it for an alarm and asked "what time?")
        {"name": "GoodMorningIntent", "slots": [], "samples": ["good morning", "morning", "good morning to you", "morning all",
                                                               "hello good morning", "good morning everyone"]},
        VOLUME_INTENT,
        *[{"name": n, "slots": [{"name": "q", "type": "AMAZON.SearchQuery"}], "samples": samples} for n, (_w, samples) in ASK_INTENTS.items()],
        # (the user, 31 Oct: "when someone says alexa play xxx, route that through peach banana": heard while the panel is open)
        # LOAD / UNLOAD (the user, 5 Nov 2026: "also use the term load to load it ready to play. unload is the opposite") and the
        # player's own controls ("turn on shuffle" had played a song called Shuffle) - all done by the house's script.peach_play
        {"name": "LoadIntent", "slots": [{"name": "what", "type": "AMAZON.SearchQuery"}],
         "samples": ["load {what}", "load up {what}", "queue up {what}", "get {what} ready"]},
        {"name": "PlayerControlIntent", "slots": [{"name": "ctl", "type": "PLAYER_CONTROL"}],
         "samples": ["{ctl}", "{ctl} please", "{ctl} the music", "{ctl} the player", "please {ctl}"]},
        {"name": "PlayThisIntent", "slots": [{"name": "what", "type": "AMAZON.SearchQuery"}],
         # (the user, 4 Nov 2026: "'alexa turn on radio 4' or 'turn on the radio' treated the same as play radio 4 - in the radio on the
         # Moon"; and the Archers: "play the most recent archers, last week's one" - the house's script.peach_play works out which)
         "samples": ["play {what}", "play me {what}", "play some {what}", "put on {what}", "listen to {what}", "turn on {what}", "switch on {what}",
                     "put {what} on", "tune in to {what}", "tune to {what}", "tune into {what}", "start {what}", "i want to hear {what}"]},
        # THE RADIO BY NAME (the user, 5 Nov 2026: with Peach Banana open, Alexa still took "play radio four" for its own player at
        # times - the catch-all "play {what}" is a weak match next to Alexa's own. A list of the stations, each said many ways, is a
        # strong one, so Peach Banana wins while it's open)
        {"name": "RadioIntent", "slots": [{"name": "station", "type": "STATION"}],
         "samples": [s.replace("VERB", v) for v in ["play", "turn on", "put on", "switch on", "start", "listen to", "tune to", "tune in to",
                                                     "tune into", "i want", "i want to hear", "can you play", "could you play", "please play", "play me"]
                     for s in ["VERB {station}", "VERB the {station}", "VERB bbc {station}"]]
                    + ["{station} please", "put {station} on", "put the {station} on", "turn {station} on", "switch {station} on",
                       # (just the station, 5 Nov 2026: "alexa bbc radio 4" went to Alexa's own player)
                       "{station}", "bbc {station}", "the {station}", "{station} now", "bbc {station} please"]},
        # BOOKS AND PODCASTS (the user, 5 Nov 2026: "include audible and similar") - Alexa keeps "read my book" / "play audible" for its
        # own Audible player unless Peach Banana's words match better
        {"name": "MyBookIntent", "slots": [],
         "samples": ["play my book", "read my book", "continue my book", "resume my book", "carry on with my book", "play my audiobook",
                     "continue my audiobook", "resume my audiobook", "play my audio book", "play audible", "continue audible", "resume audible",
                     "play my audible book", "read me my book", "play my latest book", "continue reading", "keep reading", "carry on reading"]},
        {"name": "BookIntent", "slots": [{"name": "title", "type": "AMAZON.SearchQuery"}],
         "samples": ["read {title}", "read me {title}", "play the audiobook {title}", "play the book {title}", "continue the book {title}",
                     "play audiobook {title}", "play audible book {title}", "listen to the book {title}", "resume the book {title}"]},
        {"name": "PodcastIntent", "slots": [{"name": "title", "type": "AMAZON.SearchQuery"}],
         "samples": ["play the podcast {title}", "play podcast {title}", "play the latest podcast {title}", "play the latest episode of {title}",
                     "listen to the podcast {title}", "put on the podcast {title}"]},
        {"name": "AMAZON.PauseIntent", "samples": []}, {"name": "AMAZON.ResumeIntent", "samples": []},
        {"name": "AMAZON.HelpIntent", "samples": []}, {"name": "AMAZON.StopIntent", "samples": []},
        {"name": "AMAZON.CancelIntent", "samples": []}, {"name": "AMAZON.FallbackIntent", "samples": []},
        {"name": "AMAZON.NavigateHomeIntent", "samples": []},
    ]
    types = [
        {"name": "STATION", "values": [{"name": {"value": v, "synonyms": syn}} for v, syn in STATIONS]},
        VOLUME_TYPE,
        {"name": "ROOM", "values": _room_values()},
        {"name": "PAGE", "values": [{"name": {"value": "home", "synonyms": ["the house", "summary", "front page"]}},
                                    {"name": {"value": "lights", "synonyms": ["the lights", "lighting"]}},
                                    {"name": {"value": "heating", "synonyms": ["radiators", "the heating", "rads", "temperatures"]}},
                                    {"name": {"value": "music", "synonyms": ["the music", "the player", "what's playing"]}},
                                    # (apesma, the house's own Music Assistant app - Alexa hears the made-up word many ways: 5 Nov 2026
                                    #  "open apesma" came out as "Open Ape Smart")
                                    {"name": {"value": "apesma", "synonyms": ["a pesma", "ape smart", "apes ma", "a pes ma", "music app", "the music app", "music assistant", "the music assistant app"]}}]},
        {"name": "ALERT_OP", "values": [{"name": {"value": v, "synonyms": syn}} for v, syn in [
            ("cancel", ["delete", "remove", "turn off", "switch off"]), ("stop", ["silence"]), ("snooze", []), ("show", ["list"])]]},
        {"name": "ALERT_THING", "values": [{"name": {"value": v, "synonyms": syn}} for v, syn in [
            ("alarm", ["alarm clock"]), ("alarms", []), ("timer", []), ("timers", []), ("reminder", []), ("reminders", [])]]},
        {"name": "PLAYER_CONTROL", "values": [{"name": {"value": v, "synonyms": syn}} for v, syn in [
            ("unload", ["unload it", "unload this", "unload everything", "clear the player", "empty the player", "clear the queue"]),
            # (a bare "shuffle" / "shuffle mode" flips it - the user, 5 Nov 2026; "on" / "off" said = that)
            ("shuffle", ["shuffle mode", "toggle shuffle", "shuffle it", "shuffle this"]),
            ("shuffle on", ["turn on shuffle", "switch on shuffle", "turn on shuffle mode", "shuffle mode on", "put shuffle on"]),
            ("shuffle off", ["turn off shuffle", "switch off shuffle", "turn off shuffle mode", "shuffle mode off", "stop shuffling", "no shuffle", "unshuffle"]),
            ("repeat", ["repeat mode", "toggle repeat", "loop", "loop it", "repeat this"]),
            ("repeat on", ["turn on repeat", "switch on repeat", "repeat mode on"]),
            ("repeat off", ["turn off repeat", "switch off repeat", "repeat mode off", "stop repeating", "no repeat"])]]},
        {"name": "MUSIC_ACTION", "values": [{"name": {"value": v, "synonyms": s}} for v, s in [
            ("pause", ["stop", "hold"]), ("play", ["resume", "carry on", "continue"]), ("next", ["skip", "next song", "skip this"]),
            ("previous", ["back", "last song", "go back"]), ("louder", ["turn up", "volume up"]), ("quieter", ["turn down", "volume down"])]]},
    ]
    return {"interactionModel": {"languageModel": {"invocationName": "peach banana", "intents": intents, "types": types}}}
