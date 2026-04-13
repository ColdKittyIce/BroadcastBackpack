"""
ui_header.py — Broadcast Backpack v6.0.0
HeaderFrame   : two-zone broadcast console header
MiniModeWindow: always-on-top compact strip
VU meters     : vertical (header) + horizontal (now-playing)
"""

import os, time, tkinter as tk, threading, logging
import customtkinter as ctk
from tkinter import filedialog, messagebox
from pathlib import Path

from config import C, VERSION, APP_NAME, lighten
from audio  import AudioManager, RecorderManager, CH_RECORDER, MicManager

log = logging.getLogger("broadcast.header")


# ═══════════════════════════════════════════════════════════════
# VERTICAL VU METER
# ═══════════════════════════════════════════════════════════════

class VerticalVU(tk.Canvas):
    """Snappy vertical VU — bars fill bottom to top."""
    BARS         = 18
    W            = 12
    H            = 90
    ATTACK       = 0.95
    DECAY        = 0.18
    PEAK_HOLD_MS = 500
    TICK_MS      = 22

    def __init__(self, parent, level_fn):
        super().__init__(parent, width=self.W, height=self.H,
                         bg=C["bg2"], highlightthickness=0)
        self._fn     = level_fn
        self._level  = 0.0
        self._peak   = 0
        self._ptimer = 0
        self._rects  = []
        self._prect  = None
        self._build()
        self._tick()

    def _build(self):
        bh = self.H // self.BARS - 1
        # top bars = red, mid = amber, low = green
        colours = ([C["red"]] * 2 + [C["amber_hi"]] * 3
                   + [C["green"]] * (self.BARS - 5))
        for i in range(self.BARS):
            y0 = i * (bh + 1)
            r  = self.create_rectangle(
                1, y0, self.W-1, y0+bh,
                fill=C["surface"], outline="")
            self._rects.append((r, colours[i]))
        self._prect = self.create_rectangle(
            0, 0, 0, 0, fill=C["amber_hi"], outline="")

    def _tick(self):
        try:
            target = float(self._fn())
        except Exception:
            target = 0.0
        bh = self.H // self.BARS - 1

        if target > self._level:
            self._level = (self._level * (1 - self.ATTACK)
                           + target * self.ATTACK)
        else:
            self._level = max(0.0, self._level - self.DECAY)

        active = int(self._level * self.BARS)
        for i, (r, col) in enumerate(self._rects):
            self.itemconfig(r, fill=col if (self.BARS - i) <= active
                            else C["surface"])

        if active >= self._peak:
            self._peak   = active
            self._ptimer = int(self.PEAK_HOLD_MS / self.TICK_MS)
        else:
            if self._ptimer > 0:
                self._ptimer -= 1
            else:
                self._peak = max(0, self._peak - 1)

        if self._peak > 0:
            row = self.BARS - self._peak
            py  = row * (bh + 1)
            self.coords(self._prect, 1, py, self.W-1, py+bh)
            self.itemconfig(self._prect,
                            fill=(C["red"] if self._peak >= self.BARS-1
                                  else C["amber_hi"]))
        else:
            self.coords(self._prect, 0, 0, 0, 0)

        if self.winfo_exists():
            self.after(self.TICK_MS, self._tick)


# ═══════════════════════════════════════════════════════════════
# TAPE RECORDER SECTION
# ═══════════════════════════════════════════════════════════════

