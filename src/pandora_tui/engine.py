"""Application state and playback lifecycle, independent of the terminal UI."""
import asyncio
from .errors import AppError, AuthenticationError
from .player import MpvPlayer
from .models import Source


class Engine:
    def __init__(self, api, store, silent=False, player_factory=MpvPlayer, preferences=None):
        self.api, self.store = api, store
        self.player = player_factory(self._player_event, silent=silent)
        self.track = None
        self.sources = []
        self.catalog_sources = {}
        self.authenticated = False
        self.status = "Stopped"
        self.error = ""
        self.busy = False
        self.position = 0.0
        self.preferences = preferences
        self.volume = preferences.volume() if preferences else .5
        self.shuffle = False
        self.started = False
        self.last_progress = 0
        self.listeners = []
        self.lock = asyncio.Lock()
        self.tasks = set()
        self.closed = False

    def spawn(self, coroutine):
        task = asyncio.create_task(self._guard(coroutine))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def _guard(self, coroutine):
        try:
            return await coroutine
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.error = str(error) if isinstance(error, AppError) else "An unexpected player error occurred. Try again."
            if isinstance(error, AuthenticationError):
                self.authenticated = False
            self.notify()

    def notify(self):
        for listener in self.listeners:
            listener()

    async def start(self):
        await self.player.start()
        await self.player.volume(self.volume)

    async def restore_login(self):
        self.busy = True
        self.notify()
        try:
            credentials = await asyncio.to_thread(self.store.load)
            if credentials:
                await self.login(*credentials, remember=False)
        finally:
            self.busy = False
            self.notify()

    async def login(self, email, password, remember=False):
        async with self.lock:
            if self.status != "Stopped":
                raise AppError("Stop playback before changing accounts.")
            self.busy = True
            self.notify()
            try:
                self.authenticated = False
                self.sources = []
                self.catalog_sources.clear()
                self.track = None
                await asyncio.to_thread(self.api.login, email, password)
                self.authenticated = True
                self.sources = await asyncio.to_thread(self.api.library)
                self.error = ""
                if remember:
                    await asyncio.to_thread(self.store.save, email, password)
            finally:
                self.busy = False
                self.notify()

    async def refresh(self):
        async with self.lock:
            self.sources = await asyncio.to_thread(self.api.library)
            self.error = ""
            self.notify()

    async def search(self, query, offset=0):
        query = query.strip()
        if not query or len(query) > 200:
            raise AppError("Enter a music search between 1 and 200 characters.")
        data = await asyncio.to_thread(self.api.search, query, offset)
        if offset == 0:
            active = self.catalog_sources.get(self.track.source_id) if self.track else None
            self.catalog_sources.clear()
            if active:
                self.catalog_sources[active.id] = active
        for row in data["results"]:
            self.catalog_sources[row["id"]] = Source(row["id"], row["name"], row["kind"], row["count"])
        return data

    @property
    def is_radio(self):
        return bool(self.track and self.track.source_id.split(":")[0] in {"ST", "SF", "AU"})

    @property
    def can_previous(self):
        if not self.track or self.track.item_type != "Track":
            return False
        return "REPLAY" in self.track.interactions if self.is_radio else "SEEK" in self.track.interactions

    async def previous(self):
        async with self.lock:
            if not self.can_previous:
                raise AppError("Pandora does not allow replay or previous for this item.")
            await self.player.pause(True)
            self.status = "Paused"
            self.busy = True
            self.notify()
            try:
                track = await asyncio.to_thread(self.api.previous, self.track, self.position, self.is_radio)
                await self._load(track)
            finally:
                self.busy = False
                self.notify()

    async def choose(self, source_id, index=0):
        async with self.lock:
            if source_id not in {s.id for s in self.sources} | self.catalog_sources.keys():
                raise AppError("That station or playlist is not in your library. Refresh and try again.")
            self.busy = True
            self.notify()
            try:
                if self.track and self.status == "Playing":
                    await self.player.pause(True)
                    self.status = "Paused"
                    await asyncio.to_thread(self.api.pause, self.track, self.position)
                track = await asyncio.to_thread(self.api.source, source_id, index)
                self.shuffle = False
                await self._load(track)
            finally:
                self.busy = False
                self.notify()

    async def _load(self, track):
        self.track = track
        self.shuffle = track.shuffled
        self.position = track.progress
        self.started = False
        self.last_progress = 0
        self.error = ""
        try:
            await self.player.load(track)
            self.status = "Playing"
        except AppError:
            self.status = "Stopped"
            raise
        self.notify()

    def _player_event(self, event):
        kind = event.get("event")
        if kind == "property-change" and event.get("name") == "time-pos":
            if isinstance(event.get("data"), (int, float)):
                self.position = float(event["data"])
                if self.status == "Playing" and self.started and self.position - self.last_progress >= 30:
                    self.last_progress = self.position
                    self.spawn(self._progress(self.track, self.position))
        elif kind == "playback-restart":
            self.spawn(self._started(self.track))
        elif kind == "end-file":
            if event.get("reason") == "eof":
                self.spawn(self.next(natural=True, expected=self.track))
            elif event.get("reason") == "error":
                self.status = "Stopped"
                self.error = "Audio could not be played. Select the source again to get a fresh stream."
                self.notify()
        elif kind == "disconnected":
            self.status = "Stopped"
            self.error = "mpv exited. Quit the player service and reopen Pandora TUI."
            self.notify()

    async def _started(self, expected):
        async with self.lock:
            if not expected or self.track is not expected or self.started or self.status != "Playing":
                return
            await asyncio.to_thread(self.api.event, "started", expected, self.position)
            self.started = True
            self.notify()

    async def _progress(self, expected, position):
        async with self.lock:
            if expected is self.track and self.status == "Playing":
                await asyncio.to_thread(self.api.event, "progress", expected, position)

    @property
    def can_next(self):
        return bool(self.track and "SKIP" in self.track.interactions)

    @property
    def can_thumb(self):
        return bool(self.track and any("THUMB" in x for x in self.track.interactions))

    async def next(self, natural=False, expected=None):
        async with self.lock:
            if not self.track or (expected is not None and expected is not self.track):
                return
            if not natural and not self.can_next:
                raise AppError("Pandora does not allow skipping this item.")
            await self.player.pause(True)
            self.status = "Paused"
            self.busy = True
            self.notify()
            try:
                track = await asyncio.to_thread(self.api.advance, self.track, self.position, natural)
                await self._load(track)
            finally:
                self.busy = False
                self.notify()

    async def pause(self):
        async with self.lock:
            if not self.track or self.status != "Playing":
                return
            await self.player.pause(True)
            self.status = "Paused"
            self.notify()
            await asyncio.to_thread(self.api.pause, self.track, self.position)

    async def play(self):
        async with self.lock:
            if not self.track or self.status == "Playing":
                return
            if self.status == "Stopped":
                await self._load(await asyncio.to_thread(self.api.current, self.track.source_id))
            else:
                self.started = False
                self.status = "Playing"
                await self.player.pause(False)
                self.notify()

    async def toggle(self):
        await (self.pause() if self.status == "Playing" else self.play())

    async def stop(self):
        async with self.lock:
            if self.track and self.status == "Playing":
                await self.player.pause(True)
                self.status = "Paused"
                try:
                    await asyncio.to_thread(self.api.pause, self.track, self.position)
                finally:
                    await self.player.stop()
                    self.status = "Stopped"
                    self.notify()
            else:
                await self.player.stop()
                self.status = "Stopped"
                self.notify()

    async def set_volume(self, value):
        self.volume = max(0.0, min(1.0, float(value)))
        await self.player.volume(self.volume)
        if self.preferences:
            await asyncio.to_thread(self.preferences.save_volume, self.volume)
        self.notify()

    async def set_shuffle(self, value):
        async with self.lock:
            if not self.track or not self.track.source_id.startswith("PL:"):
                raise AppError("Choose a playlist to shuffle its tracks.")
            await asyncio.to_thread(self.api.shuffle, self.track.source_id, bool(value))
            self.shuffle = bool(value)
            self.notify()

    async def thumb(self, positive):
        async with self.lock:
            if not self.can_thumb:
                raise AppError("Pandora does not offer ratings for this item.")
            await asyncio.to_thread(self.api.thumb, self.track, self.position, positive)
            self.error = ""
            self.notify()
        if not positive:
            await self.next()

    async def logout(self):
        await self.stop()
        await asyncio.to_thread(self.store.forget)
        await asyncio.to_thread(self.api.logout)
        self.authenticated = False
        self.sources = []
        self.track = None
        self.catalog_sources.clear()
        self.notify()

    def snapshot(self):
        name = next((s.name for s in [*self.sources, *self.catalog_sources.values()] if self.track and s.id == self.track.source_id), "")
        return {"authenticated": self.authenticated, "status": self.status,
                "track": self.track.public() if self.track else None, "source_name": name,
                "position": self.position, "volume": self.volume, "shuffle": self.shuffle,
                "can_next": self.can_next, "can_thumb": self.can_thumb,
                "can_previous": self.can_previous, "previous_label": "Replay" if self.is_radio else "Previous",
                "busy": self.busy, "error": self.error}

    async def close(self):
        self.closed = True
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        try:
            await self.stop()
        except AppError:
            pass
        await self.player.close()
