from __future__ import annotations

import os
from typing import Any

_ui = None
_error = ""


def ready() -> tuple[bool, str]:
    if os.path.exists("/dev/uinput") and os.access("/dev/uinput", os.W_OK):
        return True, ""
    if not os.path.exists("/dev/uinput"):
        return False, "uinput module is not loaded"
    return False, "no write access to /dev/uinput (run setup)"


def _ensure() -> Any:
    global _ui, _error
    if _ui is not None:
        return _ui
    ok, err = ready()
    if not ok:
        _error = err
        raise RuntimeError(err)
    try:
        from evdev import UInput, ecodes as e
    except ImportError as exc:
        _error = "python-evdev is not installed"
        raise RuntimeError(_error) from exc
    cap = {
        e.EV_KEY: [
            e.BTN_LEFT,
            e.BTN_RIGHT,
            e.BTN_MIDDLE,
            e.BTN_SIDE,
            e.BTN_EXTRA,
            *range(e.KEY_ESC, min(e.KEY_MICMUTE, 256)),
        ],
        e.EV_REL: [e.REL_X, e.REL_Y, e.REL_WHEEL, e.REL_HWHEEL],
    }
    _ui = UInput(cap, name="Deskshare", vendor=0xD1CE, product=0x5A4E)
    return _ui


def close() -> None:
    global _ui
    if _ui is not None:
        _ui.close()
        _ui = None


_BTN = {1: 0x110, 2: 0x112, 3: 0x111}  # LEFT, MIDDLE, RIGHT
_KEYS = {
    "Escape": 1,
    "1": 2,
    "2": 3,
    "3": 4,
    "4": 5,
    "5": 6,
    "6": 7,
    "7": 8,
    "8": 9,
    "9": 10,
    "0": 11,
    "minus": 12,
    "equal": 13,
    "BackSpace": 14,
    "Tab": 15,
    "q": 16,
    "w": 17,
    "e": 18,
    "r": 19,
    "t": 20,
    "y": 21,
    "u": 22,
    "i": 23,
    "o": 24,
    "p": 25,
    "bracketleft": 26,
    "bracketright": 27,
    "Return": 28,
    "Control_L": 29,
    "a": 30,
    "s": 31,
    "d": 32,
    "f": 33,
    "g": 34,
    "h": 35,
    "j": 36,
    "k": 37,
    "l": 38,
    "semicolon": 39,
    "apostrophe": 40,
    "grave": 41,
    "Shift_L": 42,
    "backslash": 43,
    "z": 44,
    "x": 45,
    "c": 46,
    "v": 47,
    "b": 48,
    "n": 49,
    "m": 50,
    "comma": 51,
    "period": 52,
    "slash": 53,
    "Shift_R": 54,
    "Alt_L": 56,
    "space": 57,
    "Caps_Lock": 58,
    "F1": 59,
    "F2": 60,
    "F3": 61,
    "F4": 62,
    "F5": 63,
    "F6": 64,
    "F7": 65,
    "F8": 66,
    "F9": 67,
    "F10": 68,
    "Num_Lock": 69,
    "Control_R": 97,
    "Alt_R": 100,
    "Super_L": 125,
    "Super_R": 126,
    "Left": 105,
    "Right": 106,
    "Up": 103,
    "Down": 108,
    "Delete": 111,
    "Home": 102,
    "End": 107,
    "Page_Up": 104,
    "Page_Down": 109,
    "Insert": 110,
}


def handle(msg: dict) -> None:
    kind = msg.get("t")
    ui = _ensure()
    from evdev import ecodes as e

    if kind == "move":
        dx = int(round(float(msg.get("dx") or 0)))
        dy = int(round(float(msg.get("dy") or 0)))
        if dx:
            ui.write(e.EV_REL, e.REL_X, dx)
        if dy:
            ui.write(e.EV_REL, e.REL_Y, dy)
        ui.syn()
    elif kind == "button":
        code = _BTN.get(int(msg.get("btn") or 1), e.BTN_LEFT)
        ui.write(e.EV_KEY, code, 1 if msg.get("down") else 0)
        ui.syn()
    elif kind == "wheel":
        dy = int(msg.get("dy") or 0)
        dx = int(msg.get("dx") or 0)
        if dy:
            ui.write(e.EV_REL, e.REL_WHEEL, dy)
        if dx:
            ui.write(e.EV_REL, e.REL_HWHEEL, dx)
        ui.syn()
    elif kind == "key":
        name = str(msg.get("code") or "")
        if len(name) == 1:
            name = name.lower()
        key = _KEYS.get(name)
        if key is None:
            return
        ui.write(e.EV_KEY, key, 1 if msg.get("down") else 0)
        ui.syn()
    elif kind == "clip":
        text = str(msg.get("text") or "")
        if not text:
            return
        import subprocess

        subprocess.run(["wl-copy"], input=text.encode(), check=False, timeout=2)