class TapeRecorderSection(ctk.CTkFrame):
    """
    Right zone of the header.
    Row 0: label | timer | status | recordings ▾
    Row 1: ⏺ REC  ▶ PLAY  ⏹ STOP  🔁 LOOP  | 📤 SaveAs  🗑 Del
    Row 2: FX buttons (toggle + right-click for settings)
    Row 3: Active FX sliders (inline, visible only when FX active)
    VU meter on left edge.
    """

    EFFECTS = [
        ("chipmunk", "🐿", "PITCH"),
        ("echo",     "🔊", "ECHO"),
        ("reverb",   "🌊", "REVERB"),
        ("reverse",  "⏪", "REVERSE"),
        ("deep",     "🐋", "DEEP"),
        ("lofi",     "📞", "LO-FI"),
    ]
    PITCH_EXCLUSIVE = {"chipmunk", "deep"}

    FX_PARAMS = {
        "chipmunk": [("semitones","Pitch",2.0,12.0,6.0,0.5),
                     ("speed","Speed",1.1,2.0,1.35,0.05)],
        "deep":     [("semitones","Pitch",-12.0,-2.0,-6.0,0.5),
                     ("speed","Speed",0.4,0.9,0.72,0.05)],
        "reverb":   [("room_size","Room",0.1,1.0,0.75,0.05),
                     ("wet","Wet",0.1,0.9,0.5,0.05)],
        "echo":     [("delay","Delay",0.1,1.0,0.4,0.05),
                     ("feedback","Feed",0.1,0.9,0.45,0.05),
                     ("mix","Mix",0.1,0.9,0.5,0.05)],
        "lofi":     [("lowpass","LPF",500.0,6000.0,3200.0,100.0),
                     ("highpass","HPF",100.0,1500.0,500.0,50.0)],
        "reverse":  [],
    }

    def __init__(self, parent, app):
        super().__init__(parent, fg_color=C["surface"],
                         corner_radius=10)
        self.app      = app
        self.recorder: RecorderManager = app.recorder
        self._loop    = False
        self._cur     = None      # currently loaded file path
        self._active_fx: set = set()
        self._fx_btns: dict  = {}
        self._popup   = None
        self._active_fx_key = None   # which fx sliders are shown
        self._fx_slider_vars: dict = {}
        self._build()
        self._tick()

    def _build(self):
        # ── Outer: left (info+transport) | right (FX grid) ───────
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=4, pady=4)

        # ── LEFT: info row + transport row ────────────────────────
        left = ctk.CTkFrame(body, fg_color="transparent")
        left.pack(side="left", fill="y", padx=(0, 6))

        # Info row
        info = ctk.CTkFrame(left, fg_color="transparent")
        info.pack(fill="x", pady=(0, 4))

        ctk.CTkLabel(info, text="RECORDER",
                     font=ctk.CTkFont("Segoe UI", 10, "bold"),
                     text_color=C["text_dim"]).pack(side="left")

        self._timer = ctk.CTkLabel(
            info, text="00:00:00",
            font=ctk.CTkFont("Courier New", 13, "bold"),
            text_color=C["text"])
        self._timer.pack(side="left", padx=(6, 0))

        self._status = ctk.CTkLabel(
            info, text="IDLE",
            font=ctk.CTkFont("Segoe UI", 10),
            text_color=C["text_dim"])
        self._status.pack(side="left", padx=(6, 0))

        # Recent recordings dropdown
        self._recent_var = tk.StringVar(value="Recent...")
        self._recent_menu = ctk.CTkOptionMenu(
            info, width=100, height=20,
            values=["Recent..."],
            variable=self._recent_var,
            font=ctk.CTkFont("Segoe UI", 9),
            dropdown_font=ctk.CTkFont("Segoe UI", 9),
            fg_color=C["btn"],
            button_color=C["btn"],
            button_hover_color=C["btn_hover"],
            dropdown_fg_color=C["surface"],
            dropdown_hover_color=C["btn_hover"],
            command=self._on_recent_select)
        self._recent_menu.pack(side="left", padx=(8, 0))
        self._refresh_recent_recordings()

        ctk.CTkButton(
            info, text="📂", width=26, height=20,
            corner_radius=4, fg_color=C["btn"],
            hover_color=C["btn_hover"],
            font=ctk.CTkFont("Segoe UI", 10),
            command=self._open_recordings_folder
        ).pack(side="right")

        # Transport row
        trans = ctk.CTkFrame(left, fg_color="transparent")
        trans.pack(fill="x")

        TBTN = dict(width=36, height=26, corner_radius=5,
                    font=ctk.CTkFont("Segoe UI", 12, "bold"))

        self._rec_btn = ctk.CTkButton(
            trans, text="⏺", fg_color="#6a1a1a",
            hover_color="#992222",
            command=self._on_rec, **TBTN)
        self._rec_btn.pack(side="left", padx=(0, 2))

        self._play_btn = ctk.CTkButton(
            trans, text="▶", fg_color=C["green_dim"],
            hover_color=C["green"],
            command=self._on_play, **TBTN)
        self._play_btn.pack(side="left", padx=2)

        self._stop_btn = ctk.CTkButton(
            trans, text="⏹", fg_color=C["btn"],
            hover_color=C["btn_hover"],
            command=self._on_stop, **TBTN)
        self._stop_btn.pack(side="left", padx=2)

        self._loop_btn = ctk.CTkButton(
            trans, text="🔁", fg_color=C["btn"],
            hover_color=C["btn_hover"],
            command=self._on_loop, **TBTN)
        self._loop_btn.pack(side="left", padx=2)

        ctk.CTkFrame(trans, width=1, height=22,
                     fg_color=C["border"]).pack(side="left", padx=4)

        SBTN = dict(width=36, height=26, corner_radius=5,
                    font=ctk.CTkFont("Segoe UI", 11))
        ctk.CTkButton(trans, text="📤",
                      fg_color=C["blue"], hover_color=C["blue_mid"],
                      command=self._on_save_as, **SBTN
                      ).pack(side="left", padx=2)
        ctk.CTkButton(trans, text="🗑",
                      fg_color=C["btn"], hover_color=C["red_dim"],
                      command=self._on_delete, **SBTN
                      ).pack(side="left", padx=2)

        # ── RIGHT: FX grid — 2 columns × 3 rows ──────────────────
        ctk.CTkFrame(body, width=1, fg_color=C["border"]
                     ).pack(side="left", fill="y", padx=(0, 6))

        fx_frame = ctk.CTkFrame(body, fg_color="transparent")
        fx_frame.pack(side="left", fill="both", expand=True)

        FXBTN = dict(width=88, height=22, corner_radius=4,
                     font=ctk.CTkFont("Segoe UI", 10, "bold"))

        for i, (key, emoji, label) in enumerate(self.EFFECTS):
            col = i % 2
            row = i // 2
            b = ctk.CTkButton(
                fx_frame,
                text=label,
                fg_color=C["blue"],
                hover_color=C["blue_light"],
                text_color=C["text_hi"],
                command=lambda k=key: self._toggle_fx(k),
                **FXBTN)
            b.grid(row=row, column=col, padx=2, pady=2, sticky="ew")
            b.bind("<Button-3>",
                   lambda e, k=key: self._open_fx_settings(e, k))
            self._fx_btns[key] = b

        fx_frame.grid_columnconfigure(0, weight=1)
        fx_frame.grid_columnconfigure(1, weight=1)

        # DnD
        try:
            from tkinterdnd2 import DND_FILES
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_file_drop)
        except Exception:
            pass

    # ── FX toggle & sliders ───────────────────────────────────────

    def _open_recordings_folder(self):
        import os
        folder = self.app.cfg.config.get(
            "recordings_folder", str(self.recorder.recording_dir))
        try:
            if os.path.isdir(folder):
                os.startfile(folder)
        except Exception as e:
            log.warning(f"Open recordings folder: {e}")

    def _refresh_recent_recordings(self):
        """Refresh the recent recordings dropdown with last 5 files."""
        import os
        folder = self.app.cfg.config.get(
            "recordings_folder", str(self.recorder.recording_dir))
        try:
            if not os.path.isdir(folder):
                return
            files = []
            for f in os.listdir(folder):
                fp = os.path.join(folder, f)
                if os.path.isfile(fp) and f.lower().endswith(('.wav', '.mp3', '.ogg', '.flac')):
                    files.append((os.path.getmtime(fp), f, fp))
            files.sort(reverse=True)
            recent = files[:5]
            if recent:
                labels = [f[:25] + "…" if len(f) > 25 else f for _, f, _ in recent]
                self._recent_files = {lbl: fp for (_, f, fp), lbl in zip(recent, labels)}
                self._recent_menu.configure(values=["Recent..."] + labels)
            else:
                self._recent_files = {}
                self._recent_menu.configure(values=["Recent..."])
        except Exception as e:
            log.warning(f"Refresh recent recordings: {e}")

    def _on_recent_select(self, choice):
        """Load selected recent recording."""
        if choice == "Recent..." or not hasattr(self, '_recent_files'):
            return
        fp = self._recent_files.get(choice)
        if fp and os.path.isfile(fp):
            self._load_file(fp)
        self._recent_var.set("Recent...")

    def _on_file_drop(self, event):
        """Load a dropped audio file into the recorder player."""
        raw   = event.data
        paths = self.tk.splitlist(raw)
        if not paths:
            return
        path = paths[0].strip().strip("{}")
        if Path(path).suffix.lower() in {".mp3",".wav",".ogg",".flac",".m4a"}:
            self._load_file(path)

    def _toggle_fx(self, key: str):
        if key in self._active_fx:
            self._active_fx.discard(key)
        else:
            if key in self.PITCH_EXCLUSIVE:
                for ex in self.PITCH_EXCLUSIVE:
                    self._active_fx.discard(ex)
                    self._fx_btns[ex].configure(
                        fg_color=C["btn"], text_color=C["text"])
            self._active_fx.add(key)

        on = key in self._active_fx
        self._fx_btns[key].configure(
            fg_color=C["amber"] if on else C["blue"],
            text_color=C["bg"] if on else C["text_hi"])

    def _open_fx_settings(self, event, key: str):
        """Right-click popup with sliders for the effect's parameters."""
        params = self.FX_PARAMS.get(key, [])
        if not params:
            return

        if hasattr(self, "_fx_popup") and self._fx_popup and \
                self._fx_popup.winfo_exists():
            self._fx_popup.destroy()

        fx_cfg   = self.app.cfg.config.get("recorder_fx_settings", {})
        cur_vals = fx_cfg.get(key, {})
        h = 50 + len(params) * 56
        w = 280

        # Calculate position — clamp to screen so it never floats off
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()

        # Try below the button first
        px = event.x_root - w // 2
        py = event.y_root + 8

        # Clamp horizontal
        px = max(4, min(px, screen_w - w - 4))

        # If popup would go off bottom, flip it above the cursor instead
        if py + h > screen_h - 4:
            py = event.y_root - h - 8
        # Final vertical clamp
        py = max(4, py)

        popup = tk.Toplevel(self)
        popup.overrideredirect(True)
        popup.configure(bg=C["border"])
        popup.geometry(f"{w}x{h}+{px}+{py}")
        popup.lift()
        popup.attributes("-topmost", True)
        self._fx_popup = popup

        # Inner frame with 1px border effect
        inner = tk.Frame(popup, bg=C["elevated"],
                         highlightbackground=C["border_hi"],
                         highlightthickness=1)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        lbl_map = {k: lbl for k, _, lbl in self.EFFECTS}
        tk.Label(inner,
                 text=f"⚙  {lbl_map.get(key, key).upper()}  Settings",
                 bg=C["elevated"], fg=C["amber"],
                 font=("Segoe UI", 11, "bold"), anchor="w").pack(
                     fill="x", padx=8, pady=(8, 4))
        tk.Frame(inner, bg=C["border_hi"], height=1).pack(
            fill="x", padx=6, pady=(0, 4))

        for param_key, param_lbl, p_min, p_max, p_def, p_res in params:
            cur = cur_vals.get(param_key, p_def)
            row = tk.Frame(inner, bg=C["elevated"])
            row.pack(fill="x", padx=8, pady=(0, 6))

            hdr = tk.Frame(row, bg=C["elevated"])
            hdr.pack(fill="x")
            tk.Label(hdr, text=param_lbl,
                     bg=C["elevated"], fg=C["text"],
                     font=("Segoe UI", 10, "bold"),
                     anchor="w").pack(side="left")
            val_var = tk.DoubleVar(value=cur)
            val_lbl = tk.Label(hdr, text=f"{cur:.2f}",
                               bg=C["elevated"], fg=C["amber_hi"],
                               font=("Courier New", 11, "bold"), width=6)
            val_lbl.pack(side="right")

            def _on_slide(v, vv=val_var, vl=val_lbl,
                          pk=param_key, ek=key, res=p_res):
                snapped = round(float(v) / res) * res
                vv.set(snapped)
                vl.configure(text=f"{snapped:.2f}")
                self.app.cfg.config.setdefault(
                    "recorder_fx_settings", {}).setdefault(ek, {})[pk] = snapped
                self.app.cfg.save()

            import customtkinter as _ctk
            _ctk.CTkSlider(row, from_=p_min, to=p_max,
                           variable=val_var, command=_on_slide,
                           width=200, height=16).pack(
                               side="left", fill="x", expand=True,
                               pady=(2, 0))

        # Close on click outside
        popup.bind("<FocusOut>", lambda e: popup.destroy()
                   if popup.winfo_exists() else None)
        popup.focus_set()


    def _on_rec(self):
        if self.recorder.state == "recording":
            self._do_stop_save()
        else:
            dev = self.app.cfg.config.get("audio_input_device","")
            if dev == "Default (System)":
                dev = ""
            ok = self.recorder.start_recording(input_device=dev)
            if ok:
                self._rec_btn.configure(fg_color=C["red"])
                self._set_status("REC", C["red"])
            else:
                messagebox.showerror(
                    "Recorder Error",
                    "Could not start recording.\n\n"
                    "Settings → Audio → Input Device\n"
                    "Choose Voicemeeter Output or Stereo Mix.")

    def _on_play(self):
        if not self._cur:
            self._toggle_popup()
            return
        if self.recorder.state == "playing":
            self.recorder.stop_playback()
        if self._active_fx:
            self._set_status("PROCESSING...", C["amber"])
            self._play_btn.configure(state="disabled")
            fx_cfg = self.app.cfg.config.get("recorder_fx_settings",{})
            self.recorder.apply_effects_and_play(
                self._cur, set(self._active_fx), fx_cfg,
                loop=self._loop,
                on_done=self._after_play)
        else:
            ok = self.recorder.load_and_play(self._cur, loop=self._loop)
            if ok:
                self._set_status("PLAYING", C["green"])

    def _after_play(self, ok: bool):
        def _ui():
            if not self.winfo_exists():
                return
            self._play_btn.configure(state="normal")
            if ok:
                self._set_status("PLAYING", C["green"])
            else:
                self._set_status("IDLE", C["text_dim"])
        try:
            self.after(0, _ui)
        except Exception:
            pass  # widget destroyed before thread finished

    def _on_stop(self):
        if self.recorder.state == "recording":
            self._do_stop_save()
        elif self.recorder.state == "playing":
            self.recorder.stop_playback()
            self._set_status("IDLE", C["text_dim"])

    def _on_loop(self):
        self._loop = not self._loop
        self._loop_btn.configure(
            fg_color=C["amber"] if self._loop else C["btn"],
            text_color=C["bg"] if self._loop else C["text"])

    def _on_save_as(self):
        if not self._cur:
            messagebox.showinfo("Nothing Loaded",
                                "Record something first.")
            return
        import shutil
        src  = Path(self._cur)
        dest = filedialog.asksaveasfilename(
            title="Export Recording",
            initialfile=src.name,
            defaultextension=src.suffix,
            filetypes=[("WAV","*.wav"),("MP3","*.mp3"),
                       ("All","*.*")])
        if dest:
            try:
                shutil.copy2(str(src), dest)
            except Exception as e:
                messagebox.showerror("Export Failed", str(e))

    def _on_delete(self):
        if not self._cur:
            return
        name = Path(self._cur).name
        if not messagebox.askyesno(
                "Delete Recording",
                f"Delete '{name}'?\nThis cannot be undone."):
            return
        if self.recorder.state == "playing":
            self.recorder.stop_playback()
        self.recorder.delete_file(self._cur)
        self._cur = None
        self._set_status("IDLE", C["text_dim"])

    def _do_stop_save(self):
        self._rec_btn.configure(fg_color="#6a1a1a")
        self._set_status("SAVING...", C["amber"])
        fmt = self.app.cfg.config.get("recording_format","wav")

        def _work():
            path = self.recorder.stop_and_save(fmt=fmt)
            self.after(0, lambda: self._save_done(path))

        threading.Thread(target=_work, daemon=True).start()

    def _save_done(self, path):
        if path:
            self._cur = str(path)
            self._set_status("READY", C["green"])
        else:
            self._set_status("IDLE", C["text_dim"])
            messagebox.showerror(
                "Save Failed",
                "Could not save recording.\n"
                "Check Settings \u2192 Audio \u2192 Input Device.")

    # ── Timer tick ────────────────────────────────────────────────

    def _tick(self):
        state = self.recorder.state
        if state == "recording":
            s = int(self.recorder.get_elapsed())
            self._timer.configure(
                text=f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}",
                text_color=C["red"])
        elif state == "playing":
            pos  = self.recorder.get_playback_position()
            s    = int(pos)
            self._timer.configure(
                text=f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}",
                text_color=C["green"])
            if not self.recorder.is_playing() and not self._loop:
                self._set_status("IDLE", C["text_dim"])
        else:
            self._timer.configure(text_color=C["text"])
        if self.winfo_exists():
            self.after(200, self._tick)

    def _set_status(self, text, color=None):
        self._status.configure(
            text=text,
            text_color=color or C["text_dim"])

    def _toggle_popup(self):
        if self._popup and self._popup.winfo_exists():
            self._popup.destroy()
            self._popup = None
        else:
            self._open_popup()

    def _open_popup(self):
        recs = self.recorder.list_recordings()[-10:][::-1]  # last 10, newest first
        self.update_idletasks()
        x = self._list_btn.winfo_rootx()
        y = self._list_btn.winfo_rooty() + \
            self._list_btn.winfo_height() + 2
        w = 380
        h = min(len(recs)*28 + 36, 280) if recs else 60

        popup = tk.Toplevel(self)
        popup.overrideredirect(True)
        popup.configure(bg=C["elevated"])
        popup.geometry(f"{w}x{h}+{x}+{y}")
        popup.lift()
        self._popup = popup

        if not recs:
            tk.Label(popup, text="No recordings yet.",
                     bg=C["elevated"], fg=C["text_dim"],
                     font=("Segoe UI", 11)).pack(pady=16)
            popup.bind("<FocusOut>", lambda e: popup.destroy())
            popup.focus_set()
            return

        frame = tk.Frame(popup, bg=C["elevated"])
        frame.pack(fill="both", expand=True, padx=2, pady=2)
        sb = tk.Scrollbar(frame, bg=C["surface"],
                          troughcolor=C["bg"], width=10)
        lb = tk.Listbox(frame, yscrollcommand=sb.set,
                        bg=C["elevated"], fg=C["text"],
                        selectbackground=C["blue_mid"],
                        selectforeground=C["text_hi"],
                        font=("Segoe UI", 11),
                        bd=0, highlightthickness=0,
                        activestyle="none")
        sb.config(command=lb.yview)
        sb.pack(side="right", fill="y")
        lb.pack(side="left", fill="both", expand=True)

        for r in recs:
            lb.insert(tk.END,
                      f"  {r['filename']}   {r['recorded_at']}")

        # Pre-select current
        if self._cur:
            for i, r in enumerate(recs):
                if r["path"] == self._cur:
                    lb.selection_set(i)
                    lb.see(i)
                    break

        def _select(e=None):
            sel = lb.curselection()
            if sel:
                rec = recs[sel[0]]
                self._load_file(rec["path"])
            popup.destroy()
            self._popup = None

        lb.bind("<ButtonRelease-1>", _select)
        lb.bind("<Return>",          _select)
        popup.bind("<FocusOut>", lambda e: popup.destroy())
        popup.focus_set()

    def _load_file(self, path: str):
        if self.recorder.state == "playing":
            self.recorder.stop_playback()
        self._cur = path
        import pygame
        try:
            snd = pygame.mixer.Sound(str(path))
            self.recorder._pb_snd = snd
            self.recorder._pb_len = snd.get_length()
        except Exception:
            pass
        short = Path(path).name
        short = short[:24] + "…" if len(short) > 24 else short
        self._set_status(short, C["blue_hi"])


