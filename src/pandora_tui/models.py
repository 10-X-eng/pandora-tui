from dataclasses import dataclass, field, asdict
import hashlib


def clean(value) -> str:
    return "".join(c for c in str(value or "") if c.isprintable())[:500]


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    kind: str
    count: int = 0

    def public(self):
        return asdict(self)


@dataclass
class Track:
    id: str
    source_id: str
    index: int
    title: str
    artist: str
    album: str
    duration: float
    art_url: str
    audio_url: str = field(repr=False)
    token: str = field(repr=False)
    interactions: list[str] = field(default_factory=list)
    progress: float = 0
    item_type: str = "Track"
    shuffled: bool = False

    @classmethod
    def parse(cls, item):
        return cls(
            str(item.get("pandoraId", "")), str(item.get("sourceId", "")),
            int(item.get("index", 0)), clean(item.get("songName") or item.get("name") or item.get("type")),
            clean(item.get("artistName")), clean(item.get("albumName")),
            float(item.get("duration") or 0), str(item.get("artUrl") or ""),
            str(item.get("audioUrl") or ""), str(item.get("trackToken") or ""),
            list(item.get("interactions") or []), float(item.get("currentProgress") or 0),
            str(item.get("type") or "Track"),
        )

    @property
    def path(self):
        digest = hashlib.sha256(f"{self.source_id}/{self.id}/{self.index}".encode()).hexdigest()[:24]
        return "/io/github/pandora_tui/track/" + digest

    def public(self):
        return {k: v for k, v in asdict(self).items() if k not in ("audio_url", "token")}
