import argparse
import asyncio
import json
import shutil
import subprocess
import sys
from .errors import AppError


def launch_ui():
    if shutil.which("hyprctl"):
        try:
            result = subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True, timeout=3)
            for client in json.loads(result.stdout):
                if client.get("class") == "io.github.pandora_tui":
                    selector = "address:" + client["address"]
                    focus = subprocess.run(["hyprctl", "dispatch",
                        "hl.dsp.focus({ window = " + json.dumps(selector) + " })"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
                    if focus.returncode != 0:
                        focus = subprocess.run(["hyprctl", "dispatch", "focuswindow", selector],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
                    if focus.returncode == 0:
                        return
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    if shutil.which("omarchy"):
        args = ["omarchy", "launch", "tui", "--app-id=io.github.pandora_tui", sys.executable, "-m", "pandora_tui"]
    elif shutil.which("xdg-terminal-exec"):
        args = ["xdg-terminal-exec", "--app-id=io.github.pandora_tui", "-e", sys.executable, "-m", "pandora_tui"]
    else:
        raise AppError("Open a terminal and run pandora-tui.")
    subprocess.Popen(args, start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    parser = argparse.ArgumentParser(description="Pandora TUI — background playback and desktop media controls")
    parser.add_argument("command", nargs="?", default="ui",
                        choices=["ui", "launch", "serve", "status", "play", "pause", "toggle", "next", "stop", "quit", "logout"])
    parser.add_argument("--silent", action="store_true", help="Use a silent audio output for service testing")
    parser.add_argument("--no-restore", action="store_true", help="Do not load keyring credentials when starting the service")
    args = parser.parse_args()
    try:
        if args.command == "serve":
            from .service import serve
            asyncio.run(serve(args.silent, not args.no_restore))
        elif args.command == "launch": launch_ui()
        elif args.command == "ui":
            from .ui import PandoraApp
            PandoraApp().run()
        else:
            from .ipc import request
            result = asyncio.run(request(args.command))
            if args.command == "status": print(json.dumps(result, indent=2))
    except (AppError, OSError) as error:
        print(str(error) if isinstance(error, AppError) else "Pandora could not start. Check your desktop session.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0
