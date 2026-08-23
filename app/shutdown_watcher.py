"""
Auto-shutdown once no browser tab is connected anymore.

Streamlit's server has no idea when you close its browser tab - a local
web server and a browser tab are decoupled by design, so the process
just keeps running (and the console window stays open) until something
kills it. This polls Streamlit's own session-tracking runtime, and once
zero sessions have been connected for a grace period, exits the whole
process - which also closes the console window that launched it, since
that window's only job was running this same process in the foreground.

Heuristic, not instant: a page refresh briefly drops to zero sessions
too, so there's a grace period before exiting. An abrupt network/laptop
sleep disconnect can also take longer than a clean tab close for the
websocket to actually report as gone.
"""
import os
import threading
import time

_watcher_started = False
GRACE_PERIOD_S = 15  # wait this long after the last disconnect before exiting


def start_once():
    """Idempotent: safe to call on every Streamlit rerun. Since this
    module is only ever imported (not re-executed) after the first time,
    _watcher_started reliably survives across main.py's reruns."""
    global _watcher_started
    if _watcher_started:
        return
    _watcher_started = True

    def _watch():
        try:
            from streamlit.runtime import Runtime
        except ImportError:
            return

        ever_connected = False
        disconnected_since = None

        while True:
            time.sleep(2)
            try:
                runtime = Runtime.instance()
                active = runtime._session_mgr.num_active_sessions()
            except Exception:
                # Runtime not up yet, or its internals changed - don't
                # exit on uncertainty, just keep watching.
                continue

            if active > 0:
                ever_connected = True
                disconnected_since = None
            elif ever_connected:
                if disconnected_since is None:
                    disconnected_since = time.time()
                elif time.time() - disconnected_since >= GRACE_PERIOD_S:
                    os._exit(0)

    threading.Thread(target=_watch, daemon=True).start()
