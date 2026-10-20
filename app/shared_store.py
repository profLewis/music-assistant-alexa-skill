"""Locked, independent snapshots for MA streams and Alexa playback metadata.

MA streams are kept per player as well as "latest overall": when Music Assistant plays on several Echoes at once it
pushes one stream per player within a fraction of a second, and with a single slot each push overwrote the last, so
every Echo was handed the same (last) stream. A request from an Echo that is mapped to a player gets that player's
stream; anything else gets the latest push, exactly as before.
"""

import time
from copy import deepcopy
from threading import RLock

_lock = RLock()
_ma = None
_ma_by_player = {}
_alexa = None
_version = 0


def get_ma(player_id=None):
    with _lock:
        if player_id and player_id in _ma_by_player:
            return deepcopy(_ma_by_player[player_id])
        return deepcopy(_ma)


def get_alexa():
    with _lock:
        return deepcopy(_alexa)


def set_ma(payload, player_id=None):
    global _ma, _version
    with _lock:
        _version += 1
        _ma = deepcopy(payload)
        _ma.update(version=_version, timestamp=time.time())
        if player_id:
            _ma_by_player[player_id] = deepcopy(_ma)
        return _version


def set_alexa(payload):
    global _alexa
    with _lock:
        _alexa = deepcopy(payload)
