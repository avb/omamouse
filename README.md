# Deskshare for Omarchy

Share one keyboard and mouse across your Tailscale machines from the Omarchy bar. Push the pointer off the edge of this screen and it appears on the next computer.

This is our own daemon and protocol. It does not wrap lan-mouse, Synergy, or Deskflow. Both sides run Deskshare. The Linux side is this plugin. A Mac can run the same Python package (`python3 -m deskshare daemon`) from a clone of this repo.

Traffic stays on Tailscale. The daemon binds its TLS listener to your tailnet IPv4 only.

## Install

```sh
omarchy plugin add https://github.com/dicebagstudios/omarchy-lan-mouse.git --enable
```

Click the mouse icon, then setup if `/dev/uinput` is not writable. That installs `python-evdev` and a udev rule so this seat can inject a virtual pointer.

Tailscale has to be connected.

## Pair a machine

The panel lists Tailscale peers that can run Deskshare (Linux, macOS, Windows). Click one to put it on the right edge. Click again to walk left / top / bottom. Right click removes it.

On the other computer, start Deskshare, copy its fingerprint, and paste it here under **Allow a peer in**. Authorize this machine's fingerprint over there the same way.

Release grab with Control+Shift+Alt+Super.

## Clipboard

When the pointer crosses, this side sends whatever `wl-paste` returns (capped). The receiver loads it with `wl-copy` or `pbcopy`. Turn the row off if you do not want that.

## Mac

```sh
git clone https://github.com/dicebagstudios/omarchy-lan-mouse.git
cd omarchy-lan-mouse
python3 -m deskshare daemon
```

Grant Accessibility if macOS asks. Receiving input (Linux controlling the Mac) is what this first cut implements on Darwin. Sending from a Mac (event tap) is next.

## Remove

```sh
python3 ~/.config/omarchy/plugins/io.github.dicebagstudios.lan-mouse/scripts/ctl stop
omarchy plugin remove io.github.dicebagstudios.lan-mouse
```

`~/.config/deskshare/` is left alone so you can reinstall without pairing again.

## License

MIT.
