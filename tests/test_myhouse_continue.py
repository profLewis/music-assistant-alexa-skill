"""'Alexa, continue' / 'unpause the radio' resume the music (the user, 10 Nov 2026) - the slot carries the words as spoken."""
from myhouse import actions


def test_continue_and_unpause_resume(monkeypatch):
    calls = []
    monkeypatch.setattr(actions.ha, "call", lambda d, s, data: calls.append((d, s)))
    monkeypatch.setattr(actions.ha, "state", lambda e: None)
    for said in ("continue", "unpause", "Un pause", "carry on", "continue playing", "resume"):
        calls.clear()
        assert actions.music(said) is None, said
        assert calls == [("media_player", "media_play")], said
