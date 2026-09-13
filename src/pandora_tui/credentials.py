"""Only the desktop Secret Service may persist a password. No plaintext fallback."""
import json
import secretstorage
from .errors import AppError

ATTRIBUTES = {"application": "pandora-tui", "purpose": "pandora-login"}


class CredentialStore:
    def _collection(self):
        bus = secretstorage.dbus_init()
        collection = secretstorage.get_default_collection(bus)
        if collection.is_locked():
            collection.unlock()
        if collection.is_locked():
            bus.close()
            raise AppError("Unlock the desktop keyring to remember your Pandora login.")
        return bus, collection

    def load(self):
        bus = None
        try:
            bus, collection = self._collection()
            for item in collection.search_items(ATTRIBUTES):
                if item.is_locked():
                    item.unlock()
                data = json.loads(item.get_secret())
                if isinstance(data.get("email"), str) and isinstance(data.get("password"), str):
                    return data["email"], data["password"]
            return None
        except Exception:
            raise AppError("Saved login is unavailable. Sign in, or unlock your desktop keyring.") from None
        finally:
            if bus:
                bus.close()

    def save(self, email, password):
        bus = None
        try:
            bus, collection = self._collection()
            collection.create_item("Pandora TUI", ATTRIBUTES,
                                   json.dumps({"email": email, "password": password}).encode(), replace=True)
        except Exception:
            raise AppError("Signed in for this session, but the desktop keyring could not save your login.") from None
        finally:
            if bus:
                bus.close()

    def forget(self):
        bus = None
        try:
            bus, collection = self._collection()
            for item in collection.search_items(ATTRIBUTES):
                item.delete()
        except Exception:
            raise AppError("Could not remove the saved login from the desktop keyring.") from None
        finally:
            if bus:
                bus.close()
