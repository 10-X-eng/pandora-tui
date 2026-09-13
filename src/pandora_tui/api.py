"""Synchronous Pandora protocol adapter. The service runs it off the UI loop."""
import json
import threading
import time
import urllib.parse
from importlib.resources import files
from Crypto.Cipher import Blowfish
from .errors import AppError, AuthenticationError
from .models import Source, Track, clean
from .transport import Transport

ORIGIN = "https://www.pandora.com"


class PandoraAPI:
    def __init__(self, device_id):
        self.device_id = device_id
        self.http = Transport()
        self.profile = json.loads(files(__package__).joinpath("device.json").read_text())
        self.partner_id = self.partner_token = self.user_id = self.user_token = None
        self.offset = None
        self._credentials = None
        self._lock = threading.RLock()

    def _radio(self, method, fields, encrypted=True):
        params, body = {"method": method}, dict(fields)
        if self.partner_id:
            params["partner_id"] = self.partner_id
        if self.user_id:
            params["user_id"] = self.user_id
        token = self.user_token or self.partner_token
        if token:
            params["auth_token"] = token
            body["userAuthToken" if self.user_token else "partnerAuthToken"] = token
        if self.offset is not None:
            body["syncTime"] = int(time.time() + self.offset)
        data = json.dumps(body).encode()
        if encrypted:
            data += b"\0" * (-len(data) % 8)
            data = Blowfish.new(self.profile["encryptKey"].encode(), Blowfish.MODE_ECB).encrypt(data).hex().encode()
        result = self.http.json("https://tuner.pandora.com/services/json/?" + urllib.parse.urlencode(params),
                                data, {"Content-Type": "text/plain", "User-Agent": "PandoraTUI/0.1"})
        if result.get("stat") != "ok":
            code = result.get("code")
            if code in (1001, 1002, 1011, 1012):
                raise AuthenticationError("Pandora could not sign you in. Check your email and password.")
            raise AppError(f"Pandora radio request failed (code {code if isinstance(code, int) else 'unknown'}).")
        return result.get("result", {})

    def login(self, email, password):
        with self._lock:
            self.partner_id = self.partner_token = self.user_id = self.user_token = None
            self.offset = None
            self._credentials = None
            self.http = Transport()
            partner = self._radio("auth.partnerLogin", {k: self.profile[k] for k in
                                  ("deviceModel", "username", "password", "version")}, encrypted=False)
            self.partner_id, self.partner_token = partner["partnerId"], partner["partnerAuthToken"]
            decoded = Blowfish.new(self.profile["decryptKey"].encode(), Blowfish.MODE_ECB).decrypt(bytes.fromhex(partner["syncTime"]))
            self.offset = int(decoded[4:14]) - time.time()
            user = self._radio("auth.userLogin", {"username": email, "password": password,
                               "loginType": "user", "returnIsSubscriber": True})
            self.user_id, self.user_token = user["userId"], user["userAuthToken"]
            self.http.request(ORIGIN + "/")
            self._credentials = (email, password)

    def logout(self):
        with self._lock:
            self._credentials = None
            self.user_token = self.partner_token = self.user_id = self.partner_id = None
            self.http = Transport()

    def _web(self, endpoint, fields, retry=True):
        with self._lock:
            if not self.user_token:
                raise AuthenticationError("Sign in to Pandora first.")
            headers = {"Content-Type": "application/json", "Origin": ORIGIN,
                       "Referer": ORIGIN + "/", "X-AuthToken": self.user_token}
            for cookie in self.http.cookies:
                if cookie.name == "csrftoken":
                    headers["X-CsrfToken"] = cookie.value
            try:
                data = self.http.json(ORIGIN + "/api/" + endpoint, json.dumps(fields).encode(), headers)
                code = data.get("errorCode")
                if code in (1001, 1002):
                    raise AuthenticationError("Pandora session expired.")
                if code or data.get("error") or data.get("errors"):
                    raise AppError(f"Pandora rejected that action (code {code if isinstance(code, int) else 'unknown'}).")
                return data
            except AuthenticationError:
                # Only retry an explicitly rejected session, never a timeout/mutation.
                if retry and self._credentials:
                    self.login(*self._credentials)
                    return self._web(endpoint, fields, retry=False)
                raise

    def library(self):
        with self._lock:
            stations = self._radio("user.getStationList", {"returnAllStations": True}).get("stations", [])
        result = [Source("ST:0:" + str(s["stationId"]), clean(s["stationName"]), "station") for s in stations]
        offset, seen = 0, set()
        while True:
            page = self._web("v6/collections/getSortedPlaylists", {"request": {
                "sortOrder": "MOST_RECENT_MODIFIED", "offset": offset, "limit": 100,
                "annotationLimit": 100}, "isRecentModifiedPlaylists": False})
            items, annotations = page.get("items", []), page.get("annotations", {})
            for item in items:
                identity = item.get("pandoraId", "")
                if not identity.startswith("PL:") or identity in seen:
                    continue
                seen.add(identity)
                detail = annotations.get(identity, {})
                result.append(Source(identity, clean(item.get("name") or detail.get("name")),
                                     "playlist", int(detail.get("totalTracks") or 0)))
            offset += len(items)
            if not items or offset >= page.get("totalCount", offset):
                break
        return result

    def tracks(self, source_id, offset=0):
        if source_id.startswith(("AL:", "AP:")):
            return self.catalog_tracks(source_id, offset)
        page = self._web("v7/playlists/getTracks", {"request": {
            "pandoraId": source_id, "offset": offset, "limit": 50}})
        items = page.get("tracks", [])
        ids = [t["pandoraId"] for t in items]
        annotations = self._web("v4/catalog/annotateObjects", {"pandoraIds": ids,
                                "annotateAlbumTracks": False}) if ids else {}
        annotations = annotations.get("annotations", annotations)
        rows = []
        for index, item in enumerate(items, offset):
            detail = annotations.get(item["pandoraId"], {})
            rows.append({"index": index, "id": item["pandoraId"],
                         "title": clean(detail.get("name") or detail.get("songName") or item["pandoraId"]),
                         "artist": clean(detail.get("artistName")),
                         "duration": item.get("duration", 0)})
        return {"tracks": rows, "total": page.get("totalTracks", len(rows)), "offset": offset}

    def catalog_tracks(self, source_id, offset=0):
        identity = "AR:" + source_id.rsplit(":", 1)[1] if source_id.startswith("AP:") else source_id
        endpoint = "v4/catalog/getDetailsWithCollaborations" if source_id.startswith("AP:") else "v4/catalog/getDetails"
        data = self._web(endpoint, {"pandoraId": identity, "listener": None})
        annotations = data.get("annotations", data)
        detail = data.get("artistDetails", {}) if source_id.startswith("AP:") else annotations.get(identity, {})
        ids = detail.get("topTracks" if source_id.startswith("AP:") else "tracks", [])
        page = ids[offset:offset + 50]
        if page:
            more = self._web("v4/catalog/annotateObjects", {"pandoraIds": page, "annotateAlbumTracks": False})
            annotations.update(more.get("annotations", more))
        rows = []
        for index, track_id in enumerate(page, offset):
            track = annotations.get(track_id, {})
            rows.append({"index": index, "id": track_id, "title": clean(track.get("name")),
                         "artist": clean(track.get("artistName")), "duration": track.get("duration", 0)})
        return {"tracks": rows, "total": len(ids), "offset": offset}

    def search(self, query, offset=0):
        data = self._web("v3/sod/search", {"query": query, "types": ["TR", "AL", "AR", "PL", "SF"],
            "listener": None, "start": offset, "count": 50, "annotate": True,
            "searchTime": None, "annotationRecipe": "CLASS_OF_2019"})
        annotations = data.get("annotations", {})
        rows = []
        kinds = {"TR": "song", "AL": "album", "AR": "artist", "PL": "playlist", "SF": "station", "ST": "station"}
        for result in data.get("results", []):
            identity = result if isinstance(result, str) else result.get("pandoraId", "")
            detail = annotations.get(identity, result if isinstance(result, dict) else {})
            prefix = identity.split(":")[0]
            if prefix not in kinds:
                continue
            source_id = "AP:16722:" + identity.split(":", 1)[1] if prefix == "AR" else identity
            rows.append({"id": source_id, "kind": kinds[prefix], "name": clean(detail.get("name")),
                         "artist": clean(detail.get("artistName")),
                         "count": int(detail.get("totalTracks") or detail.get("trackCount") or 0)})
        return {"results": rows, "offset": offset, "has_more": len(data.get("results", [])) == 50}

    def previous(self, track, elapsed, replay=False):
        fields = {**self._fields(track, elapsed), "includeItem": True, "includeSource": True}
        if replay:
            fields["trackToken"] = track.token
        data = self._web("v1/action/replay" if replay else "v1/action/previous", fields)
        return self._track(data) if data.get("item") else self.current(track.source_id)

    def up_next(self, source_id):
        """Read the station's upcoming item without advancing playback."""
        data = self._web("v1/playback/peek", {"sourceId": source_id,
            "deviceUuid": self.device_id, "includeSource": True})
        item = data.get("item")
        if not isinstance(item, dict) or item.get("type") != "Track":
            return None
        track = Track.parse(item)
        return {"id": track.id, "title": track.title, "artist": track.artist,
                "duration": track.duration, "index": track.index}

    def source(self, source_id, index=0):
        fields = {"sourceId": source_id, "deviceUuid": self.device_id,
                  "includeItem": True, "includeSource": True}
        if source_id.startswith("PL:"):
            fields["index"] = index
            fields["shuffle"] = False
        elif source_id.startswith(("AL:", "AP:")):
            page = self.catalog_tracks(source_id, index)
            if page["tracks"]:
                fields["itemId"] = page["tracks"][0]["id"]
        else:
            fields["index"] = index
        return self._track(self._web("v1/playback/source", fields))

    def _track(self, data):
        item = data.get("item")
        if isinstance(item, dict) and item.get("type") == "SimStreamViolation":
            raise AppError("Pandora is playing on another device. Pause it there, then select your station or playlist again.")
        if not isinstance(item, dict) or not item.get("audioUrl"):
            raise AppError("Pandora did not return playable audio for this selection.")
        track = Track.parse(item)
        track.source_id = str((data.get("source") or {}).get("pandoraId") or track.source_id)
        track.shuffled = bool((data.get("source") or {}).get("shuffle", False))
        # Pandora sometimes supplies plain HTTP CDN links; use TLS for playback.
        if urllib.parse.urlsplit(track.audio_url).scheme == "http":
            track.audio_url = "https:" + track.audio_url[5:]
        if urllib.parse.urlsplit(track.audio_url).scheme != "https":
            raise AppError("Pandora returned an unsupported audio URL.")
        return track

    def event(self, event, track, elapsed):
        return self._web("v1/event/" + event, self._fields(track, elapsed))

    def _fields(self, track, elapsed):
        return {"deviceUuid": self.device_id, "sourceId": track.source_id,
                "index": track.index, "elapsedTime": max(0, elapsed)}

    def pause(self, track, elapsed):
        return self._web("v1/action/pause", {**self._fields(track, elapsed),
                         "pandoraId": track.id, "sync": False})

    def advance(self, track, elapsed, natural=False):
        fields = {**self._fields(track, elapsed), "includeItem": True, "includeSource": True}
        if natural:
            fields["reason"] = "NORMAL"
        else:
            fields["checkOnly"] = False
        data = self._web("v1/event/ended" if natural else "v1/action/skip", fields)
        # Ended may acknowledge with {} after advancing the server cursor.
        # Fetch that cursor; replaying the mutation would skip another song.
        if not data.get("item"):
            return self.current(track.source_id)
        return self._track(data)

    def current(self, source_id):
        return self._track(self._web("v1/playback/current", {
            "sourceId": source_id, "deviceUuid": self.device_id,
            "includeItem": True, "includeSource": True}))

    def thumb(self, track, elapsed, positive):
        return self._web("v1/action/thumbUp" if positive else "v1/action/thumbDown", {
            **self._fields(track, elapsed), "pandoraId": track.id, "trackToken": track.token})

    def shuffle(self, source_id, enabled):
        self._web("v1/action/shuffle", {"sourceId": source_id, "deviceUuid": self.device_id, "enabled": enabled})
