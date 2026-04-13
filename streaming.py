"""
streaming.py — Broadcast Backpack v6.0.0
Icecast/Shoutcast streaming engine.

Captures audio from a sounddevice input (Voicemeeter virtual output),
encodes to MP3 via lameenc, and pushes to Icecast via HTTP.
Supports both PUT (Icecast 2.4+) and SOURCE (legacy) methods.
Includes auto-reconnect on unexpected dropout.

Optional deps: pip install sounddevice lameenc
"""

import threading, logging, socket, base64, time
from enum import Enum

log = logging.getLogger("broadcast.stream")

try:
    import sounddevice as sd
    HAS_SD = True
except ImportError:
    HAS_SD = False

try:
    import lameenc
    HAS_LAME = True
except ImportError:
    HAS_LAME = False


class StreamState(Enum):
    IDLE        = "idle"
    CONNECTING  = "connecting"
    LIVE        = "live"
    RECONNECTING = "reconnecting"
    ERROR       = "error"
    STOPPING    = "stopping"


class StreamEngine:
    CHUNK_FRAMES     = 2048
    RECONNECT_DELAY  = 5      # seconds between reconnect attempts

    def __init__(self, cfg: dict):
        self._cfg          = cfg
        self._state        = StreamState.IDLE
        self._thread       = None
        self._stop_evt     = threading.Event()
        self._cb           = None
        self._sock         = None
        self._encoder      = None
        self._bytes_sent   = 0
        self._connect_time = None
        self._use_chunked  = True
        self._reconnect_count = 0
        self._user_stopped = False   # True when user explicitly stopped

    # ── Public API ────────────────────────────────────────────────

    def set_status_callback(self, fn):
        self._cb = fn

    def start(self):
        if self._state in (StreamState.LIVE, StreamState.CONNECTING,
                           StreamState.RECONNECTING):
            return
        if not HAS_SD:
            self._set_state(StreamState.ERROR,
                "sounddevice not installed — run: pip install sounddevice lameenc")
            return
        if not HAS_LAME:
            self._set_state(StreamState.ERROR,
                "lameenc not installed — run: pip install sounddevice lameenc")
            return
        self._stop_evt.clear()
        self._user_stopped    = False
        self._bytes_sent      = 0
        self._connect_time    = None
        self._reconnect_count = 0
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="broadcast-stream")
        self._thread.start()

    def stop(self):
        if self._state == StreamState.IDLE:
            return
        self._user_stopped = True
        self._set_state(StreamState.STOPPING, "Stopping stream…")
        self._stop_evt.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=6)
        self._close_socket()
        self._set_state(StreamState.IDLE, "Stream stopped")

    def update_config(self, cfg: dict):
        """Update credentials without restarting."""
        self._cfg = cfg

    @property
    def state(self):
        return self._state

    @property
    def bytes_sent(self):
        return self._bytes_sent

    @property
    def uptime_seconds(self):
        if self._connect_time and self._state == StreamState.LIVE:
            return time.monotonic() - self._connect_time
        return 0.0

    @property
    def reconnect_count(self):
        return self._reconnect_count

    @staticmethod
    def list_input_devices():
        if not HAS_SD:
            return []
        try:
            return [(i, d["name"])
                    for i, d in enumerate(sd.query_devices())
                    if d["max_input_channels"] > 0]
        except Exception:
            return []

    @staticmethod
    def dependencies_ok():
        return HAS_SD and HAS_LAME

    # ── Internal ─────────────────────────────────────────────────

    def _set_state(self, state: StreamState, msg: str = ""):
        self._state = state
        log.info(f"Stream → {state.value}  {msg}")
        if self._cb:
            try:
                self._cb(state, msg)
            except Exception:
                pass

    def _run(self):
        cfg = self._cfg
        max_attempts = int(cfg.get("stream_reconnect_attempts", 5))
        auto_reconnect = cfg.get("stream_auto_reconnect", True)

        while not self._stop_evt.is_set():
            success = self._stream_session()
            if self._stop_evt.is_set() or self._user_stopped:
                break
            if not auto_reconnect:
                break
            self._reconnect_count += 1
            if max_attempts > 0 and self._reconnect_count > max_attempts:
                self._set_state(StreamState.ERROR,
                    f"Stream failed after {max_attempts} reconnect attempts")
                break
            self._set_state(StreamState.RECONNECTING,
                f"Reconnecting in {self.RECONNECT_DELAY}s "
                f"(attempt {self._reconnect_count}/{max_attempts})…")
            self._stop_evt.wait(self.RECONNECT_DELAY)

        if not self._user_stopped:
            self._close_socket()
            if self._state not in (StreamState.ERROR, StreamState.STOPPING):
                self._set_state(StreamState.IDLE, "Stream ended")

    def _stream_session(self) -> bool:
        """Attempt one streaming session. Returns True if ended cleanly."""
        cfg        = self._cfg
        host       = cfg.get("stream_host",       "")
        port       = int(cfg.get("stream_port",   80))
        mount      = cfg.get("stream_mount",      "/live")
        user       = cfg.get("stream_user",       "source")
        password   = cfg.get("stream_password",   "")
        bitrate    = int(cfg.get("stream_bitrate",    128))
        samplerate = int(cfg.get("stream_samplerate", 44100))
        device     = cfg.get("stream_audio_device", None)
        show_name  = cfg.get("show_name", "Live Broadcast")
        if device in ("default", ""):
            device = None

        self._set_state(StreamState.CONNECTING,
                        f"Connecting to {host}:{port}{mount}…")

        # ── Build encoder ─────────────────────────────────────────
        try:
            enc = lameenc.Encoder()
            enc.set_bit_rate(bitrate)
            enc.set_in_sample_rate(samplerate)
            enc.set_channels(2)
            enc.set_quality(2)
            self._encoder = enc
        except Exception as e:
            self._set_state(StreamState.ERROR, f"Encoder init failed: {e}")
            return False

        # ── Connect + handshake ───────────────────────────────────
        sock = None
        connected = False
        method_used = "PUT"
        last_response = ""

        for method in ("SOURCE", "PUT"):
            try:
                sock = socket.create_connection((host, port), timeout=15)
                sock.settimeout(15)
            except Exception as e:
                self._set_state(StreamState.ERROR,
                                f"Cannot connect to {host}:{port} — {e}")
                return False

            try:
                creds = base64.b64encode(
                    f"{user}:{password}".encode()).decode()
                if method == "PUT":
                    req = (
                        f"PUT {mount} HTTP/1.1\r\n"
                        f"Host: {host}:{port}\r\n"
                        f"Authorization: Basic {creds}\r\n"
                        f"Content-Type: audio/mpeg\r\n"
                        f"Ice-Public: 0\r\n"
                        f"Ice-Name: {show_name}\r\n"
                        f"Ice-Genre: Talk/Entertainment\r\n"
                        f"Ice-Audio-Info: bitrate={bitrate};"
                        f"samplerate={samplerate};channels=2\r\n"
                        f"Transfer-Encoding: chunked\r\n\r\n"
                    )
                else:
                    req = (
                        f"SOURCE {mount} HTTP/1.0\r\n"
                        f"Authorization: Basic {creds}\r\n"
                        f"Content-Type: audio/mpeg\r\n"
                        f"ice-public: 0\r\n"
                        f"ice-name: {show_name}\r\n"
                        f"ice-genre: Talk/Entertainment\r\n"
                        f"ice-bitrate: {bitrate}\r\n\r\n"
                    )
                sock.sendall(req.encode())

                response = b""
                while b"\r\n\r\n" not in response:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    response += chunk
                    if len(response) > 8192:
                        break

                last_response = response.decode(errors="replace")
                log.info(f"[{method}] response: {last_response[:120]}")

                if "200" in last_response or "OK" in last_response:
                    connected    = True
                    method_used  = method
                    break
                else:
                    try:
                        sock.close()
                    except Exception:
                        pass
                    sock = None

            except Exception as e:
                try:
                    sock.close()
                except Exception:
                    pass
                sock = None
                if method == "PUT":
                    self._set_state(StreamState.ERROR,
                                    f"Handshake failed: {e}")
                    return False

        if not connected:
            first_line = (last_response.split("\r\n")[0]
                          if last_response else "No response")
            self._set_state(StreamState.ERROR,
                            f"Server rejected: {first_line}")
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass
            return False

        self._sock         = sock
        self._connect_time = time.monotonic()
        self._use_chunked  = (method_used == "PUT")
        self._set_state(StreamState.LIVE,
                        f"● LIVE → {host}:{port}{mount} "
                        f"@ {bitrate}kbps [{method_used}]")

        # ── Audio capture loop ────────────────────────────────────
        clean_exit = False
        try:
            import numpy as np
            with sd.InputStream(device=device,
                                channels=2,
                                samplerate=samplerate,
                                dtype="float32",
                                blocksize=self.CHUNK_FRAMES) as stream:
                while not self._stop_evt.is_set():
                    audio_data, overflowed = stream.read(self.CHUNK_FRAMES)
                    if overflowed:
                        log.warning("Audio buffer overflow")
                    pcm      = (audio_data * 32767).astype("int16")
                    mp3_data = self._encoder.encode(pcm.tobytes())
                    if mp3_data:
                        self._send_audio(sock, mp3_data)

                final = self._encoder.flush()
                if final:
                    self._send_audio(sock, final)
                if self._use_chunked:
                    try:
                        sock.sendall(b"0\r\n\r\n")
                    except Exception:
                        pass
                clean_exit = True

        except Exception as e:
            if not self._stop_evt.is_set():
                log.warning(f"Stream audio error: {e}")

        self._close_socket()
        return clean_exit

    def _send_audio(self, sock, data: bytes):
        if self._use_chunked:
            chunk = f"{len(data):X}\r\n".encode() + data + b"\r\n"
            sock.sendall(chunk)
        else:
            sock.sendall(data)
        self._bytes_sent += len(data)

    def _close_socket(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
