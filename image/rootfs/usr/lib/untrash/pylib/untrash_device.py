"""The device UntrashOS runs on, as the board describes it.

model(root)  {"name": "NAS542", "title": "Zyxel NAS542", "bays": 4, ...}
             from /run/untrash/model.json (written at boot by the board's
             untrash-model), else the board family from board.json
             ("title"), else a neutral "NAS".  Never guesses a model:
             a wrong one is worse than none (docs/board-interface.md).

root: test prefix (ZT_DESK_ROOT and friends); "" on the NAS.
"""
import json

MODEL = "/run/untrash/model.json"
BOARD = "/usr/share/untrash/board.json"


def _json(path):
    try:
        with open(path) as f:
            v = json.load(f)
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def model(root=""):
    m = _json(root + MODEL)
    if isinstance(m.get("name"), str) and m.get("name") and isinstance(m.get("title"), str):
        out = {"name": m["name"], "title": m["title"], "id": m.get("id") or "",
               "source": m.get("source") or ""}
        if m.get("bays") in (1, 2, 3, 4, 5, 6, 7, 8):
            out["bays"] = m["bays"]
        return out
    title = _json(root + BOARD).get("title")
    if isinstance(title, str) and title:
        return {"name": title, "title": title, "id": "", "source": "board"}
    return {"name": "NAS", "title": "NAS", "id": "", "source": "none"}
