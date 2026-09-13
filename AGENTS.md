# Working on Pandora TUI

## Project rules

- This is an independent Python application, not a Pithos fork. Keep the
  backend minimal and modules separate. Do not add a browser runtime.
- Closing the TUI must keep music playing. The single background service owns
  mpv, authentication, and MPRIS. The TUI only talks to its private Unix socket.
- Persist volume across service restarts. Keep preferences separate from credentials.
- Tracks follows the playing source automatically. Do not require a manual
  browse action to display the active playlist.
- CAVA is owned by the TUI and must stop when hidden or when the TUI closes.
  It monitors audio output; it must not create another Pandora session.
- Preserve MPRIS controls and truthful capability reporting. Never bypass
  Pandora's account restrictions or skip limits.

## Install and run

Work from the repository root. On Arch/Omarchy, install system dependencies:

```sh
sudo pacman -S --needed base-devel python python-textual python-dbus-next \
  python-secretstorage python-pycryptodome mpv cava python-build \
  python-installer python-setuptools
```

Use the environment's normal privilege mechanism; use a desktop authentication
prompt if no interactive sudo terminal is available. Do not request or store a
sudo password. Omarchy also supports `omarchy pkg add` for dependencies.

For development:

```sh
python -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
.venv/bin/pandora-tui
```

For native packaging:

```sh
python packaging/prepare.py
cd packaging
makepkg -Cf
sudo pacman -U ./pandora-tui-*.pkg.tar.zst
```

Run makepkg as a regular user. The package installs the CLI and desktop entry;
it does not change personal keybindings. The README includes an optional
Omarchy Lua binding. Never edit packaged `/usr/share/omarchy` files.

Normal startup needs desktop D-Bus, mpv, and an unlocked Secret Service keyring
if remembering login. `pandora-tui launch` opens or focuses a terminal window.
`pandora-tui quit` ends the player; `pandora-tui logout` also removes its login.

## Tests and live-account work

- Run `python -m pytest -q` in the environment after relevant changes. Tests
  must be offline and must use fake clients; disable the real visualizer in
  headless UI tests unless explicitly testing that monitor's lifecycle.
- Check UI layouts at 60x28, 80x40, and larger sizes. Inspect rendered images
  and, when available, the actual tiled terminal. Verify source changes,
  Tracks population, resize behavior, and quitting without stopping audio.
- Never run two Pandora playback sessions. Use the existing service for live
  desktop tests. Stop it and wait for shutdown before a standalone live test.
- Do not use someone's real account without their authorization. The optional
  `tests/live_playback.py` prompts for credentials; keep it out of CI. Never
  place credentials in arguments, source, screenshots, logs, or test fixtures.
- The service may be running installed code while the TUI uses a checkout.
  Restart the service only when backend changes require it; coordinate any
  playback interruption. UI-only updates need only a TUI restart.

## Privacy and releases

- No personal usernames, email addresses, passwords, auth tokens, device IDs,
  private library IDs, home-directory paths, recordings, or live-account
  captures in tracked files or release artifacts. Use synthetic fixtures.
- `src/pandora_tui/device.json` contains required public partner protocol
  constants. Those are shared client parameters, not personal credentials.
  Do not replace them with anyone's account details.
- Preserve sanitization in API/IPC errors. Never log raw authentication data,
  response bodies, request URLs with tokens, or signed audio URLs.
- Never use `git add .` without inspecting untracked files. Stage an explicit
  allowlist. `.gitignore` is a guardrail, not proof that content is safe.
- Run `python scripts/audit_release.py` after staging. It scans exact staged
  bytes, including filenames, for obvious personal data. When authorized,
  pass `--sensitive-file /path/outside/repo` containing a JSON list of extra
  private strings to reject. It reports locations, never matched values.
- Run `python packaging/prepare.py`; it creates an allowlisted source archive
  with normalized owner metadata and timestamps. Audit it too:
  `python scripts/audit_release.py --archive packaging/pandora-tui-0.2.0.tar.gz`.
- Build/install the Arch package from the generated archive and verify the
  wheel contains only application modules and normal package metadata.
  Native `.BUILDINFO` may contain local build paths: do not upload locally
  built binaries without separately auditing their expanded contents.
- Keep `.venv`, caches, credentials, experiments, screenshots, and build trees
  out of Git. Source-only releases are the default.
- Before pushing, inspect `git diff --cached --stat` and the complete staged
  diff. Do not change repository visibility or publish releases without user
  authorization. Never disclose a secret just to prove it was found.
