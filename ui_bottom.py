"""
ui_bottom.py — Broadcast Backpack v6.0.0
BottomStrip   : full-width bottom bar
QueuePanel    : drag-and-drop music queue with transport
NowPlayingBar : current track + progress + waveform VU
"""

import os, time, tkinter as tk, tkinterdnd2 as dnd, logging
import customtkinter as ctk
from tkinter import filedialog
from pathlib import Path

from config import C, lighten
from audio  import AudioManager, CH_QUEUE

log = logging.getLogger("broadcast.bottom")

try:
    from tkinterdnd2 import DND_FILES
    HAS_DND = True
except ImportError:
    HAS_DND = False


# ═══════════════════════════════════════════════════════════════
# HORIZONTAL VU  (now-playing bar)
# ═══════════════════════════════════════════════════════════════

class HorizontalVU(tk.Canvas):
    BARS    = 24
    H       = 6
    ATTACK  = 0.88
    DECAY   = 0.20
    TICK_MS = 25

    def __init__(self, parent, level_fn):
        super().__init__(parent, height=self.H,
                         bg=C["bg"], highlightthickness=0)
        self._fn    = level_fn
        self._level = 0.0
        self._rects = []
        self.bind("<Configure>", self._on_resize)
        self._tick()

    def _on_resize(self, e=None):
        self.delete("all")
        self._rects.clear()
        w = self.winfo_width()
        if w < 10:
            return
        bw = w / self.BARS
        colours = ([C["green"]] * int(self.BARS * 0.6)
                   + [C["amber"]] * int(self.BARS * 0.25)
                   + [C["red"]]  * (self.BARS - int(self.BARS * 0.85)))
        for i in range(self.BARS):
            x0 = int(i * bw) + 1
            x1 = int((i + 1) * bw) - 1
            r  = self.create_rectangle(
                x0, 0, x1, self.H,
                fill=C["surface"], outline="")
            self._rects.append((r, colours[i]))

    def _tick(self):
        try:
            target = float(self._fn())
        except Exception:
            target = 0.0
        if target > self._level:
            self._level = self._level * (1-self.ATTACK) + target * self.ATTACK
        else:
            self._level = max(0.0, self._level - self.DECAY)
        active = int(self._level * self.BARS)
        for i, (r, col) in enumerate(self._rects):
            self.itemconfig(r, fill=col if i < active else C["surface"])
        if self.winfo_exists():
            self.after(self.TICK_MS, self._tick)


# ═══════════════════════════════════════════════════════════════
# NOW PLAYING BAR
# ═══════════════════════════════════════════════════════════════