# ═══════════════════════════════════════════════════════════════
# MIC PANEL
# ═══════════════════════════════════════════════════════════════

class MicPanel(ctk.CTkFrame):
    """
    Compact mic control strip — sits between PANIC and tape recorder.
    Row 0: MIC label + horizontal VU meter
    Row 1: 🎙 LIVE/MUTED  |  PTT (hold)
    Row 2: 🎚 Duck (toggle)  |  🎚 Hold (momentary)
    Row 3: GAIN slider
    """

    def __init__(self, parent, app, mic: MicManager):
        super().__init__(parent, fg_color=C["surface"],
                         corner_radius=8)
        self.app          = app
        self.mic          = mic
        self._duck_toggled = False
        self._build()
        self._tick()

    def _fade_setter(self, v: float):
        """Push a value into both the audio engine and the soundboard slider."""
        try:
            self.app.audio.set_performance_fade(v)
            self.app.soundboard._set_fade(v)
        except Exception:
            pass

    def _fade_getter(self) -> float:
        try:
            return self.app.audio.get_performance_fade()
        except Exception:
            return 1.0

    def _duck_duration(self) -> float:
        return float(self.app.cfg.config.get("fade_duration", 3.0))

    def _build(self):
        S10B = ctk.CTkFont("Segoe UI", 10, "bold")
        S10  = ctk.CTkFont("Segoe UI", 10)

        # Left col: VU + GAIN  |  Right col: LIVE + DUCK
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=6, pady=(6, 3))

        # ── Left: VU bar + GAIN — wider ──────────────────────────
        left = ctk.CTkFrame(body, fg_color="transparent", width=229)
        left.pack(side="left", fill="y", padx=(0, 6))
        left.pack_propagate(False)

        lbl_row = ctk.CTkFrame(left, fg_color="transparent")
        lbl_row.pack(fill="x", pady=(0, 3))
        self._mic_status_lbl = ctk.CTkLabel(
            lbl_row, text="🎙 MIC",
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
            text_color=C["text_dim"])
        self._mic_status_lbl.pack(side="left")
        self._vu_canvas = tk.Canvas(
            lbl_row, height=8, bg=C["elevated"],
            highlightthickness=0)
        self._vu_canvas.pack(side="left", fill="x",
                              expand=True, padx=(6, 0))
        self._vu_bar = self._vu_canvas.create_rectangle(
            0, 0, 0, 8, fill=C["green"], outline="")

        gain_row = ctk.CTkFrame(left, fg_color="transparent")
        gain_row.pack(fill="x")
        ctk.CTkLabel(gain_row, text="GAIN",
                     font=S10, text_color=C["text_dim"]
                     ).pack(side="left", padx=(0, 4))
        self._gain_var = ctk.DoubleVar(value=self.mic.get_gain())
        ctk.CTkSlider(
            gain_row, from_=0.0, to=1.0,
            variable=self._gain_var,
            command=lambda v: self.mic.set_gain(float(v)),
            height=14
        ).pack(side="left", fill="x", expand=True)

        # ── Right: LIVE + DUCK ────────────────────────────────────
        right = ctk.CTkFrame(body, fg_color="transparent")
        right.pack(side="left", fill="y")

        self._mute_btn = ctk.CTkButton(
            right, text="🎙 LIVE", width=76, height=26,
            corner_radius=5,
            fg_color=C["green"], hover_color=C["green_dim"],
            font=S10B, command=self._toggle_mute)
        self._mute_btn.pack(fill="x", pady=(0, 3))

        self._duck_tog_btn = ctk.CTkButton(
            right, text="🎚 Duck", width=76, height=26,
            corner_radius=5,
            fg_color=C["btn"], hover_color=C["btn_hover"],
            font=S10B, command=self._duck_toggle)
        self._duck_tog_btn.pack(fill="x")

    # ── Mute / PTT ────────────────────────────────────────────────

    def _toggle_mute(self):
        if not self.mic.is_bound:
            # Not bound — prompt user to set device in Settings
            try:
                from tkinter import messagebox
                messagebox.showwarning(
                    "No Mic Device",
                    "No mic input device is bound.\n\n"
                    "Go to Settings \u2192 Audio \u2192 Mic Input Device "
                    "and select your microphone.")
            except Exception:
                pass
            return
        muted = self.mic.toggle_mute()
        self._update_mute_btn(muted)

    def _update_mute_btn(self, muted: bool):
        if muted:
            self._mute_btn.configure(
                text="🔴 MUTED",
                fg_color=C["red_dim"], hover_color=C["red_dim"])
        else:
            self._mute_btn.configure(
                text="🎙 LIVE",
                fg_color=C["green"], hover_color=C["green_dim"])

    # ── Duck toggle ───────────────────────────────────────────────

    def _duck_toggle(self):
        """Toggle duck: press to fade down, press again to fade back up."""
        dur = self._duck_duration()
        if not self._duck_toggled:
            # Duck down
            self._duck_toggled      = True
            self.mic._duck_active   = True
            self.mic._pre_duck_fade = self._fade_getter()
            target = float(self.app.cfg.config.get("mic_duck_level", 0.3))
            self._duck_tog_btn.configure(
                fg_color=C["amber"], text_color=C["bg"],
                text="🎚 Ducked")
            self.mic.duck_smooth(
                self._fade_getter(), target, dur,
                self.after, self._fade_setter)
        else:
            # Unduck
            self._duck_toggled    = False
            self.mic._duck_active = False
            self._duck_tog_btn.configure(
                fg_color=C["btn"], text_color=C["text"],
                text="🎚 Duck")
            self.mic.duck_smooth(
                self._fade_getter(), self.mic._pre_duck_fade, dur,
                self.after, self._fade_setter)

    # ── Surprise buttons ─────────────────────────────────────────

    _cough_job = None
    _cough_was_muted = False  # track state before cough press

    def _cough_press(self):
        """Push-to-talk: mute mic when button pressed."""
        if not self.mic.is_bound:
            return
        self._cough_was_muted = self.mic.is_muted()
        if not self._cough_was_muted:
            self.mic.set_mute(True)
            self._update_mute_btn(True)

    def _cough_release(self):
        """Push-to-talk: unmute mic when button released."""
        if not self.mic.is_bound:
            return
        # Only unmute if mic wasn't already muted before we pressed
        if not self._cough_was_muted:
            self.mic.set_mute(False)
            self._update_mute_btn(False)

    def _cough(self):
        """Legacy method — kept for compatibility."""
        self._cough_press()

    _brb_fade = 1.0

    def _brb(self):
        """Break — mute mic + fade music up full + log it."""
        self._brb_fade = self._fade_getter()
        if not self.mic.is_muted():
            self.mic.set_mute(True)
            self._update_mute_btn(True)
        dur = self._duck_duration()
        self.mic.duck_smooth(self._brb_fade, 1.0, dur,
                             self.after, self._fade_setter)
        try:
            self.app.right_panel.session_log.log_event("☕ On break")
        except Exception:
            pass

    def _back(self):
        """Back from break — restore fade + unmute mic + log it."""
        dur = self._duck_duration()
        target = getattr(self, "_brb_fade", 0.7)
        self.mic.duck_smooth(self._fade_getter(), target, dur,
                             self.after, self._fade_setter)
        if self.mic.is_muted():
            self.mic.set_mute(False)
            self._update_mute_btn(False)
        try:
            self.app.right_panel.session_log.log_event("🎙 Back on air")
        except Exception:
            pass

    def _clip_it(self):
        """Stamp a gold moment clip marker in the session log instantly."""
        try:
            sl = self.app.right_panel.session_log
            ts = sl._ts()
            sl._entries.append({"ts": ts, "type": "gold",
                                 "text": "⭐ CLIP THIS"})
            sl._write([(f"[{ts}] ", "ts"), ("⭐ CLIP THIS", "gold")])
        except Exception:
            pass
        try:
            self.app.log_gold_moment()
        except Exception:
            pass

    # ── Tick ──────────────────────────────────────────────────────

    def _tick(self):
        try:
            level = self.mic.get_level()
            self._vu_canvas.update_idletasks()
            w = self._vu_canvas.winfo_width()
            if w > 4:
                fill_w = int(w * level)
                col = (C["red"]   if level > 0.75 else
                       C["amber"] if level > 0.45 else
                       C["green"])
                self._vu_canvas.coords(self._vu_bar, 0, 0, fill_w, 8)
                self._vu_canvas.itemconfig(self._vu_bar, fill=col)
            # Bind status on label
            if self.mic.is_bound:
                self._mic_status_lbl.configure(
                    text="🎙 MIC", text_color=C["text_dim"])
            else:
                self._mic_status_lbl.configure(
                    text="🎙 NO DEVICE", text_color=C["red_dim"])
        except Exception:
            pass
        if self.winfo_exists():
            self.after(80, self._tick)




