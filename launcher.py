"""Native macOS launcher for the Easel.

This is the entry point PyInstaller bundles into ``Easel.app``. It picks a workspace
folder once (and remembers it), starts the FastAPI app, and opens the browser to it —
no terminal, no Docker, no Python install required.

Structure (important): the server runs on a **background thread** and a tiny **Tk event
loop runs on the main thread**. That single design choice is what makes Easel behave
like a real Mac app:

* The Tk loop keeps the process "alive" to macOS, so the **Dock icon stays** for as long
  as Easel is running instead of dropping after launch.
* ``::tk::mac::ReopenApplication`` (fired when the user clicks the Dock/Finder icon while
  Easel is already running) **opens a fresh browser tab** instead of doing nothing.
* ``::tk::mac::Quit`` (Cmd+Q) **shuts the server down cleanly**.
* The first-run folder picker reuses the persistent root and the root is never destroyed
  out from under a blocked main thread, so it leaves **no orphaned empty window**.

The two filesystem roots are resolved as the app resolves them (see ``paths``): the
launcher sets ``EASEL_WORKSPACE`` and leaves ``EASEL_DATA_DIR`` unset, so the
databases default to the hidden Application Support directory.
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import tkinter as tk
from tkinter import filedialog, messagebox

from paths import data_dir


HOST = "127.0.0.1"
# 8000 in normal use; EASEL_PORT overrides it (handy for testing or to dodge a
# conflicting process on the default port).
PORT = int(os.environ.get("EASEL_PORT", "8000"))
URL = f"http://{HOST}:{PORT}"
HEALTH_URL = f"{URL}/healthz"
APP_MARKER = "easel"  # substring returned by the app's /healthz endpoint
WORKSPACE_FILE_NAME = "workspace.json"

_server = None  # the uvicorn.Server, set once the background thread starts it


# --- logging -----------------------------------------------------------------

def setup_logging() -> Path:
    """Route all logging to a rotating file in the data dir; return its path."""
    log_dir = data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "easel.log"

    handler = RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        root.addHandler(handler)
    return log_path


# --- browser + health --------------------------------------------------------

def open_url() -> None:
    """Open the app URL in the default browser via macOS ``open`` (reliable from any
    process state, including a Tk callback); fall back to webbrowser if needed."""
    try:
        subprocess.run(["open", URL], check=False)
    except Exception:  # pragma: no cover - extremely unlikely on macOS
        webbrowser.open(URL)


def server_responds(timeout: float = 2.0) -> bool:
    """True if a Easel instance answers /healthz (used for detect-and-focus and for
    the readiness poll before opening the browser)."""
    try:
        with urlopen(HEALTH_URL, timeout=timeout) as response:
            return APP_MARKER in response.read().decode("utf-8", "replace")
    except (HTTPError, URLError, OSError):
        return False


def port_held_by_other() -> bool:
    """True if the port answers but is NOT Easel (so we should not try to bind it)."""
    try:
        with urlopen(HEALTH_URL, timeout=2) as response:
            return APP_MARKER not in response.read().decode("utf-8", "replace")
    except HTTPError:
        return True
    except (URLError, OSError):
        return False


# --- workspace selection -----------------------------------------------------

def _workspace_file() -> Path:
    return data_dir() / WORKSPACE_FILE_NAME


def remembered_workspace() -> str | None:
    """Return a previously-chosen workspace path if it still exists, else None."""
    path = _workspace_file()
    if not path.exists():
        return None
    try:
        stored = json.loads(path.read_text(encoding="utf-8")).get("path")
    except (OSError, ValueError):
        return None
    if stored and Path(stored).is_dir():
        return stored
    return None


def choose_workspace(root: tk.Tk) -> str:
    """Explain-then-pick using the *persistent* root (returns "" if the user cancels).

    Crucially this does NOT create or destroy its own root: the modal dialogs are torn
    down by Tk's own event pumping, and the long-lived root is kept alive by the main
    loop — so nothing is ever orphaned into a ghost window.
    """
    messagebox.showinfo(
        "Welcome to Easel",
        "Easel keeps your notes and memory in a folder you choose.\n\n"
        "If you already have a Easel or Obsidian vault, select it on the next "
        "screen. Otherwise, pick or create a folder to use.",
        parent=root,
    )
    chosen = filedialog.askdirectory(
        title="Choose your Easel workspace folder", parent=root
    )
    if not chosen:
        return ""
    _workspace_file().write_text(json.dumps({"path": chosen}), encoding="utf-8")
    return chosen


# --- the server (runs on a background thread) --------------------------------

def run_server() -> None:
    """Run uvicorn in this (non-main) thread, with signal handlers disabled."""
    global _server
    import uvicorn
    from app import app

    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="info", log_config=None)
    _server = uvicorn.Server(config)
    # signal.signal only works on the main thread; we're not on it.
    _server.install_signal_handlers = lambda: None
    _server.run()


def open_browser_when_ready() -> None:
    """Poll until the server answers, then open the browser (on a daemon thread)."""

    def _wait_and_open() -> None:
        for _ in range(80):  # ~20s ceiling
            if server_responds(timeout=1.0):
                break
            time.sleep(0.25)
        open_url()

    threading.Thread(target=_wait_and_open, daemon=True).start()


# --- error dialog ------------------------------------------------------------

def show_error(log_path: Path, root: "tk.Tk | None" = None) -> None:
    """Show a native 'couldn't start' dialog pointing at the log (best effort)."""
    try:
        owns = root is None
        if owns:
            root = tk.Tk(); root.withdraw()
        messagebox.showerror(
            "Easel couldn't start",
            "Easel ran into a problem and couldn't start.\n\n"
            f"Details were saved to:\n{log_path}",
            parent=root,
        )
        if owns:
            root.destroy()
    except Exception:  # pragma: no cover - GUI may be unavailable; the log still has it
        pass