class NowPlayingBar(ctk.CTkFrame):
    """
    Right section of the bottom strip.
    Large prominent track name + timer. Readable from across the room.
    """

    def __init__(self, parent, audio: AudioManager, cfg=None):
        super().__init__(parent, fg_color=C["surface"], corner_radius=0)
        self.audio = audio
        self.cfg   = cfg
        self._flash_state = False
        self._build()
        self._tick()

    def _build(self):
        # Section header with Stop button
        hdr = tk.Frame(self, bg=C["elevated"])
        hdr.pack(fill="x")
        tk.Label(hdr, text="NOW PLAYING",
                 bg=C["elevated"], fg=C["text_dim"],
                 font=("Segoe UI", 11, "bold"),
                 padx=8, pady=3).pack(side="left")

        # Stop button in header
        self._stop_btn = tk.Button(
            hdr, text="■", bg=C["red"], fg=C["text_hi"],
            activebackground=C["red_dim"], activeforeground=C["text_hi"],
            relief="flat", bd=0, padx=8, pady=2,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
            command=self._stop_all)
        self._stop_btn.pack(side="right", padx=4, pady=2)

        self._bank_lbl = tk.Label(
            hdr, text="", bg=C["elevated"],
            fg=C["text_dim"], font=("Segoe UI", 11))
        self._bank_lbl.pack(side="right", padx=4)

        # Track name — large, full label (no truncation)
        self._np_lbl = tk.Label(
            self, text="—",
            bg=C["surface"], fg=C["text"],
            font=("Segoe UI", 13, "bold"),
            anchor="w", wraplength=260)
        self._np_lbl.pack(fill="x", padx=10, pady=(6, 0))

        # Timer — very large, elapsed white / remaining red-orange
        timer_f = tk.Frame(self, bg=C["surface"])
        timer_f.pack(fill="x", padx=10, pady=(2, 2))

        self._elapsed_lbl = tk.Label(
            timer_f, text="0:00",
            bg=C["surface"], fg=C["text"],
            font=("Courier New", 28, "bold"))
        self._elapsed_lbl.pack(side="left")

        tk.Label(timer_f, text=" / ",
                 bg=C["surface"], fg=C["text_dim"],
                 font=("Courier New", 20)).pack(side="left")

        self._remain_lbl = tk.Label(
            timer_f, text="-0:00",
            bg=C["surface"], fg="#ff4500",
            font=("Courier New", 28, "bold"))
        self._remain_lbl.pack(side="left")

        # Progress bar — thicker
        self._prog_outer = tk.Frame(self, bg=C["elevated"], height=8)
        self._prog_outer.pack(fill="x", padx=10, pady=(0, 4))
        self._prog_outer.pack_propagate(False)
        self._prog_inner = tk.Frame(
            self._prog_outer, bg=C["blue_mid"], height=8)
        self._prog_inner.place(x=0, y=0, width=0, relheight=1)

        # VU meter row (simple left/right bars)
        vu_f = tk.Frame(self, bg=C["surface"])
        vu_f.pack(fill="x", padx=10, pady=(0, 2))
        
        tk.Label(vu_f, text="L", bg=C["surface"], fg=C["text_dim"],
                 font=("Segoe UI", 8)).pack(side="left")
        self._vu_l_outer = tk.Frame(vu_f, bg=C["elevated"], height=6, width=100)
        self._vu_l_outer.pack(side="left", padx=2)
        self._vu_l_outer.pack_propagate(False)
        self._vu_l_inner = tk.Frame(self._vu_l_outer, bg=C["green"], height=6)
        self._vu_l_inner.place(x=0, y=0, width=0, relheight=1)
        
        tk.Label(vu_f, text="R", bg=C["surface"], fg=C["text_dim"],
                 font=("Segoe UI", 8)).pack(side="left", padx=(4, 0))
        self._vu_r_outer = tk.Frame(vu_f, bg=C["elevated"], height=6, width=100)
        self._vu_r_outer.pack(side="left", padx=2)
        self._vu_r_outer.pack_propagate(False)
        self._vu_r_inner = tk.Frame(self._vu_r_outer, bg=C["green"], height=6)
        self._vu_r_inner.place(x=0, y=0, width=0, relheight=1)

        # Date/time stamp
        self._dt_lbl = tk.Label(
            self, text="",
            bg=C["surface"], fg=C["text_dim"],
            font=("Segoe UI", 11))
        self._dt_lbl.pack(anchor="w", padx=10, pady=(0, 6))

    def _stop_all(self):
        """Stop all playing audio."""
        try:
            self.audio.stop_all()
        except Exception:
            pass

    def _tick(self):
        import time as _t
        from datetime import datetime as _dt
        import random
        try:
            np = self.audio.get_now_playing()
            if np:
                ch, info   = np
                label      = info.get("label", "")
                bank       = info.get("bank", "")
                start      = info.get("start", _t.monotonic())
                dur        = info.get("duration", 0.0)
                elapsed    = _t.monotonic() - start

                # Full label, no truncation
                self._np_lbl.configure(text=label if label else "—")
                self._bank_lbl.configure(text=bank)

                if dur > 0:
                    frac = min(1.0, elapsed / dur)
                    rem  = max(0.0, dur - elapsed)
                    e_s  = int(elapsed)
                    r_s  = int(rem)

                    # Read flash threshold from config
                    flash_secs = 30
                    if self.cfg:
                        try:
                            flash_secs = int(self.cfg.config.get(
                                "nowplaying_flash_secs", 30))
                        except Exception:
                            pass

                    if 0 < rem < flash_secs:
                        # Blink red — alternate visible/dim each tick
                        self._flash_state = not self._flash_state
                        timer_col = C["red"] if self._flash_state else C["text_dim"]
                    else:
                        self._flash_state = False
                        timer_col = C["text"]  # white when no urgency

                    self._elapsed_lbl.configure(
                        text=f"{e_s//60}:{e_s%60:02d}",
                        fg=timer_col)
                    self._remain_lbl.configure(
                        text=f"-{r_s//60}:{r_s%60:02d}",
                        fg=timer_col)
                    self._prog_outer.update_idletasks()
                    w = self._prog_outer.winfo_width()
                    self._prog_inner.place(
                        x=0, y=0, width=int(w * frac), relheight=1)
                    self._prog_inner.configure(
                        bg=C["amber"] if rem < 15 else C["blue_mid"])
                    
                    # Update VU meters (simulated based on playback)
                    # In future could hook into actual audio levels
                    vu_base = 0.4 + 0.4 * (1 - frac)  # Fade out as track ends
                    vu_l = min(1.0, vu_base + random.uniform(-0.15, 0.15))
                    vu_r = min(1.0, vu_base + random.uniform(-0.15, 0.15))
                    self._update_vu(vu_l, vu_r)
                else:
                    self._elapsed_lbl.configure(text="0:00")
                    self._remain_lbl.configure(text="-0:00")
                    self._prog_inner.place(x=0, y=0, width=0, relheight=1)
                    self._update_vu(0, 0)
            else:
                self._np_lbl.configure(text="—")
                self._bank_lbl.configure(text="")
                self._elapsed_lbl.configure(text="0:00")
                self._remain_lbl.configure(text="-0:00")
                self._prog_inner.place(x=0, y=0, width=0, relheight=1)
                self._update_vu(0, 0)

            # Always show live date/time
            self._dt_lbl.configure(
                text=_dt.now().strftime("%I:%M %p  %A, %m/%d/%Y"))
        except Exception:
            pass
        self.after(500, self._tick)

    def _update_vu(self, left: float, right: float):
        """Update VU meter bars (0.0 to 1.0)."""
        try:
            self._vu_l_outer.update_idletasks()
            self._vu_r_outer.update_idletasks()
            w = self._vu_l_outer.winfo_width()
            
            # Color based on level
            def vu_color(level):
                if level > 0.85:
                    return C["red"]
                elif level > 0.6:
                    return C["amber"]
                else:
                    return C["green"]
            
            self._vu_l_inner.configure(bg=vu_color(left))
            self._vu_r_inner.configure(bg=vu_color(right))
            self._vu_l_inner.place(x=0, y=0, width=int(w * left), relheight=1)
            self._vu_r_inner.place(x=0, y=0, width=int(w * right), relheight=1)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
