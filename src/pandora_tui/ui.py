import asyncio
from pathlib import Path
import tomllib
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import Button, Checkbox, DataTable, Footer, Header, Input, Label, Static, TabbedContent, TabPane
from .errors import AppError
from . import ipc
from .visualizer import Spectrum


def clock(seconds):
    seconds = max(0, int(seconds or 0))
    return f"{seconds // 60}:{seconds % 60:02d}"


class LoginScreen(ModalScreen):
    def compose(self) -> ComposeResult:
        with Vertical(id="login-card"):
            yield Label("Sign in to Pandora", id="login-title")
            yield Static("Your password goes directly to Pandora.\nRemembered logins use your desktop keyring.", markup=False)
            yield Input(placeholder="Email address", id="email")
            yield Input(placeholder="Password", password=True, id="password")
            yield Checkbox("Remember in desktop keyring", value=True, id="remember")
            yield Static("", id="login-error", markup=False)
            with Horizontal():
                yield Button("Sign in", id="sign-in", variant="primary")
                yield Button("Cancel", id="cancel-login")

    def on_mount(self): self.query_one("#email", Input).focus()

    @on(Input.Submitted, "#email")
    def next_field(self): self.query_one("#password", Input).focus()

    @on(Button.Pressed, "#cancel-login")
    def cancel(self): self.dismiss()

    @on(Input.Submitted, "#password")
    @on(Button.Pressed, "#sign-in")
    @work(exclusive=True)
    async def submit(self):
        email = self.query_one("#email", Input).value.strip()
        password = self.query_one("#password", Input).value
        button = self.query_one("#sign-in", Button)
        button.disabled = True
        self.query_one("#login-error", Static).update("Signing in…")
        try:
            await self.app.client.request("login", email=email, password=password,
                              remember=self.query_one("#remember", Checkbox).value)
            self.query_one("#password", Input).value = ""
            self.dismiss()
            self.app.reload_library()
        except AppError as error:
            self.query_one("#login-error", Static).update(str(error))
        finally:
            password = ""
            button.disabled = False


