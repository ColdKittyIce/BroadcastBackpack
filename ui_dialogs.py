"""
ui_dialogs.py — Broadcast Backpack v6.0.0
All modal dialogs:
  ColorPickerDialog    — colour swatch + hex + system picker
  ButtonSettingsDialog — name + button color + text color
  FXPanel              — pedalboard FX editor for soundboard slots
  PostShowDialog       — end-of-show reminder with title/description
  SettingsWindow       — full settings
"""

import os, sys, copy, webbrowser, logging, threading
import tkinter as tk
from tkinter import filedialog, messagebox, colorchooser
import customtkinter as ctk
from pathlib import Path
from datetime import datetime

from config import (C, VERSION, APP_NAME,
                    DATA_DIR, SESSION_DIR, RECORDING_DIR, THEMES,
                    THEMES_BASE, derive_palette, text_for_bg, luminance,
                    DEFAULT_FX, lighten, darken, fs)

log = logging.getLogger("broadcast.ui")

try:
    from pedalboard import Pedalboard
    HAS_PEDALBOARD = True
except ImportError:
    HAS_PEDALBOARD = False

try:
    import keyboard as kb
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False

from PIL import Image
from config import ASSET_DIR


def load_logo(size=(48, 54)):
    try:
        img = Image.open(ASSET_DIR / "logo.png").convert("RGBA")
        img = img.resize(size, Image.LANCZOS)
        return ctk.CTkImage(img, size=size)
    except Exception:
        return None


