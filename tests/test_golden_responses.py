"""Replays every golden case and requires the skill's response to match the recording exactly.

tests/golden/upstream-v1.4.1.json was recorded from the unmodified upstream skill (timlaing v1.4.1, the version the
add-on 1.3.6 ships). A case whose behaviour the fork changes ON PURPOSE is listed in tests/golden/fork-changes.json
with the new expected record and a reason; every other case must stay byte-identical to upstream.

Re-record (only after an intentional change): python scripts/record_golden.py
"""

import json
from pathlib import Path

import pytest
from golden_cases import case_ids, run_case

GOLDEN = Path(__file__).parent / "golden"
UPSTREAM = json.loads((GOLDEN / "upstream-v1.4.1.json").read_text())
_changes_file = GOLDEN / "fork-changes.json"
CHANGES = json.loads(_changes_file.read_text()) if _changes_file.exists() else {}


def test_golden_covers_every_case():
    assert sorted(UPSTREAM) == sorted(case_ids())


def test_fork_changes_are_documented():
    for case_id, change in CHANGES.items():
        assert case_id in UPSTREAM, case_id
        assert change.get("reason"), f"{case_id}: every deliberate change needs a reason"
        assert change["expected"] != UPSTREAM[case_id], f"{case_id}: listed as changed but identical to upstream"


@pytest.mark.parametrize("case_id", case_ids())
def test_response_matches_golden(case_id, monkeypatch):
    expected = CHANGES[case_id]["expected"] if case_id in CHANGES else UPSTREAM[case_id]
    actual = run_case(case_id, monkeypatch)
    assert json.dumps(actual, sort_keys=True, indent=1) == json.dumps(expected, sort_keys=True, indent=1)
