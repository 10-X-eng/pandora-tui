import asyncio
import json
import os
import subprocess
import shutil
import sys
from .errors import AppError
from .paths import socket_path


async def request(command, **args):
    try:
        reader, writer = await asyncio.open_unix_connection(str(socket_path()), limit=2**20)
    except (OSError, ConnectionError):
        raise AppError("The Pandora player service is not running.") from None
    try:
        writer.write((json.dumps({"command": command, **args}) + "\n").encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), 90)
        data = json.loads(line)
        if not data.get("ok"):
            raise AppError(data.get("error", "Player request failed."))
        return data.get("result")
    except (OSError, ValueError, asyncio.TimeoutError):
        raise AppError("The Pandora player service did not respond. Try reopening the TUI.") from None
    finally:
        writer.close()
        await writer.wait_closed()


async def ensure_service():
    try:
        await request("status")
        return
    except AppError:
        pass
    command = [sys.executable, "-m", "pandora_tui", "serve"]
    managed = False
    if shutil.which("systemd-run"):
        # A detached process still inherits its terminal's systemd cgroup.
        # A user service survives uwsm/terminal scope cleanup on Omarchy.
        try:
            result = await asyncio.to_thread(subprocess.run,
                ["systemd-run", "--user", "--quiet", "--collect",
                 "--unit=pandora-tui", "--property=Type=exec", "--", *command],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=10)
            managed = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            pass
    if not managed:
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True, env=os.environ.copy())
    for attempt in range(450):
        # A quitting predecessor may retain the lock while reporting its pause.
        # Retry the transient unit after it exits; an active unit rejects duplicates.
        if managed and attempt and attempt % 30 == 0:
            try:
                await asyncio.to_thread(subprocess.run,
                    ["systemd-run", "--user", "--quiet", "--collect",
                     "--unit=pandora-tui", "--property=Type=exec", "--", *command],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                pass
        await asyncio.sleep(.1)
        try:
            await request("status")
            return
        except AppError:
            continue
    raise AppError("The player service could not start. Run ‘pandora-tui serve’ to diagnose it.")
