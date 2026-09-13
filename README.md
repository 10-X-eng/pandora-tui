# Pandora TUI

A Linux terminal player for Pandora stations and saved playlists, with background
playback, desktop media controls, and a live audio spectrum. Built from scratch
in Python with Textual and mpv, with Omarchy integration.

## Install on Omarchy or Arch Linux

Clone this repository and open its directory. Install the runtime and build tools:

```sh
sudo pacman -S --needed base-devel python python-textual python-dbus-next \
  python-secretstorage python-pycryptodome mpv cava python-build \
  python-installer python-setuptools
python packaging/prepare.py
cd packaging
makepkg -f
sudo pacman -U ./pandora-tui-*.pkg.tar.zst
```

On Omarchy, `omarchy pkg add` can also install the listed dependencies. Run
`makepkg` as your regular user, never as root. A running desktop D-Bus session
is required. Remembering your login requires an unlocked Secret Service keyring,
such as GNOME Keyring or a compatible KWallet setup.

Open **Pandora TUI** from the application menu, or run:

```sh
pandora-tui
```

Enter your own Pandora email and password in the TUI. Browser login and manual
token extraction are not required. “Remember” saves your credentials in the
desktop keyring. Uncheck it to keep credentials in memory for this session.

### Optional Omarchy shortcut

The application does not edit desktop settings during installation. To assign
Super+Shift+P on an Omarchy installation using Hyprland Lua, add these lines to
`~/.config/hypr/bindings.lua`, replacing any existing binding for that combination:

```lua
hl.unbind("SUPER + SHIFT + P")
o.bind("SUPER + SHIFT + P", "Pandora TUI", { launch = "pandora-tui launch" })
```

Then run `hyprctl reload` and check `hyprctl configerrors`. The launcher opens the
TUI or focuses its existing window.

## Use

Tracks follows the playing source automatically: playlist songs appear when a
playlist is playing; radio shows the current song and an upcoming song when
Pandora makes one available. Radio is not a fixed playlist. Playlists load 50
songs at a time; use **Load more tracks** to continue browsing.

| Key | Action |
| --- | --- |
| 1 / 2 / 3 | Stations / playlists / tracks for the playing source |
| / | Search stations and playlists |
| Escape | Return from search to the browser |
| Enter | Play the selected station, playlist, or playlist track |
| Space | Play or pause |
| n | Skip, when Pandora permits it |
| b | Open Tracks |
| v | Hide or show the audio spectrum |
| r / l | Refresh library / sign in |
| q | Close the TUI and keep music playing |
| Ctrl+Q | Stop music and quit the background player |

Closing the terminal leaves music playing. Reopening the TUI reconnects to the
same player. On systemd desktops, the player starts on demand as a transient
user service, independent of the terminal's scope. It does not start music at boot.

The existing desktop media panel can show song, artist, album, and artwork and
control play/pause, next, and volume through MPRIS. Stations and playlists are
also exported through MPRIS Playlists. Omarchy's stock panel does not currently
provide a picker for that list, so choose sources in the TUI.

The spectrum uses CAVA to monitor the default PipeWire output at 30 fps. Other
apps playing through that output also appear in it. CAVA runs only while the TUI
is open and the spectrum is enabled; it creates no Pandora playback session.
Missing CAVA or a failed audio monitor does not prevent music playback.

Additional commands:

```sh
pandora-tui status
pandora-tui play
pandora-tui pause
pandora-tui next
pandora-tui stop     # Stop audio, leave service running
pandora-tui quit     # End the service
pandora-tui logout   # Stop playback and remove the saved keyring login
```

## Limitations and troubleshooting

This is an unofficial client using undocumented Pandora endpoints. It has been
live-tested with a Premium account; other tiers and regions may behave differently.
Saved playlists and on-demand playback depend on your account. Ratings and skips
are subject to Pandora's permissions. Previous/seek controls are not exposed yet.

- **Another-device message:** Pandora permits one active playback session. Pause
  other Pandora clients, then select a source again. Do not run an independent
  live test while this player is running.
- **Cannot remember login:** unlock your desktop keyring or uncheck Remember.
  The app does not fall back to a plaintext password file.
- **Player will not start:** check that mpv is installed and run
  `pandora-tui serve` in a terminal, after quitting any existing service.
- **No spectrum:** check CAVA and your default PipeWire audio output; press `v`
  to hide it. The spectrum captures output audio, not microphone input.

Do not attach account credentials, raw API responses, cookie exports, or signed
audio URLs to issues. `status` excludes credentials and stream URLs but includes
music/library metadata; review anything you share.

## Development and testing

Linux, Python 3.11+, mpv, and a desktop session are required for normal operation.
Other Linux distributions can install their mpv/CAVA/keyring packages and use a
Python virtual environment instead of the Arch package:

```sh
python -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
.venv/bin/pandora-tui
```

The automated tests use fake Pandora clients and do not require credentials,
network access, audio hardware, or a running desktop service. The optional
`tests/live_playback.py` prompts interactively for credentials and refuses to
start if a background player is already running. It uses silent output and is
never part of normal tests or CI.

Code is separated into protocol (`api`, `transport`), audio (`player`), lifecycle
(`engine`), MPRIS (`mpris`), service/IPC, credentials, and UI/visualizer modules.
The UI never owns the music playback process. Passwords and session tokens stay
in the service/keyring; signed stream URLs reach mpv through private IPC.

See [AGENTS.md](AGENTS.md) for installation, testing, and release instructions
for coding agents, and [SECURITY.md](SECURITY.md) for handling sensitive data.

## License and protocol compatibility

MIT; see [LICENSE](LICENSE). Not affiliated with Pandora or Pithos.
`device.json` contains shared public Android protocol compatibility constants,
verified against [Pithos's public device definitions](https://github.com/pithos/pithos/blob/master/pithos/pandora/data.py).
Its partner username/password are
not a listener's login. No Pithos implementation is imported or packaged.