def _detect_browsers():
    candidates = [
        ("Chrome",  r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        ("Chrome",  r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        ("Firefox", r"C:\Program Files\Mozilla Firefox\firefox.exe"),
        ("Edge",    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        ("Edge",    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        ("Brave",   r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ]
    found = [("Default (system)", "")]
    seen  = set()
    for label, path in candidates:
        if path and os.path.exists(path) and path not in seen:
            found.append((label, path))
            seen.add(path)
    return found


# ═══════════════════════════════════════════════════════════════
# COLOR PICKER
# ═══════════════════════════════════════════════════════════════

class ColorPickerDialog(ctk.CTkToplevel):
    PRESETS = [
        "#0e1c30","#1c3d78","#2a55a8","#4070c8",
        "#f0a020","#ffbb40","#ffd700","#ff8800",
        "#e02233","#cc0000","#ff6644","#ff4488",
        "#20b85a","#126835","#00bcd4","#00e5ff",
        "#9b59b6","#8855d5","#7040c8","#3d1c78",
        "#607d8b","#c8d8f0","#132238","#060b14",
    ]

    def __init__(self, parent, initial="#1c3d78", callback=None):
        super().__init__(parent)
        self.callback = callback
        self._color   = initial or "#1c3d78"
        self.title("Choose Colour")
        self.geometry("400x340")
        self.configure(fg_color=C["bg2"])
        self.grab_set()
        self.resizable(False, False)
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="🎨  Colour Picker",
                     font=ctk.CTkFont("Segoe UI", 14, "bold"),
                     text_color=C["amber"]).pack(pady=(14, 6))

        self._swatch = tk.Label(self, bg=self._color,
                                width=20, height=3, relief="flat")
        self._swatch.pack(pady=(0, 6))

        hex_row = ctk.CTkFrame(self, fg_color="transparent")
        hex_row.pack(pady=(0, 8))
        ctk.CTkLabel(hex_row, text="#",
                     font=ctk.CTkFont("Consolas", 13),
                     text_color=C["text"]).pack(side="left")
        self._hex_var = ctk.StringVar(value=self._color.lstrip("#"))
        self._hex_var.trace_add("write", self._on_hex)
        ctk.CTkEntry(hex_row, textvariable=self._hex_var,
                     width=100, font=ctk.CTkFont("Consolas", 13)
                     ).pack(side="left", padx=4)
        ctk.CTkButton(hex_row, text="System Picker", width=120,
                      fg_color=C["blue"], font=ctk.CTkFont("Segoe UI", 11),
                      command=self._sys_picker).pack(side="left", padx=4)

        pf = ctk.CTkFrame(self, fg_color="transparent")
        pf.pack(pady=4)
        for i, col in enumerate(self.PRESETS):
            tk.Button(pf, bg=col, width=2, height=1,
                      relief="flat", bd=1, cursor="hand2",
                      command=lambda c=col: self._pick(c)
                      ).grid(row=i//8, column=i%8, padx=2, pady=2)

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(pady=10)
        ctk.CTkButton(row, text="✓  Use Colour", width=150, height=34,
                      fg_color=C["green"],
                      font=ctk.CTkFont("Segoe UI", 12, "bold"),
                      command=self._confirm).pack(side="left", padx=6)
        ctk.CTkButton(row, text="Cancel", width=80, height=34,
                      fg_color=C["surface"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=self.destroy).pack(side="left", padx=6)

    def _pick(self, col):
        self._color = col
        self._swatch.configure(bg=col)
        self._hex_var.set(col.lstrip("#"))

    def _on_hex(self, *_):
        val = self._hex_var.get().strip()
        if len(val) == 6:
            try:
                int(val, 16)
                self._color = "#" + val
                self._swatch.configure(bg=self._color)
            except ValueError:
                pass

    def _sys_picker(self):
        col = colorchooser.askcolor(color=self._color, title="Pick Colour")
        if col and col[1]:
            self._pick(col[1])

    def _confirm(self):
        if self.callback:
            self.callback(self._color)
        self.destroy()


# ═══════════════════════════════════════════════════════════════
# BUTTON SETTINGS DIALOG
# ═══════════════════════════════════════════════════════════════

class ButtonSettingsDialog(ctk.CTkToplevel):
    """
    Combined Name + Button Colour + Text Colour dialog.
    Colour swatches and hex entry are inline — no intermediate popup.
    System picker still available as a single button.
    allow_rename=False hides the label field.
    result = {label, color, text_color} or None if cancelled.
    """

    PRESETS = [
        "#0e1c30","#1c3d78","#2a55a8","#4070c8",
        "#f0a020","#ffbb40","#ffd700","#ff8800",
        "#e02233","#cc0000","#ff6644","#ff4488",
        "#20b85a","#126835","#00bcd4","#00e5ff",
        "#9b59b6","#8855d5","#607d8b","#c8d8f0",
        "#132238","#060b14","#ffffff","#000000",
    ]

    def __init__(self, parent, label="", color="",
                 text_color="", allow_rename=True):
        super().__init__(parent)
        self.result        = None
        self._label        = label
        self._color        = color or C["btn"]
        self._text_color   = text_color or ""
        self._allow_rename = allow_rename
        self._active_target = "button"   # "button" or "text"

        self.title("Customize Button")
        h = 500 if allow_rename else 460
        self.geometry(f"420x{h}")
        self.configure(fg_color=C["bg2"])
        self.grab_set()
        self.resizable(False, False)
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="Customize Button",
                     font=ctk.CTkFont("Segoe UI", 13, "bold"),
                     text_color=C["amber"]).pack(pady=(12, 6))

        sf = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=8)
        sf.pack(fill="x", padx=14, pady=(0, 6))

        # ── Label ────────────────────────────────────────────────
        if self._allow_rename:
            ctk.CTkLabel(sf, text="Label:",
                         font=ctk.CTkFont("Segoe UI", 11),
                         text_color=C["text_dim"]).pack(
                             padx=12, pady=(10, 2), anchor="w")
            self._lv = ctk.StringVar(value=self._label)
            ctk.CTkEntry(sf, textvariable=self._lv,
                         width=360, font=ctk.CTkFont("Segoe UI", 11)
                         ).pack(padx=12, pady=(0, 8))

        # ── Colour target selector ────────────────────────────────
        sel_row = ctk.CTkFrame(sf, fg_color="transparent")
        sel_row.pack(fill="x", padx=12, pady=(6, 4))

        self._btn_swatch = tk.Label(
            sel_row, bg=self._color, width=4, height=2,
            relief="solid", bd=1, cursor="hand2")
        self._btn_swatch.pack(side="left", padx=(0, 4))
        ctk.CTkButton(sel_row, text="Button Colour",
                      width=120, height=26,
                      fg_color=C["blue_mid"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=lambda: self._set_target("button")
                      ).pack(side="left", padx=(0, 10))

        self._txt_swatch = tk.Label(
            sel_row, bg=self._text_color or C["text"],
            width=4, height=2, relief="solid", bd=1, cursor="hand2")
        self._txt_swatch.pack(side="left", padx=(0, 4))
        ctk.CTkButton(sel_row, text="Text Colour",
                      width=110, height=26,
                      fg_color=C["btn"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=lambda: self._set_target("text")
                      ).pack(side="left")

        # ── Active target label ───────────────────────────────────
        self._target_lbl = ctk.CTkLabel(
            sf, text="Editing: Button Colour",
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=C["amber"])
        self._target_lbl.pack(anchor="w", padx=12, pady=(0, 4))

        # ── Preset swatches ───────────────────────────────────────
        pf = tk.Frame(sf, bg=C["surface"])
        pf.pack(padx=12, pady=(0, 6))
        for i, col in enumerate(self.PRESETS):
            tk.Button(pf, bg=col, width=2, height=1,
                      relief="flat", bd=1, cursor="hand2",
                      command=lambda c=col: self._pick(c)
                      ).grid(row=i//8, column=i%8, padx=2, pady=2)

        # ── Hex entry + system picker ─────────────────────────────
        hex_row = ctk.CTkFrame(sf, fg_color="transparent")
        hex_row.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkLabel(hex_row, text="#",
                     font=ctk.CTkFont("Consolas", 12),
                     text_color=C["text"]).pack(side="left")
        self._hex_var = ctk.StringVar(
            value=self._color.lstrip("#") if self._color else "")
        self._hex_entry = ctk.CTkEntry(
            hex_row, textvariable=self._hex_var,
            width=90, font=ctk.CTkFont("Consolas", 11))
        self._hex_entry.pack(side="left", padx=4)
        self._hex_var.trace_add("write", self._on_hex)
        ctk.CTkButton(hex_row, text="System Picker", width=120,
                      fg_color=C["btn"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=self._sys_picker).pack(side="left", padx=4)
        ctk.CTkButton(hex_row, text="Reset",
                      width=60, fg_color=C["surface"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=self._reset_current).pack(side="left", padx=4)

        # ── Confirm / Cancel ──────────────────────────────────────
        br = ctk.CTkFrame(self, fg_color="transparent")
        br.pack(pady=10)
        ctk.CTkButton(br, text="Apply", width=120, height=34,
                      fg_color=C["green"],
                      font=ctk.CTkFont("Segoe UI", 12, "bold"),
                      command=self._confirm).pack(side="left", padx=6)
        ctk.CTkButton(br, text="Cancel", width=80, height=34,
                      fg_color=C["surface"],
                      command=self.destroy).pack(side="left", padx=6)

    def _set_target(self, target: str):
        self._active_target = target
        if target == "button":
            self._target_lbl.configure(text="Editing: Button Colour")
            self._hex_var.set(self._color.lstrip("#"))
        else:
            self._target_lbl.configure(text="Editing: Text Colour")
            self._hex_var.set(
                (self._text_color or C["text"]).lstrip("#"))

    def _pick(self, col: str):
        if self._active_target == "button":
            self._color = col
            self._btn_swatch.configure(bg=col)
        else:
            self._text_color = col
            self._txt_swatch.configure(bg=col)
        self._hex_var.set(col.lstrip("#"))

    def _on_hex(self, *_):
        val = self._hex_var.get().strip()
        if len(val) == 6:
            try:
                int(val, 16)
                self._pick("#" + val)
            except ValueError:
                pass

    def _sys_picker(self):
        cur = self._color if self._active_target == "button" \
            else (self._text_color or C["text"])
        col = colorchooser.askcolor(color=cur, title="Pick Colour")
        if col and col[1]:
            self._pick(col[1])

    def _reset_current(self):
        if self._active_target == "button":
            self._color = ""
            self._btn_swatch.configure(bg=C["btn"])
            self._hex_var.set("")
        else:
            self._text_color = ""
            self._txt_swatch.configure(bg=C["text"])
            self._hex_var.set("")

    def _confirm(self):
        self.result = {
            "label":      self._lv.get().strip() if self._allow_rename else "",
            "color":      self._color,
            "text_color": self._text_color,
        }
        self.destroy()

    def _confirm(self):
        self.result = {
            "label":      (self._lv.get().strip()
                           if self._allow_rename else ""),
            "color":      self._color,
            "text_color": self._text_color,
        }
        self.destroy()


# ═══════════════════════════════════════════════════════════════
# FX PANEL
# ═══════════════════════════════════════════════════════════════

class FXPanel(ctk.CTkToplevel):
    """Pedalboard FX editor for a soundboard slot."""

    EFFECTS = [
        ("volume",   "Volume Boost",    0.0,    3.0,  1.0, 0.05),
        ("pitch",    "Pitch Shift",    -12.0,  12.0,  0.0, 0.5),
        ("speed",    "Speed",           0.25,   4.0,  1.0, 0.05),
        ("reverb",   "Reverb",          0.0,    1.0,  0.3, 0.05),
        ("echo",     "Echo / Delay",    0.0,    1.0,  0.3, 0.05),
        ("lowpass",  "Low-pass (Hz)", 500.0, 20000.0, 4000.0, 100.0),
        ("highpass", "High-pass (Hz)", 20.0,  2000.0,  200.0, 10.0),
    ]

    def __init__(self, parent, slot_source, idx, cfg, audio, on_apply=None):
        super().__init__(parent)
        self.cfg        = cfg
        self.audio      = audio
        self.slot_source = slot_source
        self.idx        = idx
        self.on_apply   = on_apply
        self.title(f"🎛  FX — {cfg.config[slot_source][idx].get('label','')}")
        self.geometry("460x480")
        self.configure(fg_color=C["bg2"])
        self.grab_set()
        self._build()

    def _build(self):
        if not HAS_PEDALBOARD:
            ctk.CTkLabel(
                self,
                text="⚠  pedalboard not installed.\n"
                     "Run: pip install pedalboard",
                font=ctk.CTkFont("Segoe UI", 12),
                text_color=C["amber"]).pack(pady=40)
            return

        ctk.CTkLabel(self, text="🎛  Effects",
                     font=ctk.CTkFont("Segoe UI", 14, "bold"),
                     text_color=C["amber"]).pack(pady=(12, 6))

        sf = ctk.CTkScrollableFrame(self, fg_color="transparent")
        sf.pack(fill="both", expand=True, padx=12)

        slot       = self.cfg.config[self.slot_source][self.idx]
        fx_config  = slot.get("fx", {})
        self._vars = {}

        for key, label, mn, mx, default, res in self.EFFECTS:
            fx   = fx_config.get(key, {"enabled": False, "value": default})
            row  = ctk.CTkFrame(sf, fg_color=C["surface"], corner_radius=6)
            row.pack(fill="x", pady=2)

            en_var = ctk.BooleanVar(value=fx.get("enabled", False))
            ctk.CTkCheckBox(row, text=label, variable=en_var,
                            font=ctk.CTkFont("Segoe UI", 11),
                            text_color=C["text"],
                            fg_color=C["blue_mid"],
                            width=160).pack(side="left", padx=8, pady=6)

            val_var = ctk.DoubleVar(value=fx.get("value", default))
            val_lbl = ctk.CTkLabel(row, text=f"{val_var.get():.2f}",
                                   font=ctk.CTkFont("Consolas", 11),
                                   text_color=C["text_dim"], width=50)
            val_lbl.pack(side="right", padx=6)

            slider = ctk.CTkSlider(row, from_=mn, to=mx,
                                   variable=val_var, width=160,
                                   command=lambda v, vl=val_lbl,
                                   vv=val_var: vl.configure(
                                       text=f"{float(v):.2f}"))
            slider.pack(side="right", padx=4)
            self._vars[key] = (en_var, val_var)

        # Preview + apply
        br = ctk.CTkFrame(self, fg_color="transparent")
        br.pack(pady=10)
        ctk.CTkButton(br, text="▶ Preview", width=100, height=32,
                      fg_color=C["blue"],
                      command=self._preview).pack(side="left", padx=4)
        ctk.CTkButton(br, text="✓ Apply", width=100, height=32,
                      fg_color=C["green"],
                      command=self._apply).pack(side="left", padx=4)
        ctk.CTkButton(br, text="↩ Reset", width=80, height=32,
                      fg_color=C["surface"],
                      command=self._reset).pack(side="left", padx=4)
        ctk.CTkButton(br, text="Close", width=80, height=32,
                      fg_color=C["surface"],
                      command=self.destroy).pack(side="left", padx=4)

    def _collect(self) -> dict:
        return {k: {"enabled": ev.get(), "value": vv.get()}
                for k, (ev, vv) in self._vars.items()}

    def _preview(self):
        from audio import CH_FX_PREV
        slot = self.cfg.config[self.slot_source][self.idx]
        path = slot.get("file", "")
        if not path or not os.path.exists(path):
            return
        fx = self._collect()
        self.audio.prepare(CH_FX_PREV, path, fx)
        self.audio.play(CH_FX_PREV)

    def _apply(self):
        fx = self._collect()
        self.cfg.config[self.slot_source][self.idx]["fx"] = fx
        self.cfg.save()
        if self.on_apply:
            self.on_apply()
        self.destroy()

    def _reset(self):
        from config import DEFAULT_FX
        import copy
        self.cfg.config[self.slot_source][self.idx]["fx"] = \
            copy.deepcopy(DEFAULT_FX)
        self.cfg.save()
        self.destroy()


# ═══════════════════════════════════════════════════════════════
# POST-SHOW DIALOG  — the new show reminder
# ═══════════════════════════════════════════════════════════════

class PostShowDialog(ctk.CTkToplevel):
    """
    Appears when the host ends the show.
    Forces a title + description before dismissing.
    Provides copy-to-clipboard button.
    """

    def __init__(self, parent, cfg, duration_str: str = "",
                 session_summary: str = "",
                 log_lines: list = None,
                 go_live_wall=None):
        super().__init__(parent)
        self.cfg             = cfg
        self.duration_str    = duration_str
        self.session_summary = session_summary
        self.log_lines       = log_lines or []
        self.go_live_wall    = go_live_wall
        self._saved          = False

        self.title("📋  Post Your Show!")
        self.geometry("680x620")
        self.configure(fg_color=C["bg2"])
        self.grab_set()
        self.resizable(True, True)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build()

    def _build(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=0)
        hdr.pack(fill="x")

        ctk.CTkLabel(hdr,
                     text="🎙  Show Complete!  Don't forget to post.",
                     font=ctk.CTkFont("Segoe UI", 14, "bold"),
                     text_color=C["amber"]).pack(
                         side="left", padx=16, pady=12)

        if self.duration_str:
            ctk.CTkLabel(hdr, text=f"⏱  {self.duration_str}",
                         font=ctk.CTkFont("Segoe UI", 11),
                         text_color=C["text_dim"]).pack(
                             side="right", padx=16)

        # Body
        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=8)

        # Episode number row
        ep_row = ctk.CTkFrame(body, fg_color="transparent")
        ep_row.pack(fill="x", pady=(4, 8))
        ctk.CTkLabel(ep_row, text="Episode #:",
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C["text_dim"]).pack(side="left", padx=(0,8))
        self._ep_var = ctk.StringVar(
            value=str(self.cfg.config.get("episode_number", 1)))
        ctk.CTkEntry(ep_row, textvariable=self._ep_var,
                     width=70, font=ctk.CTkFont("Segoe UI", 11)
                     ).pack(side="left")

        # Title
        ctk.CTkLabel(body, text="Show Title:",
                     font=ctk.CTkFont("Segoe UI", 11, "bold"),
                     text_color=C["text"]).pack(anchor="w", pady=(0, 4))

        default_title = self.cfg.format_title(self.duration_str)
        self._title_var = ctk.StringVar(value=default_title)

        title_row = ctk.CTkFrame(body, fg_color="transparent")
        title_row.pack(fill="x", pady=(0, 4))
        self._title_entry = ctk.CTkEntry(
            title_row, textvariable=self._title_var,
            font=ctk.CTkFont("Segoe UI", 12), height=36)
        self._title_entry.pack(side="left", fill="x", expand=True,
                               padx=(0, 6))
        ctk.CTkButton(title_row, text="📋", width=36, height=36,
                      fg_color=C["btn"], hover_color=C["btn_hover"],
                      font=ctk.CTkFont("Segoe UI", 13),
                      command=lambda: self._copy(
                          self._title_var.get())
                      ).pack(side="left")

        # Description
        ctk.CTkLabel(body, text="Show Description / Notes:",
                     font=ctk.CTkFont("Segoe UI", 11, "bold"),
                     text_color=C["text"]).pack(
                         anchor="w", pady=(12, 4))
        ctk.CTkLabel(body,
                     text="Describe what happened on the show. "
                          "You can pull from your session log below.",
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C["text_dim"], justify="left"
                     ).pack(anchor="w", pady=(0, 4))

        self._desc_box = ctk.CTkTextbox(
            body, height=120,
            font=ctk.CTkFont("Segoe UI", 11),
            fg_color=C["surface"], text_color=C["text"],
            border_color=C["border"], border_width=1)
        self._desc_box.pack(fill="x")

        # Session log highlights
        if self.session_summary:
            ctk.CTkLabel(body, text="Session Log (for reference):",
                         font=ctk.CTkFont("Segoe UI", 11, "bold"),
                         text_color=C["text_dim"]).pack(
                             anchor="w", pady=(12, 4))
            log_box = ctk.CTkTextbox(
                body, height=100,
                font=ctk.CTkFont("Consolas", 11),
                fg_color=C["bg"],
                text_color=C["text_dim"],
                state="normal")
            log_box.insert("1.0", self.session_summary)
            log_box.configure(state="disabled")
            log_box.pack(fill="x")

        # Action buttons
        btn_frame = ctk.CTkFrame(self, fg_color=C["surface"],
                                  corner_radius=0)
        btn_frame.pack(fill="x", side="bottom")

        ctk.CTkButton(btn_frame,
                      text="📋 Copy",
                      width=80, height=38,
                      fg_color=C["blue_mid"],
                      font=ctk.CTkFont("Segoe UI", 11, "bold"),
                      command=self._copy_all
                      ).pack(side="left", padx=6, pady=8)

        ctk.CTkButton(btn_frame,
                      text="🎙️ Markers",
                      width=90, height=38,
                      fg_color=C["green_dim"],
                      hover_color=C["green"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=self._open_markers
                      ).pack(side="left", padx=4, pady=8)

        ctk.CTkButton(btn_frame,
                      text="📦 Archive",
                      width=90, height=38,
                      fg_color=C["amber"],
                      hover_color=C["amber_hi"] if "amber_hi" in C else C["amber"],
                      text_color=C["bg"],
                      font=ctk.CTkFont("Segoe UI", 11, "bold"),
                      command=self._archive_show
                      ).pack(side="left", padx=4, pady=8)

        ctk.CTkButton(btn_frame,
                      text="✓ Done",
                      width=80, height=38,
                      fg_color=C["green"],
                      font=ctk.CTkFont("Segoe UI", 12, "bold"),
                      command=self._done
                      ).pack(side="right", padx=6, pady=8)

        ctk.CTkButton(btn_frame,
                      text="Dismiss",
                      width=75, height=38,
                      fg_color=C["surface"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=self._on_close
                      ).pack(side="right", padx=4, pady=8)

    def _copy(self, text: str):
        try:
            import pyperclip
            pyperclip.copy(text)
        except Exception:
            self.clipboard_clear()
            self.clipboard_append(text)

    def _copy_all(self):
        title = self._title_var.get().strip()
        desc  = self._desc_box.get("1.0", "end").strip()
        combined = f"{title}\n\n{desc}" if desc else title
        self._copy(combined)

    def _open_markers(self):
        try:
            from ui_exp_features import MarkerExportDialog
            MarkerExportDialog(self, self.cfg,
                               self.log_lines, self.go_live_wall,
                               self.duration_str)
        except Exception as e:
            messagebox.showerror("Marker Export",
                                 f"Could not open marker export:\n{e}")

    def _archive_show(self):
        """Bundle session log, notes, recordings, and markers into a dated folder."""
        import shutil
        from datetime import datetime
        
        # Get episode info
        try:
            ep_num = int(self._ep_var.get())
        except ValueError:
            ep_num = self.cfg.config.get("episode_number", 1)
        
        # Create archive folder name
        if self.go_live_wall:
            date_str = self.go_live_wall.strftime("%Y-%m-%d")
        else:
            date_str = datetime.now().strftime("%Y-%m-%d")
        
        show_name = self.cfg.config.get("show_name", "Show").replace(" ", "_")
        folder_name = f"{show_name}_Ep{ep_num}_{date_str}"
        
        # Ask user where to create the archive
        from tkinter import filedialog
        base_dir = self.cfg.config.get(
            "archive_folder",
            str(DATA_DIR / "archives"))
        
        archive_path = filedialog.askdirectory(
            title="Select Archive Location",
            initialdir=base_dir)
        
        if not archive_path:
            return
        
        archive_folder = Path(archive_path) / folder_name
        try:
            archive_folder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror("Archive Failed", f"Could not create folder:\n{e}")
            return
        
        files_copied = []
        
        # 1. Save session log
        try:
            log_file = archive_folder / "session_log.txt"
            log_file.write_text(self.session_summary, encoding="utf-8")
            files_copied.append("session_log.txt")
        except Exception as e:
            log.warning(f"Archive session log: {e}")
        
        # 2. Save show title and description
        try:
            title = self._title_var.get().strip()
            desc = self._desc_box.get("1.0", "end").strip()
            post_file = archive_folder / "post_info.txt"
            post_content = f"TITLE:\n{title}\n\nDESCRIPTION:\n{desc}\n\nDURATION: {self.duration_str}"
            post_file.write_text(post_content, encoding="utf-8")
            files_copied.append("post_info.txt")
        except Exception as e:
            log.warning(f"Archive post info: {e}")
        
        # 3. Save notes
        try:
            notes_content = self.cfg.config.get("notes_content", {})
            for tab_name, content in notes_content.items():
                if content.strip():
                    safe_name = tab_name.replace(" ", "_").replace("/", "-")
                    notes_file = archive_folder / f"notes_{safe_name}.txt"
                    notes_file.write_text(content, encoding="utf-8")
                    files_copied.append(f"notes_{safe_name}.txt")
        except Exception as e:
            log.warning(f"Archive notes: {e}")
        
        # 4. Copy recent recordings (from today)
        try:
            rec_folder = Path(self.cfg.config.get(
                "recordings_folder",
                str(RECORDING_DIR)))
            if rec_folder.exists():
                today = datetime.now().strftime("%Y%m%d")
                recordings_dir = archive_folder / "recordings"
                recordings_dir.mkdir(exist_ok=True)
                for f in rec_folder.iterdir():
                    if f.is_file() and today in f.name:
                        shutil.copy2(f, recordings_dir / f.name)
                        files_copied.append(f"recordings/{f.name}")
        except Exception as e:
            log.warning(f"Archive recordings: {e}")
        
        # 5. Generate markers file
        try:
            markers = []
            for e in self.log_lines:
                ts = e.get("timestamp", "")
                t = e.get("type", "")
                if t == "sound":
                    markers.append(f"{ts}\t{e.get('label', 'Sound')}")
                elif t == "call_start":
                    markers.append(f"{ts}\tCall Started")
                elif t == "call_end":
                    markers.append(f"{ts}\tCall Ended ({e.get('duration', '')})")
                elif t in ("event", "stamp"):
                    markers.append(f"{ts}\t{e.get('text', '')}")
            if markers:
                markers_file = archive_folder / "markers.txt"
                markers_file.write_text("\n".join(markers), encoding="utf-8")
                files_copied.append("markers.txt")
        except Exception as e:
            log.warning(f"Archive markers: {e}")
        
        # Show success and open folder
        messagebox.showinfo(
            "Archive Complete",
            f"Show archived to:\n{archive_folder}\n\n"
            f"Files: {len(files_copied)}\n" +
            "\n".join(f"  • {f}" for f in files_copied[:8]) +
            (f"\n  ... and {len(files_copied)-8} more" if len(files_copied) > 8 else ""))
        
        # Open the folder
        try:
            os.startfile(str(archive_folder))
        except Exception:
            pass

    def _done(self):
        # Save episode number update
        try:
            ep = int(self._ep_var.get())
            self.cfg.config["episode_number"] = ep + 1
        except ValueError:
            self.cfg.increment_episode()
        self.cfg.save()
        self._saved = True
        self.destroy()

    def _on_close(self):
        if not self._saved:
            if not messagebox.askyesno(
                    "Skip Posting?",
                    "Are you sure you want to dismiss without posting?\n\n"
                    "The episode number will NOT be incremented.",
                    icon="warning"):
                return
        self.destroy()


# ═══════════════════════════════════════════════════════════════
# SETTINGS WINDOW
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# MICROSIP SETUP WIZARD
# ═══════════════════════════════════════════════════════════════

class MicroSIPWizard(ctk.CTkToplevel):
    """
    Auto-configures MicroSIP.ini to fire call events to the Companion.
    Writes cmdCallStart and cmdCallEnd using the user's Python path
    and the path to call_hook.py.
    """

    INI_PATH = Path.home() / "AppData" / "Roaming" / "MicroSIP" / "MicroSIP.ini"

    def __init__(self, parent):
        super().__init__(parent)
        self.title("MicroSIP Setup Wizard")
        self.geometry("560x520")
        self.configure(fg_color=C["bg2"])
        self.grab_set()
        self.lift()
        self._result = None
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="MicroSIP Setup Wizard",
                     font=ctk.CTkFont("Segoe UI", 14, "bold"),
                     text_color=C["amber"]).pack(pady=(14, 4))
        ctk.CTkLabel(self,
            text="This wizard writes the call hook settings into your\n"
                 "MicroSIP.ini automatically. MicroSIP must be closed first.",
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=C["text_dim"],
            justify="center").pack(pady=(0, 8))

        frm = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=8)
        frm.pack(fill="x", padx=16, pady=4)

        # ── Python executable ─────────────────────────────────────
        self._lbl(frm, "Python executable path:")
        py_row = ctk.CTkFrame(frm, fg_color="transparent")
        py_row.pack(fill="x", padx=12, pady=(0, 8))
        self._py_var = ctk.StringVar(value=self._detect_python())
        py_e = ctk.CTkEntry(py_row, textvariable=self._py_var,
                            width=380, font=ctk.CTkFont("Consolas", 11))
        py_e.pack(side="left", padx=(0, 4))
        ctk.CTkButton(py_row, text="Browse…", width=80, height=28,
                      fg_color=C["btn"],
                      command=self._browse_python).pack(side="left")

        # ── call_hook.py path ─────────────────────────────────────
        self._lbl(frm, "call_hook.py path:")
        hook_row = ctk.CTkFrame(frm, fg_color="transparent")
        hook_row.pack(fill="x", padx=12, pady=(0, 8))
        self._hook_var = ctk.StringVar(value=self._detect_hook())
        hook_e = ctk.CTkEntry(hook_row, textvariable=self._hook_var,
                              width=380, font=ctk.CTkFont("Consolas", 11))
        hook_e.pack(side="left", padx=(0, 4))
        ctk.CTkButton(hook_row, text="Browse…", width=80, height=28,
                      fg_color=C["btn"],
                      command=self._browse_hook).pack(side="left")

        # ── INI path ──────────────────────────────────────────────
        self._lbl(frm, "MicroSIP.ini path:")
        ini_row = ctk.CTkFrame(frm, fg_color="transparent")
        ini_row.pack(fill="x", padx=12, pady=(0, 10))
        self._ini_var = ctk.StringVar(value=str(self.INI_PATH))
        ctk.CTkEntry(ini_row, textvariable=self._ini_var,
                     width=380, font=ctk.CTkFont("Consolas", 11)
                     ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(ini_row, text="Browse…", width=80, height=28,
                      fg_color=C["btn"],
                      command=self._browse_ini).pack(side="left")

        # ── Preview ───────────────────────────────────────────────
        ctk.CTkLabel(self, text="Lines that will be written:",
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C["text_dim"]).pack(
                         anchor="w", padx=16, pady=(8, 2))
        self._preview = ctk.CTkTextbox(
            self, height=80, fg_color=C["surface"],
            font=ctk.CTkFont("Consolas", 11),
            text_color=C["text_dim"], state="disabled")
        self._preview.pack(fill="x", padx=16)

        # Status label
        self._status = ctk.CTkLabel(
            self, text="",
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=C["text_dim"])
        self._status.pack(pady=(6, 0))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=10)
        ctk.CTkButton(btn_row, text="Preview", width=90, height=32,
                      fg_color=C["btn"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=self._do_preview).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="Write to INI", width=120, height=32,
                      fg_color=C["blue_mid"],
                      font=ctk.CTkFont("Segoe UI", 11, "bold"),
                      command=self._do_write).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="Close", width=80, height=32,
                      fg_color=C["surface"],
                      command=self.destroy).pack(side="left", padx=4)

        # Auto-populate preview on open
        self._do_preview()

    def _lbl(self, parent, text):
        ctk.CTkLabel(parent, text=text,
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C["text_dim"],
                     anchor="w").pack(padx=12, pady=(8, 2), anchor="w")

    def _detect_python(self) -> str:
        import sys
        return sys.executable

    def _detect_hook(self) -> str:
        # Look next to this script file
        here = Path(__file__).parent / "call_hook.py"
        if here.exists():
            return str(here)
        return ""

    def _browse_python(self):
        path = filedialog.askopenfilename(
            title="Select Python Executable",
            filetypes=[("Python", "python.exe"), ("All", "*.*")])
        if path:
            self._py_var.set(path)
            self._do_preview()

    def _browse_hook(self):
        path = filedialog.askopenfilename(
            title="Select call_hook.py",
            filetypes=[("Python", "*.py"), ("All", "*.*")])
        if path:
            self._hook_var.set(path)
            self._do_preview()

    def _browse_ini(self):
        path = filedialog.askopenfilename(
            title="Select MicroSIP.ini",
            filetypes=[("INI", "*.ini"), ("All", "*.*")])
        if path:
            self._ini_var.set(path)

    def _make_lines(self):
        py   = self._py_var.get().strip()
        hook = self._hook_var.get().strip()
        # Wrap paths containing spaces in quotes
        if " " in py:
            py = f'"{py}"'
        if " " in hook:
            hook = f'"{hook}"'
        start = f'cmdCallStart={py} {hook} start'
        end   = f'cmdCallEnd={py} {hook} end'
        return start, end

    def _do_preview(self):
        try:
            start, end = self._make_lines()
            self._preview.configure(state="normal")
            self._preview.delete("1.0", "end")
            self._preview.insert("end", f"{start}\n{end}")
            self._preview.configure(state="disabled")
        except Exception as e:
            self._status.configure(
                text=f"Preview error: {e}", text_color=C["red"])

    def _do_write(self):
        ini_path = Path(self._ini_var.get().strip())
        if not ini_path.exists():
            messagebox.showerror(
                "INI Not Found",
                f"MicroSIP.ini not found at:\n{ini_path}\n\n"
                "Make sure MicroSIP has been run at least once,\n"
                "then browse to the correct location.")
            return

        py   = self._py_var.get().strip()
        hook = self._hook_var.get().strip()

        if not py or not hook:
            messagebox.showerror("Missing Paths",
                "Please fill in both the Python path and the hook script path.")
            return

        # Check for spaces — MicroSIP won't fire hooks with spaces in the path
        hook_clean = hook.strip('"')
        if " " in hook_clean:
            messagebox.showwarning(
                "Path Contains Spaces",
                f"The call_hook.py path contains spaces:\n\n"
                f"  {hook_clean}\n\n"
                f"MicroSIP cannot fire a hook with spaces in the path.\n\n"
                f"The app should have auto-fixed this on startup.\n"
                f"If you see this, move the folder to a path with no spaces\n"
                f"and re-run the wizard.")
            return

        if not Path(hook_clean).exists():
            messagebox.showerror("Hook Not Found",
                f"call_hook.py not found at:\n{hook_clean}\n\n"
                "Make sure the path is correct.")
            return

        start_line, end_line = self._make_lines()

        # Read existing INI
        try:
            text = ini_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            messagebox.showerror("Read Error", str(e))
            return

        # Back up the INI first
        backup = ini_path.with_suffix(".ini.bak")
        try:
            backup.write_text(text, encoding="utf-8")
        except Exception:
            pass

        # Process lines — replace existing keys or append to [app] section
        lines     = text.splitlines()
        new_lines = []
        wrote_start = False
        wrote_end   = False

        for line in lines:
            stripped = line.strip()
            if stripped.lower().startswith("cmdcallstart="):
                new_lines.append(start_line)
                wrote_start = True
            elif stripped.lower().startswith("cmdcallend="):
                new_lines.append(end_line)
                wrote_end = True
            else:
                new_lines.append(line)

        # If keys weren't found, append at end (MicroSIP reads them globally)
        if not wrote_start:
            new_lines.append(start_line)
        if not wrote_end:
            new_lines.append(end_line)

        try:
            ini_path.write_text("\n".join(new_lines), encoding="utf-8")
        except Exception as e:
            messagebox.showerror("Write Error", str(e))
            return

        self._status.configure(
            text=f"Written successfully. Backup saved to {backup.name}",
            text_color=C["green"])
        messagebox.showinfo(
            "Done",
            f"MicroSIP.ini updated successfully.\n\n"
            f"Backup saved to:\n{backup}\n\n"
            f"Start MicroSIP and make a test call to verify.")


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent, cfg, app):
        super().__init__(parent)
        self.cfg = cfg
        self.app = app
        self.title("⚙  Settings")
        self.geometry("700x720")
        self.configure(fg_color=C["bg2"])
        self.grab_set()
        self._browser_paths = {}
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="⚙  Settings",
                     font=ctk.CTkFont("Segoe UI", 14, "bold"),
                     text_color=C["amber"]).pack(pady=(12, 4))

        tabs = ctk.CTkTabview(
            self, fg_color=C["surface"],
            segmented_button_fg_color=C["elevated"],
            segmented_button_selected_color=C["blue_mid"])
        tabs.pack(fill="both", expand=True, padx=12, pady=4)
        self._tabs = tabs

        for n in ["Streaming", "Audio", "Soundboard",
                  "Websites", "Show", "Hotkeys", "Visual",
                  "Integrations", "About"]:
            tabs.add(n)

        self._tab_streaming(tabs.tab("Streaming"))
        self._tab_show(tabs.tab("Show"))
        self._tab_audio(tabs.tab("Audio"))
        self._tab_soundboard(tabs.tab("Soundboard"))
        self._tab_hotkeys(tabs.tab("Hotkeys"))
        self._tab_websites(tabs.tab("Websites"))
        self._tab_visual(tabs.tab("Visual"))
        self._tab_integrations(tabs.tab("Integrations"))
        self._tab_about(tabs.tab("About"))

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(pady=8)
        ctk.CTkButton(row, text="💾  Save & Close",
                      fg_color=C["blue_mid"], width=160,
                      font=ctk.CTkFont("Segoe UI", 12, "bold"),
                      command=self._save).pack(side="left", padx=6)
        ctk.CTkButton(row, text="Cancel",
                      fg_color=C["surface"], width=90,
                      command=self.destroy).pack(side="left", padx=6)

    def _lbl(self, p, t, bold=False):
        ctk.CTkLabel(p, text=t,
                     font=ctk.CTkFont("Segoe UI", 11,
                                       "bold" if bold else "normal"),
                     text_color=C["text"] if bold else C["text_dim"],
                     anchor="w").pack(padx=12, pady=(8,1), anchor="w")

    # ── Streaming tab ─────────────────────────────────────────────

    def _tab_streaming(self, p):
        from streaming import StreamEngine as SE
        sf = ctk.CTkScrollableFrame(p, fg_color="transparent")
        sf.pack(fill="both", expand=True)

        if not SE.dependencies_ok():
            ctk.CTkLabel(sf,
                text="⚠  sounddevice / lameenc not installed.\n"
                     "Run:  pip install sounddevice lameenc",
                font=ctk.CTkFont("Segoe UI", 11),
                text_color=C["amber"],
                justify="left").pack(anchor="w", padx=12, pady=8)

        # ── Masked field helper ───────────────────────────────────
        self._stream_vars  = {}
        self._stream_shows = {}   # key → show/hide state var

        def _masked_row(parent, label, key, default):
            """Field that starts hidden with a reveal toggle."""
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=f"{label}:", width=150,
                         font=ctk.CTkFont("Segoe UI", 11),
                         text_color=C["text"], anchor="w").pack(side="left")
            var     = ctk.StringVar(
                value=str(self.cfg.config.get(key, default)))
            show_v  = ctk.BooleanVar(value=False)
            entry   = ctk.CTkEntry(
                row, textvariable=var, width=210,
                font=ctk.CTkFont("Consolas", 11), show="•")
            entry.pack(side="left", padx=(0, 4))

            def _toggle(e=entry, sv=show_v):
                sv.set(not sv.get())
                e.configure(show="" if sv.get() else "•")
                btn.configure(text="Hide" if sv.get() else "Show")

            btn = ctk.CTkButton(
                row, text="Show", width=46, height=26,
                fg_color=C["btn"], hover_color=C["btn_hover"],
                font=ctk.CTkFont("Segoe UI", 11),
                command=_toggle)
            btn.pack(side="left")
            self._stream_vars[key]  = var
            self._stream_shows[key] = show_v

        def _plain_row(parent, label, key, default):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=f"{label}:", width=150,
                         font=ctk.CTkFont("Segoe UI", 11),
                         text_color=C["text"], anchor="w").pack(side="left")
            var = ctk.StringVar(
                value=str(self.cfg.config.get(key, default)))
            ctk.CTkEntry(row, textvariable=var, width=260,
                         font=ctk.CTkFont("Consolas", 11)).pack(side="left")
            self._stream_vars[key] = var

        self._lbl(sf, "Server", bold=True)
        _plain_row(sf,  "Host",           "stream_host",   "")
        _plain_row(sf,  "Port",           "stream_port",   "80")
        _masked_row(sf, "Mount Point",    "stream_mount",  "/live")
        _masked_row(sf, "Username",       "stream_user",   "source")
        _masked_row(sf, "Password",       "stream_password", "")

        self._lbl(sf, "Encoding", bold=True)
        _plain_row(sf,  "Bitrate (kbps)", "stream_bitrate", "128")

        self._lbl(sf, "Audio Input Device", bold=True)
        dev_row = ctk.CTkFrame(sf, fg_color="transparent")
        dev_row.pack(fill="x", pady=3)
        ctk.CTkLabel(dev_row, text="Device:", width=150,
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C["text"], anchor="w").pack(side="left")
        dev_names = ["default"] + [name for _, name in SE.list_input_devices()]
        cur_dev   = self.cfg.config.get("stream_audio_device", "default")
        self._stream_dev_var = ctk.StringVar(value=cur_dev)
        ctk.CTkOptionMenu(
            dev_row, variable=self._stream_dev_var,
            values=dev_names, width=260,
            font=ctk.CTkFont("Segoe UI", 11)).pack(side="left")

        self._lbl(sf, "Reconnect", bold=True)
        rc_row = ctk.CTkFrame(sf, fg_color="transparent")
        rc_row.pack(fill="x", pady=3)
        ctk.CTkLabel(rc_row, text="Auto-Reconnect:", width=150,
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C["text"], anchor="w").pack(side="left")
        self._stream_reconnect_var = ctk.BooleanVar(
            value=self.cfg.config.get("stream_auto_reconnect", True))
        ctk.CTkCheckBox(
            rc_row, text="", variable=self._stream_reconnect_var,
            fg_color=C["green"], hover_color=C["green_dim"],
            checkmark_color=C["bg"]).pack(side="left", padx=4)

        att_row = ctk.CTkFrame(sf, fg_color="transparent")
        att_row.pack(fill="x", pady=3)
        ctk.CTkLabel(att_row, text="Max Attempts:", width=150,
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C["text"], anchor="w").pack(side="left")
        self._stream_attempts_var = ctk.StringVar(
            value=str(self.cfg.config.get("stream_reconnect_attempts", 5)))
        ctk.CTkEntry(att_row, textvariable=self._stream_attempts_var,
                     width=60,
                     font=ctk.CTkFont("Consolas", 11)).pack(side="left")

        ctk.CTkLabel(sf,
            text="🔒  Mount point, username and password are hidden by default.\n"
                 "    Click Show to reveal. Never share your config file.",
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=C["text_dim"],
            justify="left").pack(anchor="w", padx=12, pady=(10, 4))

    # ── Show tab ──────────────────────────────────────────────────

    def _tab_show(self, p):
        sf = ctk.CTkScrollableFrame(p, fg_color="transparent")
        sf.pack(fill="both", expand=True)

        self._lbl(sf, "Show Name:", bold=True)
        self._show_name = ctk.StringVar(
            value=self.cfg.config.get("show_name", ""))
        ctk.CTkEntry(sf, textvariable=self._show_name,
                     width=400).pack(padx=12, anchor="w")

        self._lbl(sf, "Current Episode Number:", bold=True)
        self._ep_num = ctk.StringVar(
            value=str(self.cfg.config.get("episode_number", 1)))
        ctk.CTkEntry(sf, textvariable=self._ep_num,
                     width=100).pack(padx=12, anchor="w")

        self._lbl(sf, "Title Template:", bold=True)
        ctk.CTkLabel(sf,
                     text="Variables: {n} = episode #, {date} = today's date,\n"
                          "{show} = show name, {duration} = show length",
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C["text_dim"], justify="left"
                     ).pack(padx=12, anchor="w")
        self._title_tmpl = ctk.StringVar(
            value=self.cfg.config.get(
                "title_template", "Episode {n} — {date}"))
        ctk.CTkEntry(sf, textvariable=self._title_tmpl,
                     width=500).pack(padx=12, anchor="w")

        ctk.CTkFrame(sf, height=1, fg_color=C["border"]).pack(
            fill="x", padx=12, pady=(16, 4))

        self._lbl(sf, "Note Tabs (comma-separated):", bold=True)
        self._note_tabs = ctk.StringVar(
            value=", ".join(self.cfg.config.get(
                "note_tabs", ["Show Notes", "Premises & Ideas"])))
        ctk.CTkEntry(sf, textvariable=self._note_tabs,
                     width=400).pack(padx=12, anchor="w")

    # ── Audio tab ─────────────────────────────────────────────────

    def _tab_audio(self, p):
        sf = ctk.CTkScrollableFrame(p, fg_color="transparent")
        sf.pack(fill="both", expand=True)

        # Output device
        ctk.CTkLabel(sf, text="🔊  Output Device (soundboard playback)",
                     font=ctk.CTkFont("Segoe UI", 11, "bold"),
                     text_color=C["amber"]).pack(
                         padx=12, pady=(12,2), anchor="w")
        out_devs   = self.app.audio.get_output_devices()
        out_labels = [d[1] for d in out_devs]
        cur_out    = self.cfg.config.get(
            "audio_output_device", "Default (System)")
        self._out_dev = ctk.StringVar(
            value=cur_out if cur_out in out_labels else out_labels[0])
        ctk.CTkOptionMenu(sf, values=out_labels,
                          variable=self._out_dev, width=420,
                          ).pack(padx=12, anchor="w", pady=(0,8))

        # Input device
        ctk.CTkLabel(sf, text="🎙  Input Device (tape recorder capture)",
                     font=ctk.CTkFont("Segoe UI", 11, "bold"),
                     text_color=C["amber"]).pack(
                         padx=12, pady=(4,2), anchor="w")
        ctk.CTkLabel(sf,
                     text="For full show recording: choose Voicemeeter Output or Stereo Mix.",
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C["text_dim"]).pack(padx=12, anchor="w")
        in_devs    = self.app.audio.get_input_devices()
        in_labels  = [d[1] for d in in_devs]
        cur_in     = self.cfg.config.get(
            "audio_input_device", "Default (System)")
        self._in_dev = ctk.StringVar(
            value=cur_in if cur_in in in_labels else in_labels[0])
        ctk.CTkOptionMenu(sf, values=in_labels,
                          variable=self._in_dev, width=420,
                          ).pack(padx=12, anchor="w", pady=(0,8))

        ctk.CTkFrame(sf, height=1, fg_color=C["border"]).pack(
            fill="x", padx=12, pady=(4,8))

        # Recordings folder
        ctk.CTkLabel(sf, text="📁  Recordings Folder",
                     font=ctk.CTkFont("Segoe UI", 11, "bold"),
                     text_color=C["amber"]).pack(
                         padx=12, pady=(4,2), anchor="w")
        self._rec_folder = self.cfg.config.get(
            "recordings_folder", str(RECORDING_DIR))
        rr = ctk.CTkFrame(sf, fg_color="transparent")
        rr.pack(fill="x", padx=12, pady=(0,8))
        self._rec_lbl = ctk.CTkLabel(
            rr, text=self._rec_folder,
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=C["text_dim"], anchor="w", wraplength=320)
        self._rec_lbl.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(rr, text="Browse", width=80, height=26,
                      fg_color=C["blue"],
                      command=self._pick_rec_folder).pack(side="right")

        # Recording format
        self._lbl(sf, "Recording Format:")
        self._rec_fmt = ctk.StringVar(
            value=self.cfg.config.get("recording_format", "wav"))
        fr = ctk.CTkFrame(sf, fg_color="transparent")
        fr.pack(fill="x", padx=12)
        for val, lbl in [("wav","WAV (lossless)"), ("mp3","MP3 (compressed)")]:
            ctk.CTkRadioButton(
                fr, text=lbl, variable=self._rec_fmt, value=val,
                fg_color=C["blue_mid"]).pack(side="left", padx=(0,16))

        ctk.CTkFrame(sf, height=1, fg_color=C["border"]).pack(
            fill="x", padx=12, pady=(12,8))

        self._lbl(sf, "Fade Out Duration (seconds):")
        self._fade = ctk.StringVar(
            value=str(self.cfg.config.get("fade_duration", 3.0)))
        ctk.CTkOptionMenu(sf, values=["1","2","3","5","8","10"],
                          variable=self._fade, width=100
                          ).pack(padx=12, anchor="w")

        self._lbl(sf, "Minimum sound duration to log (seconds):")
        self._log_min = ctk.StringVar(
            value=str(self.cfg.config.get("log_audio_min_secs", 30)))
        ctk.CTkOptionMenu(sf,
                          values=["0","5","10","15","20","30","45","60"],
                          variable=self._log_min, width=100
                          ).pack(padx=12, anchor="w")


        ctk.CTkFrame(sf, height=1, fg_color=C["border"]).pack(
            fill="x", padx=12, pady=(12, 8))

        # Mic input device
        ctk.CTkLabel(sf, text="🎙️  Mic Input Device",
                     font=ctk.CTkFont("Segoe UI", 11, "bold"),
                     text_color=C["amber"]).pack(
                         padx=12, pady=(0, 2), anchor="w")
        ctk.CTkLabel(sf,
                     text="The Windows input device the Mute button controls.\n"
                          "For Voicemeeter: pick the strip your mic is on.",
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C["text_dim"],
                     justify="left").pack(padx=12, anchor="w", pady=(0, 4))
        mic_devs   = self.app.audio.get_input_devices()
        mic_labels = [d[1] for d in mic_devs]
        cur_mic    = self.cfg.config.get(
            "mic_input_device", "Default (System)")
        self._mic_dev = ctk.StringVar(
            value=cur_mic if cur_mic in mic_labels else mic_labels[0])
        ctk.CTkOptionMenu(sf, values=mic_labels,
                          variable=self._mic_dev, width=420
                          ).pack(padx=12, anchor="w", pady=(0, 10))

        # Duck level
        ctk.CTkLabel(sf, text="🎚  Duck Level",
                     font=ctk.CTkFont("Segoe UI", 11, "bold"),
                     text_color=C["amber"]).pack(
                         padx=12, pady=(0, 2), anchor="w")
        ctk.CTkLabel(sf,
                     text="How far the VOL/FADE slider drops when you press Duck.",
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C["text_dim"]).pack(
                         padx=12, anchor="w", pady=(0, 4))
        self._duck_level = ctk.DoubleVar(
            value=self.cfg.config.get("mic_duck_level", 0.3))
        self._duck_level_lbl = ctk.CTkLabel(
            sf, text=f'{self._duck_level.get():.0%}',
            font=ctk.CTkFont("Segoe UI", 11), text_color=C["text_dim"])
        self._duck_level_lbl.pack(padx=12, anchor="w")
        ctk.CTkSlider(sf, from_=0.0, to=1.0, width=280,
                      variable=self._duck_level,
                      command=lambda v: self._duck_level_lbl.configure(
                          text=f"{float(v):.0%}")
                      ).pack(padx=12, anchor="w", pady=(0, 12))

    def _pick_rec_folder(self):
        f = filedialog.askdirectory(
            title="Choose Recordings Folder",
            initialdir=self._rec_folder)
        if f:
            self._rec_folder = f
            self._rec_lbl.configure(text=f)

    # ── Soundboard tab ────────────────────────────────────────────

    def _tab_soundboard(self, p):
        sf = ctk.CTkScrollableFrame(p, fg_color="transparent")
        sf.pack(fill="both", expand=True)

        self._lbl(sf, "Pinned Row Button Count:")
        self._pinned = ctk.StringVar(
            value=str(self.cfg.config.get("pinned_count", 8)))
        ctk.CTkOptionMenu(sf,
                          values=["2","3","4","5","6","7","8","10","12"],
                          variable=self._pinned, width=100
                          ).pack(padx=12, anchor="w")

        self._lbl(sf, "Music Bank (for detailed logging):")
        groups = [g["name"] for g in
                  self.cfg.config.get("soundboard_groups", [])]
        self._music_bank = ctk.StringVar(
            value=self.cfg.config.get("music_bank_name", "Music"))
        if groups:
            ctk.CTkOptionMenu(sf, values=groups,
                              variable=self._music_bank, width=180
                              ).pack(padx=12, anchor="w")

        # Playback Mode Settings
        ctk.CTkFrame(sf, height=1, fg_color=C["border"]).pack(
            fill="x", padx=12, pady=(12,4))
        ctk.CTkLabel(sf, text="Playback Modes",
                     font=ctk.CTkFont("Segoe UI", 11, "bold"),
                     text_color=C["amber"]).pack(padx=12, anchor="w", pady=(4,2))

        # Touch Play mode
        self._touch_play_var = ctk.BooleanVar(
            value=self.cfg.config.get("touch_play_mode", False))
        ctk.CTkCheckBox(sf, text="Touch Play Mode (click always restarts sound)",
                        variable=self._touch_play_var,
                        font=ctk.CTkFont("Segoe UI", 11)
                        ).pack(padx=12, anchor="w", pady=2)

        # Automix
        self._automix_var = ctk.BooleanVar(
            value=self.cfg.config.get("automix_enabled", False))
        ctk.CTkCheckBox(sf, text="Automix (crossfade between queue tracks)",
                        variable=self._automix_var,
                        font=ctk.CTkFont("Segoe UI", 11)
                        ).pack(padx=12, anchor="w", pady=2)

        # Crossfade duration
        cf_row = ctk.CTkFrame(sf, fg_color="transparent")
        cf_row.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(cf_row, text="Crossfade duration (sec):",
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C["text_dim"]).pack(side="left")
        self._crossfade_var = ctk.StringVar(
            value=str(self.cfg.config.get("automix_crossfade_sec", 3)))
        ctk.CTkEntry(cf_row, textvariable=self._crossfade_var, width=50
                     ).pack(side="left", padx=8)

        # Board Gain
        ctk.CTkFrame(sf, height=1, fg_color=C["border"]).pack(
            fill="x", padx=12, pady=(12,4))
        ctk.CTkLabel(sf, text="Board Gain",
                     font=ctk.CTkFont("Segoe UI", 11, "bold"),
                     text_color=C["amber"]).pack(padx=12, anchor="w", pady=(4,2))
        ctk.CTkLabel(sf, text="Boost soundboard clips to cut through music",
                     font=ctk.CTkFont("Segoe UI", 10),
                     text_color=C["text_dim"]).pack(padx=12, anchor="w")

        gain_row = ctk.CTkFrame(sf, fg_color="transparent")
        gain_row.pack(fill="x", padx=12, pady=4)

        self._board_gain_var = ctk.IntVar(
            value=self.cfg.config.get("board_gain_db", 0))
        self._board_gain_lbl = ctk.CTkLabel(
            gain_row, text=f"+{self._board_gain_var.get()} dB", width=50,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            text_color=C["amber"])
        self._board_gain_lbl.pack(side="left")

        self._board_gain_slider = ctk.CTkSlider(
            gain_row, from_=0, to=12, number_of_steps=12, width=200,
            command=self._on_board_gain_slider)
        self._board_gain_slider.set(self._board_gain_var.get())
        self._board_gain_slider.pack(side="left", padx=8)

        ctk.CTkLabel(gain_row, text="0=off, 6=2x, 12=4x louder",
                     font=ctk.CTkFont("Segoe UI", 10),
                     text_color=C["text_dim"]).pack(side="left", padx=8)

        ctk.CTkFrame(sf, height=1, fg_color=C["border"]).pack(
            fill="x", padx=12, pady=(12,4))
        ctk.CTkLabel(sf, text="Bank Editor",
                     font=ctk.CTkFont("Segoe UI", 11, "bold"),
                     text_color=C["amber"]).pack(padx=12, anchor="w")

        self._bank_frame  = ctk.CTkFrame(sf, fg_color="transparent")
        self._bank_frame.pack(fill="x", padx=12, pady=4)
        self._grp_entries = []
        self._redraw_banks()

        ctk.CTkButton(sf, text="+ Add Bank", width=100, height=28,
                      fg_color=C["blue_mid"],
                      command=self._add_bank).pack(
                          padx=12, anchor="w", pady=4)

    def _redraw_banks(self):
        for w in self._bank_frame.winfo_children():
            w.destroy()
        self._grp_entries.clear()
        for i, g in enumerate(self.cfg.config.get(
                "soundboard_groups", [])):
            row = ctk.CTkFrame(self._bank_frame,
                               fg_color=C["surface"], corner_radius=5)
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=f"{i+1}.", width=24,
                         text_color=C["text_dim"]).pack(
                             side="left", padx=(6,0))
            ne = ctk.CTkEntry(row, width=140)
            ne.insert(0, g.get("name",""))
            ne.pack(side="left", padx=4, pady=4)
            entries = [ne]
            for lbl, key, w in [("R","rows",48),("C","cols",48)]:
                ctk.CTkLabel(row, text=lbl, width=12,
                             text_color=C["text_dim"]).pack(side="left")
                e = ctk.CTkEntry(row, width=w)
                e.insert(0, str(g.get(key, 2 if key=="rows" else 8)))
                e.pack(side="left", padx=2, pady=4)
                entries.append(e)

            # Bank color swatch
            bank_color = g.get("color", "") or C["neutral"]
            color_box = [bank_color]  # mutable ref
            swatch = tk.Label(row, bg=bank_color, width=3, height=1,
                              relief="solid", bd=1, cursor="hand2")
            swatch.pack(side="left", padx=4)

            def _pick_bank_color(sw=swatch, cb=color_box, gi=i, glist=g):
                col = colorchooser.askcolor(color=cb[0],
                                             title=f"Bank Color")
                if col and col[1]:
                    cb[0] = col[1]
                    sw.configure(bg=col[1])
                    self.cfg.config["soundboard_groups"][gi]["color"] = col[1]
            swatch.bind("<Button-1>", lambda e, f=_pick_bank_color: f())
            entries.append(color_box)  # store ref so save can read it

            self._grp_entries.append((i, entries))
            ctk.CTkButton(row, text="🗑", width=28, height=28,
                          corner_radius=4, fg_color=C["surface"],
                          hover_color=C["red_dim"],
                          command=lambda idx=i: self._del_bank(idx)
                          ).pack(side="right", padx=4)
            ctk.CTkButton(row, text="↓", width=24, height=28,
                          corner_radius=4, fg_color=C["surface"],
                          hover_color=C["btn_hover"],
                          command=lambda idx=i: self._move_bank(idx, 1)
                          ).pack(side="right", padx=1)
            ctk.CTkButton(row, text="↑", width=24, height=28,
                          corner_radius=4, fg_color=C["surface"],
                          hover_color=C["btn_hover"],
                          command=lambda idx=i: self._move_bank(idx, -1)
                          ).pack(side="right", padx=1)

    def _add_bank(self):
        self.cfg.config["soundboard_groups"].append(
            {"name": f"Bank {len(self.cfg.config['soundboard_groups'])+1}",
             "rows": 2, "cols": 8, "color": ""})
        self._redraw_banks()

    def _on_board_gain_slider(self, val):
        """Handle board gain slider change."""
        db = int(round(val))
        self._board_gain_var.set(db)
        self._board_gain_lbl.configure(text=f"+{db} dB")

    def _del_bank(self, idx):
        grps = self.cfg.config["soundboard_groups"]
        if len(grps) > 1:
            grps.pop(idx)
            self._redraw_banks()

    def _move_bank(self, idx: int, direction: int):
        """Move a bank up (-1) or down (+1), swapping its slots with the neighbour."""
        grps  = self.cfg.config["soundboard_groups"]
        slots = self.cfg.config["soundboard"]
        other = idx + direction
        if other < 0 or other >= len(grps):
            return

        # Calculate offsets for both banks
        def _offset(bank_i):
            pos = 0
            for k in range(bank_i):
                pos += grps[k].get("rows", 2) * grps[k].get("cols", 8)
            return pos

        idx_start   = _offset(idx)
        idx_size    = grps[idx].get("rows", 2) * grps[idx].get("cols", 8)
        other_start = _offset(other)
        other_size  = grps[other].get("rows", 2) * grps[other].get("cols", 8)

        # Extract both banks' slots
        idx_slots   = slots[idx_start:   idx_start   + idx_size]
        other_slots = slots[other_start: other_start + other_size]

        # Swap groups metadata
        grps[idx], grps[other] = grps[other], grps[idx]

        # Recalculate offsets after swap and write slots back
        new_idx_start   = _offset(idx)
        new_other_start = _offset(other)
        for j, s in enumerate(other_slots):
            slots[new_idx_start + j] = s
        for j, s in enumerate(idx_slots):
            slots[new_other_start + j] = s

        self._redraw_banks()

    # ── Hotkeys tab ───────────────────────────────────────────────

    # Actions that can have hotkeys assigned
    HOTKEY_ACTIONS = [
        ("pinned_1", "Pinned Button 1"),
        ("pinned_2", "Pinned Button 2"),
        ("pinned_3", "Pinned Button 3"),
        ("pinned_4", "Pinned Button 4"),
        ("pinned_5", "Pinned Button 5"),
        ("pinned_6", "Pinned Button 6"),
        ("pinned_7", "Pinned Button 7"),
        ("pinned_8", "Pinned Button 8"),
        ("go_live", "GO LIVE / END LIVE"),
        ("cough", "COUGH (Push-to-Talk Mute)"),
        ("break_on", "BREAK (Mute + Fade Up)"),
        ("break_off", "BACK (Return from Break)"),
        ("panic", "PANIC (Stop All)"),
        ("queue_play", "Queue Play/Pause"),
        ("queue_next", "Queue Next Track"),
        ("record_toggle", "Start/Stop Recording"),
        ("countdown_toggle", "Countdown Start/Stop"),
        ("stopwatch_lap", "Stopwatch Lap"),
        ("mute_mic", "Mute Mic Toggle"),
        ("mini_mode", "Toggle Mini Mode"),
        ("gold_moment", "Gold Moment"),
        ("timestamp", "Add Timestamp"),
    ]

    HOTKEY_DEFAULTS = {
        "pinned_1": "F1",
        "pinned_2": "F2",
        "pinned_3": "F3",
        "pinned_4": "F4",
        "pinned_5": "F5",
        "pinned_6": "F6",
        "pinned_7": "F7",
        "pinned_8": "F8",
        "go_live": "F9",
        "cough": "F10",
        "panic": "F12",
        "queue_play": "space",
        "queue_next": "n",
    }

    def _tab_hotkeys(self, p):
        self._hk = {}
        self._hk_capturing = None

        # Header with instructions
        hdr = ctk.CTkFrame(p, fg_color="transparent")
        hdr.pack(fill="x", padx=12, pady=(12, 4))
        ctk.CTkLabel(hdr, text="⌨  Configure Hotkeys",
                     font=ctk.CTkFont("Segoe UI", 12, "bold"),
                     text_color=C["amber"]).pack(side="left")
        ctk.CTkLabel(hdr, text="Click a field, then press your key combo",
                     font=ctk.CTkFont("Segoe UI", 10),
                     text_color=C["text_dim"]).pack(side="right")

        # Scrollable list
        sf = ctk.CTkScrollableFrame(p, fg_color="transparent")
        sf.pack(fill="both", expand=True, padx=8, pady=4)

        hotkeys = self.cfg.config.get("hotkeys", {})

        for action_id, action_label in self.HOTKEY_ACTIONS:
            row = ctk.CTkFrame(sf, fg_color="transparent")
            row.pack(fill="x", pady=2)

            ctk.CTkLabel(row, text=action_label, width=180,
                         font=ctk.CTkFont("Segoe UI", 11),
                         text_color=C["text"], anchor="w").pack(side="left", padx=(4, 0))

            entry = ctk.CTkEntry(row, width=140,
                                 font=ctk.CTkFont("Segoe UI", 11),
                                 placeholder_text="Click to set...")
            entry.pack(side="left", padx=8)
            combo = hotkeys.get(action_id, "")
            if combo:
                entry.insert(0, combo)
            entry.bind("<FocusIn>", lambda e, aid=action_id: self._hk_start_capture(aid))
            entry.bind("<FocusOut>", lambda e: self._hk_stop_capture())
            entry.bind("<Key>", lambda e, aid=action_id: self._hk_on_key(e, aid))
            self._hk[action_id] = entry

            ctk.CTkButton(row, text="✕", width=28, height=26,
                          fg_color=C["btn"], hover_color=C["red_dim"],
                          font=ctk.CTkFont("Segoe UI", 10),
                          command=lambda aid=action_id: self._hk_clear_one(aid)
                          ).pack(side="left", padx=2)

        # Button bar
        btn_frame = ctk.CTkFrame(p, fg_color="transparent")
        btn_frame.pack(fill="x", padx=12, pady=(4, 8))

        ctk.CTkButton(btn_frame, text="Reset to Defaults", width=120, height=28,
                      fg_color=C["btn"], hover_color=C["btn_hover"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=self._hk_reset_defaults
                      ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(btn_frame, text="Clear All", width=80, height=28,
                      fg_color=C["btn"], hover_color=C["red_dim"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=self._hk_clear_all
                      ).pack(side="left")

    def _hk_start_capture(self, action_id):
        """Start capturing keystrokes for an action."""
        self._hk_capturing = action_id
        entry = self._hk.get(action_id)
        if entry:
            entry.configure(border_color=C["amber"])

    def _hk_stop_capture(self):
        """Stop capturing keystrokes."""
        if self._hk_capturing:
            entry = self._hk.get(self._hk_capturing)
            if entry:
                entry.configure(border_color=C["border"])
        self._hk_capturing = None

    def _hk_on_key(self, event, action_id):
        """Capture a key press and convert to combo string."""
        if self._hk_capturing != action_id:
            return

        # Build modifier string
        mods = []
        if event.state & 0x4:  # Control
            mods.append("Ctrl")
        if event.state & 0x1:  # Shift
            mods.append("Shift")
        if event.state & 0x20000:  # Alt
            mods.append("Alt")

        # Get the key
        key = event.keysym

        # Skip if just a modifier key
        if key in ("Control_L", "Control_R", "Shift_L", "Shift_R",
                   "Alt_L", "Alt_R", "Meta_L", "Meta_R"):
            return "break"

        # Build combo string
        if mods:
            combo = "+".join(mods) + "+" + key
        else:
            combo = key

        # Update entry
        entry = self._hk.get(action_id)
        if entry:
            entry.delete(0, "end")
            entry.insert(0, combo)

        # Move focus away to stop capture
        self.focus_set()
        return "break"

    def _hk_clear_one(self, action_id):
        """Clear a single hotkey."""
        entry = self._hk.get(action_id)
        if entry:
            entry.delete(0, "end")

    def _hk_clear_all(self):
        """Clear all hotkeys."""
        for entry in self._hk.values():
            entry.delete(0, "end")

    def _hk_reset_defaults(self):
        """Reset to default hotkeys."""
        for action_id, entry in self._hk.items():
            entry.delete(0, "end")
            if action_id in self.HOTKEY_DEFAULTS:
                entry.insert(0, self.HOTKEY_DEFAULTS[action_id])

    # ── Visual tab ────────────────────────────────────────────────

    # ── Mic tab ─────────────────────────────────

    def _tab_websites(self, p):
        sf = ctk.CTkScrollableFrame(p, fg_color="transparent")
        sf.pack(fill="both", expand=True)

        ctk.CTkLabel(sf, text="🌐  Websites",
                     font=ctk.CTkFont("Segoe UI", 11, "bold"),
                     text_color=C["amber"]).pack(
                         padx=12, pady=(12, 2), anchor="w")
        ctk.CTkLabel(sf,
                     text="These appear in the Quick Folders + Sites dropdown.",
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C["text_dim"]).pack(
                         padx=12, anchor="w", pady=(0, 6))

        self._web_frame = ctk.CTkFrame(sf, fg_color="transparent")
        self._web_frame.pack(fill="x", padx=12)
        self._web_entries = []
        self._redraw_websites()

        ctk.CTkButton(sf, text="+ Add Website",
                      width=130, height=28,
                      fg_color=C["blue_mid"],
                      command=self._add_website
                      ).pack(padx=12, anchor="w", pady=(6, 4))

    def _redraw_websites(self):
        for w in self._web_frame.winfo_children():
            w.destroy()
        self._web_entries.clear()
        sites = self.cfg.config.get("websites", [])
        for i, s in enumerate(sites):
            row = ctk.CTkFrame(self._web_frame,
                               fg_color=C["surface"], corner_radius=5)
            row.pack(fill="x", pady=2)
            le = ctk.CTkEntry(row, width=120, placeholder_text="Label")
            le.insert(0, s.get("label", ""))
            le.pack(side="left", padx=(6, 4), pady=4)
            ue = ctk.CTkEntry(row, width=260, placeholder_text="https://")
            ue.insert(0, s.get("url", ""))
            ue.pack(side="left", padx=(0, 4), pady=4)
            ctk.CTkButton(row, text="🗑", width=28, height=28,
                          corner_radius=4,
                          fg_color=C["surface"],
                          hover_color=C["red_dim"],
                          command=lambda ii=i: self._del_website(ii)
                          ).pack(side="right", padx=4)
            self._web_entries.append((le, ue))

    def _add_website(self):
        self._save_websites()
        self.cfg.config.setdefault("websites", []).append(
            {"label": "New Site", "url": "https://"})
        self._redraw_websites()

    def _del_website(self, idx):
        self._save_websites()
        sites = self.cfg.config.get("websites", [])
        if 0 <= idx < len(sites):
            sites.pop(idx)
        self._redraw_websites()

    def _save_websites(self):
        if not hasattr(self, "_web_entries"):
            return
        sites = []
        for le, ue in self._web_entries:
            lbl = le.get().strip()
            url = ue.get().strip()
            if lbl and url:
                sites.append({"label": lbl, "url": url})
        self.cfg.config["websites"] = sites

    def _tab_visual(self, p):
        sf = ctk.CTkScrollableFrame(p, fg_color="transparent")
        sf.pack(fill="both", expand=True)

        # ── SECTION 1: Color Theme ────────────────────────────────
        def _sec(text):
            ctk.CTkLabel(sf, text=text,
                         font=ctk.CTkFont("Segoe UI", 12, "bold"),
                         text_color=C["amber"]).pack(
                             padx=12, pady=(14, 4), anchor="w")
            ctk.CTkFrame(sf, height=1, fg_color=C["border"]).pack(
                fill="x", padx=12, pady=(0, 6))

        _sec("🎨  Color Theme")
        ctk.CTkLabel(sf, text="Theme change requires app restart.",
                     font=ctk.CTkFont("Segoe UI", 10),
                     text_color=C["text_dim"]).pack(padx=12, anchor="w")

        self._theme = ctk.StringVar(
            value=self.cfg.config.get("color_theme", "Slate Broadcast"))
        tf = ctk.CTkFrame(sf, fg_color=C["surface"], corner_radius=8)
        tf.pack(fill="x", padx=12, pady=(4, 6))

        theme_names = list(THEMES.keys()) + ["Custom"]
        for name in theme_names:
            pal = THEMES.get(name, self.cfg.config.get("custom_theme", {}))
            row = ctk.CTkFrame(tf, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=3)
            ctk.CTkRadioButton(
                row, text=name, variable=self._theme, value=name,
                fg_color=C["blue_mid"], text_color=C["text"],
                command=self._on_theme_select
            ).pack(side="left", padx=(4, 8))
            if name != "Custom":
                for key in ["bg2", "blue_mid", "amber", "green", "red"]:
                    tk.Label(row, bg=pal.get(key, "#888"),
                             width=2, height=1, relief="flat", bd=1
                             ).pack(side="left", padx=1)

        # Custom theme editor (shown only when Custom selected)
        self._custom_frame = ctk.CTkFrame(sf, fg_color=C["elevated"],
                                           corner_radius=6)
        self._custom_frame.pack(fill="x", padx=12, pady=(0, 4))
        self._build_custom_editor(self._custom_frame)
        self._on_theme_select()  # show/hide

        # Export / Import row
        exp_row = ctk.CTkFrame(sf, fg_color="transparent")
        exp_row.pack(fill="x", padx=12, pady=(0, 4))
        ctk.CTkButton(exp_row, text="Export Theme", width=120, height=28,
                      fg_color=C["btn"], font=ctk.CTkFont("Segoe UI", 10),
                      command=self._export_theme).pack(side="left", padx=(0, 6))
        ctk.CTkButton(exp_row, text="Import Theme", width=120, height=28,
                      fg_color=C["btn"], font=ctk.CTkFont("Segoe UI", 10),
                      command=self._import_theme).pack(side="left")

        # ── SECTION 2: Soundboard Appearance ─────────────────────
        _sec("🎛  Soundboard Appearance")

        # Playing button color
        pb_row = ctk.CTkFrame(sf, fg_color=C["surface"], corner_radius=6)
        pb_row.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(pb_row, text="Playing button color:",
                     font=ctk.CTkFont("Segoe UI", 10),
                     text_color=C["text"]).pack(side="left", padx=(10, 8))
        self._playing_color = self.cfg.config.get("playing_btn_color", "")
        self._playing_swatch = tk.Label(
            pb_row,
            bg=self._playing_color if self._playing_color else C["green"],
            width=4, height=1, relief="solid", bd=1, cursor="hand2")
        self._playing_swatch.pack(side="left", padx=(0, 6))
        self._playing_swatch.bind("<Button-1>", self._pick_playing_color)
        self._playing_auto_var = ctk.BooleanVar(
            value=(not self._playing_color))
        ctk.CTkCheckBox(pb_row, text="Auto (theme default)",
                        variable=self._playing_auto_var,
                        fg_color=C["blue_mid"],
                        command=self._on_playing_auto_toggle
                        ).pack(side="left", padx=4)

        # Blink
        blink_row = ctk.CTkFrame(sf, fg_color=C["surface"], corner_radius=6)
        blink_row.pack(fill="x", padx=12, pady=2)
        self._blink_var = ctk.BooleanVar(
            value=self.cfg.config.get("playing_btn_blink", False))
        ctk.CTkCheckBox(blink_row, text="Blink button when playing",
                        variable=self._blink_var,
                        fg_color=C["blue_mid"]
                        ).pack(side="left", padx=(10, 16))
        ctk.CTkLabel(blink_row, text="Rate:",
                     font=ctk.CTkFont("Segoe UI", 10),
                     text_color=C["text_dim"]).pack(side="left")
        self._blink_rate = ctk.StringVar(
            value=self.cfg.config.get("playing_btn_blink_rate", "medium"))
        for rate in ("slow", "medium", "fast"):
            ctk.CTkRadioButton(blink_row, text=rate.title(),
                               variable=self._blink_rate, value=rate,
                               fg_color=C["blue_mid"], width=70
                               ).pack(side="left", padx=4)

        # Now Playing flash
        np_row = ctk.CTkFrame(sf, fg_color=C["surface"], corner_radius=6)
        np_row.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(np_row, text="Flash Now Playing timer at:",
                     font=ctk.CTkFont("Segoe UI", 10),
                     text_color=C["text"]).pack(side="left", padx=(10, 8))
        self._np_flash_var = ctk.StringVar(
            value=str(self.cfg.config.get("nowplaying_flash_secs", 30)))
        ctk.CTkEntry(np_row, textvariable=self._np_flash_var,
                     width=50).pack(side="left", padx=(0, 4))
        ctk.CTkLabel(np_row, text="seconds remaining",
                     font=ctk.CTkFont("Segoe UI", 10),
                     text_color=C["text_dim"]).pack(side="left")

        # Active bank tab highlight
        tab_row = ctk.CTkFrame(sf, fg_color=C["surface"], corner_radius=6)
        tab_row.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(tab_row, text="Active bank tab:",
                     font=ctk.CTkFont("Segoe UI", 10),
                     text_color=C["text"]).pack(side="left", padx=(10, 8))

        self._tab_hi_color = self.cfg.config.get(
            "bank_tab_highlight_color", "#0078d4")
        self._tab_hi_swatch = tk.Label(
            tab_row, bg=self._tab_hi_color,
            width=4, height=1, relief="solid", bd=1, cursor="hand2",
            text="Border")
        self._tab_hi_swatch.pack(side="left", padx=(0, 4))
        self._tab_hi_swatch.bind("<Button-1>",
            lambda e: self._pick_tab_color("border"))

        self._tab_bg_color = self.cfg.config.get("bank_tab_highlight_bg", "")
        _bg_disp = self._tab_bg_color if self._tab_bg_color else C["blue_mid"]
        self._tab_bg_swatch = tk.Label(
            tab_row, bg=_bg_disp,
            width=4, height=1, relief="solid", bd=1, cursor="hand2",
            text="Fill")
        self._tab_bg_swatch.pack(side="left", padx=(0, 4))
        self._tab_bg_swatch.bind("<Button-1>",
            lambda e: self._pick_tab_color("bg"))
        ctk.CTkLabel(tab_row, text="← Border  Fill →",
                     font=ctk.CTkFont("Segoe UI", 9),
                     text_color=C["text_dim"]).pack(side="left", padx=4)

        # ── SECTION 3: Window ─────────────────────────────────────
        _sec("🪟  Window")

        self._lbl(sf, "Window Opacity:")
        self._opacity = ctk.DoubleVar(
            value=self.cfg.config.get("opacity", 1.0))
        ctk.CTkSlider(sf, from_=0.3, to=1.0, width=240,
                      variable=self._opacity,
                      command=lambda v: self.app.set_opacity(v)
                      ).pack(padx=12, anchor="w", pady=(0, 12))

        self._lbl(sf, "Button Font Size (8-20):")
        self._font_size = ctk.StringVar(
            value=str(self.cfg.config.get("font_size", 11)))
        ctk.CTkEntry(sf, textvariable=self._font_size, width=60,
                     placeholder_text="11"
                     ).pack(padx=12, anchor="w", pady=(0, 12))

    # ── Custom theme helpers ──────────────────────────────────────

    # Color keys shown in custom editor
    _CUSTOM_KEYS = [
        ("bg",         "Background"),
        ("bg2",        "Background 2"),
        ("surface",    "Surface"),
        ("elevated",   "Elevated"),
        ("border",     "Border"),
        ("blue_mid",   "Accent (Primary)"),
        ("amber",      "Accent (Secondary)"),
        ("text",       "Text"),
        ("text_dim",   "Text Dim"),
        ("btn",        "Button"),
        ("btn_hover",  "Button Hover"),
        ("green",      "Green"),
        ("red",        "Red"),
        ("panic",      "Panic"),
        ("neutral",    "Neutral"),
    ]

    def _build_custom_editor(self, parent):
        """Inline custom theme editor — simple + advanced tabs."""
        self._custom_color_vars = {}

        # Derive from accent section
        derive_f = ctk.CTkFrame(parent, fg_color="transparent")
        derive_f.pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkLabel(derive_f, text="Simple Mode — pick accents, derive the rest:",
                     font=ctk.CTkFont("Segoe UI", 10),
                     text_color=C["text_dim"]).pack(anchor="w")

        acc_row = ctk.CTkFrame(derive_f, fg_color="transparent")
        acc_row.pack(fill="x", pady=4)

        self._derive_dark = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(acc_row, text="Dark base",
                        variable=self._derive_dark,
                        fg_color=C["blue_mid"]
                        ).pack(side="left", padx=(0, 10))

        ctk.CTkLabel(acc_row, text="Primary:",
                     font=ctk.CTkFont("Segoe UI", 10),
                     text_color=C["text"]).pack(side="left")
        ct = self.cfg.config.get("custom_theme", {})
        self._derive_primary = ct.get("blue_mid", "#0078d4")
        self._primary_swatch = tk.Label(acc_row, bg=self._derive_primary,
                                         width=4, height=1, relief="solid",
                                         bd=1, cursor="hand2")
        self._primary_swatch.pack(side="left", padx=4)
        self._primary_swatch.bind("<Button-1>",
            lambda e: self._pick_derive_color("primary"))

        ctk.CTkLabel(acc_row, text="Secondary:",
                     font=ctk.CTkFont("Segoe UI", 10),
                     text_color=C["text"]).pack(side="left", padx=(8, 0))
        self._derive_secondary = ct.get("amber", "#e8952a")
        self._secondary_swatch = tk.Label(acc_row, bg=self._derive_secondary,
                                           width=4, height=1, relief="solid",
                                           bd=1, cursor="hand2")
        self._secondary_swatch.pack(side="left", padx=4)
        self._secondary_swatch.bind("<Button-1>",
            lambda e: self._pick_derive_color("secondary"))

        ctk.CTkButton(acc_row, text="Derive →", width=90, height=26,
                      fg_color=C["blue_mid"],
                      font=ctk.CTkFont("Segoe UI", 10, "bold"),
                      command=self._derive_theme
                      ).pack(side="left", padx=(10, 0))

        # ── Enhanced Live Preview Panel ──────────────────────────────
        preview_lbl = ctk.CTkLabel(derive_f, text="Live Preview:",
                                    font=ctk.CTkFont("Segoe UI", 10),
                                    text_color=C["text_dim"])
        preview_lbl.pack(anchor="w", pady=(8, 2))

        self._preview_frame = tk.Frame(derive_f, bd=1, relief="solid")
        self._preview_frame.pack(fill="x", pady=(0, 4))

        # Build the mini UI preview
        self._build_preview_widgets()

        # Separator
        ctk.CTkFrame(parent, height=1, fg_color=C["border"]).pack(
            fill="x", padx=10, pady=6)

        # Advanced — all keys grid
        adv_lbl = ctk.CTkLabel(parent, text="▶  Advanced — all color keys",
                                font=ctk.CTkFont("Segoe UI", 10),
                                text_color=C["text_dim"],
                                cursor="hand2")
        adv_lbl.pack(anchor="w", padx=10)

        self._adv_frame = ctk.CTkFrame(parent, fg_color="transparent")
        # Build grid
        grid = ctk.CTkFrame(self._adv_frame, fg_color="transparent")
        grid.pack(fill="x", padx=6, pady=4)
        for i, (key, label) in enumerate(self._CUSTOM_KEYS):
            col_offset = (i % 2) * 3
            row_i = i // 2
            cur = ct.get(key, C.get(key, "#888888"))
            self._custom_color_vars[key] = cur
            ctk.CTkLabel(grid, text=label,
                         font=ctk.CTkFont("Segoe UI", 10),
                         text_color=C["text"],
                         width=100, anchor="w").grid(
                             row=row_i, column=col_offset,
                             padx=(6, 4), pady=2, sticky="w")
            sw = tk.Label(grid, bg=cur, width=4, height=1,
                          relief="solid", bd=1, cursor="hand2")
            sw.grid(row=row_i, column=col_offset+1, padx=2, pady=2)
            sw.bind("<Button-1>",
                    lambda e, k=key, s=sw: self._pick_custom_key(k, s))
            hex_var = ctk.StringVar(value=cur)
            hex_e = ctk.CTkEntry(grid, textvariable=hex_var,
                                  width=70, font=ctk.CTkFont("Consolas", 9))
            hex_e.grid(row=row_i, column=col_offset+2, padx=(2, 16), pady=2)
            hex_var.trace_add("write",
                lambda *_, k=key, v=hex_var, s=sw: self._on_hex_entry(k, v, s))
            self._custom_color_vars[key+"__sw"]  = sw
            self._custom_color_vars[key+"__var"] = hex_var

        self._adv_visible = False
        def _toggle_adv():
            self._adv_visible = not self._adv_visible
            if self._adv_visible:
                self._adv_frame.pack(fill="x", padx=10)
                adv_lbl.configure(text="▼  Advanced — all color keys")
            else:
                self._adv_frame.pack_forget()
                adv_lbl.configure(text="▶  Advanced — all color keys")
        adv_lbl.bind("<Button-1>", lambda e: _toggle_adv())

    def _build_preview_widgets(self):
        """Build a mini UI mockup for live theme preview."""
        ct = self.cfg.config.get("custom_theme", {})
        
        def _col(key):
            return ct.get(key, C.get(key, "#888888"))
        
        # Clear existing
        for w in self._preview_frame.winfo_children():
            w.destroy()
        
        # Store widget references for live updates
        self._preview_widgets = {}
        
        # Main background frame
        main_bg = tk.Frame(self._preview_frame, bg=_col("bg"), padx=8, pady=6)
        main_bg.pack(fill="both", expand=True)
        self._preview_widgets["bg"] = main_bg
        
        # Header row (bg2)
        header = tk.Frame(main_bg, bg=_col("bg2"), padx=6, pady=4)
        header.pack(fill="x", pady=(0, 4))
        self._preview_widgets["bg2"] = header
        
        # ON AIR badge (red)
        onair = tk.Label(header, text="● ON AIR", bg=_col("red"),
                         fg="#ffffff", font=("Segoe UI", 9, "bold"),
                         padx=6, pady=2)
        onair.pack(side="left", padx=(0, 8))
        self._preview_widgets["red"] = onair
        
        # Timer (text on bg2)
        timer = tk.Label(header, text="01:23:45", bg=_col("bg2"),
                         fg=_col("text"), font=("Courier New", 11, "bold"))
        timer.pack(side="left")
        self._preview_widgets["timer_text"] = timer
        
        # Surface panel
        surface = tk.Frame(main_bg, bg=_col("surface"), padx=6, pady=6,
                           bd=1, relief="flat",
                           highlightbackground=_col("border"),
                           highlightthickness=1)
        surface.pack(fill="x", pady=2)
        self._preview_widgets["surface"] = surface
        self._preview_widgets["border"] = surface
        
        # Buttons row
        btn_row = tk.Frame(surface, bg=_col("surface"))
        btn_row.pack(fill="x")
        
        # Normal button
        btn1 = tk.Label(btn_row, text="Button", bg=_col("btn"),
                        fg=_col("text"), font=("Segoe UI", 9),
                        padx=10, pady=4, relief="flat")
        btn1.pack(side="left", padx=(0, 4))
        self._preview_widgets["btn"] = btn1
        self._preview_widgets["btn_text"] = btn1
        
        # Primary accent button
        btn2 = tk.Label(btn_row, text="Primary", bg=_col("blue_mid"),
                        fg="#ffffff", font=("Segoe UI", 9, "bold"),
                        padx=10, pady=4, relief="flat")
        btn2.pack(side="left", padx=(0, 4))
        self._preview_widgets["blue_mid"] = btn2
        
        # Secondary accent button
        btn3 = tk.Label(btn_row, text="Secondary", bg=_col("amber"),
                        fg="#ffffff", font=("Segoe UI", 9, "bold"),
                        padx=10, pady=4, relief="flat")
        btn3.pack(side="left", padx=(0, 4))
        self._preview_widgets["amber"] = btn3
        
        # Green button
        btn4 = tk.Label(btn_row, text="Go", bg=_col("green"),
                        fg="#ffffff", font=("Segoe UI", 9),
                        padx=8, pady=4, relief="flat")
        btn4.pack(side="left", padx=(0, 4))
        self._preview_widgets["green"] = btn4
        
        # Text samples row
        text_row = tk.Frame(surface, bg=_col("surface"))
        text_row.pack(fill="x", pady=(6, 0))
        
        txt1 = tk.Label(text_row, text="Primary text", bg=_col("surface"),
                        fg=_col("text"), font=("Segoe UI", 10))
        txt1.pack(side="left", padx=(0, 12))
        self._preview_widgets["text"] = txt1
        
        txt2 = tk.Label(text_row, text="Dim text", bg=_col("surface"),
                        fg=_col("text_dim"), font=("Segoe UI", 10))
        txt2.pack(side="left")
        self._preview_widgets["text_dim"] = txt2

    def _update_preview(self):
        """Update the live preview panel with current custom theme colors."""
        ct = self.cfg.config.get("custom_theme", {})
        
        def _col(key):
            return ct.get(key, C.get(key, "#888888"))
        
        if not hasattr(self, "_preview_widgets"):
            return
        
        try:
            # Background areas
            if "bg" in self._preview_widgets:
                self._preview_widgets["bg"].configure(bg=_col("bg"))
            if "bg2" in self._preview_widgets:
                self._preview_widgets["bg2"].configure(bg=_col("bg2"))
            if "surface" in self._preview_widgets:
                self._preview_widgets["surface"].configure(
                    bg=_col("surface"),
                    highlightbackground=_col("border"))
            
            # Timer text
            if "timer_text" in self._preview_widgets:
                self._preview_widgets["timer_text"].configure(
                    bg=_col("bg2"), fg=_col("text"))
            
            # Buttons
            if "btn" in self._preview_widgets:
                self._preview_widgets["btn"].configure(
                    bg=_col("btn"), fg=_col("text"))
            if "blue_mid" in self._preview_widgets:
                self._preview_widgets["blue_mid"].configure(bg=_col("blue_mid"))
            if "amber" in self._preview_widgets:
                self._preview_widgets["amber"].configure(bg=_col("amber"))
            if "green" in self._preview_widgets:
                self._preview_widgets["green"].configure(bg=_col("green"))
            if "red" in self._preview_widgets:
                self._preview_widgets["red"].configure(bg=_col("red"))
            
            # Text
            if "text" in self._preview_widgets:
                self._preview_widgets["text"].configure(
                    bg=_col("surface"), fg=_col("text"))
            if "text_dim" in self._preview_widgets:
                self._preview_widgets["text_dim"].configure(
                    bg=_col("surface"), fg=_col("text_dim"))
            
            # Update btn_row backgrounds to match surface
            for widget in self._preview_widgets.values():
                if hasattr(widget, "master"):
                    try:
                        if widget.master.winfo_class() == "Frame":
                            p_bg = widget.master.cget("bg")
                            if p_bg == _col("surface") or "surface" in str(p_bg):
                                widget.master.configure(bg=_col("surface"))
                    except Exception:
                        pass
        except Exception:
            pass

    def _on_theme_select(self):
        if self._theme.get() == "Custom":
            # Initialize custom_theme with Classic colors if not set
            if not self.cfg.config.get("custom_theme"):
                from config import THEMES
                self.cfg.config["custom_theme"] = dict(THEMES["Classic"])
                # Update the editor swatches with Classic colors
                self._refresh_custom_editor_from_config()
            self._custom_frame.pack(fill="x", padx=12, pady=(0, 4))
        else:
            self._custom_frame.pack_forget()

    def _refresh_custom_editor_from_config(self):
        """Refresh custom editor swatches from config."""
        ct = self.cfg.config.get("custom_theme", {})
        # Update derive accents
        self._derive_primary = ct.get("blue_mid", "#0078d4")
        self._derive_secondary = ct.get("amber", "#e8952a")
        try:
            self._primary_swatch.configure(bg=self._derive_primary)
            self._secondary_swatch.configure(bg=self._derive_secondary)
        except Exception:
            pass
        # Update advanced grid if it exists
        for key in list(self._custom_color_vars.keys()):
            if key.endswith("__sw") or key.endswith("__var"):
                continue
            col = ct.get(key, "#888888")
            self._custom_color_vars[key] = col
            sw = self._custom_color_vars.get(key+"__sw")
            var = self._custom_color_vars.get(key+"__var")
            if sw:
                try: sw.configure(bg=col)
                except Exception: pass
            if var:
                try: var.set(col)
                except Exception: pass
        # Update live preview panel
        self._update_preview()

    def _pick_derive_color(self, which: str):
        cur = self._derive_primary if which == "primary"             else self._derive_secondary
        col = colorchooser.askcolor(color=cur, title="Pick Colour")
        if col and col[1]:
            if which == "primary":
                self._derive_primary = col[1]
                self._primary_swatch.configure(bg=col[1])
            else:
                self._derive_secondary = col[1]
                self._secondary_swatch.configure(bg=col[1])

    def _derive_theme(self):
        """Generate full palette from two accents + dark/light toggle."""
        dark = self._derive_dark.get()
        p    = self._derive_primary
        s    = self._derive_secondary

        def _lighter(hex_col, amt):
            hex_col = hex_col.lstrip("#")
            r,g,b = int(hex_col[0:2],16), int(hex_col[2:4],16), int(hex_col[4:6],16)
            r = min(255, int(r + (255-r)*amt))
            g = min(255, int(g + (255-g)*amt))
            b = min(255, int(b + (255-b)*amt))
            return f"#{r:02x}{g:02x}{b:02x}"

        def _darker(hex_col, amt):
            hex_col = hex_col.lstrip("#")
            r,g,b = int(hex_col[0:2],16), int(hex_col[2:4],16), int(hex_col[4:6],16)
            r = max(0, int(r*(1-amt)))
            g = max(0, int(g*(1-amt)))
            b = max(0, int(b*(1-amt)))
            return f"#{r:02x}{g:02x}{b:02x}"

        if dark:
            derived = {
                "bg": "#060810", "bg2": "#0a0e18", "surface": "#0e1420",
                "elevated": "#121a28", "border": "#1a2438", "border_hi": "#223050",
                "blue": _darker(p, 0.3), "blue_mid": p,
                "blue_light": _lighter(p, 0.3), "blue_hi": _lighter(p, 0.5),
                "amber": s, "amber_hi": _lighter(s, 0.3),
                "text": "#c8d8f0", "text_dim": "#4a6480", "text_hi": "#e8f0ff",
                "red": "#e02233", "red_dim": "#881122",
                "green": "#20b85a", "green_dim": "#126835",
                "gold": "#ffd700", "panic": "#cc0000",
                "neutral": "#0e1420", "btn": "#0e1a2a", "btn_hover": "#162234",
                "pinned": "#1a2e00", "shine": "#1a2840", "shadow": "#030508",
            }
        else:
            derived = {
                "bg": "#f0f2f5", "bg2": "#e8eaed", "surface": "#ffffff",
                "elevated": "#f8f9fa", "border": "#dadce0", "border_hi": "#b0b8c4",
                "blue": _darker(p, 0.2), "blue_mid": p,
                "blue_light": _lighter(p, 0.3), "blue_hi": _lighter(p, 0.5),
                "amber": s, "amber_hi": _lighter(s, 0.2),
                "text": "#1c1c1c", "text_dim": "#5f6368", "text_hi": "#ffffff",
                "red": "#d13438", "red_dim": "#a4262c",
                "green": "#107c10", "green_dim": "#0e6b0e",
                "gold": "#8a6914", "panic": "#d13438",
                "neutral": "#e1e4e8", "btn": "#e1e4e8", "btn_hover": "#d0d4d9",
                "pinned": "#e8f4fd", "shine": "#ffffff", "shadow": "#c8cdd2",
            }

        self.cfg.config["custom_theme"] = derived
        # Update advanced key swatches + entries
        for key, _ in self._CUSTOM_KEYS:
            col = derived.get(key, "#888888")
            self._custom_color_vars[key] = col
            sw  = self._custom_color_vars.get(key+"__sw")
            var = self._custom_color_vars.get(key+"__var")
            if sw:
                try: sw.configure(bg=col)
                except Exception: pass
            if var:
                try: var.set(col)
                except Exception: pass
        # Update live preview
        self._update_preview()

    def _pick_custom_key(self, key: str, swatch):
        cur = self._custom_color_vars.get(key, "#888888")
        col = colorchooser.askcolor(color=cur, title=f"Pick: {key}")
        if col and col[1]:
            self._custom_color_vars[key] = col[1]
            swatch.configure(bg=col[1])
            var = self._custom_color_vars.get(key+"__var")
            if var:
                var.set(col[1])
            self.cfg.config.setdefault("custom_theme", {})[key] = col[1]
            # Update live preview
            self._update_preview()

    def _on_hex_entry(self, key: str, var, swatch):
        val = var.get().strip().lstrip("#")
        if len(val) == 6:
            try:
                int(val, 16)
                col = "#" + val
                self._custom_color_vars[key] = col
                swatch.configure(bg=col)
                self.cfg.config.setdefault("custom_theme", {})[key] = col
                # Update live preview
                self._update_preview()
            except ValueError:
                pass

    def _pick_playing_color(self, event):
        cur = self._playing_color or C["green"]
        col = colorchooser.askcolor(color=cur, title="Playing Button Color")
        if col and col[1]:
            self._playing_color = col[1]
            self._playing_swatch.configure(bg=col[1])
            self._playing_auto_var.set(False)

    def _on_playing_auto_toggle(self):
        if self._playing_auto_var.get():
            self._playing_color = ""
            self._playing_swatch.configure(bg=C["green"])

    def _pick_tab_color(self, which: str):
        cur = self._tab_hi_color if which == "border" else (
            self._tab_bg_color or C["blue_mid"])
        col = colorchooser.askcolor(color=cur,
                                     title="Tab Border" if which=="border"
                                     else "Tab Background")
        if col and col[1]:
            if which == "border":
                self._tab_hi_color = col[1]
                self._tab_hi_swatch.configure(bg=col[1])
            else:
                self._tab_bg_color = col[1]
                self._tab_bg_swatch.configure(bg=col[1])

    def _export_theme(self):
        import json as _json
        theme_name = self._theme.get()
        if theme_name == "Custom":
            pal = self.cfg.config.get("custom_theme", {})
        else:
            pal = dict(THEMES.get(theme_name, {}))
        path = filedialog.asksaveasfilename(
            title="Export Theme",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All", "*.*")],
            initialfile=f"{theme_name.replace(' ', '_')}_theme.json")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                _json.dump({"name": theme_name, "colors": pal}, f, indent=2)
            messagebox.showinfo("Exported", f"Theme saved to:\n{path}")

    def _import_theme(self):
        import json as _json
        path = filedialog.askopenfilename(
            title="Import Theme",
            filetypes=[("JSON", "*.json"), ("All", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = _json.load(f)
            pal = data.get("colors", data)
            self.cfg.config["custom_theme"] = pal
            self._theme.set("Custom")
            self._on_theme_select()
            # Refresh advanced swatches
            for key, _ in self._CUSTOM_KEYS:
                col = pal.get(key, "#888888")
                self._custom_color_vars[key] = col
                sw  = self._custom_color_vars.get(key+"__sw")
                var = self._custom_color_vars.get(key+"__var")
                if sw:
                    try: sw.configure(bg=col)
                    except Exception: pass
                if var:
                    try: var.set(col)
                    except Exception: pass
            messagebox.showinfo("Imported", "Theme imported. Click Save & Close to apply.")
        except Exception as e:
            messagebox.showerror("Import Failed", str(e))

    # ── Integrations tab ──────────────────────────────────────────

    def _tab_integrations(self, p):
        sf = ctk.CTkScrollableFrame(p, fg_color="transparent")
        sf.pack(fill="both", expand=True)

        ctk.CTkLabel(sf, text="Discord Webhook",
                     font=ctk.CTkFont("Segoe UI", 11, "bold"),
                     text_color=C["amber"]).pack(
                         padx=12, pady=(12,2), anchor="w")
        self._discord_en = ctk.BooleanVar(
            value=self.cfg.config.get("discord_enabled", False))
        ctk.CTkCheckBox(sf, text="Enable go-live notification",
                        variable=self._discord_en,
                        fg_color=C["blue_mid"]
                        ).pack(padx=12, anchor="w")
        self._lbl(sf, "Webhook URL:")
        self._discord_url = ctk.StringVar(
            value=self.cfg.config.get("discord_webhook", ""))
        ctk.CTkEntry(sf, textvariable=self._discord_url,
                     width=450).pack(padx=12, anchor="w")
        self._lbl(sf, "Message:")
        self._discord_msg = ctk.StringVar(
            value=self.cfg.config.get(
                "discord_message",
                "🎙 We're LIVE! Tune in now!"))
        ctk.CTkEntry(sf, textvariable=self._discord_msg,
                     width=450).pack(padx=12, anchor="w")

        ctk.CTkFrame(sf, height=1, fg_color=C["border"]).pack(
            fill="x", padx=12, pady=(16, 8))

        # MicroSIP auto-setup
        ctk.CTkLabel(sf, text="MicroSIP Call Logging",
                     font=ctk.CTkFont("Segoe UI", 11, "bold"),
                     text_color=C["amber"]).pack(
                         padx=12, pady=(4, 2), anchor="w")
        ctk.CTkLabel(sf,
            text="Automatically configures MicroSIP to send call\n"
                 "events to the Companion.",
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=C["text_dim"],
            justify="left").pack(padx=12, anchor="w")
        ctk.CTkButton(sf, text="Launch MicroSIP Setup Wizard",
                      width=240, height=32,
                      fg_color=C["blue_mid"],
                      font=ctk.CTkFont("Segoe UI", 11, "bold"),
                      command=lambda: MicroSIPWizard(self)
                      ).pack(padx=12, pady=(6, 4), anchor="w")

        ctk.CTkFrame(sf, height=1, fg_color=C["border"]).pack(
            fill="x", padx=12, pady=(8, 8))

        # Browser preference
        ctk.CTkLabel(sf, text="Preferred Browser",
                     font=ctk.CTkFont("Segoe UI", 11, "bold"),
                     text_color=C["amber"]).pack(
                         padx=12, pady=(4,2), anchor="w")
        browsers = _detect_browsers()
        for label, path in browsers:
            self._browser_paths[label] = path
        blabels  = [b[0] for b in browsers]
        cur_path = self.cfg.config.get("browser_preference", "")
        cur_lbl  = next(
            (l for l, p in self._browser_paths.items()
             if p == cur_path), "Default (system)")
        self._browser = ctk.StringVar(value=cur_lbl)
        ctk.CTkOptionMenu(sf, values=blabels,
                          variable=self._browser, width=220
                          ).pack(padx=12, anchor="w")

    # ── About tab ─────────────────────────────────────────────────

    def _tab_about(self, p):
        logo = load_logo((64, 72))
        if logo:
            ctk.CTkLabel(p, image=logo, text="").pack(pady=(16,4))
        ctk.CTkLabel(p, text=f"{APP_NAME}  v{VERSION}",
                     font=ctk.CTkFont("Segoe UI", 13, "bold"),
                     text_color=C["amber"]).pack()
        ctk.CTkLabel(p, text=self.cfg.config.get("show_name", "My Show"),
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C["text_dim"]).pack(pady=4)

        # Help guide
        help_row = ctk.CTkFrame(p, fg_color="transparent")
        help_row.pack(pady=8)
        ctk.CTkButton(
            help_row, text="📖  Open Help Guide",
            fg_color=C["blue_mid"], width=180,
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
            command=lambda: self._open_help(in_app=True)
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            help_row, text="🌐  Open in Browser",
            fg_color=C["surface"], width=150,
            command=lambda: self._open_help(in_app=False)
        ).pack(side="left", padx=4)

        ctk.CTkButton(p, text="🌐  GitHub Repository",
                      fg_color=C["surface"],
                      command=lambda: webbrowser.open(
                          "https://github.com/ColdKittyIce/BroadcastBackpack")
                      ).pack(pady=4)
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.pack(pady=4)
        ctk.CTkButton(row, text="🔒  Backup Config",
                      fg_color=C["surface"],
                      command=self._backup).pack(side="left", padx=4)
        ctk.CTkButton(row, text="📂  Data Folder",
                      fg_color=C["surface"],
                      command=lambda: os.startfile(str(DATA_DIR))
                      ).pack(side="left", padx=4)

    def _open_help(self, in_app: bool = True):
        from pathlib import Path
        html_path = Path(__file__).parent / "help.html"
        if not html_path.exists():
            messagebox.showerror("Help Not Found",
                f"help.html not found at:\n{html_path}")
            return
        if not in_app:
            webbrowser.open(html_path.as_uri())
            return
        # ── In-app viewer ──────────────────────────────────────
        win = ctk.CTkToplevel(self)
        win.title(f"{APP_NAME} — Help Guide")
        win.geometry("1020x720")
        win.configure(fg_color="#ffffff")
        win.grab_set()

        # Toolbar
        tb = ctk.CTkFrame(win, fg_color="#f3f4f6", corner_radius=0)
        tb.pack(fill="x")
        ctk.CTkLabel(tb, text=f"📖  {APP_NAME} — Help Guide",
                     font=ctk.CTkFont("Segoe UI", 12, "bold"),
                     text_color="#1f2937"
                     ).pack(side="left", padx=12, pady=8)
        ctk.CTkButton(
            tb, text="🌐 Open in Browser",
            fg_color="#1a73e8", hover_color="#1557b0",
            text_color="white", height=30,
            font=ctk.CTkFont("Segoe UI", 11),
            command=lambda: webbrowser.open(html_path.as_uri())
        ).pack(side="right", padx=12, pady=6)

        # Try embedded browser (Windows WebView2 via pywebview)
        loaded = False
        try:
            import webview  # type: ignore
            # pywebview needs its own window — fall through to text viewer
        except ImportError:
            pass

        if not loaded:
            # Fallback: styled scrollable text viewer
            import tkinter as _tk
            import html as _html
            import re as _re
            container = ctk.CTkScrollableFrame(
                win, fg_color="#ffffff")
            container.pack(fill="both", expand=True,
                           padx=0, pady=0)

            raw = html_path.read_text(encoding="utf-8")
            # Strip tags for plain-text display
            text = _re.sub(r"<style[^>]*>.*?</style>",
                           "", raw, flags=_re.S)
            text = _re.sub(r"<script[^>]*>.*?</script>",
                           "", text, flags=_re.S)
            text = _re.sub(r"<br\s*/?>|</p>|</li>|</tr>|</h[1-6]>",
                           "\n", text)
            text = _re.sub(r"<[^>]+>", "", text)
            text = _re.sub(r"\n{3,}", "\n\n", text)
            text = _html.unescape(text).strip()

            txt = _tk.Text(
                container, wrap="word",
                font=("Segoe UI", 12),
                bg="#ffffff", fg="#1f2937",
                relief="flat", bd=0,
                padx=40, pady=20,
                spacing1=2, spacing3=4)
            txt.pack(fill="both", expand=True)
            txt.insert("1.0", text)
            txt.configure(state="disabled")

            ctk.CTkLabel(
                win,
                text="Tip: Click \"Open in Browser\" above for the full "
                     "styled guide with diagrams and navigation.",
                font=ctk.CTkFont("Segoe UI", 11),
                text_color="#6b7280",
                fg_color="#f9fafb"
            ).pack(fill="x", pady=(0, 0))

    def _backup(self):
        p = self.cfg.backup()
        if p:
            messagebox.showinfo("Backup", f"Saved:\n{p}")
        else:
            messagebox.showerror("Error", "Backup failed.")

    # ── Save ──────────────────────────────────────────────────────

    def _save(self):
        c = self.cfg.config

        # Streaming
        if hasattr(self, "_stream_vars"):
            numeric = {"stream_port", "stream_bitrate"}
            for key, var in self._stream_vars.items():
                val = var.get().strip()
                if key in numeric:
                    try:
                        val = int(val)
                    except ValueError:
                        pass
                c[key] = val
        if hasattr(self, "_stream_dev_var"):
            c["stream_audio_device"] = self._stream_dev_var.get()
        if hasattr(self, "_stream_reconnect_var"):
            c["stream_auto_reconnect"] = self._stream_reconnect_var.get()
        if hasattr(self, "_stream_attempts_var"):
            try:
                c["stream_reconnect_attempts"] = int(
                    self._stream_attempts_var.get())
            except ValueError:
                pass
        # Push updated config to streaming engine
        try:
            self.app.stream.update_config(c)
        except Exception:
            pass

        # Show
        c["show_name"]      = self._show_name.get().strip()
        try:
            c["episode_number"] = int(self._ep_num.get())
        except ValueError:
            pass
        c["title_template"] = self._title_tmpl.get().strip()
        tabs = [t.strip() for t in self._note_tabs.get().split(",") if t.strip()]
        if tabs:
            c["note_tabs"] = tabs

        # Audio
        new_out = self._out_dev.get()
        old_out = c.get("audio_output_device", "Default (System)")
        c["audio_output_device"] = new_out
        c["audio_input_device"]  = self._in_dev.get()
        c["recordings_folder"]   = self._rec_folder
        c["recording_format"]    = self._rec_fmt.get()
        try:
            c["fade_duration"] = float(self._fade.get())
        except ValueError:
            pass
        try:
            c["log_audio_min_secs"] = int(self._log_min.get())
        except ValueError:
            pass

        # Soundboard
        try:
            c["pinned_count"] = int(self._pinned.get())
        except ValueError:
            pass
        c["music_bank_name"] = self._music_bank.get()
        
        # Playback modes
        c["touch_play_mode"] = self._touch_play_var.get()
        c["automix_enabled"] = self._automix_var.get()
        try:
            c["automix_crossfade_sec"] = max(1, min(10, int(self._crossfade_var.get())))
        except ValueError:
            c["automix_crossfade_sec"] = 3
        
        # Board gain
        c["board_gain_db"] = self._board_gain_var.get()
        try:
            self.app.audio.set_board_gain_db(c["board_gain_db"])
        except Exception:
            pass
        
        groups = []
        for i, entries in self._grp_entries:
            try: rows = max(1, int(entries[1].get()))
            except: rows = 2
            try: cols = max(1, int(entries[2].get()))
            except: cols = 8
            name = entries[0].get().strip() or f"Bank {i+1}"
            existing = (c["soundboard_groups"][i]
                        if i < len(c["soundboard_groups"]) else {})
            groups.append({"name": name, "rows": rows, "cols": cols,
                           "color": entries[3][0] if len(entries) > 3
                                    else existing.get("color", "")})
        if groups:
            # ── Resize slot array bank-by-bank so adjacent banks don't shift ──
            old_groups = c["soundboard_groups"]
            slots      = c["soundboard"]

            # Walk old groups to find each bank's current start offset
            offsets = []
            pos = 0
            for g in old_groups:
                offsets.append(pos)
                pos += g.get("rows", 2) * g.get("cols", 8)

            # Process in reverse so earlier insertions don't affect later offsets
            for i in range(len(old_groups) - 1, -1, -1):
                if i >= len(groups):
                    # Bank was deleted — remove its slots
                    old_size  = old_groups[i].get("rows",2) * old_groups[i].get("cols",8)
                    del slots[offsets[i]: offsets[i] + old_size]
                else:
                    old_size  = old_groups[i].get("rows",2) * old_groups[i].get("cols",8)
                    new_size  = groups[i]["rows"] * groups[i]["cols"]
                    diff      = new_size - old_size
                    end       = offsets[i] + old_size
                    if diff > 0:
                        # Bank grew — insert empty slots at its end
                        import copy as _copy
                        for _ in range(diff):
                            empty = {"label": f"Sound {len(slots)+1}",
                                     "file": "", "color": "", "text_color": "",
                                     "loop": False, "overlap": False,
                                     "hotkey": "",
                                     "fx": _copy.deepcopy(DEFAULT_FX)}
                            slots.insert(end, empty)
                    elif diff < 0:
                        # Bank shrank — remove from its end (keep assigned slots at front)
                        del slots[end + diff: end]

            # Handle any new banks appended
            for i in range(len(old_groups), len(groups)):
                import copy as _copy
                new_size = groups[i]["rows"] * groups[i]["cols"]
                for _ in range(new_size):
                    slots.append({"label": f"Sound {len(slots)+1}",
                                  "file": "", "color": "", "text_color": "",
                                  "loop": False, "overlap": False,
                                  "hotkey": "",
                                  "fx": _copy.deepcopy(DEFAULT_FX)})

            # Cap at 508
            del slots[508:]
            c["soundboard_groups"] = groups

        # Hotkeys
        c.setdefault("hotkeys", {})
        for key, entry in self._hk.items():
            val = entry.get().strip()
            if val:
                c["hotkeys"][key] = val
            elif key in c["hotkeys"]:
                del c["hotkeys"][key]

        # Websites
        self._save_websites()

        # Mic
        if hasattr(self, "_mic_dev"):
            new_mic = self._mic_dev.get()
            c["mic_input_device"] = new_mic
            # Reinit MicManager with new device
            try:
                self.app.mic.reinit(new_mic)
            except Exception:
                pass
        if hasattr(self, "_duck_level"):
            c["mic_duck_level"] = round(self._duck_level.get(), 2)

        # Visual
        new_theme = self._theme.get()
        old_theme = c.get("color_theme", "Slate Broadcast")
        theme_changed = new_theme != old_theme
        if theme_changed:
            c["color_theme"] = new_theme
            if self.cfg.has_any_custom_colors():
                keep = messagebox.askyesno(
                    "Custom Button Colours",
                    "Keep your custom button colours with the new theme?\n\n"
                    "• Yes — keep\n• No — reset to theme defaults")
                if not keep:
                    self.cfg.clear_custom_colors()
        if new_theme == "Custom":
            # Custom theme already stored in custom_theme key via editor
            c["color_theme"] = "Custom"
        try:
            fs = int(self._font_size.get())
            c["font_size"] = max(8, min(20, fs))  # Clamp 8-20
        except ValueError:
            pass
        c["opacity"] = self._opacity.get()

        # Soundboard appearance
        c["playing_btn_color"]        = "" if self._playing_auto_var.get() \
                                        else self._playing_color
        c["playing_btn_blink"]        = self._blink_var.get()
        c["playing_btn_blink_rate"]   = self._blink_rate.get()
        c["bank_tab_highlight_color"] = self._tab_hi_color
        c["bank_tab_highlight_bg"]    = self._tab_bg_color
        try:
            c["nowplaying_flash_secs"] = int(self._np_flash_var.get())
        except ValueError:
            c["nowplaying_flash_secs"] = 30

        # Integrations
        c["discord_enabled"] = self._discord_en.get()
        c["discord_webhook"] = self._discord_url.get().strip()
        c["discord_message"] = self._discord_msg.get().strip()
        lbl = self._browser.get()
        c["browser_preference"] = self._browser_paths.get(lbl, "")

        self.cfg.save()

        # Reinit mixer if output device changed
        if new_out != old_out:
            self.app.audio.reinit(
                "" if new_out == "Default (System)" else new_out)

        # Apply recordings folder
        if hasattr(self.app, "recorder"):
            self.app.recorder.set_recordings_folder(self._rec_folder)

        self.app.register_hotkeys()
        self.app.apply_bg_color()
        try:
            self.app.soundboard.full_refresh()
        except Exception:
            pass

        # Apply theme changes without restart
        if theme_changed:
            self.cfg.apply_theme(new_theme)
            self.app.refresh_theme()

        self.destroy()