# --- entry point -------------------------------------------------------------

def main() -> None:
    log_path = setup_logging()
    log = logging.getLogger("launcher")
    root: "tk.Tk | None" = None

    try:
        # Detect-and-focus: a leftover/other instance is already serving the port.
        if server_responds():
            log.info("Easel already serving; opening the browser.")
            open_url()
            return
        if port_held_by_other():
            raise RuntimeError(f"Port {PORT} is in use by another application.")

        # One persistent, withdrawn Tk root for the whole session: it powers the
        # first-run picker, keeps the Dock icon alive, and receives macOS app events.
        root = tk.Tk()
        root.withdraw()

        workspace = remembered_workspace()
        if workspace is None:
            workspace = choose_workspace(root)
            if not workspace:
                log.info("No workspace chosen; exiting.")
                root.destroy()
                return
        os.environ["EASEL_WORKSPACE"] = workspace
        # EASEL_DATA_DIR left unset -> databases live in the hidden data dir.

        threading.Thread(target=run_server, daemon=True).start()
        open_browser_when_ready()

        def on_reopen() -> None:
            log.info("Reopen event; opening a browser tab.")
            open_url()

        def on_quit() -> None:
            log.info("Quit event; shutting the server down.")
            if _server is not None:
                _server.should_exit = True
            # Give uvicorn a moment to run its graceful shutdown, then end the loop.
            root.after(400, root.destroy)

        root.createcommand("::tk::mac::ReopenApplication", on_reopen)
        root.createcommand("::tk::mac::Quit", on_quit)

        log.info("Easel running on %s (Dock app; reopen + quit handled).", URL)
        root.mainloop()
    except SystemExit:
        raise
    except Exception as error:  # noqa: BLE001 - top-level guard for a console-less app
        log.exception("Fatal startup error: %s", error)
        show_error(log_path, root)
        sys.exit(1)


if __name__ == "__main__":
    main()