# ═══════════════════════════════════════════════════════════════
# HEADER FRAME
# ═══════════════════════════════════════════════════════════════

class HeaderFrame(ctk.CTkFrame):
    """
    Two-zone broadcast console header.

    Zone A (left, ~65% width):
      [VU] Logo | Show info | ON AIR | LIVE timer | GO LIVE
           ---- second row ----
           COUNTDOWN | VOL | MUTE | PANIC

    Zone B (right, ~35% width):
      [VU] Tape Recorder section
    """

    HEIGHT = 100

    def __init__(self, parent, app):
        super().__init__(parent,
                         fg_color=C["bg2"], corner_radius=0)
        self.app = app
        self.configure(height=self.HEIGHT)
        self.pack_propagate(False)

        self._call_running = False
        self._call_start   = None

        self._build()

    # ── Build ─────────────────────────────────────────────────────

    def _build(self):
        from ui_dialogs import load_logo

        # ── LEFT: Logo + Branding ────────────────────────────────
        left = ctk.CTkFrame(self, fg_color="transparent")
        left.pack(side="left", padx=(6, 0), pady=4)

        brand_f = ctk.CTkFrame(left, fg_color="transparent")
        brand_f.pack(side="left")
        logo = load_logo((44, 50))
        if logo:
            ctk.CTkLabel(brand_f, image=logo, text="").pack(side="left", padx=(0, 6))
        brand_txt = ctk.CTkFrame(brand_f, fg_color="transparent")
        brand_txt.pack(side="left")
        ctk.CTkLabel(brand_txt, text=APP_NAME,
                     font=ctk.CTkFont("Segoe UI", 13, "bold"),
                     text_color=C["text"]).pack(anchor="w")
        ctk.CTkLabel(brand_txt,
                     text=(f"{self.app.cfg.config.get('show_name', 'My Show')}"
                           f"  •  v{VERSION}"),
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C["text_dim"]).pack(anchor="w")

        # ── CENTRE: all broadcast controls in one row ─────────────
        mid = ctk.CTkFrame(self, fg_color="transparent")
        mid.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=4)

        # ON AIR badge
        self.onair_frame = ctk.CTkFrame(
            mid, width=96, height=36, corner_radius=6, fg_color=C["surface"])
        self.onair_frame.pack(side="left", padx=(0, 6))
        self.onair_frame.pack_propagate(False)
        self.onair_lbl = ctk.CTkLabel(
            self.onair_frame, text="● OFF AIR",
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            text_color=C["text_dim"])
        self.onair_lbl.place(relx=0.5, rely=0.5, anchor="center")

        # LIVE timer block
        live_blk = ctk.CTkFrame(mid, fg_color="transparent")
        live_blk.pack(side="left", padx=(0, 6))
        ctk.CTkLabel(live_blk, text="LIVE",
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C["text_dim"]).pack(anchor="w")
        self.live_lbl = ctk.CTkLabel(
            live_blk, text="00:00:00",
            font=ctk.CTkFont("Courier New", 18, "bold"),
            text_color=C["text"])
        self.live_lbl.pack(anchor="w")

        # GO LIVE button
        _gl = self.app.cfg.get_btn_custom("golive", 0)
        self.golive_btn = ctk.CTkButton(
            mid, text=_gl.get("label", "GO LIVE"),
            width=82, height=36, corner_radius=6,
            fg_color=_gl.get("color", C["blue"]) or C["blue"],
            text_color=_gl.get("text_color", C["text_hi"]) or C["text_hi"],
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            command=self.app.manual_go_live)
        self.golive_btn.pack(side="left", padx=(0, 8))
        self.golive_btn.bind("<Button-3>",
            lambda e: self._btn_ctx(e, "golive", 0, allow_rename=True))

        ctk.CTkFrame(mid, width=1, height=36, fg_color=C["border"]).pack(side="left", padx=6)

        # CALL timer badge — dim when idle, amber when active
        call_blk = ctk.CTkFrame(mid, fg_color="transparent")
        call_blk.pack(side="left", padx=(0, 6))
        ctk.CTkLabel(call_blk, text="CALL",
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C["text_dim"]).pack(anchor="w")
        self.call_lbl = ctk.CTkLabel(
            call_blk, text="00:00",
            font=ctk.CTkFont("Courier New", 15, "bold"),
            text_color=C["text_dim"])
        self.call_lbl.pack(anchor="w")

        ctk.CTkFrame(mid, width=1, height=36, fg_color=C["border"]).pack(side="left", padx=6)

        # COUNTDOWN block
        cd_blk = ctk.CTkFrame(mid, fg_color="transparent")
        cd_blk.pack(side="left", padx=(0, 8))
        ctk.CTkLabel(cd_blk, text="COUNTDOWN",
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C["text_dim"]).pack(anchor="w")
        self.cd_lbl = ctk.CTkLabel(
            cd_blk, text="00:00",
            font=ctk.CTkFont("Courier New", 15, "bold"),
            text_color=C["text"])
        self.cd_lbl.pack(anchor="w")
        cd_ctrl = ctk.CTkFrame(cd_blk, fg_color="transparent")
        cd_ctrl.pack(anchor="w")
        self.cd_entry = ctk.CTkEntry(
            cd_ctrl, width=46, height=18,
            placeholder_text="MM:SS",
            font=ctk.CTkFont("Segoe UI", 11))
        self.cd_entry.pack(side="left", padx=(0, 2))
        ctk.CTkButton(cd_ctrl, text="▶", width=20, height=18,
                      corner_radius=3, fg_color=C["green"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=self.app.start_countdown).pack(side="left", padx=1)
        ctk.CTkButton(cd_ctrl, text="⏹", width=20, height=18,
                      corner_radius=3, fg_color=C["btn"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=self.app.stop_countdown).pack(side="left", padx=1)
        ctk.CTkButton(cd_ctrl, text="5m", width=22, height=18,
                      corner_radius=3, fg_color=C["btn"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=lambda: self.app.quick_countdown(5)).pack(side="left", padx=1)
        ctk.CTkButton(cd_ctrl, text="10m", width=26, height=18,
                      corner_radius=3, fg_color=C["btn"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=lambda: self.app.quick_countdown(10)).pack(side="left", padx=1)

        ctk.CTkFrame(mid, width=1, height=36, fg_color=C["border"]).pack(side="left", padx=6)

        # STOPWATCH block — count UP timer
        sw_blk = ctk.CTkFrame(mid, fg_color="transparent")
        sw_blk.pack(side="left", padx=(0, 8))
        ctk.CTkLabel(sw_blk, text="STOPWATCH",
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C["text_dim"]).pack(anchor="w")
        self.sw_lbl = ctk.CTkLabel(
            sw_blk, text="00:00",
            font=ctk.CTkFont("Courier New", 15, "bold"),
            text_color=C["text"])
        self.sw_lbl.pack(anchor="w")
        sw_ctrl = ctk.CTkFrame(sw_blk, fg_color="transparent")
        sw_ctrl.pack(anchor="w")
        ctk.CTkButton(sw_ctrl, text="▶", width=20, height=18,
                      corner_radius=3, fg_color=C["green"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=self.app.start_stopwatch).pack(side="left", padx=1)
        ctk.CTkButton(sw_ctrl, text="⏸", width=20, height=18,
                      corner_radius=3, fg_color=C["btn"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=self.app.pause_stopwatch).pack(side="left", padx=1)
        ctk.CTkButton(sw_ctrl, text="⏹", width=20, height=18,
                      corner_radius=3, fg_color=C["btn"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=self.app.reset_stopwatch).pack(side="left", padx=1)
        ctk.CTkButton(sw_ctrl, text="📌", width=20, height=18,
                      corner_radius=3, fg_color=C["amber"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=self.app.lap_stopwatch).pack(side="left", padx=1)

        ctk.CTkFrame(mid, width=1, height=36, fg_color=C["border"]).pack(side="left", padx=6)

        # MUTE + PANIC — stacked vertically
        mp_blk = ctk.CTkFrame(mid, fg_color="transparent")
        mp_blk.pack(side="left", padx=(0, 0))

        _mu = self.app.cfg.get_btn_custom("mute", 0)
        self.mute_btn = ctk.CTkButton(
            mp_blk, text="🔇 MUTE", width=86, height=26,
            corner_radius=5,
            fg_color=_mu.get("color", C["btn"]) or C["btn"],
            text_color=_mu.get("text_color", C["text"]) or C["text"],
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            command=self.app.toggle_mute)
        self.mute_btn.pack(pady=(0, 3))
        self.mute_btn.bind("<Button-3>",
            lambda e: self._btn_ctx(e, "mute", 0, allow_rename=False))

        _pa = self.app.cfg.get_btn_custom("panic", 0)
        self.panic_btn = ctk.CTkButton(
            mp_blk, text="🚨 PANIC", width=86, height=26,
            corner_radius=5,
            fg_color=_pa.get("color", C["panic"]) or C["panic"],
            text_color=_pa.get("text_color", C["text_hi"]) or C["text_hi"],
            hover_color="#ff0000",
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            command=self.app.panic)
        self.panic_btn.pack()
        self.panic_btn.bind("<Button-3>",
            lambda e: self._btn_ctx(e, "panic", 0, allow_rename=False))

        # ── MIC PANEL ────────────────────────────────────────────
        ctk.CTkFrame(mid, width=1, height=36,
                     fg_color=C["border"]).pack(side="left", padx=6)

        self.mic_panel = MicPanel(mid, self.app, self.app.mic)
        self.mic_panel.pack(side="left", fill="y", pady=4)

        # ── Surprise buttons ─────────────────────────────────────
        ctk.CTkFrame(mid, width=1, height=36,
                     fg_color=C["border"]).pack(side="left", padx=6)

        sb_blk = ctk.CTkFrame(mid, fg_color="transparent")
        sb_blk.pack(side="left", fill="y", pady=4)

        SBBTN = dict(width=76, height=26, corner_radius=4,
                     font=ctk.CTkFont("Segoe UI", 10, "bold"))

        # 2x2 grid so all 4 fit in the header height
        row0 = ctk.CTkFrame(sb_blk, fg_color="transparent")
        row0.pack(pady=(0, 3))
        row1 = ctk.CTkFrame(sb_blk, fg_color="transparent")
        row1.pack()

        self._cough_btn = ctk.CTkButton(row0, text="💨 COUGH",
                      fg_color="#3a1a00", hover_color="#5a2800",
                      text_color=C["amber"],
                      command=lambda: None,  # handled by press/release
                      **SBBTN)
        self._cough_btn.pack(side="left", padx=(0, 3))
        # Push-to-talk: press to mute, release to unmute
        self._cough_btn.bind("<ButtonPress-1>", lambda e: self.mic_panel._cough_press())
        self._cough_btn.bind("<ButtonRelease-1>", lambda e: self.mic_panel._cough_release())

        ctk.CTkButton(row0, text="☕ BREAK",
                      fg_color=C["btn"], hover_color=C["btn_hover"],
                      text_color=C["text"],
                      command=self.mic_panel._brb,
                      **SBBTN).pack(side="left")

        ctk.CTkButton(row1, text="🎙 BACK",
                      fg_color=C["btn"], hover_color=C["btn_hover"],
                      text_color=C["text"],
                      command=self.mic_panel._back,
                      **SBBTN).pack(side="left", padx=(0, 3))

        ctk.CTkButton(row1, text="⭐ CLIP IT",
                      fg_color="#2a1f00", hover_color="#3a2d00",
                      text_color=C["gold"],
                      command=self.mic_panel._clip_it,
                      **SBBTN).pack(side="left")

        # ── RIGHT: recorder zone — natural width ─────────────────
        ctk.CTkFrame(self, width=1, height=self.HEIGHT - 12,
                     fg_color=C["border"]).pack(side="right", padx=0, pady=6)

        right = ctk.CTkFrame(self, fg_color="transparent")
        right.pack(side="right", fill="y", padx=(4, 4), pady=4)

        self._vu_recorder = VerticalVU(right,
            lambda: self.app.audio.get_recorder_vu_level())
        self._vu_recorder.pack(side="left", padx=(4, 6))

        self.tape_recorder = TapeRecorderSection(right, self.app)
        self.tape_recorder.pack(side="left", fill="y")



    def start_call_from_log(self):
        """Called by session log Start Call button."""
        import time as _t
        if self._call_running:
            return
        self._call_start   = _t.monotonic()
        self._call_running = True
        self.call_lbl.configure(text_color=C["amber"])
        self._tick_call()

    def end_call_from_log(self):
        """Called by session log End Call button. Returns elapsed secs."""
        import time as _t
        if not self._call_running:
            return 0
        self._call_running = False
        elapsed = int(_t.monotonic() - self._call_start) \
            if self._call_start else 0
        self.call_lbl.configure(
            text="00:00", text_color=C["text_dim"])
        return elapsed

    def _tick_call(self):
        if not self._call_running:
            return
        import time as _t
        e = int(_t.monotonic() - self._call_start)
        self.call_lbl.configure(text=f"{e//60:02d}:{e%60:02d}")
        self.after(1000, self._tick_call)

    def _btn_ctx(self, e, btn_type, idx, allow_rename):
        from ui_dialogs import ButtonSettingsDialog
        m = tk.Menu(self, tearoff=0,
                    bg=C["surface"], fg=C["text"],
                    activebackground=C["blue_mid"],
                    font=("Segoe UI", 11))
        m.add_command(
            label="🎨  Customize...",
            command=lambda: self._open_customize(
                btn_type, idx, allow_rename))
        m.add_command(label="↩  Reset",
                      command=lambda: self._reset_custom(
                          btn_type, idx))
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    def _open_customize(self, btn_type, idx, allow_rename):
        from ui_dialogs import ButtonSettingsDialog
        custom = self.app.cfg.get_btn_custom(btn_type, idx)
        defs   = {
            "golive": ("GO LIVE",  C["blue"],  C["text_hi"]),
            "panic":  ("🚨 PANIC", C["panic"], C["text_hi"]),
            "mute":   ("🔇 MUTE",  C["btn"],   C["text"]),
        }
        dl, dc, dt = defs.get(btn_type, ("", C["btn"], C["text"]))
        dlg = ButtonSettingsDialog(
            self,
            label=custom.get("label", dl),
            color=custom.get("color", dc),
            text_color=custom.get("text_color", dt),
            allow_rename=allow_rename)
        self.wait_window(dlg)
        if dlg.result:
            data = {"color":      dlg.result["color"],
                    "text_color": dlg.result["text_color"]}
            if allow_rename:
                data["label"] = dlg.result["label"]
            self.app.cfg.set_btn_custom(btn_type, idx, data)
            self.app.cfg.save()
            self._apply_custom(btn_type, idx)

    def _reset_custom(self, btn_type, idx):
        self.app.cfg.set_btn_custom(btn_type, idx, {})
        self.app.cfg.save()
        self._apply_custom(btn_type, idx)

    def _apply_custom(self, btn_type, idx):
        c = self.app.cfg.get_btn_custom(btn_type, idx)
        if btn_type == "golive":
            self.golive_btn.configure(
                text=c.get("label","GO LIVE") or "GO LIVE",
                fg_color=c.get("color",C["blue"]) or C["blue"],
                text_color=c.get("text_color",C["text_hi"]) or C["text_hi"])
        elif btn_type == "mute":
            self.mute_btn.configure(
                fg_color=c.get("color",C["btn"]) or C["btn"],
                text_color=c.get("text_color",C["text"]) or C["text"])
        elif btn_type == "panic":
            self.panic_btn.configure(
                fg_color=c.get("color",C["panic"]) or C["panic"],
                text_color=c.get("text_color",C["text_hi"]) or C["text_hi"])

    # ── Public update methods ─────────────────────────────────────

    def set_on_air(self, live: bool):
        c = self.app.cfg.get_btn_custom("golive", 0)
        if live:
            self.onair_lbl.configure(text="● ON AIR",
                                      text_color=C["red"])
            self.onair_frame.configure(fg_color="#3a0808")
            self.golive_btn.configure(text="END LIVE",
                                       fg_color=C["red_dim"])
        else:
            self.onair_lbl.configure(text="● OFF AIR",
                                      text_color=C["text_dim"])
            self.onair_frame.configure(fg_color=C["surface"])
            self.golive_btn.configure(
                text=c.get("label","GO LIVE") or "GO LIVE",
                fg_color=c.get("color",C["blue"]) or C["blue"])

    def set_connecting(self):
        """Show a connecting state while waiting for stream."""
        self.onair_lbl.configure(text="● CONNECTING",
                                  text_color=C["amber"])
        self.onair_frame.configure(fg_color="#2a1e00")
        self.golive_btn.configure(text="CANCEL",
                                   fg_color=C["btn"])

    def update_live(self, hh, mm, ss):
        self.live_lbl.configure(
            text=f"{hh:02d}:{mm:02d}:{ss:02d}")

    def update_countdown(self, mm, ss, urgent=False):
        self.cd_lbl.configure(
            text=f"{mm:02d}:{ss:02d}",
            text_color=C["red"] if urgent else C["text"])

    def update_stopwatch(self, mm, ss):
        self.sw_lbl.configure(text=f"{mm:02d}:{ss:02d}")

    def set_mute_state(self, muted: bool):
        if muted:
            self.mute_btn.configure(text="🔊 UNMUTE",
                                     fg_color=C["amber"],
                                     text_color=C["bg"])
        else:
            c = self.app.cfg.get_btn_custom("mute", 0)
            self.mute_btn.configure(
                text="🔇 MUTE",
                fg_color=c.get("color",C["btn"]) or C["btn"],
                text_color=c.get("text_color",C["text"]) or C["text"])

    def flash_red(self):
        self._flash(6)

    def _flash(self, n):
        if n <= 0:
            self.configure(fg_color=C["bg2"])
            return
        self.configure(fg_color="#350000" if n%2 else C["bg2"])
        self.after(300, lambda: self._flash(n-1))

    def refresh_theme(self):
        """Refresh header colors after theme change."""
        try:
            self.configure(fg_color=C["bg2"])
            # Update key buttons
            if hasattr(self, "golive_btn"):
                self.golive_btn.configure(fg_color=C["blue"],
                                          hover_color=C["blue_mid"])
            if hasattr(self, "panic_btn"):
                self.panic_btn.configure(fg_color=C["panic"])
            if hasattr(self, "onair_frame"):
                self.onair_frame.configure(fg_color=C["surface"])
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
# MINI MODE WINDOW
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# MENU BAR
# ═══════════════════════════════════════════════════════════════

class MenuBarFrame(ctk.CTkFrame):
    """
    Custom dark-themed menu bar that sits between the title bar and
    the header.  Uses CTkButton tabs that pop up tk.Menu dropdowns.

    Menus
    -----
    File  — Save Notes, Export Bank, Import Bank, Export Session Log, Exit
    Edit  — Undo, Lock/Unlock Board, Settings
    View  — Opacity submenu
    Tools — Quick Folders submenu, Edit Websites, Discord Settings
    Help  — About, GitHub link, Open Data Folder
    """

    HEIGHT = 26

    def __init__(self, parent, app):
        super().__init__(parent,
                         fg_color=C["bg2"],
                         corner_radius=0,
                         height=self.HEIGHT)
        self.app = app
        self.pack_propagate(False)
        self._build()

    # ── Build ─────────────────────────────────────────────────────

    def _build(self):
        labels = ["  File  ", "  Edit  ", "  View  ", "  Tools  ", "  Help  "]
        builders = [
            self._build_file,
            self._build_edit,
            self._build_view,
            self._build_tools,
            self._build_help,
        ]
        for lbl, fn in zip(labels, builders):
            btn = tk.Button(
                self,
                text=lbl,
                font=("Segoe UI", 11),
                bg=C["bg2"],
                fg=C["text"],
                activebackground=C["elevated"],
                activeforeground=C["text_hi"],
                bd=0,
                padx=4,
                pady=3,
                cursor="hand2",
                relief="flat",
            )
            btn.pack(side="left")
            btn.configure(command=lambda b=btn, f=fn: self._popup(b, f))

        # Thin border bottom
        tk.Frame(self, bg=C["border"], height=1).pack(
            side="bottom", fill="x")

    def _menu_style(self):
        return dict(
            bg=C["elevated"],
            fg=C["text"],
            activebackground=C["blue_mid"],
            activeforeground=C["text_hi"],
            relief="flat",
            bd=0,
            tearoff=False,
        )

    def _popup(self, btn, builder):
        """Position and display the menu below the clicked button."""
        m = builder()
        x = btn.winfo_rootx()
        y = btn.winfo_rooty() + btn.winfo_height()
        try:
            m.tk_popup(x, y)
        finally:
            m.grab_release()

    # ── Menu builders ─────────────────────────────────────────────

    def _build_file(self):
        m = tk.Menu(self, **self._menu_style())

        m.add_command(label="💾  Save Notes",
                      command=self._save_notes)
        m.add_separator()
        m.add_command(label="📤  Export Bank",
                      command=self._export_bank)
        m.add_command(label="📥  Import Bank",
                      command=self._import_bank)
        m.add_separator()
        m.add_command(label="📋  Export Session Log",
                      command=self._export_session_log)
        m.add_separator()
        m.add_command(label="✖  Exit",
                      command=self.app._on_close)
        return m

    def _build_edit(self):
        m = tk.Menu(self, **self._menu_style())

        m.add_command(label="↩  Undo",
                      command=self.app.undo_last)
        m.add_separator()

        locked = self.app.cfg.config.get("soundboard_locked", False)
        lock_lbl = "🔓  Unlock Board" if locked else "🔒  Lock Board"
        m.add_command(label=lock_lbl,
                      command=self._toggle_lock)
        m.add_separator()
        m.add_command(label="⚙  Settings",
                      command=self.app.open_settings)
        return m

    def _build_view(self):
        m = tk.Menu(self, **self._menu_style())

        opacity_menu = tk.Menu(m, **self._menu_style())
        for label, value in [
            ("100%  (Full)",  1.0),
            ("90%",           0.9),
            ("80%",           0.8),
            ("70%",           0.7),
            ("50%  (Ghost)",  0.5),
        ]:
            opacity_menu.add_command(
                label=label,
                command=lambda v=value: self.app.set_opacity(v))

        m.add_cascade(label="🔆  Opacity", menu=opacity_menu)
        m.add_separator()
        m.add_command(label="🎨  Visual Settings...",
                      command=lambda: self.app.open_settings(tab="Visual"))
        m.add_command(label="⌨  Hotkeys...",
                      command=lambda: self.app.open_settings(tab="Hotkeys"))
        return m

    def _build_tools(self):
        m = tk.Menu(self, **self._menu_style())

        # Quick Folders submenu
        folder_menu = tk.Menu(m, **self._menu_style())
        import os
        folders = self.app.cfg.config.get("folders", [])
        any_folder = False
        for f in folders:
            path  = f.get("path", "")
            label = f.get("label", "")
            if path:
                any_folder = True
                folder_menu.add_command(
                    label=f"📁  {label}",
                    command=lambda p=path: (
                        os.startfile(p) if os.path.isdir(p) else None))
            else:
                folder_menu.add_command(
                    label=f"     {label} (empty)",
                    state="disabled")
        if not any_folder:
            folder_menu.add_command(
                label="     (no folders configured)",
                state="disabled")
        m.add_cascade(label="📁  Quick Folders", menu=folder_menu)
        m.add_separator()
        m.add_command(label="🌐  Edit Websites",
                      command=lambda: self.app.open_settings(tab="Websites"))
        m.add_command(label="📡  Stream Settings",
                      command=lambda: self.app.open_settings(tab="Streaming"))
        m.add_command(label="📡  Discord Settings",
                      command=lambda: self.app.open_settings(tab="Integrations"))
        m.add_separator()
        m.add_command(label="🎙   Marker Export",
                      command=self.app.open_marker_export)
        m.add_command(label="📊  Show Analytics",
                      command=self.app.open_analytics)
        return m

    def _build_help(self):
        m = tk.Menu(self, **self._menu_style())

        import webbrowser
        github_url = "https://github.com/ColdKittyIce/BroadcastBackpack"

        m.add_command(label=f"ℹ  {APP_NAME}  v{VERSION}",
                      state="disabled")
        m.add_separator()
        m.add_command(label="📖  Help Guide",
                      command=self._open_help_inapp)
        m.add_command(label="🌐  Help Guide in Browser",
                      command=self._open_help_browser)
        m.add_separator()
        m.add_command(label="🌐  GitHub Repository",
                      command=lambda: webbrowser.open(github_url))
        m.add_separator()
        m.add_command(label="📂  Open Data Folder",
                      command=self._open_data_dir)
        return m

    def _open_help_inapp(self):
        try:
            from ui_dialogs import SettingsWindow
            # Reuse the same _open_help logic from SettingsWindow
            from pathlib import Path
            import webbrowser as _wb
            import tkinter as _tk
            import html as _html
            import re as _re
            import customtkinter as _ctk
            html_path = Path(__file__).parent / "help.html"
            if not html_path.exists():
                from tkinter import messagebox
                messagebox.showerror("Help Not Found",
                    f"help.html not found at:\n{html_path}")
                return
            win = _ctk.CTkToplevel(self)
            win.title(f"{APP_NAME} — Help Guide")
            win.geometry("1020x720")
            win.configure(fg_color="#ffffff")
            win.lift()
            win.focus_force()
            tb = _ctk.CTkFrame(win, fg_color="#f3f4f6", corner_radius=0)
            tb.pack(fill="x")
            _ctk.CTkLabel(tb,
                text=f"📖  {APP_NAME} — Help Guide",
                font=_ctk.CTkFont("Segoe UI", 12, "bold"),
                text_color="#1f2937"
            ).pack(side="left", padx=12, pady=8)
            _ctk.CTkButton(
                tb, text="🌐 Open in Browser",
                fg_color="#1a73e8", hover_color="#1557b0",
                text_color="white", height=30,
                font=_ctk.CTkFont("Segoe UI", 11),
                command=lambda: _wb.open(html_path.as_uri())
            ).pack(side="right", padx=12, pady=6)
            raw  = html_path.read_text(encoding="utf-8")
            text = _re.sub(r"<style[^>]*>.*?</style>", "", raw, flags=_re.S)
            text = _re.sub(r"<script[^>]*>.*?</script>", "", text, flags=_re.S)
            text = _re.sub(r"<br\s*/?>|</p>|</li>|</tr>|</h[1-6]>", "\n", text)
            text = _re.sub(r"<[^>]+>", "", text)
            text = _re.sub(r"\n{3,}", "\n\n", text)
            text = _html.unescape(text).strip()
            container = _ctk.CTkScrollableFrame(win, fg_color="#ffffff")
            container.pack(fill="both", expand=True)
            txt = _tk.Text(container, wrap="word",
                font=("Segoe UI", 12),
                bg="#ffffff", fg="#1f2937",
                relief="flat", bd=0,
                padx=40, pady=20,
                spacing1=2, spacing3=4)
            txt.pack(fill="both", expand=True)
            txt.insert("1.0", text)
            txt.configure(state="disabled")
            _ctk.CTkLabel(win,
                text='Tip: Click "Open in Browser" for the full styled guide with diagrams.',
                font=_ctk.CTkFont("Segoe UI", 11),
                text_color="#6b7280",
                fg_color="#f9fafb"
            ).pack(fill="x")
        except Exception as e:
            log.warning(f"Help open error: {e}")

    def _open_help_browser(self):
        from pathlib import Path
        import webbrowser as _wb
        html_path = Path(__file__).parent / "help.html"
        if html_path.exists():
            _wb.open(html_path.as_uri())
        else:
            from tkinter import messagebox
            messagebox.showerror("Help Not Found",
                f"help.html not found at:\n{html_path}")

    # ── Action callbacks ──────────────────────────────────────────

    def _save_notes(self):
        try:
            self.app.right_panel.notes.save_all()
        except Exception as e:
            log.warning(f"MenuBar save_notes: {e}")

    def _export_bank(self):
        try:
            sb = self.app.soundboard
            sb._export_bank(sb._current_bank)
        except Exception as e:
            log.warning(f"MenuBar export_bank: {e}")

    def _import_bank(self):
        try:
            sb = self.app.soundboard
            sb._import_bank(sb._current_bank)
        except Exception as e:
            log.warning(f"MenuBar import_bank: {e}")

    def _export_session_log(self):
        try:
            self.app.right_panel.session_log._export()
        except Exception as e:
            log.warning(f"MenuBar export_session_log: {e}")

    def _toggle_lock(self):
        try:
            self.app.soundboard._toggle_lock()
        except Exception as e:
            log.warning(f"MenuBar toggle_lock: {e}")

    def _open_data_dir(self):
        import os
        from config import DATA_DIR
        path = str(DATA_DIR)
        try:
            if os.path.isdir(path):
                os.startfile(path)
        except Exception as e:
            log.warning(f"MenuBar open_data_dir: {e}")


class MiniModeWindow(tk.Toplevel):
    """
    Always-on-top compact mini console.
    Rows: broadcast | now playing+transport | queue view + mini soundboard | stamp
    """

    W  = 900
    H  = 420

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app            = app
        self._tick_job      = None
        self._mini_bank     = 0   # mini soundboard current bank
        self._mini_btns     = []
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=C["bg2"])
        self.geometry(f"{self.W}x{self.H}+50+50")
        self._drag_x = self._drag_y = 0
        self._build()
        self._tick()

    def _build(self):
        import customtkinter as _ctk
        BG   = C["bg2"]
        SRF  = C["surface"]
        S8   = ("Segoe UI", 11)
        S9B  = ("Segoe UI", 11, "bold")
        S10B = ("Segoe UI", 11, "bold")
        S11B = ("Segoe UI", 11, "bold")
        CNB  = ("Courier New", 15, "bold")

        outer = tk.Frame(self, bg=BG, bd=1, relief="solid",
                         highlightbackground=C["border"],
                         highlightthickness=1)
        outer.pack(fill="both", expand=True)

        # ── Title bar ──────────────────────────────────────────────
        bar = tk.Frame(outer, bg=SRF, height=18)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        tk.Label(bar, text=f"  {APP_NAME} — Mini Mode",
                 bg=SRF, fg=C["text_dim"], font=S8).pack(side="left")
        tk.Button(bar, text="⛶ Expand",
                  bg=SRF, fg=C["blue_hi"],
                  activebackground=C["btn_hover"],
                  relief="flat", bd=0, padx=8,
                  font=S8, cursor="hand2",
                  command=self._expand).pack(side="right")
        for w in (bar, outer):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>",     self._drag_move)

        # ── Row 1: Broadcast controls ──────────────────────────────
        r1 = tk.Frame(outer, bg=BG)
        r1.pack(fill="x", padx=6, pady=(4, 2))

        self._onair = tk.Label(r1, text="● OFF AIR",
                                bg=SRF, fg=C["text_dim"],
                                font=S11B, width=10,
                                relief="flat", bd=0)
        self._onair.pack(side="left", padx=(0, 6), ipady=5)

        lv_f = tk.Frame(r1, bg=BG)
        lv_f.pack(side="left", padx=(0, 6))
        tk.Label(lv_f, text="LIVE", bg=BG,
                 fg=C["text_dim"], font=S8).pack(anchor="w")
        self._live = tk.Label(lv_f, text="00:00:00",
                               bg=BG, fg=C["text"], font=CNB)
        self._live.pack(anchor="w")

        self._golive = tk.Button(
            r1, text="GO LIVE",
            bg=C["blue"], fg=C["text_hi"],
            activebackground=C["blue_mid"],
            font=S10B, relief="flat", bd=0,
            padx=12, pady=4, cursor="hand2",
            command=self.app.manual_go_live)
        self._golive.pack(side="left", padx=(0, 8))

        tk.Frame(r1, bg=C["border"], width=1).pack(
            side="left", fill="y", padx=4)

        self._mic_mute = tk.Button(
            r1, text="🎙 LIVE",
            bg=C["green"], fg=C["bg"],
            activebackground=C["green_dim"],
            font=S9B, relief="flat", bd=0,
            padx=10, pady=4, cursor="hand2",
            command=self._toggle_mic_mute)
        self._mic_mute.pack(side="left", padx=(0, 6))

        mic_vu_f = tk.Frame(r1, bg=BG)
        mic_vu_f.pack(side="left", padx=(0, 6))
        tk.Label(mic_vu_f, text="MIC", bg=BG,
                 fg=C["text_dim"], font=S8).pack(anchor="w")
        self._mic_vu_c = tk.Canvas(
            mic_vu_f, width=80, height=10,
            bg=C["elevated"], highlightthickness=0)
        self._mic_vu_c.pack(anchor="w")
        self._mic_vu_bar = self._mic_vu_c.create_rectangle(
            0, 0, 0, 10, fill=C["green"], outline="")

        mic_sl_f = tk.Frame(r1, bg=BG)
        mic_sl_f.pack(side="left", padx=(0, 8))
        tk.Label(mic_sl_f, text="GAIN", bg=BG,
                 fg=C["text_dim"], font=S8).pack(anchor="w")
        self._mic_gain_var = _ctk.DoubleVar(value=1.0)
        try: self._mic_gain_var.set(self.app.mic.get_gain())
        except Exception: pass
        self._mic_sl = _ctk.CTkSlider(
            mic_sl_f, from_=0.0, to=1.0,
            variable=self._mic_gain_var,
            command=lambda v: self.app.mic.set_gain(float(v)),
            width=80, height=14)
        self._mic_sl.pack(anchor="w")

        # ── Row 2: Now Playing + transport + sound VOL ─────────────
        r2 = tk.Frame(outer, bg=BG)
        r2.pack(fill="x", padx=6, pady=(0, 2))

        np_f = tk.Frame(r2, bg=BG)
        np_f.pack(side="left", padx=(0, 6))
        tk.Label(np_f, text="NOW PLAYING", bg=BG,
                 fg=C["text_dim"], font=S8).pack(anchor="w")
        self._np = tk.Label(np_f, text="—",
                             bg=BG, fg=C["text"],
                             font=S9B, width=22, anchor="w")
        self._np.pack(anchor="w")

        tp_f = tk.Frame(r2, bg=BG)
        tp_f.pack(side="left", padx=(0, 8))
        for sym, cmd in [
            ("⏮", lambda: self._queue_cmd("prev")),
            ("▶", lambda: self._queue_cmd("play")),
            ("⏸", lambda: self._queue_cmd("pause")),
            ("⏹", lambda: self._queue_cmd("stop")),
            ("⏭", lambda: self._queue_cmd("next")),
        ]:
            tk.Button(tp_f, text=sym,
                      bg=C["btn"], fg=C["text"],
                      activebackground=C["btn_hover"],
                      relief="flat", bd=0,
                      padx=6, pady=2,
                      font=("Segoe UI", 11),
                      cursor="hand2",
                      command=cmd).pack(side="left", padx=1)

        tk.Frame(r2, bg=C["border"], width=1).pack(
            side="left", fill="y", padx=6)

        snd_vu_f = tk.Frame(r2, bg=BG)
        snd_vu_f.pack(side="left", padx=(0, 4))
        tk.Label(snd_vu_f, text="SND", bg=BG,
                 fg=C["text_dim"], font=S8).pack(anchor="w")
        self._snd_vu_c = tk.Canvas(
            snd_vu_f, width=80, height=10,
            bg=C["elevated"], highlightthickness=0)
        self._snd_vu_c.pack(anchor="w")
        self._snd_vu_bar = self._snd_vu_c.create_rectangle(
            0, 0, 0, 10, fill=C["green"], outline="")

        vol_f = tk.Frame(r2, bg=BG)
        vol_f.pack(side="left", padx=(0, 8))
        tk.Label(vol_f, text="VOL", bg=BG,
                 fg=C["text_dim"], font=S8).pack(anchor="w")
        self._vol_var = _ctk.DoubleVar(value=self.app.audio.master_vol)
        self._vol_sl = _ctk.CTkSlider(
            vol_f, from_=0.0, to=1.0,
            variable=self._vol_var,
            command=lambda v: self.app.set_master_volume(float(v)),
            width=90, height=14)
        self._vol_sl.pack(anchor="w")

        tk.Button(r2, text="⏹ Stop All",
                  bg=C["btn"], fg=C["text"],
                  activebackground=C["btn_hover"],
                  font=S9B, relief="flat", bd=0,
                  padx=10, pady=4, cursor="hand2",
                  command=self.app.panic).pack(side="left", padx=(0, 6))
        tk.Button(r2, text="🚨 PANIC",
                  bg=C["panic"], fg=C["text_hi"],
                  activebackground="#ff0000",
                  font=S10B, relief="flat", bd=0,
                  padx=10, pady=4, cursor="hand2",
                  command=self.app.panic).pack(side="left", padx=(0, 4))

        # ── Row 3: Queue view (left) + Mini Soundboard (right) ─────
        r3 = tk.Frame(outer, bg=BG)
        r3.pack(fill="both", expand=True, padx=6, pady=(2, 2))

        # Queue list panel
        q_panel = tk.Frame(r3, bg=C["surface"], bd=0)
        q_panel.pack(side="left", fill="both",
                     expand=False, padx=(0, 6))
        q_panel.configure(width=200)
        q_panel.pack_propagate(False)

        tk.Label(q_panel, text="QUEUE", bg=C["surface"],
                 fg=C["text_dim"], font=S8).pack(anchor="w", padx=4, pady=(3,0))

        self._q_listbox = tk.Listbox(
            q_panel,
            bg=C["elevated"], fg=C["text"],
            selectbackground=C["blue_mid"],
            selectforeground=C["text_hi"],
            activestyle="none",
            relief="flat", bd=0,
            font=("Segoe UI", 11),
            highlightthickness=0)
        self._q_listbox.pack(fill="both", expand=True, padx=4, pady=(2, 4))
        self._q_listbox.bind("<Double-Button-1>", self._q_jump)

        # Mini Soundboard panel
        sb_panel = tk.Frame(r3, bg=BG)
        sb_panel.pack(side="left", fill="both", expand=True)

        # Bank tab bar
        self._mini_tab_bar = tk.Frame(sb_panel, bg=BG, height=22)
        self._mini_tab_bar.pack(fill="x")
        self._mini_tab_bar.pack_propagate(False)

        # Button grid (4x4 max)
        self._mini_grid = tk.Frame(sb_panel, bg=BG)
        self._mini_grid.pack(fill="both", expand=True)

        self._build_mini_soundboard()

        # ── Row 4: Stamp bar ───────────────────────────────────────
        r4 = tk.Frame(outer, bg=BG)
        r4.pack(fill="x", padx=6, pady=(0, 4))

        self._ts_entry = tk.Entry(
            r4, bg=C["surface"], fg=C["text"],
            insertbackground=C["text"],
            relief="flat", font=("Segoe UI", 11), width=34)
        self._ts_entry.pack(side="left", padx=(0, 4), ipady=3, ipadx=4)
        self._ts_entry.insert(0, "note...")
        self._ts_entry.configure(fg=C["text_dim"])
        self._ts_entry.bind("<FocusIn>",  self._ts_focus_in)
        self._ts_entry.bind("<FocusOut>", self._ts_focus_out)
        self._ts_entry.bind("<Return>",   lambda e: self._do_stamp())

        tk.Button(r4, text="📌 Stamp",
                  bg=C["btn"], fg=C["amber_hi"],
                  activebackground=C["btn_hover"],
                  relief="flat", bd=0,
                  padx=10, pady=3,
                  font=S9B, cursor="hand2",
                  command=self._do_stamp).pack(side="left")

        # Bind drag to rows only; protect sliders
        self._bind_drag_rows(r1, r2, r4)
        def _no_drag(e): return "break"
        for sl in (self._mic_sl, self._vol_sl):
            try:
                sl.bind("<ButtonPress-1>", _no_drag, add=True)
                sl.bind("<B1-Motion>",     _no_drag, add=True)
            except Exception:
                pass

    # ── Mini Soundboard ───────────────────────────────────────────

    def _build_mini_soundboard(self):
        from ui_soundboard import SoundButton
        # Clear existing
        for w in self._mini_tab_bar.winfo_children():
            w.destroy()
        for w in self._mini_grid.winfo_children():
            w.destroy()
        self._mini_btns.clear()

        groups = self.app.cfg.config.get("soundboard_groups", [])
        if not groups:
            return

        # ── Tab bar ───────────────────────────────────────────
        for i, g in enumerate(groups):
            is_cur = (i == self._mini_bank)
            bg = C["blue_mid"] if is_cur else g.get("color","") or C["btn"]
            fg = C["text_hi"] if is_cur else g.get("text_color","") or C["text_dim"]
            tk.Button(
                self._mini_tab_bar,
                text=g["name"],
                bg=bg, fg=fg,
                activebackground=C["blue_mid"],
                activeforeground=C["text_hi"],
                relief="flat", bd=0, padx=8,
                font=("Segoe UI", 11, "bold" if is_cur else "normal"),
                cursor="hand2",
                command=lambda idx=i: self._switch_mini_bank(idx)
            ).pack(side="left", fill="y", padx=1)

        # ── Scrollable grid matching full bank layout ─────────
        g     = groups[self._mini_bank]
        rows  = g.get("rows", 2)
        cols  = g.get("cols", 8)
        start, _ = self.app.cfg.bank_range(self._mini_bank)
        slots    = self.app.cfg.config.get("soundboard", [])

        # Scrollable canvas + inner frame
        canvas = tk.Canvas(self._mini_grid,
                           bg=C["bg2"],
                           highlightthickness=0)
        vsb = tk.Scrollbar(self._mini_grid, orient="vertical",
                           command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=C["bg2"])
        canvas_win = canvas.create_window((0, 0), window=inner,
                                          anchor="nw")

        # Configure columns to fill canvas width
        def _resize(e):
            canvas.itemconfig(canvas_win, width=e.width)
        canvas.bind("<Configure>", _resize)

        for c in range(cols):
            inner.grid_columnconfigure(c, weight=1)

        # Button height: 36px — readable, not too tall
        BTN_H = 36

        for i in range(rows * cols):
            slot_idx = start + i
            if slot_idx >= len(slots):
                break
            r, c = divmod(i, cols)
            slot  = slots[slot_idx]
            color = slot.get("color", "") or C["neutral"]
            tc    = slot.get("text_color", "") or C["text_hi"]
            full_label = slot.get("label", f"Sound {slot_idx+1}")
            dot        = "● " if slot.get("file") else ""

            # Truncate label to ~10 chars + ellipsis
            MAX_CH = 10
            disp = (full_label[:MAX_CH] + "…"
                    if len(full_label) > MAX_CH else full_label)

            # Use a real SoundButton for full right-click + play support
            sb = SoundButton(
                inner,
                self.app.cfg,
                self.app.audio,
                "soundboard",
                slot_idx,
                session_log=None,
                on_update=lambda: None)
            sb.grid(row=r, column=c,
                    sticky="nsew", padx=1, pady=1)
            sb.configure(height=BTN_H)

            # Override label with truncated version
            try:
                sb._btn.configure(
                    text=f"{dot}{disp}",
                    wraplength=0)  # no wrap — single line
            except Exception:
                pass

            # Tooltip showing full label
            if len(full_label) > MAX_CH:
                self._mini_tooltip(sb._btn, full_label)

            self._mini_btns.append(sb)

        # Update scroll region once grid is populated
        inner.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))

        # Mouse wheel scrolling
        def _wheel(e):
            canvas.yview_scroll(int(-1*(e.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _wheel)

    def _mini_tooltip(self, widget, text: str):
        """Attach a hover tooltip showing the full label."""
        tip = None

        def _show(e):
            nonlocal tip
            tip = tk.Toplevel(widget)
            tip.overrideredirect(True)
            tip.attributes("-topmost", True)
            tk.Label(tip, text=text,
                     bg="#ffffe0", fg="#1f2937",
                     font=("Segoe UI", 11),
                     relief="solid", bd=1,
                     padx=6, pady=3).pack()
            x = widget.winfo_rootx() + 10
            y = widget.winfo_rooty() + widget.winfo_height() + 2
            tip.geometry(f"+{x}+{y}")

        def _hide(e):
            nonlocal tip
            if tip:
                try: tip.destroy()
                except Exception: pass
                tip = None

        widget.bind("<Enter>", _show)
        widget.bind("<Leave>", _hide)

    def _switch_mini_bank(self, idx):
        self._mini_bank = idx
        self._build_mini_soundboard()

    # ── Queue helpers ─────────────────────────────────────────────

    def _q_jump(self, e):
        """Double-click a queue item to jump to it."""
        try:
            sel = self._q_listbox.curselection()
            if sel:
                self.app.soundboard.queue._play_track(sel[0])
        except Exception:
            pass

    def _refresh_queue(self):
        """Update the queue listbox to reflect current state."""
        try:
            q   = self.app.soundboard.queue
            cur = q._current_idx
            items = q._queue
            self._q_listbox.delete(0, "end")
            for i, (_, _, label) in enumerate(items):
                prefix = "▶ " if i == cur else "   "
                self._q_listbox.insert("end", f"{prefix}{label}")
            if 0 <= cur < len(items):
                self._q_listbox.see(cur)
        except Exception:
            pass

    # ── Existing helpers (unchanged) ──────────────────────────────

    def _toggle_mic_mute(self):
        try:
            muted = self.app.mic.toggle_mute()
            self.update_mute(muted)
            self.app.header.mic_panel._update_mute_btn(muted)
        except Exception:
            pass

    def _queue_cmd(self, cmd):
        try:
            q = self.app.soundboard.queue
            {"prev":  q._prev,
             "play":  q._play_pause,
             "pause": q._play_pause,
             "stop":  q._stop,
             "next":  q._next}[cmd]()
        except Exception as e:
            import logging; logging.getLogger(__name__
                ).warning(f"mini queue cmd {cmd}: {e}")

    def _ts_focus_in(self, e):
        if self._ts_entry.get() == "note...":
            self._ts_entry.delete(0, "end")
            self._ts_entry.configure(fg=C["text"])

    def _ts_focus_out(self, e):
        if not self._ts_entry.get().strip():
            self._ts_entry.insert(0, "note...")
            self._ts_entry.configure(fg=C["text_dim"])

    def _do_stamp(self):
        raw  = self._ts_entry.get().strip()
        note = "" if raw == "note..." else raw
        try:
            self.app.right_panel.session_log._do_stamp_from(note)
        except Exception:
            try:
                sl = self.app.right_panel.session_log
                from datetime import datetime as _dt
                wall = _dt.now().strftime("%b %d %H:%M:%S")
                text = f"📌 {note}" if note else "📌"
                sl._write([(f"[{wall}] ", "ts"), (text, "stamp")])
            except Exception:
                pass
        self._ts_entry.delete(0, "end")
        self._ts_entry.insert(0, "note...")
        self._ts_entry.configure(fg=C["text_dim"])

    # ── Tick ──────────────────────────────────────────────────────

    def _tick(self):
        try:
            if self.app._live:
                self._onair.configure(
                    text="● ON AIR", bg="#3a0808", fg=C["red"])
                self._golive.configure(text="END LIVE", bg=C["red_dim"])
            else:
                self._onair.configure(
                    text="● OFF AIR", bg=C["surface"], fg=C["text_dim"])
                self._golive.configure(text="GO LIVE", bg=C["blue"])
            h = getattr(self.app, "_live_h", 0)
            m = getattr(self.app, "_live_m", 0)
            s = getattr(self.app, "_live_s", 0)
            self._live.configure(text=f"{h:02d}:{m:02d}:{s:02d}")

            try:
                muted = self.app.mic.is_muted()
                self._mic_mute.configure(
                    text="🔴 MUTED" if muted else "🎙 LIVE",
                    bg=C["red_dim"] if muted else C["green"],
                    fg=C["text_hi"] if muted else C["bg"])
            except Exception:
                pass

            try:
                lv = float(self.app.mic.get_level())
                col = (C["red"] if lv > 0.75 else
                       C["amber"] if lv > 0.45 else C["green"])
                self._mic_vu_c.coords(self._mic_vu_bar, 0, 0, int(80*lv), 10)
                self._mic_vu_c.itemconfig(self._mic_vu_bar, fill=col)
            except Exception:
                pass

            try:
                lv = float(self.app.audio.get_vu_level())
                col = (C["red"] if lv > 0.75 else
                       C["amber"] if lv > 0.45 else C["green"])
                self._snd_vu_c.coords(self._snd_vu_bar, 0, 0, int(80*lv), 10)
                self._snd_vu_c.itemconfig(self._snd_vu_bar, fill=col)
            except Exception:
                pass

            np = self.app.audio.get_now_playing()
            if np:
                _, info = np
                self._np.configure(
                    text=info.get("label","")[:24], fg=C["text"])
            else:
                self._np.configure(text="—", fg=C["text_dim"])

            try: self._vol_var.set(self.app.audio.master_vol)
            except Exception: pass

            self._refresh_queue()

        except Exception:
            pass
        if self.winfo_exists():
            self._tick_job = self.after(200, self._tick)

    # ── Drag + expand ─────────────────────────────────────────────

    def _expand(self):
        if self._tick_job:
            try: self.after_cancel(self._tick_job)
            except Exception: pass
        # Clean up bind_all for mouse wheel
        try:
            self.unbind_all("<MouseWheel>")
        except Exception:
            pass
        self.app.toggle_mini_mode()

    def _drag_start(self, e):
        self._drag_x = e.x_root - self.winfo_x()
        self._drag_y = e.y_root - self.winfo_y()

    def _drag_move(self, e):
        self.geometry(f"+{e.x_root - self._drag_x}"
                      f"+{e.y_root - self._drag_y}")

    def _bind_drag_rows(self, *frames):
        for f in frames:
            f.bind("<ButtonPress-1>", self._drag_start)
            f.bind("<B1-Motion>",     self._drag_move)

    def update_mute(self, muted: bool):
        try:
            self._mic_mute.configure(
                text="🔴 MUTED" if muted else "🎙 LIVE",
                bg=C["red_dim"] if muted else C["green"],
                fg=C["text_hi"] if muted else C["bg"])
        except Exception:
            pass

