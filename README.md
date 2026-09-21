# OmaMouse

Share one keyboard and mouse across the machines on your Tailscale tailnet, from the Omarchy bar. Push the pointer off the edge of this screen and it appears on the next computer. Keystrokes follow it.

The engine is [lan-mouse](https://github.com/feschber/lan-mouse). This plugin is ours: Tailscale discovery, pairing in the panel, and clipboard on pointer-enter. It is not a fork of other Omarchy lan-mouse widgets.

## Install

```sh
omarchy plugin add https://github.com/avb/omamouse.git --enable
```

Click the mouse icon, then install lan-mouse from the panel if it is missing, or:

```sh
~/.config/omarchy/plugins/io.github.avb.omamouse/setup
```

Turn the switch on. Tailscale has to be connected first.

On this computer, the panel's **Install lan-mouse on this computer** link runs `omarchy pkg add lan-mouse`.

## Pair a machine

The panel lists Tailscale peers that can run lan-mouse (Linux, macOS, Windows). Click a name to select it, then:

- **Install** puts lan-mouse on that machine over SSH, starts it, and exchanges fingerprints so the pointer can cross
- **Layout** is a map of this screen. Click a computer, then click an edge. That sets this machine and the opposite edge on the other computer so the pointer comes back.
- **Retry SSH** and the user/password fields appear only if that first SSH attempt fails
- **Copy steps** is the hand-install fallback, also only after SSH fails (always for Windows)
- **Restart there** kills and reopens Lan Mouse on that computer (Mac: desktop session, then rewrite pairing)
- **Forget pair** removes the edge here and the pairing file on that computer
- **Release pointer** drops a stuck capture on this machine

**macOS.** SSH uses the short Tailscale hostname (`spatha`, not the `.ts.net` name), then the Tailscale IP if that name does not connect. Host keys are accepted automatically. If usernames differ or there is no key, the panel asks for an SSH user and password after the first failure. The password is not stored. If it works we copy this computer's public key over. After the app is on the Mac we start it, write this computer's fingerprint into its config, and pull its fingerprint back so both sides are authorized. Grant Accessibility if macOS asks.

Both sides can send. Off this right goes to tachi; off tachi’s left comes here. While the pointer is on the other computer, that computer’s mouse is captured. Slide back to the facing edge, or Control+Shift+Alt+Super (on a Mac: Control+Shift+Option+Command). **Release pointer** in the panel (or `u`) drops a stuck capture on this machine.

On a Mac, Lan Mouse has to run in the logged-in desktop session. A daemon started over SSH uses a dummy backend and never moves the cursor. Re-pair opens the app in that session, then writes the pairing file again because the window can blank fingerprints. If the pointer leaves this screen and the other computer is down, toggle OmaMouse off in the bar to get the cursor back.

**Windows.** Always manual. Copy steps and run the zip.

**Linux.** Over SSH we try `pacman` when it is there. Otherwise copy steps.

On the other computer, if you installed by hand:

1. Install [lan-mouse](https://github.com/feschber/lan-mouse/releases). On a Mac, drop the .app in Applications, clear quarantine with `xattr -rd com.apple.quarantine "Lan Mouse.app"`, and grant Accessibility.
2. Start it and copy its fingerprint.
3. Back here, paste that fingerprint under **Allow a peer in** with the Tailscale hostname.
4. On the other computer, authorize *this* machine's fingerprint the same way.

UDP `4242` has to reach the peer on Tailscale. If a Mac still cannot connect, check Tailscale is up on both sides and that neither end is using an exit node that blocks peer-to-peer.

## Clipboard

When the pointer enters a peer, `scripts/clipboard-push` runs. It sends `wl-paste` over SSH to `pbcopy` on macOS or `wl-copy` on Linux. Turn the clipboard row off if you do not want that.

The reverse direction needs a hook on the other computer:

```sh
pbpaste | ssh dirk wl-copy
```

## Keys

| Key | Action |
|-----|--------|
| `s` | Start or stop lan-mouse |
| `u` | Release a stuck pointer on this machine |
| `c` | Copy this machine's fingerprint |
| `b` | Toggle clipboard |
| `x` | Remove the highlighted peer |
| `r` | Refresh |
| `i` | Install lan-mouse on the selected peer, or on this computer |
| `n` | Install on the selected peer |
| `t` | Retry SSH to the selected peer |
| `a` | Add or cycle the selected peer's screen edge |
| Esc | Close |

Right click the bar icon to start or stop. Middle click refreshes.

## Remove

```sh
omarchy-shell io.github.avb.omamouse stop
omarchy plugin remove io.github.avb.omamouse
```

`~/.config/lan-mouse/` is left alone so you can reinstall without pairing again.

## License

MIT. lan-mouse itself is GPL-3.0-or-later. This plugin talks to it as a separate program.
