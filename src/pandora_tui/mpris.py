"""Standard desktop controls; playlists also expose stations as selectable sources."""
import hashlib
from dbus_next import Variant, DBusError
from dbus_next.aio import MessageBus
from dbus_next.constants import PropertyAccess, NameFlag, RequestNameReply
from dbus_next.service import ServiceInterface, method, dbus_property

NAME = "org.mpris.MediaPlayer2.pandora_tui"
PATH = "/org/mpris/MediaPlayer2"


class Root(ServiceInterface):
    def __init__(self, quit_callback, raise_callback):
        super().__init__("org.mpris.MediaPlayer2")
        self.quit_callback, self.raise_callback = quit_callback, raise_callback

    @method()
    def Raise(self):
        self.raise_callback()

    @method()
    def Quit(self):
        self.quit_callback()

    @dbus_property(access=PropertyAccess.READ)
    def CanQuit(self) -> 'b': return True

    @dbus_property(access=PropertyAccess.READ)
    def CanRaise(self) -> 'b': return True

    @dbus_property(access=PropertyAccess.READ)
    def HasTrackList(self) -> 'b': return False

    @dbus_property(access=PropertyAccess.READ)
    def Identity(self) -> 's': return "Pandora TUI"

    @dbus_property(access=PropertyAccess.READ)
    def DesktopEntry(self) -> 's': return "pandora-tui"

    @dbus_property(access=PropertyAccess.READ)
    def SupportedUriSchemes(self) -> 'as': return []

    @dbus_property(access=PropertyAccess.READ)
    def SupportedMimeTypes(self) -> 'as': return []


class Player(ServiceInterface):
    def __init__(self, engine):
        super().__init__("org.mpris.MediaPlayer2.Player")
        self.engine = engine

    @method()
    async def Play(self): await self.engine._guard(self.engine.play())

    @method()
    async def Pause(self): await self.engine._guard(self.engine.pause())

    @method()
    async def PlayPause(self): await self.engine._guard(self.engine.toggle())

    @method()
    async def Stop(self): await self.engine._guard(self.engine.stop())

    @method()
    async def Next(self): await self.engine._guard(self.engine.next())

    @method()
    async def Previous(self): await self.engine._guard(self.engine.previous())

    @method()
    def Seek(self, Offset: 'x'): pass

    @method()
    def SetPosition(self, TrackId: 'o', Position: 'x'): pass

    @method()
    def OpenUri(self, Uri: 's'):
        raise DBusError("org.mpris.MediaPlayer2.Error.NotSupported", "Select a source from your Pandora library.")

    @dbus_property(access=PropertyAccess.READ)
    def PlaybackStatus(self) -> 's': return self.engine.status

    @dbus_property(access=PropertyAccess.READ)
    def Metadata(self) -> 'a{sv}':
        track = self.engine.track
        if not track:
            return {}
        result = {"mpris:trackid": Variant('o', track.path),
                  "mpris:length": Variant('x', int(track.duration * 1_000_000)),
                  "xesam:title": Variant('s', track.title),
                  "xesam:artist": Variant('as', [track.artist]),
                  "xesam:album": Variant('s', track.album)}
        if track.art_url.startswith("https://"):
            result["mpris:artUrl"] = Variant('s', track.art_url)
        return result

    @dbus_property(access=PropertyAccess.READ)
    def Position(self) -> 'x': return int(self.engine.position * 1_000_000)

    @dbus_property()
    def Rate(self) -> 'd': return 1.0

    @Rate.setter
    def Rate(self, value: 'd'):
        if value != 1:
            raise DBusError("org.freedesktop.DBus.Error.NotSupported", "Only normal playback speed is supported.")

    @dbus_property(access=PropertyAccess.READ)
    def MinimumRate(self) -> 'd': return 1.0

    @dbus_property(access=PropertyAccess.READ)
    def MaximumRate(self) -> 'd': return 1.0

    @dbus_property()
    def Volume(self) -> 'd': return self.engine.volume

    @Volume.setter
    def Volume(self, value: 'd'): self.engine.spawn(self.engine.set_volume(value))

    @dbus_property()
    def Shuffle(self) -> 'b': return self.engine.shuffle

    @Shuffle.setter
    def Shuffle(self, value: 'b'): self.engine.spawn(self.engine.set_shuffle(value))

    @dbus_property(access=PropertyAccess.READ)
    def CanGoNext(self) -> 'b': return self.engine.can_next and not self.engine.busy

    @dbus_property(access=PropertyAccess.READ)
    def CanGoPrevious(self) -> 'b': return self.engine.can_previous and not self.engine.busy

    @dbus_property(access=PropertyAccess.READ)
    def CanPlay(self) -> 'b': return bool(self.engine.track) and not self.engine.busy

    @dbus_property(access=PropertyAccess.READ)
    def CanPause(self) -> 'b': return bool(self.engine.track) and not self.engine.busy

    @dbus_property(access=PropertyAccess.READ)
    def CanSeek(self) -> 'b': return False

    @dbus_property(access=PropertyAccess.READ)
    def CanControl(self) -> 'b': return True

    def changed(self):
        names = ("PlaybackStatus", "Metadata", "Volume", "Shuffle", "CanGoNext", "CanGoPrevious", "CanPlay", "CanPause")
        self.emit_properties_changed({name: getattr(self, name) for name in names})


