"""
ui_soundboard.py — Broadcast Backpack v6.0.0
SoundboardFrame  : pinned row + bank tabs + button grid
SoundButton      : individual playback button
Dynamic sizing   : buttons fill their grid — zero dead space
"""

import os, time, tkinter as tk, logging, copy
import customtkinter as ctk
from tkinter import filedialog, messagebox
from pathlib import Path

from config import C, lighten
from audio  import AudioManager, CH_QUEUE

log = logging.getLogger("broadcast.soundboard")

try:
    from tkinterdnd2 import DND_FILES
    HAS_DND = True
except ImportError:
    HAS_DND = False

_SLOT_CLIPBOARD = None   # module-level cut/copy buffer


# ═══════════════════════════════════════════════════════════════
# SOUND BUTTON
# ═══════════════════════════════════════════════════════════════

class SoundButton(tk.Frame):
    """
    A single soundboard button.
    Uses tk.Frame + tk.Button so it can stretch to fill grid cells.
    """

    def __init__(self, parent, cfg, audio: AudioManager,
                 slot_source: str, idx: int,
                 session_log=None, on_update=None):
        super().__init__(parent, bg=C["bg"], bd=0, highlightthickness=0)
        self.cfg          = cfg
        self.audio        = audio
        self.slot_source  = slot_source
        self.idx          = idx
        self.session_log  = session_log
        self.on_update    = on_update or (lambda: None)
        self._playing     = False
        self._blink_job   = None
        self._blink_state = False
        self._build()

    def _playing_color(self) -> str:
        custom = self.cfg.config.get("playing_btn_color", "")
        if custom:
            return custom
        slot  = self._slot()
        color = slot.get("color", "") or C["neutral"]
        return lighten(color, 1.35)

    def _build(self):
        slot  = self._slot()
        color = slot.get("color", "") or C["neutral"]
        tc    = slot.get("text_color", "") or C["text_hi"]
        label = slot.get("label", f"Sound {self.idx+1}")
        font_size = self.cfg.config.get("font_size", 11)

        self._btn = tk.Button(
            self,
            text=label,
            bg=color,
            fg=tc,
            activebackground=lighten(color, 1.25),
            activeforeground=tc,
            relief="flat",
            bd=0,
            cursor="hand2",
            font=("Segoe UI", font_size),
            wraplength=95,
            command=self._play,
            anchor="center",
        )
        self._btn.pack(fill="both", expand=True, padx=1, pady=1)
        self._btn.bind("<Button-3>", self._ctx)
        self.bind("<Button-3>", self._ctx)

    def _slot(self) -> dict:
        return self.cfg.config[self.slot_source][self.idx]

    def refresh(self):
        slot  = self._slot()
        color = slot.get("color", "") or C["neutral"]
        tc    = slot.get("text_color", "") or C["text_hi"]
        label = slot.get("label", f"Sound {self.idx+1}")
        playing_col = self._playing_color()
        self._btn.configure(
            text=label,
            bg=playing_col if self._playing else color,
            fg=tc,
            activebackground=lighten(color, 1.25))

    def _set_playing(self, state: bool):
        self._playing = state
        if state and self.cfg.config.get("playing_btn_blink", False):
            self._start_blink()
        else:
            self._stop_blink()
            self.refresh()

    def _start_blink(self):
        self._stop_blink()
        rates = {"slow": 800, "medium": 450, "fast": 220}
        ms = rates.get(
            self.cfg.config.get("playing_btn_blink_rate", "medium"), 450)
        self._blink_cycle(ms)

    def _blink_cycle(self, ms: int):
        if not self._playing:
            return
        slot  = self._slot()
        color = slot.get("color", "") or C["neutral"]
        self._blink_state = not self._blink_state
        self._btn.configure(
            bg=self._playing_color() if self._blink_state else color)
        self._blink_job = self.after(ms, lambda: self._blink_cycle(ms))

    def _stop_blink(self):
        if self._blink_job:
            try: self.after_cancel(self._blink_job)
            except Exception: pass
            self._blink_job = None
        self._blink_state = False

    # ── Playback ──────────────────────────────────────────────────

    def _play(self):
        slot = self._slot()
        path = slot.get("file", "")
        if not path:
            return

        if not os.path.exists(path):
            messagebox.showerror("File Missing",
                                 f"File not found:\n{path}")
            return

        # Touch Play mode: always restart, never toggle-stop
        touch_mode = self.cfg.config.get("touch_play_mode", False)
        
        if self.audio.is_playing(self.idx):
            if touch_mode:
                # Stop and restart
                self.audio.stop(self.idx)
            else:
                # Normal toggle: stop
                self.audio.stop(self.idx)
                self._set_playing(False)
                return

        ok = self.audio.prepare(
            self.idx, path, slot.get("fx", {}))
        if ok:
            # Apply per-button volume (0.0 to 1.0, default 1.0)
            vol = slot.get("volume", 1.0)
            self.audio.play(
                self.idx,
                loop=slot.get("loop", False),
                overlap=slot.get("overlap", False),
                volume=vol)
            self._set_playing(True)
            dur = self.audio.get_sound_duration(path)
            self.audio.notify_play(
                self.idx, slot["label"],
                self.slot_source, path, dur)
            if self.session_log:
                try:
                    self.session_log.log_sound(
                        slot["label"], path, dur, from_queue=False)
                except Exception:
                    pass
            # Auto-clear playing state after duration
            if not slot.get("loop") and dur > 0:
                self.after(int(dur * 1000) + 200,
                           lambda: self._set_playing(False))

    def _set_playing(self, state: bool):
        self._playing = state
        self.refresh()

    # ── Context menu ──────────────────────────────────────────────

    def _ctx(self, e):
        global _SLOT_CLIPBOARD
        locked = self.cfg.config.get("soundboard_locked", False)
        m = tk.Menu(self, tearoff=0,
                    bg=C["surface"], fg=C["text"],
                    activebackground=C["blue_mid"],
                    activeforeground=C["text_hi"],
                    font=("Segoe UI", 11))

        m.add_command(label="▶  Play / Stop", command=self._play)
        m.add_command(label="⏮  Fade Stop",   command=self._fade)
        m.add_command(label="➕  Add to Queue",command=self._queue_add)
        m.add_separator()

        if not locked:
            m.add_command(label="📂  Assign File",
                          command=self._assign)
            m.add_command(label="🎨  Customize Button...",
                          command=self._customize)
            m.add_command(label="🎛  FX Editor",
                          command=self._fx_editor)
            slot = self._slot()
            m.add_command(
                label=("☑  Loop: ON"
                       if slot.get("loop") else "☐  Loop: OFF"),
                command=self._toggle_loop)
            m.add_command(
                label=("☑  Overlap: ON"
                       if slot.get("overlap") else "☐  Overlap: OFF"),
                command=self._toggle_overlap)
            
            # Volume submenu
            vol_menu = tk.Menu(m, tearoff=0,
                               bg=C["surface"], fg=C["text"],
                               activebackground=C["blue_mid"],
                               font=("Segoe UI", 11))
            cur_vol = slot.get("volume", 1.0)
            for pct in [100, 75, 50, 25, 10]:
                vol_val = pct / 100.0
                prefix = "● " if abs(cur_vol - vol_val) < 0.05 else "   "
                vol_menu.add_command(
                    label=f"{prefix}{pct}%",
                    command=lambda v=vol_val: self._set_volume(v))
            m.add_cascade(label=f"🔊  Volume ({int(cur_vol*100)}%)", menu=vol_menu)
            
            m.add_separator()
            m.add_command(label="✂  Cut",   command=self._cut)
            m.add_command(label="⎘  Copy",  command=self._copy)
            m.add_command(label="📋  Paste",
                          command=self._paste,
                          state="normal" if _SLOT_CLIPBOARD else "disabled")
            m.add_separator()
            m.add_command(label="🗑  Clear Slot", command=self._clear)
        else:
            m.add_command(label="(Board locked)", state="disabled")

        m.tk_popup(e.x_root, e.y_root)

    # ── Slot operations ───────────────────────────────────────────

    def _assign(self):
        path = filedialog.askopenfilename(
            title="Assign Audio File",
            filetypes=[("Audio", "*.mp3 *.wav *.ogg *.flac"),
                       ("All", "*.*")])
        if path:
            self._assign_file(path)

    def _assign_file(self, path: str):
        self._save_undo()
        s = self.cfg.config[self.slot_source][self.idx]
        s["file"]  = path
        s["label"] = Path(path).stem[:50]
        self.cfg.save()
        self.refresh()
        self.on_update()

    def _customize(self):
        from ui_dialogs import ButtonSettingsDialog
        slot = self._slot()
        dlg  = ButtonSettingsDialog(
            self.winfo_toplevel(),
            label=slot.get("label",""),
            color=slot.get("color",""),
            text_color=slot.get("text_color",""),
            allow_rename=True)
        self.winfo_toplevel().wait_window(dlg)
        if dlg.result:
            s = self.cfg.config[self.slot_source][self.idx]
            if dlg.result["label"]:
                s["label"] = dlg.result["label"]
            s["color"]      = dlg.result["color"]
            s["text_color"] = dlg.result["text_color"]
            self.cfg.save()
            self.refresh()

    def _fx_editor(self):
        from ui_dialogs import FXPanel
        FXPanel(self.winfo_toplevel(), self.slot_source,
                self.idx, self.cfg, self.audio,
                on_apply=self.refresh)

    def _fade(self):
        ms = int(self.cfg.config.get("fade_duration", 3.0) * 1000)
        self.audio.fade_stop(self.idx, ms)
        self._set_playing(False)

    def _queue_add(self):
        slot = self._slot()
        if slot.get("file"):
            try:
                root = self.winfo_toplevel()
                app  = getattr(root, "_app", None)
                if app and hasattr(app, "soundboard") and hasattr(app.soundboard, "queue"):
                    app.soundboard.queue.add_file(slot["file"])
            except Exception:
                pass

    def _toggle_loop(self):
        self.cfg.config[self.slot_source][self.idx]["loop"] ^= True
        self.cfg.save()
        self.refresh()

    def _toggle_overlap(self):
        self.cfg.config[self.slot_source][self.idx]["overlap"] ^= True
        self.cfg.save()
        self.refresh()

    def _set_volume(self, vol: float):
        """Set per-button volume (0.0 to 1.0)."""
        self.cfg.config[self.slot_source][self.idx]["volume"] = vol
        self.cfg.save()

    def _cut(self):
        global _SLOT_CLIPBOARD
        _SLOT_CLIPBOARD = copy.deepcopy(self._slot())
        self._clear()

    def _copy(self):
        global _SLOT_CLIPBOARD
        _SLOT_CLIPBOARD = copy.deepcopy(self._slot())

    def _paste(self):
        if _SLOT_CLIPBOARD:
            self._save_undo()
            self.cfg.config[self.slot_source][self.idx] = \
                copy.deepcopy(_SLOT_CLIPBOARD)
            self.cfg.save()
            self.refresh()

    def _clear(self):
        self._save_undo()
        from config import DEFAULT_FX
        self.cfg.config[self.slot_source][self.idx] = {
            "label": f"Sound {self.idx+1}", "file": "",
            "color": "", "text_color": "",
            "loop": False, "overlap": False, "hotkey": "",
            "fx": copy.deepcopy(DEFAULT_FX),
        }
        self.cfg.save()
        self.refresh()

    def _save_undo(self):
        try:
            root = self.winfo_toplevel()
            if hasattr(root, "_app"):
                root._app._undo_stack.append(
                    (self.slot_source, self.idx,
                     copy.deepcopy(self._slot())))
        except Exception:
            pass

    # ── DnD ───────────────────────────────────────────────────────

    def handle_drop(self, path: str):
        path = path.strip().strip("{}")
        if os.path.exists(path):
            self._assign_file(path)


