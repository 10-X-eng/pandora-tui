"""Small local playback preferences; credentials stay in the desktop keyring."""
import json
import math
import os
import tempfile
from .paths import state_dir


class Preferences:
    def __init__(self, path=None):
        self.path = path if path is not None else state_dir() / "preferences.json"

    def volume(self):
        try:
            value = float(json.loads(self.path.read_text())["volume"])
            return max(0.0, min(1.0, value)) if math.isfinite(value) else .5
        except (OSError, ValueError, TypeError, KeyError):
            return .5

    def save_volume(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(prefix=".preferences-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump({"volume": value}, stream)
                stream.write("\n")
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
