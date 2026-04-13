"""
audio.py — Broadcast Backpack v6.0.0
AudioManager  : pygame-based playback, FX, VU metering
RecorderManager: sounddevice loopback capture, WAV/MP3 export
"""

import os, threading, time, wave, logging, gc
import numpy as np
import pygame
from pathlib import Path
from datetime import datetime

log = logging.getLogger("broadcast.audio")

# ── Optional deps ─────────────────────────────────────────────────
try:
    from pedalboard import (Pedalboard, Reverb, Delay,
                             LowpassFilter, HighpassFilter,
                             PitchShift, Gain)
    from pedalboard.io import AudioFile
    HAS_PEDALBOARD = True
except ImportError:
    HAS_PEDALBOARD = False

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except ImportError:
    HAS_SOUNDDEVICE = False

try:
    from pydub import AudioSegment
    HAS_PYDUB = True
except ImportError:
    HAS_PYDUB = False

try:
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    from comtypes import CLSCTX_ALL
    HAS_PYCAW = True
except ImportError:
    HAS_PYCAW = False

# Reserved channels
CH_QUEUE    = 510   # music queue
CH_RECORDER = 509   # tape recorder playback
CH_FX_PREV  = 508   # FX preview


# ═══════════════════════════════════════════════════════════════
# AUDIO MANAGER
# ═══════════════════════════════════════════════════════════════

