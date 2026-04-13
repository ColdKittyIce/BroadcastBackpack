"""
main.py — Broadcast Backpack v6.0.0
Application entry point and main window orchestrator.
"""

import os, sys, time, logging, threading
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import customtkinter as ctk
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

import tkinter as tk
from tkinter import messagebox

from config import (
    ConfigManager, C, VERSION, APP_NAME,
    LOG_DIR, DATA_DIR, ANALYTICS_DIR
)
from audio   import AudioManager, RecorderManager, MicManager
from network import NetworkMonitor, DiscordWebhook, MicroSIPListener
from streaming import StreamEngine, StreamState
from analytics import AnalyticsManager

# ── DnD ───────────────────────────────────────────────────────────
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
except ImportError:
    HAS_DND = False

# ── Hotkeys ───────────────────────────────────────────────────────
try:
    import keyboard as kb
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False


def _setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    fh = RotatingFileHandler(
        LOG_DIR / "broadcast.log",
        maxBytes=2_000_000, backupCount=3,
        encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(name)s  %(message)s"))
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    root.addHandler(fh)
    root.addHandler(ch)


log = logging.getLogger("broadcast.main")


# ═══════════════════════════════════════════════════════════════
# APPLICATION
# ═══════════════════════════════════════════════════════════════

class BroadcastApp(ctk.CTk if not HAS_DND else TkinterDnD.Tk):

    def __init__(self):
        super().__init__()

        # ── Config + theme ────────────────────────────────────────
        self.cfg      = ConfigManager()
        self.cfg.apply_theme()

        # ── Audio ─────────────────────────────────────────────────
        out_dev = self.cfg.config.get("audio_output_device","")
        if out_dev == "Default (System)": out_dev = ""
        self.audio    = AudioManager()
        if out_dev:
            self.audio.reinit(out_dev)
        # Initialize independent volumes from config
        self.audio.set_board_volume(self.cfg.config.get("board_volume", 1.0))
        self.audio.set_queue_volume(self.cfg.config.get("queue_volume", 1.0))
        self.audio.set_board_gain_db(self.cfg.config.get("board_gain_db", 0))
        
        self.recorder = RecorderManager(
            self.cfg.config.get(
                "recordings_folder",
                str(DATA_DIR / "recordings")))
        self.mic = MicManager(self.cfg)

        # ── Network ───────────────────────────────────────────────
        stream_host = self.cfg.config.get("stream_host", "")
        stream_port = self.cfg.config.get("stream_port", 80)
        self.net      = NetworkMonitor(stream_host, stream_port)
        self.microsip = MicroSIPListener(self)
        self.discord  = DiscordWebhook()

        # ── Streaming + Analytics ─────────────────────────────────
        self.stream    = StreamEngine(self.cfg.config)
        self.stream.set_status_callback(self._on_stream_state)
        self.analytics = AnalyticsManager(ANALYTICS_DIR)

        # ── State ─────────────────────────────────────────────────
        self._live         = False
        self._live_start   = None
        self._live_wall    = None   # wall-clock datetime of GO LIVE
        self._live_h = self._live_m = self._live_s = 0
        self._stream_pending = False  # True while waiting for stream to connect
        self._stream_failsafe_job = None
        self._cd_running   = False
        self._cd_total     = 0
        self._cd_end       = 0.0
        self._sw_running   = False
        self._sw_paused    = False
        self._sw_start     = 0.0
        self._sw_elapsed   = 0.0
        self._sw_laps      = []
        self._mini_mode    = False
        self._mini_win     = None
        self._undo_stack:  list = []

        # ── Window ────────────────────────────────────────────────
        w = self.cfg.config.get("window_width",  1600)
        h = self.cfg.config.get("window_height",  960)
        self.title(f"{APP_NAME}  v{VERSION}")
        self.geometry(f"{w}x{h}")
        self.minsize(1100, 700)
        self.configure(bg=C["bg"])
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        op = self.cfg.config.get("opacity", 1.0)
        if op < 1.0:
            self.attributes("-alpha", op)

        # Store app ref on root for child widgets
        self._app = self

        # ── Build UI ──────────────────────────────────────────────
        self._build_ui()

        # ── DnD root handler ─────────────────────────────────────
        if HAS_DND:
            try:
                self.drop_target_register(DND_FILES)
                self.dnd_bind("<<Drop>>", self._on_dnd_drop)
            except Exception as e:
                log.warning(f"DnD register: {e}")

        # ── Hotkeys ───────────────────────────────────────────────
        self.register_hotkeys()

        # ── Network monitor ───────────────────────────────────────
        self.net.start(on_change=self._on_net_change)
        self.microsip.start()

        # ── Timers ───────────────────────────────────────────────
        self.after(500,  self._tick_live)
        self.after(750,  self._tick_countdown)
        self.after(250,  self._tick_stopwatch)
        self.after(5000, self._autosave_config)

        log.info(f"{APP_NAME} v{VERSION} started")

    # ── UI Build ──────────────────────────────────────────────────

    def _build_ui(self):
        from ui_header      import HeaderFrame, MenuBarFrame
        from ui_soundboard  import SoundboardFrame
        from ui_right_panel import RightPanel
        from ui_bottom      import BottomStrip

        # Menu bar
        self.menu_bar = MenuBarFrame(self, self)
        self.menu_bar.pack(fill="x", side="top")

        # Header — full width
        self.header = HeaderFrame(self, self)
        self.header.pack(fill="x", side="top")
        tk.Frame(self, bg=C["border"], height=1).pack(fill="x", side="top")

        # ── Outer row: (soundboard+bottom LEFT) | (right panel RIGHT) ──
        outer = tk.Frame(self, bg=C["bg"])
        outer.pack(fill="both", expand=True, side="top")

        # Right panel — full height, flush to bottom of window
        from ui_right_panel import RightPanel
        self.right_panel = RightPanel(
            outer, self.cfg, self.audio,
            get_elapsed=self._get_elapsed_str,
            get_is_live=lambda: self._live)
        self.right_panel.pack(side="right", fill="y")
        tk.Frame(outer, bg=C["border"], width=1).pack(side="right", fill="y")

        # Left zone: soundboard on top, bottom strip below
        left_zone = tk.Frame(outer, bg=C["bg"])
        left_zone.pack(side="left", fill="both", expand=True)

        # Bottom strip — inside left zone only
        self.bottom = BottomStrip(
            left_zone, self.cfg, self.audio,
            get_elapsed=self._get_elapsed_str,
            get_is_live=lambda: self._live)
        self.bottom.pack(fill="x", side="bottom")
        tk.Frame(left_zone, bg=C["border"], height=1).pack(
            fill="x", side="bottom")

        # Soundboard — fills remaining space in left zone
        self.soundboard = SoundboardFrame(
            left_zone, self.cfg, self.audio,
            session_log=self.right_panel.session_log)
        self.soundboard.pack(fill="both", expand=True)

        # Wire references
        self.soundboard.queue.session_log  = self.right_panel.session_log
        self.bottom.session_log            = self.right_panel.session_log
        self.bottom.notes.session_log      = self.right_panel.session_log
        self.queue_panel                   = self.soundboard.queue

    # ── Live / broadcast ──────────────────────────────────────────

    def manual_go_live(self):
        if self._live:
            self._end_live()
        elif self._stream_pending:
            # Cancel the pending stream connection
            self._stream_pending = False
            if self._stream_failsafe_job:
                self.after_cancel(self._stream_failsafe_job)
                self._stream_failsafe_job = None
            threading.Thread(target=self.stream.stop, daemon=True).start()
            self.header.set_on_air(False)
            log.info("GO LIVE cancelled by user")
        else:
            self._start_live()

    def _start_live(self):
        """Phase 1 — attempt stream connection. Timer starts when stream confirms LIVE."""
        self._stream_pending = True
        self.header.set_connecting()

        # Failsafe — if stream hasn't connected within 20s, start anyway
        self._stream_failsafe_job = self.after(
            20_000, self._stream_failsafe)

        # Start stream in background
        threading.Thread(target=self.stream.start, daemon=True).start()
        log.info("GO LIVE pressed — awaiting stream connection")

    def _stream_failsafe(self):
        """Start the show timer even if stream never connected."""
        if not self._stream_pending:
            return
        log.warning("Stream did not connect within 20s — starting show anyway")
        self._stream_pending = False
        self._stream_failsafe_job = None
        self._begin_live(stream_ok=False)

    def _begin_live(self, stream_ok: bool = True):
        """Phase 2 — officially start the show clock and session log."""
        self._live       = True
        self._live_start = time.monotonic()
        self._live_wall  = datetime.now()
        self._live_h = self._live_m = self._live_s = 0
        self.header.set_on_air(True)
        self.right_panel.session_log.log_live_start()

        # Analytics
        self.analytics.start_show(self._live_wall)

        if not stream_ok:
            self.right_panel.session_log.log_event(
                "⚠ Stream did not connect — show started without stream")

        # Discord notification
        if self.cfg.config.get("discord_enabled"):
            self.discord.fire(
                self.cfg.config.get("discord_webhook",""),
                self.cfg.config.get("discord_message",""))
        log.info("LIVE started")

    def _end_live(self):
        self._live           = False
        self._stream_pending = False
        if self._stream_failsafe_job:
            self.after_cancel(self._stream_failsafe_job)
            self._stream_failsafe_job = None

        dur_str   = (f"{self._live_h:02d}:"
                     f"{self._live_m:02d}:"
                     f"{self._live_s:02d}")
        elapsed_s = (time.monotonic() - self._live_start
                     if self._live_start else 0)
        self.header.set_on_air(False)
        self.right_panel.session_log.log_live_end(dur_str)
        self._live_h = self._live_m = self._live_s = 0
        self.header.update_live(0, 0, 0)

        # Stop stream
        threading.Thread(target=self.stream.stop, daemon=True).start()

        # Analytics
        self.analytics.end_show(elapsed_s)

        log.info(f"LIVE ended — {dur_str}")
        self._show_post_dialog(dur_str)

    def _tick_live(self):
        if self._live and self._live_start:
            elapsed      = time.monotonic() - self._live_start
            self._live_h = int(elapsed // 3600)
            self._live_m = int((elapsed % 3600) // 60)
            self._live_s = int(elapsed % 60)
            self.header.update_live(
                self._live_h, self._live_m, self._live_s)
        self.after(500, self._tick_live)

    def _get_elapsed_str(self) -> str:
        if not self._live:
            return ""
        return (f"{self._live_h:02d}:"
                f"{self._live_m:02d}:"
                f"{self._live_s:02d}")

    # ── Post-show dialog ──────────────────────────────────────────

    def _show_post_dialog(self, dur_str: str):
        from ui_dialogs import PostShowDialog
        summary   = self.right_panel.session_log.get_summary_text()
        log_lines = self.right_panel.session_log.entries_as_lines()
        self.after(400, lambda: PostShowDialog(
            self, self.cfg,
            duration_str=dur_str,
            session_summary=summary,
            log_lines=log_lines,
            go_live_wall=self._live_wall))

    # ── Panic ─────────────────────────────────────────────────────

    def panic(self):
        self.audio.stop_all()
        self.soundboard.stop_all()
        if self.recorder.state == "playing":
            self.recorder.stop_playback()
        self.header.flash_red()
        self.right_panel.session_log.log_event("🚨 PANIC")
        self.analytics.record_panic()
        log.warning("PANIC fired")

    # ── Mute ─────────────────────────────────────────────────────

    def toggle_mute(self):
        muted = self.audio.toggle_mute()
        self.header.set_mute_state(muted)
        if self._mini_win:
            try:
                self._mini_win.update_mute(muted)
            except Exception:
                pass

    # ── Volume ────────────────────────────────────────────────────

    def set_master_volume(self, v):
        self.audio.set_master_volume(float(v))

    # ── Countdown ────────────────────────────────────────────────

    def start_countdown(self):
        raw = self.header.cd_entry.get().strip()
        parts = raw.split(":")
        try:
            if len(parts) == 2:
                mm, ss = int(parts[0]), int(parts[1])
            elif len(parts) == 1:
                mm, ss = int(parts[0]), 0
            else:
                return
        except ValueError:
            return
        total = mm * 60 + ss
        if total <= 0:
            return
        self._cd_total   = total
        self._cd_end     = time.monotonic() + total
        self._cd_running = True
        self.right_panel.session_log.log_countdown_start(mm, ss)

    def quick_countdown(self, minutes: int):
        self._cd_total   = minutes * 60
        self._cd_end     = time.monotonic() + self._cd_total
        self._cd_running = True

    def stop_countdown(self):
        self._cd_running = False
        self.header.update_countdown(0, 0, urgent=False)

    def _tick_countdown(self):
        if self._cd_running:
            remaining = self._cd_end - time.monotonic()
            if remaining <= 0:
                self._cd_running = False
                self.header.update_countdown(0, 0, urgent=False)
                self.right_panel.session_log.log_countdown_end()
            else:
                mm = int(remaining // 60)
                ss = int(remaining % 60)
                self.header.update_countdown(
                    mm, ss, urgent=remaining <= 30)
        self.after(500, self._tick_countdown)

    # ── Stopwatch ───────────────────────────────────────────────

    def start_stopwatch(self):
        """Start or resume stopwatch."""
        if self._sw_running:
            return
        if self._sw_paused:
            # Resume from pause
            self._sw_start = time.monotonic() - self._sw_elapsed
        else:
            # Fresh start
            self._sw_start = time.monotonic()
            self._sw_elapsed = 0.0
            self._sw_laps.clear()
        self._sw_running = True
        self._sw_paused = False

    def pause_stopwatch(self):
        """Pause stopwatch, preserving elapsed time."""
        if self._sw_running:
            self._sw_elapsed = time.monotonic() - self._sw_start
            self._sw_running = False
            self._sw_paused = True

    def reset_stopwatch(self):
        """Stop and reset stopwatch to zero."""
        self._sw_running = False
        self._sw_paused = False
        self._sw_elapsed = 0.0
        self._sw_start = 0.0
        self._sw_laps.clear()
        self.header.update_stopwatch(0, 0)

    def lap_stopwatch(self):
        """Record current time as a lap marker and log it."""
        if self._sw_running or self._sw_paused:
            elapsed = self._sw_elapsed if self._sw_paused else (time.monotonic() - self._sw_start)
            mm = int(elapsed // 60)
            ss = int(elapsed % 60)
            lap_str = f"{mm:02d}:{ss:02d}"
            lap_num = len(self._sw_laps) + 1
            self._sw_laps.append(elapsed)
            # Log to session log
            self.right_panel.session_log.log(f"📌 Lap {lap_num}: {lap_str}")

    def _tick_stopwatch(self):
        if self._sw_running:
            elapsed = time.monotonic() - self._sw_start
            mm = int(elapsed // 60)
            ss = int(elapsed % 60)
            self.header.update_stopwatch(mm, ss)
        self.after(250, self._tick_stopwatch)

    # ── Mini mode ─────────────────────────────────────────────────

    def toggle_mini_mode(self):
        if self._mini_mode:
            self._exit_mini()
        else:
            self._enter_mini()

    def _enter_mini(self):
        from ui_header import MiniModeWindow
        self._mini_mode = True
        self.withdraw()
        self._mini_win  = MiniModeWindow(self, self)

    def _exit_mini(self):
        self._mini_mode = False
        if self._mini_win:
            try:
                self._mini_win.destroy()
            except Exception:
                pass
            self._mini_win = None
        self.deiconify()
        self.lift()

    # ── DnD ───────────────────────────────────────────────────────

    def _on_dnd_drop(self, e):
        raw   = e.data
        paths = self.tk.splitlist(raw)
        x, y  = e.x_root, e.y_root
        w     = self.winfo_containing(x, y)

        for path in paths:
            path = path.strip().strip("{}")
            if not path:
                continue

            # Route to soundboard button
            if w and hasattr(w, "handle_drop"):
                w.handle_drop(path)
                continue

            # Walk up widget tree
            parent = w
            while parent:
                if hasattr(parent, "route_drop"):
                    parent.route_drop(w, path)
                    break
                try:
                    parent = parent.master
                except Exception:
                    break
            else:
                # Default: add to queue
                self.soundboard.queue.add_file(path)

    # ── Network callback ──────────────────────────────────────────

    def _on_net_change(self, connected: bool):
        pass  # Could add a status indicator in future

    # ── Hotkeys ───────────────────────────────────────────────────

    def register_hotkeys(self):
        if not HAS_KEYBOARD:
            return
        try:
            kb.unhook_all()
        except Exception:
            pass
        hk = self.cfg.config.get("hotkeys", {})
        
        # Map action IDs to handler functions
        bindings = {
            "go_live":         self.manual_go_live,
            "panic":           self.panic,
            "mute_mic":        self.toggle_mute,
            "timestamp":       self._hotkey_timestamp,
            "gold_moment":     self._hotkey_gold,
            "mini_mode":       self.toggle_mini_mode,
            "cough":           self._hotkey_cough,
            "break_on":        self._hotkey_break_on,
            "break_off":       self._hotkey_break_off,
            "queue_play":      self._hotkey_queue_play,
            "queue_next":      self._hotkey_queue_next,
            "record_toggle":   self._hotkey_record_toggle,
            "countdown_toggle": self._hotkey_countdown_toggle,
            "stopwatch_lap":   self._hotkey_stopwatch_lap,
            "hotkey_legend":   self._hotkey_show_legend,
        }
        
        # Add pinned button hotkeys (1-8)
        for i in range(1, 9):
            bindings[f"pinned_{i}"] = lambda idx=i-1: self._hotkey_pinned(idx)
        
        for key, fn in bindings.items():
            combo = hk.get(key, "")
            if combo:
                try:
                    kb.add_hotkey(combo, fn, suppress=False)
                except Exception as e:
                    log.warning(f"Hotkey '{combo}': {e}")

    def _hotkey_pinned(self, idx):
        """Play pinned button by index (0-7)."""
        try:
            self.soundboard.play_pinned(idx)
        except Exception:
            pass

    def _hotkey_cough(self):
        """Trigger cough button."""
        try:
            self.header.cough_press()
        except Exception:
            pass

    def _hotkey_break_on(self):
        """Trigger BREAK button."""
        try:
            self.header.break_press()
        except Exception:
            pass

    def _hotkey_break_off(self):
        """Trigger BACK button."""
        try:
            self.header.back_press()
        except Exception:
            pass

    def _hotkey_queue_play(self):
        """Toggle queue play/pause."""
        try:
            self.soundboard.queue_panel._play_pause()
        except Exception:
            pass

    def _hotkey_queue_next(self):
        """Skip to next track in queue."""
        try:
            self.soundboard.queue_panel._skip()
        except Exception:
            pass

    def _hotkey_record_toggle(self):
        """Toggle recording."""
        try:
            self.header.toggle_record()
        except Exception:
            pass

    def _hotkey_countdown_toggle(self):
        """Toggle countdown."""
        try:
            self.header._countdown_start_stop()
        except Exception:
            pass

    def _hotkey_stopwatch_lap(self):
        """Mark stopwatch lap."""
        try:
            self.lap_stopwatch()
        except Exception:
            pass

    def _hotkey_show_legend(self):
        """Show hotkey legend overlay."""
        try:
            self._show_hotkey_legend()
        except Exception:
            pass

    def _show_hotkey_legend(self):
        """Display a semi-transparent overlay showing all hotkeys."""
        hk = self.cfg.config.get("hotkeys", {})
        if not hk:
            return
        
        # Create overlay window
        overlay = tk.Toplevel(self)
        overlay.title("Hotkey Legend")
        overlay.attributes("-topmost", True)
        overlay.attributes("-alpha", 0.9)
        overlay.configure(bg=C["surface"])
        overlay.geometry("350x450")
        
        tk.Label(overlay, text="⌨  HOTKEY LEGEND", 
                 bg=C["surface"], fg=C["text"],
                 font=("Segoe UI", 14, "bold")).pack(pady=10)
        
        # Build legend
        action_names = dict(HotkeyDialog.ACTIONS) if 'HotkeyDialog' in dir() else {
            "pinned_1": "Pinned 1", "pinned_2": "Pinned 2", "pinned_3": "Pinned 3",
            "pinned_4": "Pinned 4", "pinned_5": "Pinned 5", "pinned_6": "Pinned 6",
            "pinned_7": "Pinned 7", "pinned_8": "Pinned 8",
            "go_live": "GO LIVE", "cough": "COUGH", "panic": "PANIC",
            "break_on": "BREAK", "break_off": "BACK",
            "queue_play": "Queue Play/Pause", "queue_next": "Queue Next",
            "record_toggle": "Recording", "countdown_toggle": "Countdown",
            "stopwatch_lap": "Stopwatch Lap", "mute_mic": "Mute Mic",
            "hotkey_legend": "This Legend",
        }
        
        for action_id, combo in hk.items():
            name = action_names.get(action_id, action_id)
            row = tk.Frame(overlay, bg=C["surface"])
            row.pack(fill="x", padx=20, pady=2)
            tk.Label(row, text=name, bg=C["surface"], fg=C["text"],
                     font=("Segoe UI", 11), anchor="w", width=25).pack(side="left")
            tk.Label(row, text=combo, bg=C["elevated"], fg=C["amber"],
                     font=("Consolas", 11, "bold"), padx=8, pady=2).pack(side="right")
        
        tk.Button(overlay, text="Close", bg=C["btn"], fg=C["text"],
                  font=("Segoe UI", 11), relief="flat", padx=20, pady=5,
                  command=overlay.destroy).pack(pady=15)
        
        # Close on Escape
        overlay.bind("<Escape>", lambda e: overlay.destroy())
        overlay.focus_set()

    def _hotkey_timestamp(self):
        try:
            self.bottom.notes._insert_timestamp()
        except Exception:
            pass

    def _hotkey_gold(self):
        try:
            self.bottom.notes._insert_gold()
        except Exception:
            pass

    # ── Window opacity ────────────────────────────────────────────

    def set_opacity(self, v: float):
        self.attributes("-alpha", max(0.2, min(1.0, float(v))))

    def apply_bg_color(self):
        self.configure(bg=C["bg"])

    def refresh_theme(self):
        """Refresh UI components after theme change (no restart required)."""
        # Update main window background
        self.configure(bg=C["bg"])
        
        # Refresh header
        try:
            self.header.refresh_theme()
        except Exception:
            pass
        
        # Refresh soundboard (already has full_refresh)
        try:
            self.soundboard.full_refresh()
        except Exception:
            pass
        
        # Refresh right panel
        try:
            self.right_panel.refresh_theme()
        except Exception:
            pass
        
        # Refresh bottom panel
        try:
            self.bottom.refresh_theme()
        except Exception:
            pass
        
        log.info("Theme refreshed without restart")

    # ── Config autosave ───────────────────────────────────────────

    def _autosave_config(self):
        try:
            self.bottom.notes.save_all()
            self.cfg.config["window_width"]  = self.winfo_width()
            self.cfg.config["window_height"] = self.winfo_height()
            self.cfg.save()
        except Exception as e:
            log.warning(f"Autosave: {e}")
        self.after(5 * 60 * 1000, self._autosave_config)

    # ── Undo ─────────────────────────────────────────────────────

    def undo_last(self):
        if not self._undo_stack:
            return
        source, idx, slot = self._undo_stack.pop()
        self.cfg.config[source][idx] = slot
        self.cfg.save()
        try:
            self.soundboard.full_refresh()
        except Exception:
            pass

    # ── Settings ─────────────────────────────────────────────────

    def open_settings(self, tab: str = None):
        from ui_dialogs import SettingsWindow
        sw = SettingsWindow(self, self.cfg, self)
        if tab:
            try:
                sw._tabs.set(tab)
            except Exception:
                pass

    def open_stream_settings(self):
        self.open_settings(tab="Streaming")

    def open_marker_export(self):
        from ui_exp_features import MarkerExportDialog
        try:
            log_lines = self.right_panel.session_log.entries_as_lines()
        except Exception:
            log_lines = []
        dur_str = (f"{self._live_h:02d}:{self._live_m:02d}:{self._live_s:02d}"
                   if self._live else "")
        MarkerExportDialog(self, self.cfg, log_lines,
                           self._live_wall, dur_str)

    def open_analytics(self):
        from ui_exp_features import AnalyticsDashboardDialog
        AnalyticsDashboardDialog(self, self.analytics)

    def _on_stream_state(self, state: StreamState, message: str):
        """Called from background thread — bounce to main thread."""
        def _update():
            try:
                sl = self.right_panel.session_log
                if state == StreamState.LIVE:
                    # Cancel failsafe timer
                    if self._stream_failsafe_job:
                        self.after_cancel(self._stream_failsafe_job)
                        self._stream_failsafe_job = None
                    # If still pending, this is the trigger to begin the show
                    if self._stream_pending:
                        self._stream_pending = False
                        self._begin_live(stream_ok=True)
                    # Log clean message — no credentials or mount details
                    sl.log_event("📡 Stream connected")
                    self.analytics.record_stream_live()

                elif state == StreamState.RECONNECTING:
                    sl.log_event("📡 Stream reconnecting…")
                    self.analytics.record_stream_reconnect()

                elif state == StreamState.ERROR:
                    sl.log_event("⚠ Stream error — check Tools → Stream Settings")
                    # If still pending, start show anyway
                    if self._stream_pending:
                        self._stream_pending = False
                        if self._stream_failsafe_job:
                            self.after_cancel(self._stream_failsafe_job)
                            self._stream_failsafe_job = None
                        self._begin_live(stream_ok=False)

                elif state == StreamState.IDLE and self._live:
                    sl.log_event("📡 Stream stopped")

            except Exception:
                pass
        self.after(0, _update)

    # ── Close ────────────────────────────────────────────────────

    def _on_close(self):
        if self._live:
            if not messagebox.askyesno(
                    "Still Live!",
                    "You are currently LIVE.\n\n"
                    "End the show and exit?",
                    icon="warning"):
                return
            self._end_live()

        try:
            self.bottom.notes.save_all()
        except Exception:
            pass
        self.cfg.config["window_width"]  = self.winfo_width()
        self.cfg.config["window_height"] = self.winfo_height()
        self.cfg.save()

        if HAS_KEYBOARD:
            try:
                kb.unhook_all()
            except Exception:
                pass
        self.net.stop()
        if hasattr(self, "microsip"):
            self.microsip.stop()

        # Stop stream if running
        try:
            self.stream.stop()
        except Exception:
            pass

        # Always restore mic to unmuted on exit
        try:
            self.mic.set_mute(False)
        except Exception:
            pass

        # Clean up audio resources to prevent memory leaks
        try:
            self.recorder.cleanup()
        except Exception:
            pass
        try:
            self.audio.cleanup()
        except Exception:
            pass

        self.destroy()


# ═══════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════

def _fix_path_spaces():
    """Auto-rename the app folder if it contains spaces — MicroSIP hook won't fire otherwise."""
    import shutil
    app_dir = Path(__file__).resolve().parent
    if " " not in str(app_dir):
        return  # no spaces, nothing to do
    new_dir = app_dir.parent / app_dir.name.replace(" ", "_")
    if new_dir == app_dir:
        return
    try:
        shutil.copytree(str(app_dir), str(new_dir), dirs_exist_ok=True)
        import subprocess, sys
        # Relaunch from new location then exit this instance
        new_exe = new_dir / Path(sys.argv[0]).name
        subprocess.Popen([str(new_exe)] + sys.argv[1:],
                         cwd=str(new_dir))
        sys.exit(0)
    except Exception:
        pass  # if rename fails, continue anyway — don't block the user


def main():
    _fix_path_spaces()
    _setup_logging()
    log.info(f"Starting {APP_NAME} v{VERSION}")

    try:
        app = BroadcastApp()

        # Ctrl+Z undo
        app.bind("<Control-z>", lambda e: app.undo_last())
        # Ctrl+, settings
        app.bind("<Control-comma>",
                 lambda e: app.open_settings())
        # Ctrl+Shift+Z mini mode (keyboard fallback)
        app.bind("<Control-Shift-Z>",
                 lambda e: app.toggle_mini_mode())

        app.mainloop()
    except Exception as e:
        log.critical(f"Fatal error: {e}", exc_info=True)
        try:
            messagebox.showerror(
                "Fatal Error",
                f"{APP_NAME} encountered a fatal error:\n\n{e}\n\n"
                f"Check logs at:\n{LOG_DIR}")
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
