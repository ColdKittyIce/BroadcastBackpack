"""
network.py — Broadcast Backpack v6.0.0
NetworkMonitor  : polls TCP connection to stream host
DiscordWebhook  : fires go-live notifications
"""

import socket, threading, time, logging, requests
log = logging.getLogger("broadcast.net")


class NetworkMonitor:
    """Polls the stream host every 5 s to detect live status."""

    POLL_INTERVAL = 5.0

    def __init__(self, host: str, port: int):
        self.host      = host
        self.port      = port
        self._connected = False
        self._running   = False
        self._thread    = None
        self._callback  = None   # called with (bool) on state change

    def start(self, on_change=None):
        self._callback = on_change
        self._running  = True
        self._thread   = threading.Thread(
            target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    @property
    def connected(self) -> bool:
        return self._connected

    def _loop(self):
        prev = False
        while self._running:
            cur = self._check()
            if cur != prev:
                self._connected = cur
                prev = cur
                if self._callback:
                    try:
                        self._callback(cur)
                    except Exception:
                        pass
            time.sleep(self.POLL_INTERVAL)

    def _check(self) -> bool:
        try:
            with socket.create_connection(
                    (self.host, self.port), timeout=3.0):
                return True
        except Exception:
            return False


class DiscordWebhook:
    """Sends a simple POST notification to a Discord webhook URL."""

    def fire(self, url: str, message: str):
        if not url:
            return
        threading.Thread(
            target=self._send, args=(url, message), daemon=True).start()

    def _send(self, url: str, text: str):
        try:
            requests.post(url, json={"content": text}, timeout=8)
            log.info("Discord webhook fired")
        except Exception as e:
            log.warning(f"Discord webhook error: {e}")


# ═══════════════════════════════════════════════════════════════
# MICROSIP CALL HOOK LISTENER
# ═══════════════════════════════════════════════════════════════

class MicroSIPListener:
    """
    Tiny HTTP server on localhost:12345.
    MicroSIP fires call_hook.py which POSTs here.
    Events: call_start, call_end
    """

    PORT = 12345

    def __init__(self, app):
        self.app     = app
        self._server = None
        self._thread = None
        self._call_start_elapsed = None  # elapsed seconds when call started

    def start(self):
        import http.server, urllib.parse, threading
        app = self.app
        listener = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                try:
                    parsed = urllib.parse.urlparse(self.path)
                    params = dict(urllib.parse.parse_qsl(parsed.query))
                    event  = params.get("event", "")
                    caller = params.get("caller", "unknown")
                    if event:
                        app.after(0, lambda e=event, c=caller:
                                  listener._handle(e, c))
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"ok")
                except Exception:
                    pass

            def log_message(self, *a):
                pass  # suppress HTTP logs

        import logging as _log
        _logger = _log.getLogger("broadcast.microsip")
        try:
            self._server = http.server.HTTPServer(
                ("127.0.0.1", self.PORT), _Handler)
            self._thread = threading.Thread(
                target=self._server.serve_forever, daemon=True)
            self._thread.start()
            _logger.info(
                f"MicroSIP listener started on port {self.PORT}")
        except Exception as e:
            _logger.warning(
                f"MicroSIP listener failed to start: {e}")

    def stop(self):
        if self._server:
            try: self._server.shutdown()
            except Exception: pass

    def _handle(self, event: str, caller: str):
        """Called on the Tk main thread via after(0, ...)."""
        try:
            sl = self.app.right_panel.session_log
        except Exception:
            return

        elapsed_secs = self._get_elapsed()
        elapsed_str  = self._fmt(elapsed_secs) if elapsed_secs is not None else None

        if event == "call_start":
            self._call_start_elapsed = elapsed_secs
            note = f"📞 Call started"
            if caller and caller != "unknown":
                note += f" — {caller}"
            sl.log_event(note)

        elif event == "call_end":
            note = f"📞 Call ended"
            if caller and caller != "unknown":
                note += f" — {caller}"
            if self._call_start_elapsed is not None and elapsed_secs is not None:
                dur_secs = elapsed_secs - self._call_start_elapsed
                if dur_secs >= 0:
                    note += f" — duration {self._fmt(dur_secs)}"
            self._call_start_elapsed = None
            sl.log_event(note)

    def _get_elapsed(self):
        """Returns current show elapsed in seconds, or None if not live."""
        try:
            if not self.app._live:
                return None
            h = getattr(self.app, "_live_h", 0)
            m = getattr(self.app, "_live_m", 0)
            s = getattr(self.app, "_live_s", 0)
            return h * 3600 + m * 60 + s
        except Exception:
            return None

    @staticmethod
    def _fmt(secs: int) -> str:
        secs = int(secs)
        h, rem = divmod(secs, 3600)
        m, s   = divmod(rem, 60)
        if h:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"