class AudioManager:
    """
    Wraps pygame.mixer for all soundboard / queue playback.
    Channels 0-247: soundboard slots
    Channel 508:    FX preview
    Channel 509:    tape recorder playback
    Channel 510:    music queue
    Channels 511:   spare
    """

    def __init__(self):
        self.initialized      = False
        self.sounds:    dict  = {}      # idx → pygame.Sound
        self.raw_sounds:dict  = {}      # idx → file path
        self.master_vol       = 1.0
        self.board_vol        = 1.0     # Soundboard volume
        self.queue_vol        = 1.0     # Queue volume
        self.board_gain_db    = 0       # Soundboard gain boost (0-12 dB)
        self._fade_vol        = 1.0
        self._dur_cache:dict  = {}   # path → float seconds
        self._muted           = False
        self._vu_level        = 0.0
        self._vu_rec_level    = 0.0
        self._vu_lock         = threading.Lock()
        self._now_playing:dict = {}
        self._play_order:list  = []
        self._last_gc         = time.monotonic()
        self._gc_interval     = 60.0  # gc every 60 seconds
        self._try_init()

    def _maybe_gc(self):
        """Run garbage collection if enough time has passed."""
        now = time.monotonic()
        if now - self._last_gc > self._gc_interval:
            gc.collect()
            self._last_gc = now
            log.debug("GC cycle completed")

    def _try_init(self, device_name: str = ""):
        try:
            pygame.mixer.quit()
        except Exception:
            pass
        try:
            if device_name and device_name != "Default (System)":
                os.environ["SDL_AUDIO_DEVICE_NAME"] = device_name
            else:
                os.environ.pop("SDL_AUDIO_DEVICE_NAME", None)
            pygame.mixer.pre_init(44100, -16, 2, 1024)
            pygame.mixer.init()
            pygame.mixer.set_num_channels(512)
            self.initialized = True
            self.sounds.clear()
            self.raw_sounds.clear()
            log.info(f"Mixer initialised → '{device_name or 'Default'}'")
        except Exception as e:
            log.error(f"Mixer init error: {e}")
            self.initialized = False

    def reinit(self, device_name: str = ""):
        self._try_init(device_name)

    # ── Device enumeration ────────────────────────────────────────

    @staticmethod
    def _pycaw_list(want_input: bool) -> list[tuple[int, str]]:
        """
        Use pycaw GetAllDevices() with EDataFlow filter to get proper
        Windows FriendlyName for each device — exactly the names shown
        in Windows Sound settings, Voicemeeter, and Mixxx.
        """
        if not HAS_PYCAW:
            return []
        try:
            from pycaw.pycaw import AudioUtilities
            from pycaw.constants import EDataFlow, DEVICE_STATE
            flow = (EDataFlow.eCapture.value
                    if want_input else EDataFlow.eRender.value)
            devs = AudioUtilities.GetAllDevices(
                data_flow=flow,
                device_state=DEVICE_STATE.ACTIVE.value)
            vm, others = [], []
            for d in devs:
                name = d.FriendlyName
                if not name:
                    continue
                (vm if "voicemeeter" in name.lower()
                 else others).append((-1, name))
            return vm + others
        except Exception as e:
            log.warning(f"pycaw device list: {e}")
            return []

    @staticmethod
    def _sd_devices(want_input: bool) -> list[tuple[int, str]]:
        """
        Fallback when pycaw unavailable.
        sounddevice with host-API deduplication.
        """
        if not HAS_SOUNDDEVICE:
            return []
        seen, result = set(), []
        try:
            for i, d in enumerate(sd.query_devices()):
                out_ch = d["max_output_channels"]
                in_ch  = d["max_input_channels"]
                if want_input:
                    if in_ch <= 0 or in_ch < out_ch:
                        continue
                else:
                    if out_ch <= 0 or out_ch < in_ch:
                        continue
                base = d["name"].split(" (")[0].strip()
                key  = base.lower()
                if key in seen:
                    continue
                seen.add(key)
                result.append((i, base))
        except Exception:
            pass
        return result

    def get_output_devices(self) -> list[tuple[int, str]]:
        """Output devices — proper Windows names via pycaw."""
        devices = [(-1, "Default (System)")]
        devs    = self._pycaw_list(want_input=False)
        if not devs:
            devs = self._sd_devices(want_input=False)
        devices += devs
        return devices

    def get_input_devices(self) -> list[tuple[int, str]]:
        """Input devices — proper Windows names via pycaw."""
        devices = [(-1, "Default (System)")]
        devs    = self._pycaw_list(want_input=True)
        if not devs:
            devs = self._sd_devices(want_input=True)
        devices += devs
        return devices

    # ── FX processing ─────────────────────────────────────────────

    def _apply_fx(self, path: str, fx: dict):
        if not HAS_PEDALBOARD:
            return pygame.mixer.Sound(path)
        try:
            effects = []
            if fx.get("volume",   {}).get("enabled"):
                effects.append(Gain(gain_db=20*(fx["volume"]["value"]-1.0)))
            if fx.get("pitch",    {}).get("enabled"):
                effects.append(PitchShift(semitones=fx["pitch"]["value"]))
            if fx.get("reverb",   {}).get("enabled"):
                rm = fx["reverb"]["value"]
                effects.append(Reverb(room_size=rm, wet_level=rm*0.6))
            if fx.get("echo",     {}).get("enabled"):
                mx = fx["echo"]["value"]
                effects.append(Delay(delay_seconds=0.35,
                                     feedback=mx*0.4, mix=mx))
            if fx.get("lowpass",  {}).get("enabled"):
                effects.append(LowpassFilter(
                    cutoff_frequency_hz=fx["lowpass"]["value"]))
            if fx.get("highpass", {}).get("enabled"):
                effects.append(HighpassFilter(
                    cutoff_frequency_hz=fx["highpass"]["value"]))
            if not effects:
                return pygame.mixer.Sound(path)

            board = Pedalboard(effects)
            with AudioFile(path) as f:
                audio, sr = f.read(f.frames), f.samplerate

            # Ensure stereo — pedalboard effects expect consistent channel depth
            if audio.ndim == 1:
                audio = np.stack([audio, audio])
            elif audio.shape[0] == 1:
                audio = np.vstack([audio, audio])

            if fx.get("speed", {}).get("enabled"):
                    spd = max(0.25, min(4.0, fx["speed"]["value"]))
                    if spd != 1.0:
                        new_len   = int(audio.shape[1] / spd)
                        resampled = np.zeros((audio.shape[0], new_len),
                                             dtype=audio.dtype)
                        for ch in range(audio.shape[0]):
                            resampled[ch] = np.interp(
                                np.linspace(0, audio.shape[1]-1, new_len),
                                np.arange(audio.shape[1]), audio[ch])
                        audio = resampled
            processed = np.clip(board(audio, sr), -1.0, 1.0)

            arr = (processed.T * 32767).astype(np.int16)
            if arr.ndim == 1:
                arr = np.column_stack([arr, arr])
            return pygame.sndarray.make_sound(np.ascontiguousarray(arr))
        except Exception as e:
            log.warning(f"FX error: {e}")
            try:
                return pygame.mixer.Sound(path)
            except Exception:
                return None

    # ── Playback ──────────────────────────────────────────────────

    def prepare(self, idx: int, path: str, fx: dict) -> bool:
        """Prepare a sound — FX processing done on a bg thread if needed."""
        if not self.initialized or not path or not os.path.exists(path):
            return False
        # Bounds check — never exceed channel count
        try:
            nc = pygame.mixer.get_num_channels()
            if idx >= nc:
                log.warning(f"Prepare: idx {idx} >= {nc} channels")
                return False
        except Exception:
            pass
        
        # Free old sound object to prevent memory buildup
        if idx in self.sounds:
            try:
                pygame.mixer.Channel(idx).stop()
            except Exception:
                pass
            try:
                del self.sounds[idx]
            except Exception:
                pass
        
        # Check if any FX are actually enabled
        has_fx = (
            HAS_PEDALBOARD and
            any(v.get("enabled") for v in fx.values()
                if isinstance(v, dict))
        ) if fx else False

        if not has_fx:
            # No FX — fast path, safe on main thread
            try:
                snd = pygame.mixer.Sound(path)
                snd.set_volume(self._effective_vol())
                self.sounds[idx]     = snd
                self.raw_sounds[idx] = path
                self._maybe_gc()
                return True
            except Exception as e:
                log.warning(f"Prepare [{idx}]: {e}")
                return False
        else:
            # FX enabled — process synchronously so play() gets the FX sound
            try:
                snd = self._apply_fx(path, fx)
                if snd:
                    snd.set_volume(self._effective_vol())
                    self.sounds[idx]     = snd
                    self.raw_sounds[idx] = path
                    self._maybe_gc()
                    return True
                else:
                    # FX failed — fall back to raw
                    raw_snd = pygame.mixer.Sound(path)
                    raw_snd.set_volume(self._effective_vol())
                    self.sounds[idx]     = raw_snd
                    self.raw_sounds[idx] = path
                    self._maybe_gc()
                    return True
            except Exception as e:
                log.warning(f"FX prepare [{idx}]: {e}")
                try:
                    raw_snd = pygame.mixer.Sound(path)
                    raw_snd.set_volume(self._effective_vol())
                    self.sounds[idx]     = raw_snd
                    self.raw_sounds[idx] = path
                    self._maybe_gc()
                    return True
                except Exception:
                    return False

    def play(self, idx: int, loop=False, overlap=False, volume=1.0):
        if not self.initialized or idx not in self.sounds:
            return
        try:
            nc = pygame.mixer.get_num_channels()
            if idx >= nc:
                return
            ch = pygame.mixer.Channel(idx)
            if not overlap:
                ch.stop()
            ch.play(self.sounds[idx], loops=-1 if loop else 0)
            # Apply per-button volume combined with appropriate channel volume
            if idx == CH_QUEUE:
                effective_vol = min(1.0, max(0.0, volume)) * self._effective_queue_vol()
            else:
                effective_vol = min(1.0, max(0.0, volume)) * self._effective_board_vol()
            ch.set_volume(effective_vol)
        except Exception as e:
            log.warning(f"Play [{idx}]: {e}")

    def stop(self, idx: int):
        if self.initialized:
            try:
                nc = pygame.mixer.get_num_channels()
                if idx < nc:
                    pygame.mixer.Channel(idx).stop()
            except Exception as e:
                log.warning(f"Stop [{idx}]: {e}")

    def fade_stop(self, idx: int, ms: int = 3000):
        if self.initialized:
            pygame.mixer.Channel(idx).fadeout(ms)

    def stop_all(self):
        if self.initialized:
            pygame.mixer.stop()

    def cleanup(self):
        """Free all resources — call on app close."""
        self.stop_all()
        # Free all stored Sound objects
        for idx in list(self.sounds.keys()):
            try:
                del self.sounds[idx]
            except Exception:
                pass
        self.sounds.clear()
        self.raw_sounds.clear()
        self._dur_cache.clear()
        self._now_playing.clear()
        self._play_order.clear()
        gc.collect()
        log.info("AudioManager cleanup complete")

    def is_playing(self, idx: int) -> bool:
        if not self.initialized:
            return False
        try:
            nc = pygame.mixer.get_num_channels()
            if idx >= nc:
                return False
            return bool(pygame.mixer.Channel(idx).get_busy())
        except Exception:
            return False

    def any_playing_in_range(self, start: int, count: int) -> bool:
        if not self.initialized:
            return False
        nc = pygame.mixer.get_num_channels()
        return any(pygame.mixer.Channel(start+i).get_busy()
                   for i in range(count) if start+i < nc)

    # ── Now-playing tracker ───────────────────────────────────────

    def notify_play(self, ch: int, label: str, bank: str,
                    path: str, duration: float):
        self._now_playing[ch] = {
            "label":    label, "bank": bank, "path": path,
            "start":    time.monotonic(), "duration": duration,
        }
        if ch in self._play_order:
            self._play_order.remove(ch)
        self._play_order.append(ch)
        if len(self._play_order) > 64:
            self._play_order = self._play_order[-32:]

    def get_now_playing(self):
        for ch in reversed(self._play_order):
            if self.is_playing(ch) and ch in self._now_playing:
                return (ch, self._now_playing[ch])
        return None

    def get_sound_duration(self, path: str) -> float:
        if path in self._dur_cache:
            return self._dur_cache[path]
        try:
            dur = pygame.mixer.Sound(path).get_length()
        except Exception:
            dur = 0.0
        self._dur_cache[path] = dur
        return dur

    def get_duration_str(self, path: str) -> str:
        s = self.get_sound_duration(path)
        return f"{int(s//60)}:{int(s%60):02d}" if s else "--:--"

    # ── Volume / mute / fade ──────────────────────────────────────

    def _effective_vol(self) -> float:
        if self._muted:
            return 0.0
        return max(0.0, min(1.0, self.master_vol * self._fade_vol))

    def _effective_board_vol(self) -> float:
        """Effective volume for soundboard sounds, including gain boost."""
        if self._muted:
            return 0.0
        # Convert dB gain to linear multiplier: 10^(dB/20)
        gain_mult = 10 ** (self.board_gain_db / 20.0) if self.board_gain_db > 0 else 1.0
        raw_vol = self.master_vol * self._fade_vol * self.board_vol * gain_mult
        return max(0.0, min(1.0, raw_vol))

    def _effective_queue_vol(self) -> float:
        """Effective volume for queue/music sounds."""
        if self._muted:
            return 0.0
        return max(0.0, min(1.0, self.master_vol * self._fade_vol * self.queue_vol))

    def set_master_volume(self, v: float):
        self.master_vol = max(0.0, min(1.0, float(v)))
        self._update_all_volumes()

    def set_board_volume(self, v: float):
        """Set soundboard volume (0.0 - 1.0)."""
        self.board_vol = max(0.0, min(1.0, float(v)))
        self._update_all_volumes()

    def set_board_gain_db(self, db: int):
        """Set soundboard gain boost (0-12 dB)."""
        self.board_gain_db = max(0, min(12, int(db)))
        self._update_all_volumes()

    def set_queue_volume(self, v: float):
        """Set queue/music volume (0.0 - 1.0)."""
        self.queue_vol = max(0.0, min(1.0, float(v)))
        # Update queue channel specifically
        try:
            if self.initialized:
                pygame.mixer.Channel(CH_QUEUE).set_volume(self._effective_queue_vol())
        except Exception:
            pass

    def _update_all_volumes(self):
        """Update volumes on all channels."""
        board_ev = self._effective_board_vol()
        queue_ev = self._effective_queue_vol()
        # Soundboard channels (0-507)
        for idx, s in self.sounds.items():
            if idx < CH_FX_PREV:  # Not queue/recorder/fx channels
                try: s.set_volume(board_ev)
                except Exception: pass
        # Queue channel
        try:
            if self.initialized:
                pygame.mixer.Channel(CH_QUEUE).set_volume(queue_ev)
        except Exception:
            pass

    def set_performance_fade(self, v: float):
        self._fade_vol = max(0.0, min(1.0, float(v)))
        self._update_all_volumes()

    def set_muted(self, muted: bool):
        self._muted = muted
        self._update_all_volumes()

    def toggle_mute(self) -> bool:
        self.set_muted(not self._muted)
        return self._muted

    @property
    def muted(self) -> bool:
        return self._muted

    def get_performance_fade(self) -> float:
        return self._fade_vol

    # ── VU levels ─────────────────────────────────────────────────

    def get_vu_level(self) -> float:
        """Snappy VU for soundboard/queue channels."""
        ev     = self._effective_vol()
        active = sum(1 for i in range(248)
                     if self.initialized
                     and pygame.mixer.Channel(i).get_busy())
        try:
            if self.initialized and pygame.mixer.Channel(CH_QUEUE).get_busy():
                active += 1
        except Exception:
            pass
        with self._vu_lock:
            if active == 0 or ev < 0.01:
                self._vu_level = max(0.0, self._vu_level - 0.30)  # faster decay
            else:
                raw    = min(1.0, 0.25 + active * 0.14)
                target = raw * ev
                self._vu_level = self._vu_level * 0.05 + target * 0.95  # fast attack
        return self._vu_level

    def get_recorder_vu_level(self) -> float:
        """VU for tape recorder playback channel."""
        if not hasattr(self, "_vu_rec"):
            self._vu_rec = 0.0
        try:
            busy = self.initialized and pygame.mixer.Channel(CH_RECORDER).get_busy()
        except Exception:
            busy = False
        if busy:
            self._vu_rec = min(0.72, self._vu_rec * 0.12 + 0.72 * 0.88)
        else:
            self._vu_rec = max(0.0, self._vu_rec - 0.20)
        return self._vu_rec


