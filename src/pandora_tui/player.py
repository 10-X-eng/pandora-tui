"""One mpv subprocess controlled over a private Unix socket; no URLs in argv."""
import asyncio
import json
import tempfile
from pathlib import Path
from .errors import AppError


class MpvPlayer:
    def __init__(self, callback, silent=False):
        self.callback = callback
        self.silent = silent
        self.process = self.writer = self.reader_task = None
        self.pending = {}
        self.serial = 0
        self.directory = None
        self.closed = False

    async def start(self):
        self.directory = tempfile.TemporaryDirectory(prefix="pandora-player-")
        path = Path(self.directory.name) / "mpv.sock"
        args = ["mpv", "--no-config", "--no-video", "--idle=yes", "--pause=yes",
                "--input-ipc-server=" + str(path)]
        if self.silent:
            args.append("--ao=null")
        try:
            self.process = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.DEVNULL,
                          stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            for _ in range(100):
                if path.exists():
                    break
                if self.process.returncode is not None:
                    raise AppError("mpv could not start.")
                await asyncio.sleep(.05)
            reader, self.writer = await asyncio.open_unix_connection(path)
            self.reader_task = asyncio.create_task(self._read(reader))
            await self.command("observe_property", 1, "time-pos")
        except (OSError, AppError):
            await self.close()
            raise AppError("Cannot start mpv. Ensure mpv is installed.") from None

    async def _read(self, reader):
        try:
            while line := await reader.readline():
                data = json.loads(line)
                future = self.pending.pop(data.get("request_id"), None)
                if future and not future.done():
                    if data.get("error") == "success":
                        future.set_result(data.get("data"))
                    else:
                        future.set_exception(AppError("mpv could not complete that playback command."))
                elif "event" in data:
                    self.callback(data)
        except (OSError, ValueError, asyncio.CancelledError):
            pass
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(AppError("The audio player disconnected."))
            self.pending.clear()
            if not self.closed:
                self.callback({"event": "disconnected"})

    async def command(self, *args):
        if not self.writer:
            raise AppError("The audio player is not running.")
        self.serial += 1
        serial = self.serial
        future = asyncio.get_running_loop().create_future()
        self.pending[serial] = future
        try:
            self.writer.write((json.dumps({"command": args, "request_id": serial}) + "\n").encode())
            await self.writer.drain()
            return await asyncio.wait_for(future, 10)
        except (OSError, asyncio.TimeoutError):
            raise AppError("The audio player did not respond.") from None
        finally:
            self.pending.pop(serial, None)

    async def load(self, track):
        await self.command("set_property", "pause", True)
        await self.command("loadfile", track.audio_url, "replace", -1,
                           {"start": str(max(0, track.progress))})
        await self.command("set_property", "pause", False)

    async def pause(self, value):
        await self.command("set_property", "pause", value)

    async def stop(self):
        await self.command("stop")

    async def volume(self, value):
        await self.command("set_property", "volume", value * 100)

    async def close(self):
        self.closed = True
        if self.writer:
            self.writer.close()
        if self.reader_task:
            self.reader_task.cancel()
            await asyncio.gather(self.reader_task, return_exceptions=True)
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        if self.directory:
            self.directory.cleanup()
