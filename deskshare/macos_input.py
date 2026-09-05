from __future__ import annotations

import ctypes
import ctypes.util
import sys
from typing import Callable

if sys.platform != "darwin":
    def ready() -> tuple[bool, str]:
        return False, "not macOS"

    def handle(msg: dict) -> None:
        return

    def start_capture(on_event: Callable, edges: dict) -> None:
        return

else:
    _cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics") or ctypes.util.find_library("ApplicationServices"))
    kCGHIDEventTap = 0
    kCGSessionEventTap = 1
    kCGHeadInsertEventTap = 0
    kCGEventTapOptionDefault = 0
    kCGEventNull = 0
    kCGEventLeftMouseDown = 1
    kCGEventLeftMouseUp = 2
    kCGEventRightMouseDown = 3
    kCGEventRightMouseUp = 4
    kCGEventMouseMoved = 5
    kCGEventLeftMouseDragged = 6
    kCGEventRightMouseDragged = 7
    kCGEventKeyDown = 10
    kCGEventKeyUp = 11
    kCGEventScrollWheel = 22
    kCGEventOtherMouseDown = 25
    kCGEventOtherMouseUp = 26
    kCGHIDEventTap = 0
    kCGEventSourceStateHIDSystemState = 1
    kCGMouseButtonLeft = 0
    kCGMouseButtonRight = 1
    kCGMouseButtonCenter = 2

    class CGPoint(ctypes.Structure):
        _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

    _cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
    _cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
    _cg.CGEventCreateScrollWheelEvent.restype = ctypes.c_void_p
    _cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    _cg.CFRelease.argtypes = [ctypes.c_void_p]

    def ready() -> tuple[bool, str]:
        return True, ""

    def _post_mouse(etype: int, btn: int, dx: float, dy: float) -> None:
        # Relative warp: get current, offset, post.
        _cg.CGEventSetType  # keep table nearby
        loc = CGPoint()
        _cg.CGEventGetLocation.restype = CGPoint
        # Create a dummy event to read location.
        ev = _cg.CGEventCreate(None)
        if ev:
            loc = _cg.CGEventGetLocation(ev)
            _cg.CFRelease(ev)
        loc.x += dx
        loc.y += dy
        event = _cg.CGEventCreateMouseEvent(None, etype, loc, btn)
        if event:
            _cg.CGEventPost(0, event)
            _cg.CFRelease(event)

    _MAC_KEYS = {
        "a": 0x00,
        "s": 0x01,
        "d": 0x02,
        "f": 0x03,
        "h": 0x04,
        "g": 0x05,
        "z": 0x06,
        "x": 0x07,
        "c": 0x08,
        "v": 0x09,
        "b": 0x0B,
        "q": 0x0C,
        "w": 0x0D,
        "e": 0x0E,
        "r": 0x0F,
        "y": 0x10,
        "t": 0x11,
        "1": 0x12,
        "2": 0x13,
        "3": 0x14,
        "4": 0x15,
        "6": 0x16,
        "5": 0x17,
        "equal": 0x18,
        "9": 0x19,
        "7": 0x1A,
        "minus": 0x1B,
        "8": 0x1C,
        "0": 0x1D,
        "o": 0x1F,
        "u": 0x20,
        "i": 0x22,
        "p": 0x23,
        "Return": 0x24,
        "l": 0x25,
        "j": 0x26,
        "k": 0x28,
        "semicolon": 0x29,
        "n": 0x2D,
        "m": 0x2E,
        "Tab": 0x30,
        "space": 0x31,
        "grave": 0x32,
        "BackSpace": 0x33,
        "Escape": 0x35,
        "Super_L": 0x37,
        "Shift_L": 0x38,
        "Alt_L": 0x3A,
        "Control_L": 0x3B,
        "Shift_R": 0x3C,
        "Alt_R": 0x3D,
        "Control_R": 0x3E,
        "Left": 0x7B,
        "Right": 0x7C,
        "Down": 0x7D,
        "Up": 0x7E,
        "Delete": 0x75,
    }

    def handle(msg: dict) -> None:
        kind = msg.get("t")
        if kind == "move":
            _post_mouse(kCGEventMouseMoved, kCGMouseButtonLeft, float(msg.get("dx") or 0), float(msg.get("dy") or 0))
        elif kind == "button":
            btn = int(msg.get("btn") or 1)
            down = bool(msg.get("down"))
            mapping = {
                1: (kCGEventLeftMouseDown, kCGEventLeftMouseUp, kCGMouseButtonLeft),
                2: (kCGEventOtherMouseDown, kCGEventOtherMouseUp, kCGMouseButtonCenter),
                3: (kCGEventRightMouseDown, kCGEventRightMouseUp, kCGMouseButtonRight),
            }
            down_t, up_t, b = mapping.get(btn, mapping[1])
            _post_mouse(down_t if down else up_t, b, 0, 0)
        elif kind == "key":
            name = str(msg.get("code") or "")
            if len(name) == 1:
                name = name.lower()
            vk = _MAC_KEYS.get(name)
            if vk is None:
                return
            event = _cg.CGEventCreateKeyboardEvent(None, vk, bool(msg.get("down")))
            if event:
                _cg.CGEventPost(0, event)
                _cg.CFRelease(event)
        elif kind == "clip":
            text = str(msg.get("text") or "")
            if not text:
                return
            import subprocess

            subprocess.run(["pbcopy"], input=text.encode(), check=False, timeout=2)

    def start_capture(on_event: Callable, edges: dict) -> None:
        # Capture on macOS needs an Accessibility event tap. The first
        # version receives input (Linux or another Mac controlling this
        # machine). Sending from a Mac is a follow-up.
        return