class Playlists(ServiceInterface):
    def __init__(self, engine):
        super().__init__("org.mpris.MediaPlayer2.Playlists")
        self.engine = engine

    @staticmethod
    def path(source):
        return "/io/github/pandora_tui/source/" + hashlib.sha256(source.id.encode()).hexdigest()[:24]

    @method()
    def GetPlaylists(self, Index: 'u', MaxCount: 'u', Order: 's', ReverseOrder: 'b') -> 'a(oss)':
        sources = sorted(self.engine.sources, key=lambda source: source.name.casefold(), reverse=ReverseOrder)
        return [[self.path(source), source.name, ""] for source in sources[Index:Index + MaxCount]]

    @method()
    async def ActivatePlaylist(self, PlaylistId: 'o'):
        for source in self.engine.sources:
            if self.path(source) == PlaylistId:
                await self.engine._guard(self.engine.choose(source.id))
                return
        raise DBusError("org.freedesktop.DBus.Error.InvalidArgs", "Unknown Pandora source")

    @dbus_property(access=PropertyAccess.READ)
    def PlaylistCount(self) -> 'u': return len(self.engine.sources)

    @dbus_property(access=PropertyAccess.READ)
    def Orderings(self) -> 'as': return ["Alphabetical"]

    @dbus_property(access=PropertyAccess.READ)
    def ActivePlaylist(self) -> '(b(oss))':
        for source in self.engine.sources:
            if self.engine.track and source.id == self.engine.track.source_id:
                return [True, [self.path(source), source.name, ""]]
        return [False, ["/", "", ""]]

    def changed(self):
        self.emit_properties_changed({"PlaylistCount": self.PlaylistCount, "ActivePlaylist": self.ActivePlaylist})


class Mpris:
    async def start(self, engine, quit_callback, raise_callback):
        self.bus = await MessageBus().connect()
        self.player, self.playlists = Player(engine), Playlists(engine)
        for interface in (Root(quit_callback, raise_callback), self.player, self.playlists):
            self.bus.export(PATH, interface)
        reply = await self.bus.request_name(NAME, NameFlag.DO_NOT_QUEUE)
        if reply != RequestNameReply.PRIMARY_OWNER:
            self.bus.disconnect()
            raise RuntimeError("Pandora player is already running")
        engine.listeners.extend([self.player.changed, self.playlists.changed])

    def close(self):
        if getattr(self, "bus", None):
            self.bus.disconnect()
