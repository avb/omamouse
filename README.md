# OmaMouse

Slide the mouse off the edge of this screen and it appears on another computer. The keyboard goes with it.

OmaMouse lives in the Omarchy bar. It lists the machines on your Tailscale network, puts the sharing software on them, and lets you pick which edge of this screen leads where.

Both computers need [Tailscale](https://tailscale.com) up and on the same tailnet. The stock Tailscale icon in the bar handles that.

## Install

```sh
omarchy plugin add https://github.com/avb/omamouse.git --enable
```

Click the mouse icon. If this computer is missing the sharing software, the panel offers to install it. Turn the switch on.

## Pair a computer

The panel lists Linux, macOS, and Windows machines from Tailscale. Click a name, then Install. That copies the app over SSH, starts it, and swaps fingerprints so the pointer can cross.

Then click an edge on the layout map. Off this edge goes there. Off their opposite edge comes back.

If SSH does not accept this computer's user or key, the panel asks for a username and password. The password is not stored. A working login copies this computer's public key over so the next time does not need it.

**macOS.** Grant Accessibility when the Mac asks. The app has to run in the logged-in desktop session. A process started over SSH never moves the cursor. Install and Re-pair open it on the desktop, then write the pairing file again, because the Mac window can blank fingerprints.

**Windows.** Install is always by hand. Copy steps, run the zip, then paste the fingerprint under Allow a peer in.

**Linux.** Install uses `pacman` over SSH when it is there. Otherwise copy steps.

To pair by hand on the other computer:

1. Install [lan-mouse](https://github.com/feschber/lan-mouse/releases). On a Mac, put `Lan Mouse.app` in Applications, run `xattr -rd com.apple.quarantine "Lan Mouse.app"`, and grant Accessibility.
2. Start it and copy its fingerprint.
3. In OmaMouse, paste that fingerprint under Allow a peer in, with the Tailscale hostname.
4. On the other computer, authorize this machine's fingerprint the same way.

UDP 4242 has to reach the peer on Tailscale. If a Mac still will not connect, check Tailscale is up on both sides and that neither end is using an exit node that blocks peer-to-peer.

## Using it

Push the pointer off the edge you placed. It shows up on the other screen. Slide back the other way to return, or press Control+Shift+Alt+Super. On a Mac that is Control+Shift+Option+Command.

If the pointer is stuck on this machine, Release pointer in the panel, or `u`. If it left this screen and the other computer is down, turn OmaMouse off in the bar.

Restart there kills the app on the other computer and opens it again. Forget pair drops the edge here and the pairing file over there.

## Clipboard

When the pointer enters the other computer, this machine's clipboard is sent with it. Turn that row off if you do not want that.

The other direction is a one-liner on that computer:

```sh
pbpaste | ssh this-machine wl-copy
```

## Keys

| Key | Action |
|-----|--------|
| `s` | Start or stop sharing |
| `u` | Release a stuck pointer on this machine |
| `c` | Copy this machine's fingerprint |
| `b` | Toggle clipboard |
| `x` | Remove the highlighted peer |
| `r` | Refresh |
| `i` | Install on the selected peer, or on this computer |
| `n` | Install on the selected peer |
| `t` | Retry SSH to the selected peer |
| `a` | Place the selected peer on an edge |
| Esc | Close |

Right click the bar icon to start or stop. Middle click refreshes.

## Remove

```sh
omarchy-shell io.github.avb.omamouse stop
omarchy plugin remove io.github.avb.omamouse
```

Pairing files in `~/.config/lan-mouse/` stay, so a reinstall does not mean pairing again.

## License

MIT. Pointer traffic is handled by [lan-mouse](https://github.com/feschber/lan-mouse) under GPL-3.0-or-later. OmaMouse talks to it as a separate program.
