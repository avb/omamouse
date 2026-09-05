from __future__ import annotations

import json
import subprocess
import threading
from typing import Callable

EDGE_PX = 4
RELEASE = {"Control_L", "Shift_L", "Alt_L", "Super_L"}


def screen_size() -> tuple[int, int]:
    try:
        proc = subprocess.run(["hyprctl", "-j", "monitors"], capture_output=True, text=True, timeout=2)
        monitors = json.loads(proc.stdout)
        right = 0
        bottom = 0
        for mon in monitors:
            scale = float(mon.get("scale") or 1) or 1
            x = int(mon.get("x") or 0)
            y = int(mon.get("y") or 0)
            w = int(round(int(mon.get("width") or 0) / scale))
            h = int(round(int(mon.get("height") or 0) / scale))
            right = max(right, x + w)
            bottom = max(bottom, y + h)
        if right and bottom:
            return right, bottom
    except Exception:
        pass
    return 1920, 1080


class Capture:
    """Edge sensors plus a fullscreen overlay, all GTK4 layer-shell."""

    def __init__(self, on_event: Callable[[dict], None], edges: dict[str, str]):
        self.on_event = on_event
        self.edges = dict(edges)  # position -> peer name
        self._held: set[str] = set()
        self._last = (0.0, 0.0)
        self._overlay = None
        self._sensors: list = []
        self._app = None
        self._active_peer: str | None = None
        self._lock = threading.Lock()

    def set_edges(self, edges: dict[str, str]) -> None:
        self.edges = dict(edges)

    def start(self) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Gdk", "4.0")
        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gtk

        self._app = Gtk.Application(application_id="studio.dicebag.deskshare")
        self._app.connect("activate", self._activate)
        threading.Thread(target=lambda: self._app.run([]), name="deskshare-gtk", daemon=True).start()

    def _activate(self, app) -> None:
        self._build_sensors()

    def _layer(self, window, *, overlay=False, edge: str | None = None) -> None:
        from gi.repository import Gtk4LayerShell as LayerShell

        LayerShell.init_for_window(window)
        LayerShell.set_namespace(window, "deskshare")
        LayerShell.set_layer(window, LayerShell.Layer.OVERLAY)
        if overlay:
            for side in (
                LayerShell.Edge.LEFT,
                LayerShell.Edge.RIGHT,
                LayerShell.Edge.TOP,
                LayerShell.Edge.BOTTOM,
            ):
                LayerShell.set_anchor(window, side, True)
            LayerShell.set_exclusive_zone(window, -1)
            LayerShell.set_keyboard_mode(window, LayerShell.KeyboardMode.EXCLUSIVE)
        else:
            mapping = {
                "left": LayerShell.Edge.LEFT,
                "right": LayerShell.Edge.RIGHT,
                "top": LayerShell.Edge.TOP,
                "bottom": LayerShell.Edge.BOTTOM,
            }
            LayerShell.set_anchor(window, mapping[edge], True)
            if edge in ("left", "right"):
                LayerShell.set_anchor(window, LayerShell.Edge.TOP, True)
                LayerShell.set_anchor(window, LayerShell.Edge.BOTTOM, True)
            else:
                LayerShell.set_anchor(window, LayerShell.Edge.LEFT, True)
                LayerShell.set_anchor(window, LayerShell.Edge.RIGHT, True)
            LayerShell.set_exclusive_zone(window, 0)
            LayerShell.set_keyboard_mode(window, LayerShell.KeyboardMode.NONE)

    def _build_sensors(self) -> None:
        from gi.repository import Gtk

        for win in list(self._sensors):
            win.destroy()
        self._sensors = []
        for edge, peer in self.edges.items():
            win = Gtk.Window(application=self._app)
            win.set_decorated(False)
            win.set_resizable(False)
            if edge in ("left", "right"):
                win.set_default_size(EDGE_PX, 100)
            else:
                win.set_default_size(100, EDGE_PX)
            self._layer(win, edge=edge)
            motion = Gtk.EventControllerMotion()
            motion.connect("enter", lambda *a, e=edge, p=peer: self._trip(e, p))
            win.add_controller(motion)
            win.present()
            self._sensors.append(win)

    def _trip(self, edge: str, peer: str) -> None:
        if self._overlay is not None:
            return
        self._active_peer = peer
        self.on_event({"t": "enter", "peer": peer, "edge": edge})
        from gi.repository import Gtk, Gdk

        win = Gtk.Window(application=self._app)
        win.set_decorated(False)
        win.set_title("deskshare")
        self._layer(win, overlay=True)
        try:
            win.set_cursor_from_name("none")
        except Exception:
            pass
        css = Gtk.CssProvider()
        css.load_from_data(b"window { background: alpha(black, 0.02); }")
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._motion)
        win.add_controller(motion)
        click = Gtk.GestureClick()
        click.set_button(0)
        click.connect("pressed", self._pressed)
        click.connect("released", self._released)
        win.add_controller(click)
        scroll = Gtk.EventControllerScroll()
        scroll.set_flags(Gtk.EventControllerScrollFlags.VERTICAL | Gtk.EventControllerScrollFlags.HORIZONTAL)
        scroll.connect("scroll", self._scroll)
        win.add_controller(scroll)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key, True)
        keys.connect("key-released", self._key, False)
        win.add_controller(keys)
        win.present()
        self._overlay = win
        self._last = (0.0, 0.0)
        self._held.clear()
        for sensor in self._sensors:
            sensor.hide()

    def _leave(self) -> None:
        peer = self._active_peer
        self._active_peer = None
        if self._overlay is not None:
            self._overlay.destroy()
            self._overlay = None
        self._held.clear()
        if peer:
            self.on_event({"t": "leave", "peer": peer})
        for sensor in self._sensors:
            sensor.show()

    def _motion(self, _c, x, y) -> None:
        if self._overlay is None:
            return
        lx, ly = self._last
        if lx == 0 and ly == 0:
            self._last = (x, y)
            return
        dx, dy = x - lx, y - ly
        self._last = (x, y)
        if dx == 0 and dy == 0:
            return
        self.on_event({"t": "move", "peer": self._active_peer, "dx": dx, "dy": dy})

    def _pressed(self, gesture, n_press, x, y) -> None:
        btn = int(gesture.get_current_button() or 1)
        self.on_event({"t": "button", "peer": self._active_peer, "btn": btn, "down": True})

    def _released(self, gesture, n_press, x, y) -> None:
        btn = int(gesture.get_current_button() or 1)
        self.on_event({"t": "button", "peer": self._active_peer, "btn": btn, "down": False})

    def _scroll(self, _c, dx, dy) -> bool:
        self.on_event({"t": "wheel", "peer": self._active_peer, "dx": int(dx), "dy": int(-dy)})
        return True

    def _key(self, _c, keyval, keycode, state, down: bool) -> bool:
        from gi.repository import Gdk

        name = Gdk.keyval_name(Gdk.keyval_to_lower(keyval)) or ""
        if down:
            self._held.add(name)
        else:
            self._held.discard(name)
        if RELEASE <= self._held:
            self._leave()
            return True
        self.on_event({"t": "key", "peer": self._active_peer, "code": name, "down": down})
        return True
