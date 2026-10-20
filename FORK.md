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

## Fork changes

1. **One stream per speaker** (2026-10-20). Upstream kept a single "latest stream" slot. When Music Assistant played on
   several Echoes at once, each push overwrote the previous one, so every Echo was handed the same stream and only one
   played. Pushes are now also stored per MA player, taken from the flow URL (`/flow/<session>/<player>/…`) or an
   explicit `playerId`. A request from an Echo that is mapped to a player on `/devices` gets that player's stream.
   Unmapped Echoes, or players with no push of their own, get the latest push exactly as upstream does.
   - The golden responses are unchanged (all 264 cases are still byte-identical to upstream).
   - The new behaviour is covered in `tests/test_multi_player.py`.
   - Note: this makes several Echoes *play*, but they are not sample-synced. Only Amazon multi-room groups give true
     sync, and a custom skill can't be started on one.

2. **APL off really ends the session** (2026-10-20). With `enable_apl=false`, a display left on a screen Echo from
   before kept polling (APL UserEvent "MetadataRefresh") and every refresh kept the session open, so Alexa kept listening
   and Alexa+ said "say 'Alexa, exit' to go back to Alexa+". The refresh now ends the session when APL is off; with APL
   on nothing changes. Golden responses unchanged (the golden refresh case uses a different argument); covered in
   `tests/test_apl_off_refresh.py` (fails on upstream, passes here).