class PandoraApp(App):
    TITLE = "Pandora"
    SUB_TITLE = "Background player"
    CSS_PATH = "ui.tcss"
    BINDINGS = [
        ("space", "toggle", "Play/pause"), ("n", "next", "Next"),
        Binding("p", "previous", "Previous", show=False),
        Binding("4", "discover", "Discover", show=False),
        Binding("s", "discover", "Find music", show=False),
        ("slash", "search", "Search"), ("q", "quit", "Close"),
        Binding("b", "browse", "Tracks", show=False),
        Binding("l", "login", "Login", show=False),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("ctrl+q", "quit_player", "Quit player", show=False),
        Binding("1", "stations", "Stations", show=False),
        Binding("2", "playlists", "Playlists", show=False),
        Binding("3", "tracks", "Tracks", show=False),
        Binding("v", "visualizer", "Spectrum", show=False),
        Binding("escape", "leave_search", "Library", show=False),
    ]

    def __init__(self, client=ipc, connect=True, visualizer=True):
        super().__init__()
        self.visualizer_enabled = visualizer
        self.client = client
        self.connect = connect
        self.sources = []
        self.state = {}
        self.selection_pending = False
        self.selected_source = None
        self.browse_source = None
        self.last_playing_source = None
        self.radio_track_key = None
        self.track_rows = []
        self.track_total = 0
        self.login_shown = False
        self.theme_stamp = None
        self.music_query = ""
        self.music_rows = []
        self.music_has_more = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="workspace"):
            with Vertical(id="now-playing"):
                yield Static("Choose something to listen to", id="song", markup=False)
                yield Static("Your stations and playlists are below", id="artist", markup=False)
                yield Static("", id="source", markup=False)
                yield Static("Stopped", id="progress", markup=False)
            with Horizontal(id="controls"):
                yield Button("Previous", id="previous")
                yield Button("Play", id="toggle", variant="primary")
                yield Button("Skip", id="next")
                yield Button("Shuffle off", id="shuffle")
                yield Button("+1", id="thumb-up")
                yield Button("−1", id="thumb-down")
                yield Button("−", id="quieter")
                yield Button("+", id="louder")
            yield Static("OUTPUT SPECTRUM", id="spectrum-label")
            yield Spectrum(enabled=self.visualizer_enabled, id="spectrum")
            yield Input(placeholder="/ Search stations and playlists", id="search")
            with TabbedContent(id="library-tabs"):
                with TabPane("1 Stations", id="stations-tab"):
                    yield DataTable(id="stations", cursor_type="row", zebra_stripes=True)
                with TabPane("2 Playlists", id="playlists-tab"):
                    yield DataTable(id="playlists", cursor_type="row", zebra_stripes=True)
                with TabPane("3 Tracks", id="tracks-tab"):
                    yield Label("Tracks will appear when playback starts", id="tracks-title")
                    yield Label("Single-click or Enter to play", classes="play-hint")
                    yield DataTable(id="tracks", cursor_type="row", zebra_stripes=True)
                    yield Button("Load more tracks", id="more")
                with TabPane("4 Discover", id="discover-tab"):
                    yield Input(placeholder="Search Pandora for songs, artists, albums…", id="music-query")
                    yield Static("Type a search and press Enter", id="music-status", markup=False)
                    yield Label("Single-click or Enter to play", classes="play-hint")
                    yield DataTable(id="discover", cursor_type="row", zebra_stripes=True)
                    yield Button("More results", id="music-more", disabled=True)
        yield Static("Connecting…", id="status", markup=False)
        yield Footer()

    async def on_mount(self):
        self.query_one("#stations", DataTable).add_column("Station")
        self.query_one("#playlists", DataTable).add_columns("Playlist", "Songs")
        self.query_one("#tracks", DataTable).add_columns("#", "Track", "Artist", "Time")
        self.query_one("#discover", DataTable).add_columns("Type", "Title", "Artist")
        self.fit_tables()
        self.set_class(self.size.height < 34, "compact")
        self.query_one("#stations", DataTable).focus()
        self.render_state()
        self.apply_omarchy_theme()
        self.set_interval(3, self.apply_omarchy_theme)
        if self.connect:
            self.start_connection()

    @work(exclusive=True, group="connection")
    async def start_connection(self):
        try:
            await self.client.ensure_service()
            self.set_interval(1, self.poll)
            await self.poll()
        except AppError as error:
            self.query_one("#status", Static).update(str(error))

    async def poll(self):
        try:
            state = await self.client.request("status")
            self.state = state
            if state["authenticated"] and not self.sources:
                await self.load_library()
            if not state["authenticated"] and not state["busy"] and not self.login_shown:
                self.login_shown = True
                self.push_screen(LoginScreen())
            playing_source = (state.get("track") or {}).get("source_id")
            if playing_source != self.last_playing_source:
                self.last_playing_source = playing_source
                self.radio_track_key = None
                self.query_one("#tracks", DataTable).clear()
                self.track_rows = []
                self.track_total = 0
                self.browse_source = None
                if playing_source and playing_source.startswith(("PL:", "AL:", "AP:")):
                    self.query_one("#tracks-title", Label).update("Loading tracks…")
                    self.browse(source_id=playing_source, reveal=False)
            if playing_source and not playing_source.startswith(("PL:", "AL:", "AP:")):
                self.render_radio_track()
            self.render_state()
        except AppError as error:
            self.query_one("#status", Static).update(str(error))

    def render_state(self):
        state = self.state
        track = state.get("track") or {}
        self.query_one("#song", Static).update(track.get("title") or "Choose something to listen to")
        self.query_one("#artist", Static).update(" · ".join(filter(None, [track.get("artist"), track.get("album")])))
        self.query_one("#source", Static).update(state.get("source_name", ""))
        position, duration = state.get("position", 0), track.get("duration", 0)
        bar_width = max(8, self.size.width - 39)
        filled = min(bar_width, max(0, int(bar_width * position / duration))) if duration else 0
        self.query_one("#progress", Static).update(
            f"{clock(position)} / {clock(duration)}  "
            + "━" * filled + "─" * (bar_width - filled) + f"  Vol {int(state.get('volume', .5)*100)}%")
        self.query_one("#toggle", Button).label = "Pause" if state.get("status") == "Playing" else "Play"
        self.query_one("#toggle", Button).disabled = not bool(track) or state.get("busy", False)
        self.query_one("#previous", Button).label = state.get("previous_label", "Previous")
        self.query_one("#previous", Button).disabled = not state.get("can_previous") or state.get("busy", False)
        self.query_one("#next", Button).label = "Skip" if state.get("previous_label") == "Replay" else "Next"
        self.query_one("#next", Button).disabled = not state.get("can_next") or state.get("busy", False)
        for identity in ("thumb-up", "thumb-down"):
            self.query_one("#" + identity, Button).display = bool(state.get("can_thumb"))
        self.query_one("#shuffle", Button).display = str(track.get("source_id", "")).startswith("PL:")
        self.query_one("#shuffle", Button).label = "Shuffle on" if state.get("shuffle") else "Shuffle off"
        self.query_one("#more", Button).display = bool(self.browse_source and self.browse_source.startswith(("PL:", "AL:", "AP:")))
        self.query_one("#more", Button).disabled = len(self.track_rows) >= self.track_total
        message = state.get("error") or ("Working…" if state.get("busy") else
                  "Enter play · 3 tracks · v spectrum · Ctrl+Q stop player")
        self.query_one("#status", Static).update(message)

    async def load_library(self):
        self.sources = await self.client.request("library")
        self.filter_library()

    @work(exclusive=True, group="library")
    async def reload_library(self): await self.load_library()

    @on(Input.Changed, "#search")
    def filter_library(self):
        query = self.query_one("#search", Input).value.casefold()
        for identity, kind in (("stations", "station"), ("playlists", "playlist")):
            table = self.query_one("#" + identity, DataTable)
            table.clear()
            for source in self.sources:
                if source["kind"] != kind or query not in source["name"].casefold():
                    continue
                row = [Text(source["name"])]
                if kind == "playlist": row.append(str(source["count"]))
                table.add_row(*row, key=source["id"])

    def active_source(self):
        active = self.query_one("#library-tabs", TabbedContent).active
        if active == "tracks-tab":
            return self.browse_source
        identity = "playlists" if active == "playlists-tab" else "stations"
        table = self.query_one("#" + identity, DataTable)
        if table.row_count:
            return str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        return None

    @on(DataTable.RowHighlighted)
    def highlighted(self, event):
        if event.data_table.id in ("stations", "playlists"):
            self.selected_source = str(event.row_key.value)

    @on(DataTable.RowSelected)
    def selected(self, event):
        if event.data_table.id == "tracks" and self.browse_source and self.browse_source.startswith(("PL:", "AL:", "AP:")):
            self.command("choose", source_id=self.browse_source, index=int(event.row_key.value))
        elif event.data_table.id == "discover":
            self.command("choose", source_id=str(event.row_key.value))
        elif event.data_table.id in ("stations", "playlists"):
            self.command("choose", source_id=str(event.row_key.value))

    @work(group="commands")
    async def command(self, command, **args):
        if command == "choose":
            if self.selection_pending:
                return
            self.selection_pending = True
        try:
            self.query_one("#status", Static).update("Working…")
            await self.client.request(command, **args)
            if command == "refresh": await self.load_library()
            await self.poll()
        except AppError as error:
            self.query_one("#status", Static).update(str(error))
        finally:
            if command == "choose":
                self.selection_pending = False

    @on(Button.Pressed)
    def button(self, event):
        identity = event.button.id
        if identity in ("toggle", "next", "previous"): self.command(identity)
        elif identity == "choose" and self.active_source():
            self.command("choose", source_id=self.active_source())
        elif identity == "browse": self.action_browse()
        elif identity == "more": self.browse(more=True)
        elif identity == "music-more": self.search_music(more=True)
        elif identity == "shuffle": self.command("shuffle", value=not self.state.get("shuffle"))
        elif identity in ("thumb-up", "thumb-down"): self.command("thumb", positive=identity == "thumb-up")
        elif identity in ("quieter", "louder"):
            self.command("volume", value=self.state.get("volume", .5) + (.05 if identity == "louder" else -.05))

    def action_toggle(self): self.command("toggle")
    def action_next(self): self.command("next")
    def action_previous(self): self.command("previous")
    def action_refresh(self): self.command("refresh")
    def action_login(self): self.push_screen(LoginScreen())
    def action_search(self):
        if self.query_one("#library-tabs", TabbedContent).active == "discover-tab":
            self.query_one("#music-query", Input).focus()
        else:
            self.action_stations()
            self.query_one("#search", Input).focus()

    def action_discover(self):
        self.show_table("discover")
        self.query_one("#music-query", Input).focus()

    @on(Input.Submitted, "#music-query")
    def submit_music_search(self): self.search_music()

    @work(exclusive=True, group="music-search")
    async def search_music(self, more=False):
        query = self.music_query if more else self.query_one("#music-query", Input).value.strip()
        if not query:
            return
        self.query_one("#music-status", Static).update("Searching Pandora…")
        self.query_one("#music-more", Button).disabled = True
        try:
            offset = len(self.music_rows) if more else 0
            data = await self.client.request("search", query=query, offset=offset)
            table = self.query_one("#discover", DataTable)
            if not more:
                table.clear()
                self.music_rows = []
            self.music_query = query
            existing = {row["id"] for row in self.music_rows}
            for row in data["results"]:
                if row["id"] not in existing:
                    table.add_row(row["kind"].title(), Text(row["name"]), Text(row["artist"]), key=row["id"])
                    existing.add(row["id"])
            self.music_rows.extend(data["results"])
            self.music_has_more = data["has_more"]
            self.query_one("#music-more", Button).disabled = not self.music_has_more
            self.query_one("#music-status", Static).update(
                f"{len(existing)} results · Enter to play" if existing else "No matches. Try another search.")
            table.focus()
        except AppError as error:
            self.query_one("#music-status", Static).update(str(error))
    def show_table(self, name):
        self.query_one("#library-tabs", TabbedContent).active = name + "-tab"
        self.query_one("#" + name, DataTable).focus()

    def action_stations(self): self.show_table("stations")
    def action_playlists(self): self.show_table("playlists")
    def action_tracks(self): self.show_table("tracks")
    def action_leave_search(self):
        active = self.query_one("#library-tabs", TabbedContent).active
        self.show_table(active.removesuffix("-tab"))

    async def action_visualizer(self):
        widget = self.query_one("#spectrum", Spectrum)
        widget.display = not widget.display
        self.query_one("#spectrum-label").display = widget.display
        if widget.display and widget.enabled:
            widget.capture = widget.listen()
        elif widget.capture:
            widget.capture.cancel()
            await widget.stop_process()

    def on_resize(self):
        self.call_after_refresh(self.resize_layout)

    def resize_layout(self):
        if len(self.query("#stations")):
            self.fit_tables()
            self.set_class(self.size.height < 34, "compact")
            self.render_state()

    def fit_tables(self):
        width = max(20, self.size.width - 8)
        specs = {"stations": [width - 2], "playlists": [width - 10, 6],
                 "tracks": [3, max(8, int((width - 17) * .6)), max(6, int((width - 17) * .4)), 5],
                 "discover": [8, max(8, int((width - 14) * .65)), max(6, int((width - 14) * .35))]}
        for name, widths in specs.items():
            table = self.query_one("#" + name, DataTable)
            for column, size in zip(table.columns.values(), widths):
                column.auto_width = False
                column.width = size
            table.refresh(layout=True)

    def action_browse(self): self.show_table("tracks")

    def render_radio_track(self):
        track = self.state.get("track") or {}
        key = (track.get("source_id"), track.get("id"), track.get("index"))
        if key == self.radio_track_key:
            return
        self.radio_track_key = key
        if str(key[0]).startswith("ST:"):
            self.load_up_next(key)
        table = self.query_one("#tracks", DataTable)
        table.clear()
        table.add_row("▶", Text(track.get("title", "")), Text(track.get("artist", "")),
                      clock(track.get("duration", 0)), key="current")
        self.browse_source = track.get("source_id")
        self.track_rows = []
        self.track_total = 0
        self.query_one("#tracks-title", Label).update(Text(
            self.state.get("source_name", "Station") + " · Current track"))

    @work(exclusive=True, group="up-next")
    async def load_up_next(self, key):
        try:
            item = await self.client.request("up_next", source_id=key[0])
        except AppError:
            return  # Some accounts/items do not expose a preview.
        if item and key == self.radio_track_key and self.last_playing_source == key[0]:
            self.query_one("#tracks", DataTable).add_row("Next", Text(item["title"]),
                Text(item["artist"]), clock(item["duration"]), key="next")
            self.query_one("#tracks-title", Label).update(Text(
                self.state.get("source_name", "Station") + " · Now playing / Up next"))

    @on(TabbedContent.TabActivated, "#library-tabs")
    def tracks_activated(self, event):
        self.query_one("#search").display = event.pane.id in ("stations-tab", "playlists-tab")
        if event.pane.id == "tracks-tab" and not self.browse_source:
            source = (self.state.get("track") or {}).get("source_id")
            if source and source.startswith(("PL:", "AL:", "AP:")):
                self.browse(source_id=source, reveal=False)

    @work(exclusive=True, group="tracks")
    async def browse(self, more=False, source_id=None, reveal=True):
        source = self.browse_source if more else (source_id or (self.state.get("track") or {}).get("source_id"))
        if not source or not source.startswith(("PL:", "AL:", "AP:")):
            self.query_one("#status", Static).update("Choose a playlist to browse its tracks. Stations generate songs as they play.")
            return
        try:
            result = await self.client.request("tracks", source_id=source, offset=len(self.track_rows) if more else 0)
            table = self.query_one("#tracks", DataTable)
            if not more:
                table.clear()
                self.track_rows = []
            self.browse_source = source
            self.track_rows.extend(result["tracks"])
            self.track_total = result["total"]
            for row in result["tracks"]:
                table.add_row(str(row["index"] + 1), Text(row["title"]), Text(row["artist"]),
                              clock(row["duration"]), key=str(row["index"]))
            name = next((s["name"] for s in self.sources if s["id"] == source), "Playlist")
            self.query_one("#tracks-title", Label).update(Text(f"{name} · {len(self.track_rows)}/{self.track_total} songs"))
            self.query_one("#more", Button).disabled = len(self.track_rows) >= self.track_total
            if reveal:
                self.show_table("tracks")
        except AppError as error:
            self.query_one("#tracks-title", Label).update(str(error))
            self.query_one("#status", Static).update(str(error))

    @work()
    async def action_quit_player(self):
        try:
            await self.client.request("quit")
            self.exit()
        except AppError as error:
            self.query_one("#status", Static).update(str(error))

    def apply_omarchy_theme(self):
        path = Path.home() / ".local/state/omarchy/current/theme/colors.toml"
        try:
            content = path.read_text()
            if content == self.theme_stamp: return
            colors = tomllib.loads(content)
            self.register_theme(Theme(name="omarchy", primary=colors["accent"],
                secondary=colors["accent"], accent=colors["accent"], foreground=colors["foreground"],
                background=colors["background"], surface=colors.get("lighter_background", colors["background"]),
                panel=colors.get("dark_background", colors["background"]),
                dark=colors.get("mode", "dark") == "dark"))
            self.theme = "omarchy"
            self.theme_stamp = content
        except (OSError, ValueError, KeyError):
            pass
