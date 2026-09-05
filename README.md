# Lan Mouse for Omarchy

Share one keyboard and mouse across the machines on your Tailscale tailnet, from the Omarchy bar. Push the pointer off the edge of this screen and it appears on the next computer. Keystrokes follow it.

This is a software KVM. It wraps [lan-mouse](https://github.com/feschber/lan-mouse) and talks to it over the same config file and CLI. Pairing happens in the panel. You do not need the GTK window for day-to-day use.

It is not Apple Universal Control. The other machine runs lan-mouse too, including macOS.

## Why this exists

The other Omarchy lan-mouse plugin is a health dashboard around the GTK app and assumes a LAN subnet plus a UFW hole. This one treats Tailscale as the network:

- Discovers online peers from `tailscale status` (MagicDNS name plus CGNAT IPv4)
- Writes those addresses into `~/.config/lan-mouse/config.toml`
- Shows this machine's TLS fingerprint in the panel so you can authorize the other side
- Copies clipboard text when the pointer crosses, via Tailscale SSH when it works, otherwise a small listener bound only to your Tailscale IP
- Skips UFW. WireGuard is the filter.

## Install

```sh
omarchy plugin add https://github.com/dicebagstudios/omarchy-lan-mouse.git --enable
```

Click the mouse icon, then the install button if `lan-mouse` is missing, or:

```sh
~/.config/omarchy/plugins/io.github.dicebagstudios.lan-mouse/setup
```

Turn the switch on. Tailscale has to be connected first.

## Pair a machine

On this computer the panel lists Tailscale peers that can run lan-mouse (Linux, macOS, Windows). Click one to put it on the right edge. Click again to walk left / top / bottom. Right click removes it.

On the other computer:

1. Install [lan-mouse](https://github.com/feschber/lan-mouse/releases). On a Mac, drop the .app in Applications, clear quarantine with `xattr -rd com.apple.quarantine "Lan Mouse.app"`, and grant Accessibility.
2. Start it and copy its fingerprint.
3. Back here, paste that fingerprint under **Allow a peer in** with the Tailscale hostname.
4. On the other computer, authorize *this* machine's fingerprint the same way (GTK Authorize, or the same fields if that computer also runs this plugin).

UDP `4242` has to reach the peer on Tailscale. That is the default lan-mouse port. If a Mac still cannot connect, check that Tailscale is up on both sides and that neither end is using an exit node that black-holes peer-to-peer.

## Clipboard

When the pointer enters a peer, this plugin runs `scripts/clipboard-push`. It tries, in order:

1. `tailscale ssh <host> pbcopy` on macOS, or `wl-copy` on Linux
2. A length-prefixed TCP send to `<tailscale-ip>:4243`, which `clipboard-recv` accepts only from `100.64.0.0/10`

Turn the clipboard row off if you do not want that.

The reverse direction (Mac copies, Linux pastes) needs a hook on the Mac. If Tailscale SSH is enabled toward this computer:

```sh
pbpaste | tailscale ssh dirk wl-copy
```

Put that in the Mac lan-mouse client's enter hook, replacing `dirk` with this machine's Tailscale name.

## Keys

| Key | Action |
|-----|--------|
| `s` | Start or stop the daemon |
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

MIT. Lan Mouse itself is GPL-3.0-or-later. This plugin talks to it as a separate program.
