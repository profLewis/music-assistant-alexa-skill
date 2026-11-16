"""Fork rules on top of upstream's skill-id restriction (private_access, upstream 1.5):

- Peach Banana (app/myhouse) shares the music skill's endpoint, so its own skill id must pass the check and reach
  invoke_skill(), which hands it to the house skill.
- An install whose deployment state names a skill but never recorded the wizard's verification (no skill-access.json)
  keeps working for THAT skill id only, rather than every Alexa request answering 503 after the upgrade.
"""

import json

import pytest
from flask import Flask

import private_access as access


def _body(skill):
    return {"context": {"System": {"application": {"applicationId": skill}}}, "request": {"type": "LaunchRequest"}}


@pytest.fixture
def check(tmp_path, monkeypatch):
    monkeypatch.setenv("SKILL_DEPLOYMENT_PATH", str(tmp_path / "state.json"))
    app = Flask(__name__)

    def run(skill):
        with app.test_request_context("/", method="POST", json=_body(skill)):
            r = access.check_private_access()
            return None if r is None else r.status_code

    return run, tmp_path / "state.json"


def test_house_skill_passes_and_others_do_not(check, monkeypatch):
    run, state = check
    from myhouse import deploy

    monkeypatch.setattr(deploy, "skill_id", lambda: "amzn1.ask.skill.house")
    access.save_allowed_skill_id("amzn1.ask.skill.music")
    assert run("amzn1.ask.skill.music") is None
    assert run("amzn1.ask.skill.house") is None
    assert run("amzn1.ask.skill.someone-else") == 403


def test_house_skill_passes_before_the_wizard_is_done(check, monkeypatch):
    run, state = check
    from myhouse import deploy

    monkeypatch.setattr(deploy, "skill_id", lambda: "amzn1.ask.skill.house")
    assert run("amzn1.ask.skill.house") is None
    assert run("amzn1.ask.skill.music") == 503


def test_unverified_state_allows_only_its_own_skill(check, monkeypatch):
    run, state = check
    from myhouse import deploy

    monkeypatch.setattr(deploy, "skill_id", lambda: None)
    state.write_text(json.dumps({"phase": "reconciled", "skill_id": "amzn1.ask.skill.music"}))
    assert run("amzn1.ask.skill.music") is None
    assert run("amzn1.ask.skill.other") == 403


def test_corrupt_access_file_still_fails_closed(check, monkeypatch):
    run, state = check
    from myhouse import deploy

    monkeypatch.setattr(deploy, "skill_id", lambda: None)
    state.write_text(json.dumps({"phase": "reconciled", "skill_id": "amzn1.ask.skill.music"}))
    access.access_path().write_text("invalid")
    assert run("amzn1.ask.skill.music") == 503