# ═══════════════════════════════════════════════════════════════
# VERTICAL VU METER  — for fader column
# ═══════════════════════════════════════════════════════════════

class VerticalVUMeter(tk.Canvas):
    """Vertical VU meter with peak-hold, placed next to the DJ fader."""
    BARS          = 16
    BAR_W         = 10
    BAR_H         = 6
    GAP           = 2
    PEAK_HOLD_MS  = 400
    DECAY_STEP    = 0.12
    ATTACK_ALPHA  = 0.85

    def __init__(self, parent, audio):
        h = self.BARS * (self.BAR_H + self.GAP)
        super().__init__(parent, width=self.BAR_W, height=h,
                         bg=C["bg2"], highlightthickness=0)
        self.audio       = audio
        self._rects      = []
        self._peak_rect  = None
        self._peak_pos   = 0
        self._peak_timer = 0
        self._level      = 0.0
        self._build()
        self._tick()

    def _build(self):
        colors = ([C["green"]] * 10 + [C["amber"]] * 4 + [C["red"]] * 2)
        for i in range(self.BARS):
            y_bot = self.BARS * (self.BAR_H + self.GAP) - i * (self.BAR_H + self.GAP)
            y_top = y_bot - self.BAR_H
            r = self.create_rectangle(0, y_top, self.BAR_W, y_bot,
                                       fill=C["surface"], outline="")
            self._rects.append((r, colors[i], y_top, y_bot))
        self._peak_rect = self.create_rectangle(0, 0, 0, 0,
                                                 fill=C["amber"], outline="")

    def _tick(self):
        target = self.audio.get_vu_level()
        if target > self._level:
            self._level = self._level * (1 - self.ATTACK_ALPHA) + target * self.ATTACK_ALPHA
        else:
            self._level = max(0.0, self._level - self.DECAY_STEP)
        active = int(self._level * self.BARS)
        for i, (r, col, yt, yb) in enumerate(self._rects):
            self.itemconfig(r, fill=col if i < active else C["surface"])
        if active >= self._peak_pos:
            self._peak_pos   = active
            self._peak_timer = int(self.PEAK_HOLD_MS / 40)
        else:
            if self._peak_timer > 0:
                self._peak_timer -= 1
            else:
                self._peak_pos = max(0, self._peak_pos - 1)
        if self._peak_pos > 0 and self._peak_pos <= self.BARS:
            _, _, yt, yb = self._rects[self._peak_pos - 1]
            pk_col = C["red"] if self._peak_pos >= self.BARS - 1 else C["amber"]
            self.coords(self._peak_rect, 0, yt, self.BAR_W, yb)
            self.itemconfig(self._peak_rect, fill=pk_col)
        else:
            self.coords(self._peak_rect, 0, 0, 0, 0)
        self.after(40, self._tick)


# ═══════════════════════════════════════════════════════════════
# QUEUE PANEL
# ═══════════════════════════════════════════════════════════════