# BOTTOM STRIP  — left of right panel only
# ═══════════════════════════════════════════════════════════════

class BottomStrip(ctk.CTkFrame):
    HEIGHT = 260

    def __init__(self, parent, cfg, audio: AudioManager,
                 session_log=None, get_elapsed=None, get_is_live=None):
        super().__init__(parent, fg_color=C["bg"],
                         corner_radius=0, height=self.HEIGHT)
        self.cfg         = cfg
        self.audio       = audio
        self.session_log = session_log
        self.get_elapsed = get_elapsed or (lambda: "")
        self.get_is_live = get_is_live or (lambda: False)
        self.pack_propagate(False)
        self._build()

    def _build(self):
        from ui_right_panel import NotesSection, SnippetsSection

        # Now Playing — fixed width right side, prominent
        self.now_playing = NowPlayingBar(self, self.audio, cfg=self.cfg)
        self.now_playing.configure(width=280)
        self.now_playing.pack(side="right", fill="y")
        tk.Frame(self, bg=C["border"], width=1).pack(side="right", fill="y")

        # Quick Copy — fixed width middle
        self.snippets = SnippetsSection(self, self.cfg)
        self.snippets.configure(width=160)
        self.snippets.pack(side="right", fill="y")
        tk.Frame(self, bg=C["border"], width=1).pack(side="right", fill="y")

        # Notes — fills remaining (narrower than before)
        self.notes = NotesSection(
            self, self.cfg,
            get_elapsed=self.get_elapsed,
            get_is_live=self.get_is_live,
            session_log=self.session_log)
        self.notes.pack(side="left", fill="both", expand=True)

    def refresh_theme(self):
        """Refresh bottom strip colors after theme change."""
        try:
            self.configure(fg_color=C["bg2"])
        except Exception:
            pass
