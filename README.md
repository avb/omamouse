# Lan Mouse for Omarchy

Share one keyboard and mouse across the machines on your Tailscale tailnet, from the Omarchy bar. Push the pointer off the edge of this screen and it appears on the next computer. Keystrokes follow it.

The engine is [lan-mouse](https://github.com/feschber/lan-mouse). This plugin is ours: Tailscale discovery, pairing in the panel, and clipboard on pointer-enter. It is not a fork of other Omarchy lan-mouse widgets.

## Install

```sh
omarchy plugin add https://github.com/dicebagstudios/omarchy-lan-mouse.git --enable
```

Click the mouse icon, then install lan-mouse from the panel if it is missing, or:

```sh
~/.config/omarchy/plugins/io.github.dicebagstudios.lan-mouse/setup
```

Turn the switch on. Tailscale has to be connected first.

## Pair a machine

The panel lists Tailscale peers that can run lan-mouse (Linux, macOS, Windows). Click one to put it on the right edge. Click again to walk left / top / bottom. Right click removes it.

On the other computer:

1. Install [lan-mouse](https://github.com/feschber/lan-mouse/releases). On a Mac, drop the .app in Applications, clear quarantine with `xattr -rd com.apple.quarantine "Lan Mouse.app"`, and grant Accessibility.
2. Start it and copy its fingerprint.
3. Back here, paste that fingerprint under **Allow a peer in** with the Tailscale hostname.
4. On the other computer, authorize *this* machine's fingerprint the same way.

UDP `4242` has to reach the peer on Tailscale. If a Mac still cannot connect, check Tailscale is up on both sides and that neither end is using an exit node that blocks peer-to-peer.

## Clipboard

When the pointer enters a peer, `scripts/clipboard-push` runs. It sends `wl-paste` over `tailscale ssh` to `pbcopy` on macOS or `wl-copy` on Linux. Turn the clipboard row off if you do not want that.

The reverse direction needs a hook on the other computer. If Tailscale SSH is enabled toward this machine:

```sh
pbpaste | tailscale ssh dirk wl-copy
```

## Keys

| Key | Action |
|-----|--------|
| `s` | Start or stop lan-mouse |
| `c` | Copy this machine's fingerprint |
| `b` | Toggle clipboard |
| `x` | Remove the highlighted peer |
| `r` | Refresh |
| `i` | Install packages |
| Esc | Close |

Right click the bar icon to start or stop. Middle click refreshes.

## Remove

```sh
omarchy-shell io.github.dicebagstudios.lan-mouse stop
omarchy plugin remove io.github.dicebagstudios.lan-mouse
```

`~/.config/lan-mouse/` is left alone so you can reinstall without pairing again.

## License

MIT. lan-mouse itself is GPL-3.0-or-later. This plugin talks to it as a separate program.
