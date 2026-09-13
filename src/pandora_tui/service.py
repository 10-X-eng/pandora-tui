import asyncio
import fcntl
import json
import os
import signal
import uuid
from .api import PandoraAPI
from .credentials import CredentialStore
from .engine import Engine
from .errors import AppError
from .mpris import Mpris
from .paths import runtime_dir, state_dir, socket_path


def device_id():
    path = state_dir() / "device-id"
    try:
        return str(uuid.UUID(path.read_text().strip()))
    except (OSError, ValueError):
        value = str(uuid.uuid4())
        path.write_text(value + "\n")
        path.chmod(0o600)
        return value


async def serve(silent=False, restore=True):
    lock = (runtime_dir() / "service.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return
    shutdown = asyncio.Event()
    engine = Engine(PandoraAPI(device_id()), CredentialStore(), silent=silent)
    mpris = Mpris()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown.set)
    # The daemon is detached from the terminal that launched it.
    loop.add_signal_handler(signal.SIGHUP, lambda: None)

    async def dispatch(data):
        command = data.get("command")
        if command == "status": return engine.snapshot()
        if command == "library": return [source.public() for source in engine.sources]
        if command == "login":
            email, password = data.get("email"), data.get("password")
            if not isinstance(email, str) or not isinstance(password, str) or not email or not password:
                raise AppError("Enter your Pandora email and password.")
            await engine.login(email, password, remember=bool(data.get("remember", False)))
        elif command == "tracks":
            identity = str(data.get("source_id", ""))
            if not any(source.id == identity and source.kind == "playlist" for source in engine.sources):
                raise AppError("Select a playlist from your library.")
            offset = max(0, int(data.get("offset", 0)))
            return await asyncio.to_thread(engine.api.tracks, identity, offset)
        elif command == "up_next":
            identity = str(data.get("source_id", ""))
            if not engine.track or engine.track.source_id != identity or not identity.startswith("ST:"):
                raise AppError("Start a radio station to see its next track.")
            try:
                return await asyncio.to_thread(engine.api.up_next, identity)
            except AppError:
                return None  # A missing optional preview must not disrupt playback.
        elif command == "choose":
            await engine.choose(str(data.get("source_id", "")), max(0, int(data.get("index", 0))))
        elif command == "volume": await engine.set_volume(float(data.get("value", .5)))
        elif command == "shuffle": await engine.set_shuffle(bool(data.get("value")))
        elif command == "thumb": await engine.thumb(bool(data.get("positive")))
        elif command == "quit": shutdown.set()
        elif command in ("play", "pause", "toggle", "next", "stop", "refresh", "logout"):
            await getattr(engine, command)()
        else:
            raise AppError("Unknown player command.")
        return engine.snapshot()

    async def connection(reader, writer):
        try:
            line = await asyncio.wait_for(reader.readline(), 10)
            data = json.loads(line)
            if not isinstance(data, dict): raise ValueError()
            result = await dispatch(data)
            response = {"ok": True, "result": result}
        except Exception as error:
            message = str(error) if isinstance(error, AppError) else "The player could not complete that request."
            engine.error = message
            engine.notify()
            response = {"ok": False, "error": message}
        try:
            writer.write((json.dumps(response) + "\n").encode())
            await writer.drain()
        except (OSError, ConnectionError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    from .cli import launch_ui
    server = None
    try:
        await engine.start()
        await mpris.start(engine, shutdown.set, launch_ui)
        socket_path().unlink(missing_ok=True)
        server = await asyncio.start_unix_server(connection, path=str(socket_path()), limit=65536)
        socket_path().chmod(0o600)
        if restore:
            engine.spawn(engine.restore_login())
        print("Pandora player service is ready.", flush=True)
        await shutdown.wait()
    finally:
        if server:
            server.close()
            await server.wait_closed()
        await engine.close()
        mpris.close()
        socket_path().unlink(missing_ok=True)
        lock.close()
