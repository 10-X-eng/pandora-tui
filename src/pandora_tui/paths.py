import os
from pathlib import Path


def state_dir():
    path = Path(os.environ.get("PANDORA_TUI_STATE_DIR", Path.home() / ".local/state/pandora-tui"))
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def runtime_dir():
    root = os.environ.get("XDG_RUNTIME_DIR", f"/tmp/pandora-tui-{os.getuid()}")
    path = Path(root) / "pandora-tui"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or path.stat().st_uid != os.getuid():
        raise RuntimeError("Unsafe Pandora runtime directory")
    path.chmod(0o700)
    return path


def socket_path():
    return runtime_dir() / "service.sock"
