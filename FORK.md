# profLewis fork

Fork of [timlaing/music-assistant-alexa-skill](https://github.com/timlaing/music-assistant-alexa-skill), branched
from **v1.4.1** - the skill image that add-on 1.3.6 ships - so it starts byte-for-byte equal to what runs today.

## Branch
- `proflewis` - the fork's working branch (base: tag `v1.4.1`).

## Golden-response tests
`tests/test_golden_responses.py` sends every Alexa request type the skill handles (launch, PlayAudio, help,
stop/pause/resume, next/previous, AudioPlayer events, PlaybackController commands, APL user events, ...) to
`lambda_handler`, for four device kinds (speaker, Echo Show with APL on, Echo Show with APL off, APL-only) and
two locales (en-GB, en-US) - 264 cases. The whole response envelope and the side effects (Music Assistant
commands, HTTP probes) must match `tests/golden/upstream-v1.4.1.json`, recorded from the unmodified upstream code.

A deliberate behaviour change goes in `tests/golden/fork-changes.json` (`{case_id: {"reason": ..., "expected":
...}}`); every case not listed there must stay identical to upstream.

    python scripts/record_golden.py --check            # (upstream code only) re-record + prove determinism
    python -m pytest tests/test_golden_responses.py    # fork vs upstream