class QueuePanel(ctk.CTkFrame):
    SMART_PREV_SECS = 3
    POLL_MS         = 250

    def __init__(self, parent, cfg, audio, session_log=None):
        super().__init__(parent, fg_color=C["surface"],
                         corner_radius=8, width=215)
        self.cfg             = cfg
        self.audio           = audio
        self.session_log     = session_log
        self._queue          = []
        self._current_idx    = -1
        self._paused         = False
        self._playing        = False
        self._auto_advance   = False
        self._play_start     = 0.0
        self._current_dur    = 0.0      # Duration of current track
        self._crossfade_started = False # Prevent double-trigger
        self._poll_job       = None
        self._drag_data      = {"item": None, "y": 0, "over": None, "line": None}
        self.pack_propagate(False)
        self._build()
        self._start_poll()

    def _build(self):
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=6, pady=(8, 2))
        ctk.CTkLabel(hdr, text="🎶  QUEUE",
                     font=ctk.CTkFont("Segoe UI", 13, "bold"),
                     text_color=C["text"]).pack(side="left")
        self._auto_btn = ctk.CTkButton(
            hdr, text="Auto: OFF", width=72, height=24,
            corner_radius=4, fg_color=C["btn"],
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            command=self._toggle_auto)
        self._auto_btn.pack(side="right", padx=(0, 2))
        ctk.CTkButton(hdr, text="Clear", width=52, height=24,
                      corner_radius=4, fg_color=C["btn"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=self.clear).pack(side="right")

        transport = ctk.CTkFrame(self, fg_color=C["elevated"], corner_radius=6)
        transport.pack(fill="x", padx=6, pady=(2, 4))
        btn_kw = dict(height=30, corner_radius=4,
                      font=ctk.CTkFont("Segoe UI", 14),
                      fg_color="transparent", hover_color=C["btn_hover"])
        ctk.CTkButton(transport, text="⏮", width=34,
                      command=self._prev, **btn_kw).pack(side="left", padx=1, pady=3)
        self._play_pause_btn = ctk.CTkButton(
            transport, text="▶", width=38, command=self._play_pause,
            height=30, corner_radius=4,
            font=ctk.CTkFont("Segoe UI", 16, "bold"),
            fg_color=C["green"], hover_color=C["green_dim"])
        self._play_pause_btn.pack(side="left", padx=1, pady=3)
        ctk.CTkButton(transport, text="⏹", width=34,
                      command=self._stop, **btn_kw).pack(side="left", padx=1, pady=3)
        ctk.CTkButton(transport, text="⏭", width=34,
                      command=self._next, **btn_kw).pack(side="left", padx=1, pady=3)
        self._status_lbl = ctk.CTkLabel(
            transport, text="", font=ctk.CTkFont("Segoe UI", 11),
            text_color=C["text_dim"])
        self._status_lbl.pack(side="right", padx=4)

        self.list_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list_frame.pack(fill="both", expand=True, padx=4, pady=(0, 2))

        browse_row = ctk.CTkFrame(self, fg_color="transparent")
        browse_row.pack(fill="x", padx=4, pady=(0, 6))
        ctk.CTkButton(browse_row, text="📂 Browse & Add",
                      height=28, fg_color=C["blue"],
                      font=ctk.CTkFont("Segoe UI", 11, "bold"),
                      command=self._browse_add).pack(fill="x")
        self._refresh_list()

    # ── Public ───────────────────────────────────────────────────

    def add_file(self, path: str):
        path = path.strip().strip("{}")
        if path and os.path.exists(path) and                 Path(path).suffix.lower() in {".mp3", ".wav", ".ogg", ".flac"}:
            label = Path(path).stem[:50]
            self._queue.append(("_file_drop_", path, label))
            self._refresh_list()

    def handle_drop_files(self, paths):
        for p in paths:
            self.add_file(p)

    def add(self, slot_source, idx, label):
        self._queue.append((slot_source, idx, label))
        self._refresh_list()

    def clear(self):
        self._stop()
        self._queue.clear()
        self._current_idx = -1
        self._refresh_list()

    # ── Auto-advance ─────────────────────────────────────────────

    def _toggle_auto(self):
        self._auto_advance = not self._auto_advance
        if self._auto_advance:
            self._auto_btn.configure(text="Auto: ON",  fg_color=C["green"], text_color=C["bg"])
        else:
            self._auto_btn.configure(text="Auto: OFF", fg_color=C["btn"],   text_color=C["text"])

    # ── Transport ────────────────────────────────────────────────

    def _play_pause(self):
        import pygame
        ch = pygame.mixer.Channel(CH_QUEUE)
        if self._paused:
            ch.unpause()
            self._paused = False; self._playing = True
            self._update_transport_btn(); self._update_status("▶ Playing")
            self._refresh_list(); return
        if self._playing and ch.get_busy():
            ch.pause()
            self._paused = True; self._playing = False
            self._update_transport_btn(); self._update_status("⏸ Paused")
            self._refresh_list(); return
        if self._current_idx < 0 and self._queue:
            self._current_idx = 0
        if 0 <= self._current_idx < len(self._queue):
            self._play_track(self._current_idx)

    def _stop(self):
        import pygame
        try: pygame.mixer.Channel(CH_QUEUE).stop()
        except Exception: pass
        self._playing = False; self._paused = False
        self._update_transport_btn(); self._update_status("⏹ Stopped")
        self._refresh_list()

    def _next(self):
        if not self._queue: return
        nxt = self._current_idx + 1
        if nxt < len(self._queue):
            self._play_track(nxt)

    def _prev(self):
        if not self._queue: return
        elapsed = (time.monotonic() - self._play_start
                   if (self._playing or self._paused) else 0)
        if elapsed > self.SMART_PREV_SECS or self._current_idx <= 0:
            if 0 <= self._current_idx < len(self._queue):
                self._play_track(self._current_idx)
        else:
            self._play_track(self._current_idx - 1)

    # ── Playback engine ──────────────────────────────────────────

    def _play_track(self, queue_idx):
        import pygame
        if queue_idx < 0 or queue_idx >= len(self._queue):
            return
        try: pygame.mixer.Channel(CH_QUEUE).stop()
        except Exception: pass

        self._current_idx = queue_idx
        self._paused      = False
        self._crossfade_started = False  # Reset for new track
        slot_source, idx, label = self._queue[queue_idx]

        if slot_source == "_file_drop_":
            path = idx
            fx   = {}
        else:
            slot = self.cfg.config[slot_source][idx]
            path = slot.get("file", "")
            fx   = slot.get("fx", {})

        if not path or not os.path.exists(path):
            self._update_status("⚠ File missing")
            self._playing = False; self._update_transport_btn()
            self._refresh_list(); return

        try:
            ok = self.audio.prepare(CH_QUEUE, path, fx)
            if ok:
                self.audio.play(CH_QUEUE)
                dur = self.audio.get_sound_duration(path)
                self._current_dur = dur  # Store duration for automix
                self.audio.notify_play(CH_QUEUE, label, "Queue", path, dur)
                if self.session_log:
                    try: self.session_log.log_sound(
                             label, path, dur, from_queue=True)
                    except Exception: pass
                self._playing    = True
                self._play_start = time.monotonic()
                self._update_transport_btn()
                self._update_status(f"▶ {label[:12]}")
                self._refresh_list()
        except Exception as e:
            log.error(f"Queue play error: {e}")
            self._playing = False
            self._update_transport_btn()
            self._update_status("⚠ Error")

    # ── Browse ───────────────────────────────────────────────────

    def _browse_add(self):
        paths = filedialog.askopenfilenames(
            title="Add files to Queue",
            filetypes=[("Audio files", "*.mp3 *.wav *.ogg *.flac"),
                       ("All files", "*.*")])
        for p in paths:
            self.add_file(p)

    # ── Auto-advance poll ────────────────────────────────────────

    def _start_poll(self):
        self._poll_tick()

    def _poll_tick(self):
        try:
            if self._playing and not self._paused:
                import pygame
                ch = pygame.mixer.Channel(CH_QUEUE)
                
                # Check for automix crossfade
                if self._auto_advance and not self._crossfade_started:
                    automix = self.cfg.config.get("automix_enabled", False)
                    crossfade_sec = self.cfg.config.get("automix_crossfade_sec", 3)
                    
                    if automix and self._current_dur > 0:
                        elapsed = time.monotonic() - self._play_start
                        remaining = self._current_dur - elapsed
                        
                        # Start crossfade when we're within crossfade_sec of the end
                        if 0 < remaining <= crossfade_sec:
                            nxt = self._current_idx + 1
                            if nxt < len(self._queue):
                                self._crossfade_started = True
                                # Fade out current track
                                fade_ms = int(crossfade_sec * 1000)
                                ch.fadeout(fade_ms)
                                self._update_status(f"↝ Crossfade...")
                
                # Check if track ended
                if not ch.get_busy():
                    self._playing = False
                    if self._auto_advance:
                        nxt = self._current_idx + 1
                        if nxt < len(self._queue):
                            self._play_track(nxt)
                        else:
                            self._update_transport_btn()
                            self._update_status("⏹ End of queue")
                            self._refresh_list()
                    else:
                        self._update_transport_btn()
                        self._update_status("⏹ Track ended")
                        self._refresh_list()
        except Exception:
            pass
        self._poll_job = self.after(self.POLL_MS, self._poll_tick)

    # ── UI helpers ───────────────────────────────────────────────

    def _update_transport_btn(self):
        if self._playing:
            self._play_pause_btn.configure(text="⏸", fg_color=C["amber"],
                                            hover_color=C["amber_hi"])
        elif self._paused:
            self._play_pause_btn.configure(text="▶", fg_color=C["blue_mid"],
                                            hover_color=C["blue"])
        else:
            self._play_pause_btn.configure(text="▶", fg_color=C["green"],
                                            hover_color=C["green_dim"])

    def _update_status(self, text):
        try: self._status_lbl.configure(text=text)
        except Exception: pass

    # ── List management ──────────────────────────────────────────

    def _move(self, i, direction):
        j = i + direction
        if 0 <= j < len(self._queue):
            self._queue[i], self._queue[j] = self._queue[j], self._queue[i]
            if self._current_idx == i:   self._current_idx = j
            elif self._current_idx == j: self._current_idx = i
            self._refresh_list()

    def _remove(self, i):
        if 0 <= i < len(self._queue):
            if i == self._current_idx:
                self._stop()
                self._current_idx = min(i, len(self._queue) - 2)
            elif i < self._current_idx:
                self._current_idx -= 1
            self._queue.pop(i)
            self._refresh_list()

    def _drag_row_start(self, event, i, row, row_widgets):
        """Highlight selected row immediately on press."""
        self._drag_data["item"] = i
        self._drag_data["y"]    = event.y_root
        self._drag_data["over"] = i
        self._drag_data["line"] = None
        # Highlight the grabbed row
        row.configure(fg_color=C["amber"])

    def _drag_motion_update(self, event, row_widgets):
        """Show insert line between rows; keep grabbed row amber."""
        if self._drag_data["item"] is None:
            return
        drag_i  = self._drag_data["item"]
        target  = self._find_insert_pos(event.y_root, row_widgets)
        if target == self._drag_data.get("over"):
            return
        self._drag_data["over"] = target

        # Reset all row colours (keep amber on dragged, blue on playing)
        for i, rw in enumerate(row_widgets):
            try:
                if i == drag_i:
                    rw.configure(fg_color=C["amber"])
                elif i == self._current_idx and (self._playing or self._paused):
                    rw.configure(fg_color=C["blue"])
                else:
                    rw.configure(fg_color=C["elevated"])
            except Exception:
                pass

        # Move / create the insert line
        line = self._drag_data.get("line")
        # Determine y position for the line
        try:
            frame = self.list_frame
            if target < len(row_widgets):
                ref = row_widgets[target]
                line_y = ref.winfo_y()
            else:
                ref = row_widgets[-1]
                line_y = ref.winfo_y() + ref.winfo_height() + 2
            if line is None:
                import tkinter as _tk
                line = _tk.Frame(frame, bg=C["amber_hi"], height=2)
                self._drag_data["line"] = line
            line.place(x=4, y=line_y, relwidth=1.0, width=-8, height=2)
            line.lift()
        except Exception:
            pass

    def _drag_row_release(self, event, row_widgets):
        """Perform the reorder on mouse release, clean up visuals."""
        # Remove insert line
        line = self._drag_data.get("line")
        if line:
            try: line.place_forget(); line.destroy()
            except Exception: pass
        self._drag_data["line"] = None

        if self._drag_data["item"] is None:
            self._refresh_list()
            return
        drag_i = self._drag_data["item"]
        self._drag_data["item"] = None
        self._drag_data["over"] = None
        target = self._find_insert_pos(event.y_root, row_widgets)
        if target == drag_i or target == drag_i + 1:
            self._refresh_list()
            return
        old_cur = self._current_idx
        item = self._queue.pop(drag_i)
        insert_at = target if target < drag_i else target - 1
        insert_at = max(0, min(insert_at, len(self._queue)))
        self._queue.insert(insert_at, item)
        if old_cur == drag_i:
            self._current_idx = insert_at
        elif drag_i < old_cur <= insert_at:
            self._current_idx = old_cur - 1
        elif insert_at <= old_cur < drag_i:
            self._current_idx = old_cur + 1
        self._refresh_list()

    def _find_insert_pos(self, y_root, row_widgets):
        for i, rw in enumerate(row_widgets):
            try:
                ry = rw.winfo_rooty()
                rh = rw.winfo_height()
                if y_root < ry + rh // 2:
                    return i
            except Exception:
                continue
        return len(self._queue)

    def _refresh_list(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        if not self._queue:
            ctk.CTkLabel(self.list_frame, text="Queue empty",
                         font=ctk.CTkFont("Segoe UI", 11),
                         text_color=C["text_dim"]).pack(pady=10)
            return
        row_widgets = []
        for i, (ss, idx, label) in enumerate(self._queue):
            is_cur    = (i == self._current_idx)
            row_color = C["blue"] if is_cur and (self._playing or self._paused)                         else C["elevated"]
            row = ctk.CTkFrame(self.list_frame, fg_color=row_color, corner_radius=5)
            row.pack(fill="x", pady=2, padx=2)
            row_widgets.append(row)

            # Drag handle
            drag_lbl = ctk.CTkLabel(row, text="⠿", width=16,
                                     font=ctk.CTkFont("Segoe UI", 12),
                                     text_color=C["text_dim"], cursor="hand2")
            drag_lbl.pack(side="left", padx=(4, 0), pady=5)
            drag_lbl.bind("<ButtonPress-1>",
                          lambda e, ii=i, r=row, rw=row_widgets:
                              self._drag_row_start(e, ii, r, rw))
            drag_lbl.bind("<B1-Motion>",
                          lambda e, rw=row_widgets: self._drag_motion_update(e, rw))
            drag_lbl.bind("<ButtonRelease-1>",
                          lambda e, rw=row_widgets: self._drag_row_release(e, rw))

            idx_text  = "▶" if is_cur and self._playing else                         "⏸" if is_cur and self._paused else str(i + 1)
            idx_color = C["text_hi"] if is_cur else C["text_dim"]
            ctk.CTkLabel(row, text=idx_text, width=18,
                         font=ctk.CTkFont("Courier New", 13, "bold"),
                         text_color=idx_color).pack(side="left", padx=(2,2), pady=5)

            lbl_color  = C["text_hi"] if is_cur else C["text"]
            lbl_widget = ctk.CTkLabel(
                row, text=label[:35],
                font=ctk.CTkFont("Segoe UI", 11, "bold" if is_cur else "normal"),
                text_color=lbl_color, anchor="w", cursor="hand2")
            lbl_widget.pack(side="left", fill="x", expand=True, pady=5)
            lbl_widget.bind("<Button-1>", lambda e, ii=i: self._play_track(ii))

            ctk.CTkButton(row, text="✕", width=22, height=20,
                          corner_radius=3, fg_color="transparent",
                          hover_color=C["red_dim"],
                          font=ctk.CTkFont("Segoe UI", 11),
                          command=lambda ii=i: self._remove(ii)).pack(
                              side="right", padx=3, pady=3)

    def destroy(self):
        if self._poll_job:
            try: self.after_cancel(self._poll_job)
            except Exception: pass
        super().destroy()



# ═══════════════════════════════════════════════════════════════
# SOUNDBOARD FRAME
# ═══════════════════════════════════════════════════════════════

class SoundboardFrame(ctk.CTkFrame):
    """
    Contains:
      - Pinned row at top (amber buttons)
      - Bank tab bar
      - Button grid (fills ALL available space — no dead space)

    Dynamic sizing: buttons use tk grid with weight=1 on all
    rows/cols so they automatically fill the cell as the frame resizes.
    """

    def __init__(self, parent, cfg, audio: AudioManager,
                 session_log=None):
        super().__init__(parent, fg_color=C["bg"], corner_radius=0)
        self.cfg         = cfg
        self.audio       = audio
        self.session_log = session_log

        self._current_bank   = 0
        self._pinned_btns:   list[SoundButton] = []
        self._board_btns:    list[SoundButton] = []
        self._resize_job     = None
        self._last_grid_size = (0, 0)   # (w, h) of grid area

        self._build()
        # Trigger initial fill after layout settles
        self.after(100, self._fit_buttons)

        # Bind to root window Configure for resize
        self.after(200, self._bind_root_resize)

    def _bind_root_resize(self):
        try:
            root = self.winfo_toplevel()
            root.bind("<Configure>", self._on_root_resize, add="+")
        except Exception:
            pass

    def _on_root_resize(self, event=None):
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(120, self._fit_buttons)

    # ── Build structure ───────────────────────────────────────────

    def _build(self):
        # ── Pinned row ────────────────────────────────────────────
        self._pinned_frame = tk.Frame(self, bg=C["bg"], height=52)
        self._pinned_frame.pack(fill="x", padx=2, pady=(2, 0))
        self._pinned_frame.pack_propagate(False)
        self._build_pinned()

        # ── Separator ─────────────────────────────────────────────
        tk.Frame(self, bg=C["border"], height=1).pack(
            fill="x", padx=0)

        # ── Search bar + BOARD volume ─────────────────────────────────
        search_frame = ctk.CTkFrame(self, fg_color=C["bg2"], height=32)
        search_frame.pack(fill="x")
        search_frame.pack_propagate(False)
        
        ctk.CTkLabel(search_frame, text="🔍",
                     font=ctk.CTkFont("Segoe UI", 12),
                     text_color=C["text_dim"]).pack(side="left", padx=(8, 2))
        
        self._search_entry = ctk.CTkEntry(
            search_frame, width=200, height=24,
            placeholder_text="Search sounds across all banks...",
            font=ctk.CTkFont("Segoe UI", 11))
        self._search_entry.pack(side="left", padx=4, pady=4)
        self._search_entry.bind("<KeyRelease>", self._on_search_key)
        
        self._search_clear_btn = ctk.CTkButton(
            search_frame, text="✕", width=24, height=24,
            corner_radius=4, fg_color=C["btn"],
            font=ctk.CTkFont("Segoe UI", 11),
            command=self._clear_search)
        self._search_clear_btn.pack(side="left", padx=2)
        
        self._search_results_lbl = ctk.CTkLabel(
            search_frame, text="",
            font=ctk.CTkFont("Segoe UI", 10),
            text_color=C["text_dim"])
        self._search_results_lbl.pack(side="left", padx=8)
        
        # BOARD volume slider (horizontal, right side of search bar)
        board_frame = ctk.CTkFrame(search_frame, fg_color="transparent")
        board_frame.pack(side="right", padx=(10, 8))
        
        self._board_fading = False
        self._board_fade_direction = "down"
        self._board_fade_job = None
        self._board_fade_btn = ctk.CTkButton(
            board_frame, text="↓", width=24, height=22,
            corner_radius=4, fg_color=C["btn"],
            font=ctk.CTkFont("Segoe UI", 11),
            command=self._toggle_board_fade)
        self._board_fade_btn.pack(side="right", padx=(4, 0))
        
        self._board_vol_lbl = ctk.CTkLabel(board_frame, text="100%",
                                           font=ctk.CTkFont("Segoe UI", 10),
                                           text_color=C["text_dim"], width=35)
        self._board_vol_lbl.pack(side="right", padx=2)
        
        self._board_slider = ctk.CTkSlider(
            board_frame, orientation="horizontal",
            from_=0.0, to=1.0, width=100, height=16,
            progress_color=C["amber"],
            button_color=C["amber"],
            button_hover_color=C["amber_hi"],
            command=self._on_board_slider)
        self._board_slider.set(self.cfg.config.get("board_volume", 1.0))
        self._board_slider.pack(side="right", padx=2)
        
        ctk.CTkLabel(board_frame, text="BOARD",
                     font=ctk.CTkFont("Segoe UI", 10, "bold"),
                     text_color=C["amber"]).pack(side="right", padx=(0, 4))
        
        self._search_active = False
        self._search_results = []  # List of (bank_idx, slot_idx, label) tuples

        # ── Bank tabs ─────────────────────────────────────────────
        self._tabs_frame = tk.Frame(self, bg=C["bg2"], height=32)
        self._tabs_frame.pack(fill="x")
        self._tabs_frame.pack_propagate(False)
        self._build_tabs()

        # ── Body: grid | fader | queue ───────────────────────────
        body = tk.Frame(self, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=2, pady=(0, 2))

        # Queue — far right
        self.queue = QueuePanel(body, self.cfg, self.audio,
                                session_log=self.session_log)
        self.queue.pack(side="right", fill="y")

        # QUEUE fader column — between grid and queue
        fader_col = ctk.CTkFrame(body, fg_color="transparent", width=72)
        fader_col.pack(side="right", fill="y", padx=(2, 2))
        fader_col.pack_propagate(False)

        ctk.CTkLabel(fader_col, text="QUEUE",
                     font=ctk.CTkFont("Segoe UI", 11, "bold"),
                     text_color=C["amber"], justify="center").pack(pady=(6, 0))
        self._queue_vol_lbl = ctk.CTkLabel(fader_col, text="100%",
                                       font=ctk.CTkFont("Segoe UI", 11),
                                       text_color=C["text_dim"])
        self._queue_vol_lbl.pack()

        fader_inner = ctk.CTkFrame(fader_col, fg_color="transparent")
        fader_inner.pack(fill="both", expand=True, padx=2, pady=2)

        self._queue_slider = ctk.CTkSlider(
            fader_inner, orientation="vertical",
            from_=0.0, to=1.0, width=24,
            progress_color=C["amber"],
            button_color=C["amber"],
            button_hover_color=C["amber_hi"],
            command=self._on_queue_slider)
        self._queue_slider.set(self.cfg.config.get("queue_volume", 1.0))
        self._queue_slider.pack(side="left", fill="y", expand=True, padx=(4, 2), pady=4)

        self._vu_meter = VerticalVUMeter(fader_inner, self.audio)
        self._vu_meter.pack(side="left", fill="y", padx=(0, 2), pady=4)

        ctk.CTkLabel(fader_col, text="0%",
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C["text_dim"]).pack(pady=(0, 2))

        # Queue fade button
        self._queue_fading = False
        self._queue_fade_direction = "down"
        self._queue_fade_job = None
        self._queue_fade_btn = ctk.CTkButton(
            fader_col, text=self._queue_fade_btn_label(),
            width=60, height=22, corner_radius=4, fg_color=C["btn"],
            font=ctk.CTkFont("Segoe UI", 11),
            command=self._toggle_queue_fade)
        self._queue_fade_btn.pack(pady=(0, 6))

        # Grid container — left, fills remaining
        self._grid_outer = tk.Frame(body, bg=C["bg"])
        self._grid_outer.pack(fill="both", expand=True)

        # Lock indicator strip
        self._lock_lbl = tk.Label(
            self._grid_outer,
            text="🔒  Board Locked — right-click a button to unlock",
            bg=C["red_dim"], fg=C["text_hi"],
            font=("Segoe UI", 11))
        # Only shown when locked

        # The actual grid frame — buttons live here
        self._grid_frame = tk.Frame(self._grid_outer, bg=C["bg"])
        self._grid_frame.pack(fill="both", expand=True)
        self._build_bank_grid(self._current_bank)

    # ── BOARD volume + fade ──────────────────────────────────────────

    def _toggle_board_fade(self):
        """Fade board volume up/down over time."""
        dur = float(self.cfg.config.get("fade_duration", 3.0))
        if self._board_fading:
            self._board_fading = False
            if self._board_fade_job:
                try: self.after_cancel(self._board_fade_job)
                except Exception: pass
                self._board_fade_job = None
            target = 1.0 if self._board_fade_direction == "down" else 0.0
            self._board_fade_direction = "up" if target == 1.0 else "down"
            if dur > 0:
                self._board_fading = True
                label = "↑" if target == 1.0 else "✕"
                color = C["green"] if target == 1.0 else C["red_dim"]
                self._board_fade_btn.configure(text=label, fg_color=color)
                steps = max(20, int(dur * 25))
                step_ms = int(dur * 1000 / steps)
                self._run_board_fade_step(float(self._board_slider.get()), target, steps, step_ms, 0)
            else:
                self._set_board_vol(target)
                self._board_fade_btn.configure(text="↓", fg_color=C["btn"])
        else:
            cur = float(self._board_slider.get())
            target = 0.0 if cur > 0.1 else 1.0
            self._board_fade_direction = "down" if target == 0.0 else "up"
            if dur > 0:
                self._board_fading = True
                label = "↑" if target == 1.0 else "↓"
                color = C["green"] if target == 1.0 else C["red_dim"]
                self._board_fade_btn.configure(text=label, fg_color=color)
                steps = max(20, int(dur * 25))
                step_ms = int(dur * 1000 / steps)
                self._run_board_fade_step(cur, target, steps, step_ms, 0)
            else:
                self._set_board_vol(target)

    def _run_board_fade_step(self, start, end, steps, step_ms, i):
        if not self._board_fading:
            return
        val = start + (end - start) * (i / steps)
        self._set_board_vol(val)
        if i < steps:
            self._board_fade_job = self.after(step_ms,
                lambda: self._run_board_fade_step(start, end, steps, step_ms, i + 1))
        else:
            self._board_fading = False
            self._board_fade_btn.configure(text="↓", fg_color=C["btn"])
            self._board_fade_direction = "down"

    def _set_board_vol(self, val):
        val = max(0.0, min(1.0, val))
        self._board_slider.set(val)
        self.audio.set_board_volume(val)
        self.cfg.config["board_volume"] = val
        try: self._board_vol_lbl.configure(text=f"{int(val * 100)}%")
        except Exception: pass

    def _on_board_slider(self, val):
        if self._board_fading:
            self._board_fading = False
            if self._board_fade_job:
                try: self.after_cancel(self._board_fade_job)
                except Exception: pass
                self._board_fade_job = None
        self._set_board_vol(float(val))

    # ── QUEUE volume + fade ──────────────────────────────────────────

    def _queue_fade_btn_label(self):
        dur = self.cfg.config.get("fade_duration", 3.0)
        return f"↓ {int(dur)}s" if dur else "↓ Fade"

    def _toggle_queue_fade(self):
        """Fade queue volume up/down over time."""
        dur = float(self.cfg.config.get("fade_duration", 3.0))
        if self._queue_fading:
            self._queue_fading = False
            if self._queue_fade_job:
                try: self.after_cancel(self._queue_fade_job)
                except Exception: pass
                self._queue_fade_job = None
            target = 1.0 if self._queue_fade_direction == "down" else 0.0
            self._queue_fade_direction = "up" if target == 1.0 else "down"
            if dur > 0:
                self._queue_fading = True
                label = "↑ Fading…" if target == 1.0 else "✕ Cancel"
                color = C["green"] if target == 1.0 else C["red_dim"]
                self._queue_fade_btn.configure(text=label, fg_color=color)
                steps = max(20, int(dur * 25))
                step_ms = int(dur * 1000 / steps)
                self._run_queue_fade_step(float(self._queue_slider.get()), target, steps, step_ms, 0)
            else:
                self._set_queue_vol(target)
                self._queue_fade_btn.configure(text=self._queue_fade_btn_label(), fg_color=C["btn"])
        else:
            cur = float(self._queue_slider.get())
            target = 0.0 if cur > 0.1 else 1.0
            self._queue_fade_direction = "down" if target == 0.0 else "up"
            if dur > 0:
                self._queue_fading = True
                label = "↑ Fading…" if target == 1.0 else "↓ Fading…"
                color = C["green"] if target == 1.0 else C["red_dim"]
                self._queue_fade_btn.configure(text=label, fg_color=color)
                steps = max(20, int(dur * 25))
                step_ms = int(dur * 1000 / steps)
                self._run_queue_fade_step(cur, target, steps, step_ms, 0)
            else:
                self._set_queue_vol(target)

    def _run_queue_fade_step(self, start, end, steps, step_ms, i):
        if not self._queue_fading:
            return
        val = start + (end - start) * (i / steps)
        self._set_queue_vol(val)
        if i < steps:
            self._queue_fade_job = self.after(step_ms,
                lambda: self._run_queue_fade_step(start, end, steps, step_ms, i + 1))
        else:
            self._queue_fading = False
            self._queue_fade_btn.configure(text=self._queue_fade_btn_label(), fg_color=C["btn"])
            self._queue_fade_direction = "down"

    def _set_queue_vol(self, val):
        val = max(0.0, min(1.0, val))
        self._queue_slider.set(val)
        self.audio.set_queue_volume(val)
        self.cfg.config["queue_volume"] = val
        try: self._queue_vol_lbl.configure(text=f"{int(val * 100)}%")
        except Exception: pass

    def _on_queue_slider(self, val):
        if self._queue_fading:
            self._queue_fading = False
            if self._queue_fade_job:
                try: self.after_cancel(self._queue_fade_job)
                except Exception: pass
                self._queue_fade_job = None
        self._set_queue_vol(float(val))

    # ── Pinned row ────────────────────────────────────────────────

    def _build_pinned(self):
        for w in self._pinned_frame.winfo_children():
            w.destroy()
        self._pinned_btns.clear()

        count = self.cfg.config.get("pinned_count", 8)
        slots = self.cfg.config.get("pinned_slots", [])

        for i in range(min(count, len(slots))):
            slot  = slots[i]
            color = slot.get("color","") or C["pinned"]
            tc    = slot.get("text_color","") or C["amber_hi"]
            label = slot.get("label", f"Pin {i+1}")
            
            sb = SoundButton(
                self._pinned_frame, self.cfg, self.audio,
                "pinned_slots", i, self.session_log,
                on_update=self._on_slot_update)
            # Override colour for pinned
            sb._btn.configure(bg=color, fg=tc,
                               activebackground=lighten(color, 1.2))
            self._pinned_btns.append(sb)

        self._repack_pinned()

    def _repack_pinned(self):
        count = len(self._pinned_btns)
        if count == 0:
            return
        for i, sb in enumerate(self._pinned_btns):
            sb.place_forget()
            sb.pack_forget()
        self._pinned_frame.update_idletasks()
        w = self._pinned_frame.winfo_width()
        if w < 10:
            self.after(50, self._repack_pinned)
            return
        btn_w = max(40, w // count - 2)
        for i, sb in enumerate(self._pinned_btns):
            sb.place(x=i*(btn_w+2), y=1,
                     width=btn_w, height=48)

    # ── Sound search ─────────────────────────────────────────────

    def _on_search_key(self, event=None):
        """Called on every keypress in search box."""
        query = self._search_entry.get().strip().lower()
        if not query:
            self._clear_search()
            return
        
        self._search_active = True
        self._search_results.clear()
        
        # Slots are in flat "soundboard" list, groups define layout
        slots = self.cfg.config.get("soundboard", [])
        groups = self.cfg.config.get("soundboard_groups", [])
        
        for bank_idx, group in enumerate(groups):
            start, count = self.cfg.bank_range(bank_idx)
            for i in range(count):
                slot_idx = start + i
                if slot_idx >= len(slots):
                    break
                slot = slots[slot_idx]
                label = slot.get("label", "").lower()
                path = slot.get("path", "").lower()
                # Match if query is in label OR in filename part of path
                if label and (query in label or query in path):
                    self._search_results.append((bank_idx, slot_idx, slot.get("label", "")))
        
        count = len(self._search_results)
        if count == 0:
            self._search_results_lbl.configure(text="No matches", text_color=C["red_dim"])
        else:
            self._search_results_lbl.configure(text=f"{count} found", text_color=C["green"])
        
        # Rebuild grid with search results
        self._build_search_grid()

    def _clear_search(self):
        """Clear search and return to normal bank view."""
        self._search_entry.delete(0, "end")
        self._search_active = False
        self._search_results.clear()
        self._search_results_lbl.configure(text="")
        self._build_bank_grid(self._current_bank)

    def _build_search_grid(self):
        """Build grid showing search results from all banks."""
        for w in self._grid_frame.winfo_children():
            w.destroy()
        self._board_btns.clear()
        
        if not self._search_results:
            lbl = tk.Label(self._grid_frame, text="No matching sounds",
                           bg=C["bg"], fg=C["text_dim"],
                           font=("Segoe UI", 12))
            lbl.place(relx=0.5, rely=0.5, anchor="center")
            return
        
        # Calculate grid dimensions
        cols = 8
        rows = (len(self._search_results) + cols - 1) // cols
        
        for col in range(cols):
            self._grid_frame.columnconfigure(col, weight=1, uniform="sb")
        for row in range(rows):
            self._grid_frame.rowconfigure(row, weight=1, uniform="sb")
        
        slots = self.cfg.config.get("soundboard", [])
        groups = self.cfg.config.get("soundboard_groups", [])
        
        for i, (bank_idx, slot_idx, label) in enumerate(self._search_results):
            r, c = divmod(i, cols)
            slot_data = slots[slot_idx] if slot_idx < len(slots) else {}
            
            sb = SoundButton(
                self._grid_frame,
                cfg=self.cfg,
                audio=self.audio,
                slot_source="soundboard",
                idx=slot_idx,
                session_log=self.session_log,
                on_update=self._on_slot_update)
            sb.grid(row=r, column=c, sticky="nsew", padx=1, pady=1)
            self._board_btns.append(sb)

    # ── Bank tabs ─────────────────────────────────────────────────

    def _build_tabs(self):
        for w in self._tabs_frame.winfo_children():
            w.destroy()

        groups = self.cfg.config.get("soundboard_groups", [])

        # Left: bank buttons
        left = tk.Frame(self._tabs_frame, bg=C["bg2"])
        left.pack(side="left", fill="y")

        for i, g in enumerate(groups):
            is_cur    = (i == self._current_bank)
            stored_bg = g.get("color", "") or ""
            stored_fg = g.get("text_color", "") or ""

            hi_border = self.cfg.config.get(
                "bank_tab_highlight_color", C["blue_mid"])
            hi_bg     = self.cfg.config.get(
                "bank_tab_highlight_bg", "") or C["blue_mid"]

            bg = hi_bg if is_cur else (stored_bg or C["btn"])
            fg = C["text_hi"] if is_cur else (stored_fg or C["text_dim"])

            # Wrap in a border frame for reliable highlight
            if is_cur:
                border_f = tk.Frame(left, bg=hi_border, bd=0)
                border_f.pack(side="left", padx=1, fill="y")
                btn_parent = tk.Frame(border_f, bg=hi_border)
                btn_parent.pack(fill="both",
                                padx=2, pady=2)  # 2px border all around
            else:
                btn_parent = left

            b = tk.Button(
                btn_parent, text=g["name"],
                bg=bg, fg=fg,
                activebackground=hi_bg,
                activeforeground=C["text_hi"],
                relief="flat", bd=0, padx=12,
                font=("Segoe UI", 11, "bold" if is_cur else "normal"),
                cursor="hand2",
                command=lambda idx=i: self.switch_bank(idx))
            b.pack(side="left" if not is_cur else "left",
                   fill="y" if not is_cur else "both",
                   padx=0 if is_cur else 1)
            b.bind("<Button-3>",
                   lambda e, idx=i: self._tab_ctx(e, idx))

        # Right: + Add Bank + lock toggle
        right = tk.Frame(self._tabs_frame, bg=C["bg2"])
        right.pack(side="right", fill="y")

        locked = self.cfg.config.get("soundboard_locked", False)
        self._lock_btn = tk.Button(
            right,
            text="🔒 Locked" if locked else "🔓 Edit",
            bg=C["red_dim"] if locked else C["btn"],
            fg=C["text"],
            activebackground=C["btn_hover"],
            relief="flat", bd=0, padx=10,
            font=("Segoe UI", 11),
            cursor="hand2",
            command=self._toggle_lock)
        self._lock_btn.pack(side="right", fill="y", padx=2)

        tk.Button(
            right, text="+ Bank",
            bg=C["btn"], fg=C["text_dim"],
            activebackground=C["blue_mid"],
            activeforeground=C["text_hi"],
            relief="flat", bd=0, padx=8,
            font=("Segoe UI", 11),
            cursor="hand2",
            command=self._add_bank_quick
        ).pack(side="right", fill="y", padx=1)

    def _tab_ctx(self, e, bank_idx):
        from ui_dialogs import ColorPickerDialog
        m = tk.Menu(self, tearoff=0,
                    bg=C["surface"], fg=C["text"],
                    activebackground=C["blue_mid"],
                    font=("Segoe UI", 11))
        m.add_command(label="✏️  Rename Bank",
                      command=lambda: self._rename_bank(bank_idx))
        m.add_separator()
        m.add_command(label="📋  Export Bank",
                      command=lambda: self._export_bank(bank_idx))
        m.add_command(label="📂  Import Bank",
                      command=lambda: self._import_bank(bank_idx))
        m.add_separator()
        m.add_command(
            label="🎨  Customize Tab...",
            command=lambda: self._customize_tab(bank_idx))
        m.add_command(label="↩  Reset Colours",
                      command=lambda: self._reset_tab_colors(bank_idx))
        m.tk_popup(e.x_root, e.y_root)

    def _rename_bank(self, bank_idx):
        groups = self.cfg.config.get("soundboard_groups", [])
        if bank_idx >= len(groups):
            return
        dlg = tk.Toplevel(self)
        dlg.title("Rename Bank")
        dlg.configure(bg=C["bg2"])
        dlg.resizable(False, False)
        dlg.grab_set()
        tk.Label(dlg, text="Bank name:", bg=C["bg2"],
                 fg=C["text"], font=("Segoe UI", 11)
                 ).pack(side="left", padx=(10, 4), pady=10)
        name_e = tk.Entry(dlg, bg=C["surface"], fg=C["text"],
                          insertbackground=C["text"],
                          relief="flat", font=("Segoe UI", 11),
                          width=18)
        name_e.insert(0, groups[bank_idx].get("name", ""))
        name_e.select_range(0, "end")
        name_e.pack(side="left", pady=10)
        def _ok():
            name = name_e.get().strip()
            if name:
                groups[bank_idx]["name"] = name
                self.cfg.save()
                self._build_tabs()
            dlg.destroy()
        tk.Button(dlg, text="OK", bg=C["blue_mid"],
                  fg=C["text_hi"], relief="flat",
                  padx=10, pady=4,
                  font=("Segoe UI", 11, "bold"),
                  command=_ok).pack(side="left", padx=6, pady=10)
        name_e.bind("<Return>", lambda e: _ok())
        name_e.focus_set()

    def _customize_tab(self, bank_idx):
        """Open ButtonSettingsDialog to set tab bg + text color."""
        from ui_dialogs import ButtonSettingsDialog
        groups = self.cfg.config.get("soundboard_groups", [])
        if bank_idx >= len(groups):
            return
        g = groups[bank_idx]
        dlg = ButtonSettingsDialog(
            self.winfo_toplevel(),
            label=g.get("name", ""),
            color=g.get("color", ""),
            text_color=g.get("text_color", ""),
            allow_rename=True)
        self.winfo_toplevel().wait_window(dlg)
        if dlg.result:
            if dlg.result["label"]:
                g["name"]       = dlg.result["label"]
            g["color"]          = dlg.result["color"]
            g["text_color"]     = dlg.result["text_color"]
            self.cfg.save()
            self._build_tabs()

    def _reset_tab_colors(self, bank_idx):
        groups = self.cfg.config.get("soundboard_groups", [])
        if bank_idx < len(groups):
            groups[bank_idx]["color"]      = ""
            groups[bank_idx]["text_color"]  = ""
            self.cfg.save()
            self._build_tabs()

    def _set_bank_color(self, bank_idx, color):
        self.cfg.config["soundboard_groups"][bank_idx]["color"] = color
        self.cfg.save()
        self._build_tabs()

    def _export_bank(self, idx):
        from tkinter import filedialog
        import json
        path = filedialog.asksaveasfilename(
            title="Export Bank",
            defaultextension=".json",
            filetypes=[("JSON","*.json")])
        if path:
            import json
            with open(path, "w") as f:
                json.dump(self.cfg.export_bank(idx), f, indent=2)

    def _import_bank(self, idx):
        import json
        path = filedialog.askopenfilename(
            title="Import Bank",
            filetypes=[("JSON","*.json")])
        if path:
            with open(path) as f:
                self.cfg.import_bank(idx, json.load(f))
            self.cfg.save()
            self._build_bank_grid(self._current_bank)

    def _add_bank_quick(self):
        """Add a new bank on the fly without opening Settings."""
        groups = self.cfg.config.setdefault("soundboard_groups", [])
        n = len(groups) + 1
        # Ask for a name via a quick dialog
        dlg = tk.Toplevel(self)
        dlg.title("Add Bank")
        dlg.configure(bg=C["bg2"])
        dlg.resizable(False, False)
        dlg.grab_set()
        tk.Label(dlg, text="Bank name:", bg=C["bg2"],
                 fg=C["text"], font=("Segoe UI", 11)
                 ).pack(side="left", padx=(10,4), pady=10)
        name_e = tk.Entry(dlg, bg=C["surface"], fg=C["text"],
                          insertbackground=C["text"],
                          relief="flat", font=("Segoe UI", 11),
                          width=18)
        name_e.insert(0, f"Bank {n}")
        name_e.pack(side="left", pady=10)
        name_e.select_range(0, "end")

        def _ok():
            name = name_e.get().strip() or f"Bank {n}"
            groups.append({"name": name, "rows": 2,
                           "cols": 8, "color": ""})
            # Initialise empty slots for this bank
            bank_idx = len(groups) - 1
            key = f"bank_{bank_idx}"
            self.cfg.config.setdefault(
                "soundboard_groups", [])
            self.cfg.save()
            dlg.destroy()
            self._build_tabs()
            self.switch_bank(bank_idx)

        tk.Button(dlg, text="Add", bg=C["blue_mid"],
                  fg=C["text_hi"], relief="flat",
                  padx=10, pady=4,
                  font=("Segoe UI", 11, "bold"),
                  command=_ok
                  ).pack(side="left", padx=6, pady=10)
        name_e.bind("<Return>", lambda e: _ok())
        name_e.focus_set()

    def _toggle_lock(self):
        locked = not self.cfg.config.get("soundboard_locked", False)
        self.cfg.config["soundboard_locked"] = locked
        self.cfg.save()
        self._build_tabs()
        if locked:
            self._lock_lbl.pack(fill="x")
        else:
            self._lock_lbl.pack_forget()

    def switch_bank(self, idx: int):
        self._current_bank = idx
        self._build_tabs()
        self._build_bank_grid(idx)
        self.after(80, self._fit_buttons)

    # ── Button grid ───────────────────────────────────────────────

    def _build_bank_grid(self, bank_idx: int):
        for w in self._grid_frame.winfo_children():
            w.destroy()
        self._board_btns.clear()

        groups = self.cfg.config.get("soundboard_groups", [])
        if not groups or bank_idx >= len(groups):
            return
        g    = groups[bank_idx]
        rows = g.get("rows", 2)
        cols = g.get("cols", 8)
        bank_color = g.get("color","")

        start, count = self.cfg.bank_range(bank_idx)
        slots        = self.cfg.config.get("soundboard", [])

        # Configure grid weights so cells expand
        for c in range(cols):
            self._grid_frame.grid_columnconfigure(c, weight=1)
        for r in range(rows):
            self._grid_frame.grid_rowconfigure(r, weight=1)

        for i in range(rows * cols):
            slot_idx = start + i
            # Extend the slot list if needed (handles legacy configs with fewer slots)
            while slot_idx >= len(slots):
                from config import _slot as _mk_slot
                slots.append(_mk_slot(len(slots)))
            if slot_idx >= 508:   # hard cap — reserved channels above this
                break
            r, c = divmod(i, cols)

            slot = slots[slot_idx]
            # Bank color overrides default neutral
            if bank_color and not slot.get("color"):
                orig_color = slot.get("color","")
                slot = dict(slot)
                slot["color"] = bank_color

            sb = SoundButton(
                self._grid_frame, self.cfg, self.audio,
                "soundboard", slot_idx,
                self.session_log,
                on_update=self._on_slot_update)
            sb.grid(row=r, column=c, sticky="nsew", padx=1, pady=1)
            self._board_btns.append(sb)

    def _fit_buttons(self):
        """
        Called after layout settles — forces grid cells to fill
        their space by recalculating available width/height.
        With weight=1 on all rows/cols this is automatic, but we
        call this to ensure propagation is correct.
        """
        try:
            self._grid_frame.update_idletasks()
            w = self._grid_frame.winfo_width()
            h = self._grid_frame.winfo_height()
            if (w, h) == self._last_grid_size or w < 20 or h < 20:
                return
            self._last_grid_size = (w, h)
            # Re-run pinned layout too since window may have resized
            self._repack_pinned()
        except Exception as e:
            log.debug(f"fit_buttons: {e}")

    def _on_slot_update(self):
        pass

    # ── Public API ────────────────────────────────────────────────

    def full_refresh(self):
        """Rebuild everything — called after Settings save."""
        self._build_pinned()
        self._build_tabs()
        self._build_bank_grid(self._current_bank)
        self.after(80, self._fit_buttons)

    def stop_all(self):
        self.audio.stop_all()
        for sb in self._pinned_btns + self._board_btns:
            sb._set_playing(False)

    # ── DnD routing (called from root handler) ────────────────────

    def route_drop(self, widget, path: str):
        """Root-level DnD router calls this."""
        for sb in self._pinned_btns + self._board_btns:
            if sb._btn is widget or sb is widget:
                sb.handle_drop(path)
                return
        # If drop landed on queue area, forward there
        try:
            w = widget
            while w:
                if w is self.queue:
                    self.queue.add_file(path)
                    return
                w = getattr(w, 'master', None)
        except Exception:
            pass
        # Fallback: add to queue
        self.queue.add_file(path)