# ═══════════════════════════════════════════════════════════════
# RECORDER MANAGER
# ═══════════════════════════════════════════════════════════════

class RecorderManager:
    """
    Captures system loopback via sounddevice, stores in memory,
    auto-saves on stop. Playback via pygame channel 249.

    States: idle | recording | stopped | playing
    """

    SAMPLERATE = 44100
    CHANNELS   = 2
    CHUNK_SECS = 0.1

    def __init__(self, recording_dir: Path):
        self.recording_dir  = Path(recording_dir)
        self.recording_dir.mkdir(parents=True, exist_ok=True)
        self._state          = "idle"
        self._chunks: list   = []
        self._stream         = None
        self._lock           = threading.Lock()
        self._rec_start      = None
        self._current_file   = None
        self._pb_snd         = None
        self._pb_start       = None
        self._pb_loop        = False
        self._pb_len         = 0.0
        self._fx_token       = 0    # incremented to cancel in-flight fx threads
        self._fx_lock        = threading.Lock()
        self._tmp_files: list = []  # temp fx files to clean up
        self._fx_thread      = None # current FX processing thread
        self._last_gc        = time.monotonic()
        self._ensure_mixer()

    def _ensure_mixer(self):
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(44100, -16, 2, 1024)
                pygame.mixer.set_num_channels(512)
        except Exception as e:
            log.warning(f"Recorder mixer: {e}")

    # ── State ─────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        return self._state

    def is_recording(self) -> bool:
        return self._state == "recording"

    def is_playing(self) -> bool:
        try:
            return bool(pygame.mixer.Channel(CH_RECORDER).get_busy())
        except Exception:
            return False

    # ── Recording ─────────────────────────────────────────────────

    def start_recording(self, input_device: str = "") -> bool:
        if self._state == "recording" or not HAS_SOUNDDEVICE:
            return False
        self._chunks    = []
        self._rec_start = time.monotonic()
        try:
            dev = self._find_input_device(input_device)
            self._stream = sd.InputStream(
                samplerate=self.SAMPLERATE, channels=self.CHANNELS,
                dtype="float32", device=dev,
                blocksize=int(self.SAMPLERATE * self.CHUNK_SECS),
                callback=self._callback)
            self._stream.start()
            self._state = "recording"
            log.info(f"Recording started (device={dev!r})")
            return True
        except Exception as e:
            log.error(f"Record start error: {e}")
            self._stream = None
            self._state  = "idle"
            return False

    def _find_input_device(self, preferred: str = ""):
        if not HAS_SOUNDDEVICE:
            return None
        try:
            devs = sd.query_devices()
            if preferred and preferred != "Default (System)":
                for i, d in enumerate(devs):
                    if d["name"] == preferred and d["max_input_channels"] > 0:
                        return i
            for i, d in enumerate(devs):
                nl = d["name"].lower()
                if d["max_input_channels"] > 0 and "voicemeeter" in nl:
                    return i
            for i, d in enumerate(devs):
                nl = d["name"].lower()
                if d["max_input_channels"] > 0 and any(
                        k in nl for k in ("stereo mix","loopback","wave out")):
                    return i
        except Exception:
            pass
        return None

    def _callback(self, indata, frames, time_info, status):
        with self._lock:
            self._chunks.append(indata.copy())

    def stop_recording(self):
        if self._state != "recording":
            return
        try:
            if self._stream:
                self._stream.stop()
                self._stream.close()
                self._stream = None
        except Exception as e:
            log.warning(f"Record stop error: {e}")
        self._state = "stopped"
        log.info(f"Recording stopped — {len(self._chunks)} chunks")

    def stop_and_save(self, fmt: str = "wav") -> Path | None:
        """Stop recording, auto-save, pre-load for playback."""
        self.stop_recording()
        # Take a safe snapshot of chunks under lock before saving
        with self._lock:
            if not self._chunks:
                return None
            chunks_snapshot = list(self._chunks)
            self._chunks = []
        path = self._save_chunks(chunks_snapshot, fmt=fmt)
        if path:
            try:
                snd = pygame.mixer.Sound(str(path))
                self._pb_snd = snd
                self._pb_len = snd.get_length()
                self._current_file = str(path)
            except Exception as e:
                log.warning(f"Pre-load error: {e}")
        return path

    def get_elapsed(self) -> float:
        if self._rec_start is None or self._state != "recording":
            return 0.0
        return time.monotonic() - self._rec_start

    # ── Save / discard ────────────────────────────────────────────

    def save(self, fmt: str = "wav") -> Path | None:
        with self._lock:
            if not self._chunks:
                return None
            chunks_snapshot = list(self._chunks)
            self._chunks = []
        return self._save_chunks(chunks_snapshot, fmt=fmt)

    def _save_chunks(self, chunks: list, fmt: str = "wav") -> Path | None:
        """Write a snapshot of chunks to disk — safe to call from any thread."""
        if not chunks:
            return None
        ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
        wav_path = self.recording_dir / f"recording_{ts}.wav"
        try:
            audio = np.concatenate(chunks, axis=0)
            i16   = (audio * 32767).astype(np.int16)
            with wave.open(str(wav_path), "w") as wf:
                wf.setnchannels(self.CHANNELS)
                wf.setsampwidth(2)
                wf.setframerate(self.SAMPLERATE)
                wf.writeframes(i16.tobytes())
            if fmt == "mp3" and HAS_PYDUB:
                mp3 = wav_path.with_suffix(".mp3")
                AudioSegment.from_wav(str(wav_path)).export(
                    str(mp3), format="mp3", bitrate="192k")
                wav_path.unlink()
                final = mp3
            else:
                final = wav_path
            self._state        = "idle"
            self._current_file = str(final)
            log.info(f"Saved → {final}")
            return final
        except Exception as e:
            log.error(f"Save error: {e}")
            return None

    def discard(self):
        with self._lock:
            self._chunks = []
        self._state = "idle"

    def set_recordings_folder(self, path: str):
        p = Path(path)
        try:
            p.mkdir(parents=True, exist_ok=True)
            self.recording_dir = p
        except Exception as e:
            log.warning(f"Set folder error: {e}")

    def delete_file(self, path: str) -> bool:
        try:
            p = Path(path)
            if p.exists():
                p.unlink()
                return True
        except Exception as e:
            log.warning(f"Delete error: {e}")
        return False

    # ── Playback ──────────────────────────────────────────────────

    def load_and_play(self, path: str, loop: bool = False) -> bool:
        self.stop_playback()
        try:
            snd = pygame.mixer.Sound(str(path))
            self._pb_snd   = snd
            self._pb_len   = snd.get_length()
            self._pb_loop  = loop
            self._pb_start = time.monotonic()
            self._current_file = str(path)
            pygame.mixer.Channel(CH_RECORDER).play(
                snd, loops=-1 if loop else 0)
            self._state = "playing"
            return True
        except Exception as e:
            log.warning(f"Playback error: {e}")
            return False

    def stop_playback(self):
        try:
            pygame.mixer.Channel(CH_RECORDER).stop()
        except Exception:
            pass
        # Free old sound object
        if self._pb_snd is not None:
            try:
                del self._pb_snd
            except Exception:
                pass
            self._pb_snd = None
        if self._state == "playing":
            self._state = "idle"
        self._pb_start = None

    def get_playback_position(self) -> float:
        if self._pb_start is None or not self.is_playing():
            return 0.0
        elapsed = time.monotonic() - self._pb_start
        if self._pb_loop:
            return elapsed % max(self._pb_len, 0.001)
        return min(elapsed, self._pb_len)

    def get_playback_length(self) -> float:
        return self._pb_len

    # ── Effect processing ─────────────────────────────────────────

    def apply_effects_and_play(self, path: str, fx_set: set,
                                fx_cfg: dict, loop: bool = False,
                                on_done=None):
        """Process file with effects in bg thread then play.
        Waits for any previous FX thread to finish before starting.
        """
        # Wait for previous FX thread to complete (max 2 seconds)
        if self._fx_thread and self._fx_thread.is_alive():
            self._fx_thread.join(timeout=2.0)
        
        with self._fx_lock:
            self._fx_token += 1
            my_token = self._fx_token

        def _worker():
            result = self._process_effects(path, fx_set, fx_cfg)
            # Check if we were cancelled by a newer request
            with self._fx_lock:
                if my_token != self._fx_token:
                    # Clean up temp file if we made one
                    if result and result != path:
                        try: Path(result).unlink(missing_ok=True)
                        except Exception: pass
                    return
            target = result if result else path
            ok = self.load_and_play(target, loop=loop)
            # Track and clean old temp files — keep only 1
            if result and result != path:
                with self._fx_lock:
                    self._tmp_files.append(result)
                    while len(self._tmp_files) > 1:
                        old = self._tmp_files.pop(0)
                        try: Path(old).unlink(missing_ok=True)
                        except Exception: pass
            # Periodic garbage collection
            if time.monotonic() - self._last_gc > 30.0:
                gc.collect()
                self._last_gc = time.monotonic()
            if on_done:
                try:
                    on_done(ok)
                except Exception:
                    pass  # widget may have been destroyed
        
        self._fx_thread = threading.Thread(target=_worker, daemon=True)
        self._fx_thread.start()

    def _process_effects(self, src: str, fx_set: set,
                          fx_cfg: dict) -> str | None:
        try:
            import tempfile

            def _p(key, param, default):
                return fx_cfg.get(key, {}).get(param, default)

            # Load
            try:
                with AudioFile(src) as f:
                    audio, sr = f.read(f.frames), f.samplerate
                HAS_PB = True
            except Exception:
                HAS_PB = False
                with wave.open(src, "rb") as wf:
                    sr    = wf.getframerate()
                    nch   = wf.getnchannels()
                    raw   = wf.readframes(wf.getnframes())
                    samp  = np.frombuffer(raw, np.int16).astype(np.float32)
                    samp /= 32768.0
                    audio = samp.reshape(-1, nch).T

            # Pedalboard effects
            if HAS_PB and HAS_PEDALBOARD:
                fx = []
                if "chipmunk" in fx_set:
                    fx.append(PitchShift(
                        semitones=_p("chipmunk","semitones",6.0)))
                elif "deep" in fx_set:
                    fx.append(PitchShift(
                        semitones=_p("deep","semitones",-6.0)))
                if "reverb" in fx_set:
                    rs  = _p("reverb","room_size",0.75)
                    wet = _p("reverb","wet",0.5)
                    fx.append(Reverb(room_size=rs, wet_level=wet,
                                     dry_level=1-wet))
                if "echo" in fx_set:
                    fx.append(Delay(
                        delay_seconds=_p("echo","delay",0.4),
                        feedback=_p("echo","feedback",0.45),
                        mix=_p("echo","mix",0.5)))
                if "lofi" in fx_set:
                    fx.append(LowpassFilter(
                        cutoff_frequency_hz=_p("lofi","lowpass",3200.0)))
                    fx.append(HighpassFilter(
                        cutoff_frequency_hz=_p("lofi","highpass",500.0)))
                    fx.append(Gain(gain_db=-3))
                if fx:
                    audio = Pedalboard(fx)(audio, sr)

            # Speed
            if "chipmunk" in fx_set:
                audio = self._resample(audio,
                                       _p("chipmunk","speed",1.35))
            elif "deep" in fx_set:
                audio = self._resample(audio, _p("deep","speed",0.72))

            if "reverse" in fx_set:
                audio = audio[:, ::-1]

            audio = np.clip(audio, -1.0, 1.0)
            out   = (audio.T * 32767).astype(np.int16)
            if out.ndim == 1:
                out = np.column_stack([out, out])

            tmp = tempfile.NamedTemporaryFile(
                suffix=".wav", delete=False, dir=self.recording_dir)
            tmp.close()
            with wave.open(tmp.name, "wb") as wf:
                wf.setnchannels(out.shape[1])
                wf.setsampwidth(2)
                wf.setframerate(sr)
                wf.writeframes(out.tobytes())
            return tmp.name
        except Exception as e:
            log.warning(f"Effect processing: {e}")
            return None

    def _resample(self, audio: np.ndarray, factor: float) -> np.ndarray:
        nch, nf = audio.shape
        new_len = max(1, int(nf / factor))
        out     = np.zeros((nch, new_len), dtype=audio.dtype)
        for c in range(nch):
            out[c] = np.interp(
                np.linspace(0, nf-1, new_len),
                np.arange(nf), audio[c])
        return out

    def cleanup(self):
        """Free all resources — call on app close."""
        self.stop_playback()
        self.stop_recording()
        # Wait for FX thread to finish
        if self._fx_thread and self._fx_thread.is_alive():
            self._fx_thread.join(timeout=1.0)
        # Delete all temp files
        with self._fx_lock:
            for tmp in self._tmp_files:
                try: Path(tmp).unlink(missing_ok=True)
                except Exception: pass
            self._tmp_files.clear()
        # Clear recording chunks
        with self._lock:
            self._chunks.clear()
        # Free playback sound
        if self._pb_snd:
            try: del self._pb_snd
            except Exception: pass
            self._pb_snd = None
        gc.collect()
        log.info("RecorderManager cleanup complete")

    # ── Recordings list ───────────────────────────────────────────

    def list_recordings(self) -> list[dict]:
        out = []
        try:
            for p in sorted(self.recording_dir.iterdir(),
                            key=lambda f: f.stat().st_mtime, reverse=True):
                if p.suffix.lower() in (".wav", ".mp3"):
                    mt = datetime.fromtimestamp(p.stat().st_mtime)
                    out.append({
                        "path":        str(p),
                        "filename":    p.name,
                        "size_mb":     round(p.stat().st_size/1_048_576, 1),
                        "recorded_at": mt.strftime("%Y-%m-%d %H:%M"),
                    })
        except Exception as e:
            log.warning(f"List recordings: {e}")
        return out


# ═══════════════════════════════════════════════════════════════
# MIC MANAGER
# ═══════════════════════════════════════════════════════════════

class MicManager:
    """
    Controls the Windows default input device (mute/gain) via pycaw,
    reads live mic level via sounddevice, and runs auto-ducking of
    the performance fade slider when voice is detected.
    """

    POLL_MS      = 80    # mic level poll interval

    def __init__(self, cfg):
        self.cfg            = cfg
        self._muted         = False
        self._pre_mute_vol  = 1.0   # volume before mute
        self._level         = 0.0
        self._level_lock    = threading.Lock()
        self._duck_active   = False
        self._pre_duck_fade = 1.0
        self._vol_intf      = None

        # Init with saved device (or default mic)
        saved = cfg.config.get("mic_input_device", "Default (System)")
        self.reinit(saved)

        # Start mic level polling thread
        if HAS_SOUNDDEVICE:
            threading.Thread(target=self._poll_level,
                             daemon=True).start()

    def reinit(self, device_name: str = "Default (System)"):
        """Bind to the named Windows input device via pycaw."""
        self._vol_intf = None
        if not HAS_PYCAW:
            return
        try:
            from pycaw.pycaw import AudioUtilities
            from pycaw.constants import EDataFlow, DEVICE_STATE
            # Get active capture devices with proper FriendlyNames
            devs = AudioUtilities.GetAllDevices(
                data_flow=EDataFlow.eCapture.value,
                device_state=DEVICE_STATE.ACTIVE.value)
            target = None
            if device_name == "Default (System)":
                target = AudioUtilities.GetMicrophone()
            else:
                for d in devs:
                    if (d.FriendlyName and
                            device_name.lower() ==
                            d.FriendlyName.lower()):
                        target = d
                        break
                # Partial match fallback
                if target is None:
                    for d in devs:
                        if (d.FriendlyName and
                                device_name.lower() in
                                d.FriendlyName.lower()):
                            target = d
                            break
            # Last resort: default microphone
            if target is None:
                target = AudioUtilities.GetMicrophone()
            if target:
                # target is a pycaw AudioDevice wrapper;
                # Activate() lives on the underlying IMMDevice (_dev)
                raw = getattr(target, '_dev', target)
                intf = raw.Activate(
                    IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                self._vol_intf = intf.QueryInterface(
                    IAudioEndpointVolume)
                log.info(f"MicManager bound to: "
                         f"{getattr(target, 'FriendlyName', device_name)}")
            else:
                log.warning("MicManager: no input device found")
        except Exception as e:
            log.warning(f"MicManager reinit: {e}")

    # ── Level polling ─────────────────────────────────────────────

    def _poll_level(self):
        """Read mic RMS level continuously in background thread."""
        cached_dev_name = None
        cached_dev_idx  = None
        cached_sr       = 44100
        while True:
            try:
                dev_name = self.cfg.config.get(
                    "mic_input_device", "Default (System)")
                # Only re-scan devices when name changes
                if dev_name != cached_dev_name:
                    cached_dev_name = dev_name
                    cached_dev_idx  = None
                    if dev_name != "Default (System)":
                        for i, d in enumerate(sd.query_devices()):
                            if (d["max_input_channels"] > 0 and
                                    dev_name.lower() in
                                    d["name"].lower()):
                                cached_dev_idx = i
                                break
                    info = sd.query_devices(
                        cached_dev_idx, kind="input")
                    cached_sr = int(info["default_samplerate"])
                data = sd.rec(
                    int(cached_sr * 0.05), samplerate=cached_sr,
                    channels=1, dtype="float32",
                    device=cached_dev_idx, blocking=True)
                rms = float(np.sqrt(np.mean(data ** 2)))
                with self._level_lock:
                    self._level = min(1.0, rms * 8.0)
            except Exception:
                with self._level_lock:
                    self._level = 0.0
                cached_dev_name = None   # force re-scan next tick
                time.sleep(0.3)

    def get_level(self) -> float:
        with self._level_lock:
            return self._level

    # ── Mute / gain ───────────────────────────────────────────────

    @property
    def is_bound(self) -> bool:
        """True if pycaw successfully bound to a real device."""
        return self._vol_intf is not None

    def is_muted(self) -> bool:
        return self._muted

    def set_mute(self, muted: bool):
        self._muted = muted
        if self._vol_intf:
            try:
                if muted:
                    # Save current volume, then zero it + set mute flag
                    self._pre_mute_vol = \
                        self._vol_intf.GetMasterVolumeLevelScalar()
                    self._vol_intf.SetMasterVolumeLevelScalar(0.0, None)
                    self._vol_intf.SetMute(1, None)
                else:
                    # Clear mute flag, restore saved volume
                    self._vol_intf.SetMute(0, None)
                    self._vol_intf.SetMasterVolumeLevelScalar(
                        max(0.05, self._pre_mute_vol), None)
            except Exception as e:
                log.warning(f"MicManager set_mute: {e}")

    def toggle_mute(self) -> bool:
        self.set_mute(not self._muted)
        return self._muted

    def get_gain(self) -> float:
        """Return 0.0–1.0 scalar gain."""
        if self._vol_intf:
            try:
                return self._vol_intf.GetMasterVolumeLevelScalar()
            except Exception:
                pass
        return 1.0

    def set_gain(self, v: float):
        if self._vol_intf:
            try:
                self._vol_intf.SetMasterVolumeLevelScalar(
                    max(0.0, min(1.0, v)), None)
            except Exception as e:
                log.warning(f"MicManager set_gain: {e}")

    # ── PTT ───────────────────────────────────────────────────────

    # ── Manual duck ───────────────────────────────────────────────

    def duck_smooth(self, start: float, end: float,
                    duration_secs: float, after_fn,
                    fade_setter, on_done=None):
        """
        Smoothly move the VOL/FADE fader from start→end over
        duration_secs using tkinter after() calls.
        Each call cancels any previous in-progress fade.
        after_fn   : widget.after
        fade_setter: callable(float) that sets the slider value
        on_done    : optional callback when fade completes
        """
        # Increment token — any running fade with an older token stops
        self._fade_token = getattr(self, '_fade_token', 0) + 1
        token   = self._fade_token
        steps   = max(20, int(duration_secs * 30))
        step_ms = max(16, int(duration_secs * 1000 / steps))

        def _step(i):
            if self._fade_token != token:
                return   # superseded by a newer fade — stop
            val = start + (end - start) * (i / steps)
            try:
                fade_setter(val)
            except Exception:
                pass
            if i < steps:
                after_fn(step_ms, lambda ii=i+1: _step(ii))
            elif on_done:
                try: on_done()
                except Exception: pass
        _step(0)
