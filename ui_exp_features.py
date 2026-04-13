"""
ui_exp_features.py — Broadcast Backpack v6.0.0
Experimental feature dialogs:
  • StreamSettingsDialog    — Icecast credentials + audio device
  • MarkerExportDialog      — Audition/Audacity marker export
  • AnalyticsDashboardDialog — Historical show stats
"""

import os, tkinter as tk, logging
import customtkinter as ctk
from tkinter import filedialog, messagebox
from pathlib import Path
from datetime import datetime, timezone, timedelta

from config import C, MARKERS_DIR, lighten

log = logging.getLogger("broadcast.exp")

try:
    import pytz
    HAS_PYTZ = True
except ImportError:
    HAS_PYTZ = False

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


# ═══════════════════════════════════════════════════════════════
# STREAM SETTINGS DIALOG
# ═══════════════════════════════════════════════════════════════

class StreamSettingsDialog(ctk.CTkToplevel):
    """Icecast stream credentials + audio device selector."""

    def __init__(self, parent, cfg, stream_engine):
        super().__init__(parent)
        self.cfg    = cfg
        self.engine = stream_engine
        self.title("📡  Stream Settings")
        self.geometry("460x500")
        self.configure(fg_color=C["bg2"])
        self.grab_set()
        self.lift()
        self._build()

    def _build(self):
        from streaming import StreamEngine as SE
        ctk.CTkLabel(self, text="📡  STREAM SETTINGS",
                     font=ctk.CTkFont("Segoe UI", 14, "bold"),
                     text_color=C["amber"]).pack(pady=(14, 4))

        if not SE.dependencies_ok():
            ctk.CTkLabel(self,
                text="⚠  sounddevice / lameenc not installed.\n"
                     "Run: pip install sounddevice lameenc",
                font=ctk.CTkFont("Segoe UI", 11),
                text_color=C["amber"],
                justify="center").pack(pady=6)

        frm = ctk.CTkScrollableFrame(self, fg_color=C["surface"])
        frm.pack(fill="both", expand=True, padx=14, pady=6)

        fields = [
            ("Server Host",     "stream_host",     "",      False),
            ("Port",            "stream_port",     "80",    False),
            ("Mount Point",     "stream_mount",    "/live", False),
            ("Username",        "stream_user",     "source",False),
            ("Password",        "stream_password", "",      True),
            ("Bitrate (kbps)",  "stream_bitrate",  "128",   False),
        ]
        self._vars = {}
        for label, key, default, masked in fields:
            row = ctk.CTkFrame(frm, fg_color="transparent")
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=f"{label}:", width=140,
                         font=ctk.CTkFont("Segoe UI", 11),
                         text_color=C["text"], anchor="w").pack(side="left")
            var = ctk.StringVar(value=str(self.cfg.config.get(key, default)))
            e = ctk.CTkEntry(row, textvariable=var, width=240,
                             font=ctk.CTkFont("Consolas", 11),
                             show="•" if masked else "")
            e.pack(side="left", padx=4)
            self._vars[key] = var

        # Auto-reconnect toggle
        rc_row = ctk.CTkFrame(frm, fg_color="transparent")
        rc_row.pack(fill="x", pady=3)
        ctk.CTkLabel(rc_row, text="Auto-Reconnect:", width=140,
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C["text"], anchor="w").pack(side="left")
        self._reconnect_var = ctk.BooleanVar(
            value=self.cfg.config.get("stream_auto_reconnect", True))
        ctk.CTkCheckBox(rc_row, text="", variable=self._reconnect_var,
                        fg_color=C["green"], hover_color=C["green_dim"],
                        checkmark_color=C["bg"]).pack(side="left", padx=4)

        # Reconnect attempts
        att_row = ctk.CTkFrame(frm, fg_color="transparent")
        att_row.pack(fill="x", pady=3)
        ctk.CTkLabel(att_row, text="Max Reconnects:", width=140,
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C["text"], anchor="w").pack(side="left")
        self._attempts_var = ctk.StringVar(
            value=str(self.cfg.config.get("stream_reconnect_attempts", 5)))
        ctk.CTkEntry(att_row, textvariable=self._attempts_var,
                     width=60, font=ctk.CTkFont("Consolas", 11)).pack(
            side="left", padx=4)

        # Audio device
        dev_row = ctk.CTkFrame(frm, fg_color="transparent")
        dev_row.pack(fill="x", pady=3)
        ctk.CTkLabel(dev_row, text="Audio Input:", width=140,
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C["text"], anchor="w").pack(side="left")
        from streaming import StreamEngine as SE
        dev_names = ["default"] + [name for _, name in SE.list_input_devices()]
        cur_dev = self.cfg.config.get("stream_audio_device", "default")
        self._dev_var = ctk.StringVar(value=cur_dev)
        ctk.CTkOptionMenu(dev_row, variable=self._dev_var,
                          values=dev_names, width=240,
                          font=ctk.CTkFont("Segoe UI", 11)).pack(
            side="left", padx=4)

        # Security note
        ctk.CTkLabel(frm,
            text="🔒  Password stored as plain text in config.json.\n"
                 "    Never share your config file.",
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=C["text_dim"],
            justify="left").pack(anchor="w", padx=4, pady=8)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=10)
        ctk.CTkButton(btn_row, text="💾 Save", width=100, height=32,
                      fg_color=C["blue_mid"],
                      font=ctk.CTkFont("Segoe UI", 11, "bold"),
                      command=self._save).pack(side="left", padx=6)
        ctk.CTkButton(btn_row, text="Cancel", width=80, height=32,
                      fg_color=C["surface"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=self.destroy).pack(side="left", padx=6)

    def _save(self):
        numeric = {"stream_port", "stream_bitrate", "stream_samplerate"}
        for key, var in self._vars.items():
            val = var.get().strip()
            if key in numeric:
                try:
                    val = int(val)
                except ValueError:
                    pass
            self.cfg.config[key] = val
        self.cfg.config["stream_audio_device"]   = self._dev_var.get()
        self.cfg.config["stream_auto_reconnect"] = self._reconnect_var.get()
        try:
            self.cfg.config["stream_reconnect_attempts"] = int(
                self._attempts_var.get())
        except ValueError:
            pass
        # Push updated config to streaming engine
        self.engine.update_config(self.cfg.config)
        self.cfg.save()
        messagebox.showinfo("Saved", "Stream settings saved.")
        self.destroy()


# ═══════════════════════════════════════════════════════════════
# MARKER EXPORT DIALOG
# ═══════════════════════════════════════════════════════════════

class MarkerExportDialog(ctk.CTkToplevel):
    """
    Export session events as markers for Adobe Audition or Audacity.

    Session log format (v4.1.0):
        [Mar 22 14:32:01  [00:23:45]] ▶ label  (1:23) [Board]
        [Mar 22 14:32:01] 🔴 WENT LIVE

    Wall clock time is in local timezone (America/Detroit).
    Show start/end can be entered in UTC if needed.
    """

    LOG_WALL_FMT  = "%b %d %H:%M:%S"   # e.g. Mar 22 14:32:01
    INPUT_UTC_FMT = "%a, %d %b %Y %H:%M:%S"   # MicroSIP-style UTC

    def __init__(self, parent, cfg, session_log_lines: list,
                 go_live_wall: datetime = None, duration_str: str = ""):
        super().__init__(parent)
        self.cfg               = cfg
        self.session_log_lines = session_log_lines
        self.go_live_wall      = go_live_wall
        self.duration_str      = duration_str
        self._markers          = []
        self.title("🎙️  Marker Export")
        self.geometry("700x620")
        self.configure(fg_color=C["bg2"])
        self.grab_set()
        self.lift()
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="🎙️  MARKER EXPORT",
                     font=ctk.CTkFont("Segoe UI", 14, "bold"),
                     text_color=C["amber"]).pack(pady=(12, 2))
        ctk.CTkLabel(self,
            text="Export your session events as markers for Audition or Audacity.",
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=C["text_dim"]).pack()

        top = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=6)
        top.pack(fill="x", padx=14, pady=8)

        # Show UTC window
        for label, attr, placeholder in [
            ("Show Start (UTC):", "_start_e",
             "Mon, 01 Jan 2025 01:00:00"),
            ("Show End (UTC):",   "_end_e",
             "Mon, 01 Jan 2025 03:00:00"),
        ]:
            row = ctk.CTkFrame(top, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=4)
            ctk.CTkLabel(row, text=label, width=150,
                         font=ctk.CTkFont("Segoe UI", 11),
                         text_color=C["text"], anchor="w").pack(side="left")
            e = ctk.CTkEntry(row, width=300,
                             placeholder_text=placeholder,
                             font=ctk.CTkFont("Consolas", 11))
            e.pack(side="left", padx=4)
            setattr(self, attr, e)

        # Pre-fill start and end from GO LIVE wall time + duration
        if self.go_live_wall and HAS_PYTZ:
            try:
                from datetime import timedelta
                tz      = pytz.timezone(
                    self.cfg.config.get("marker_timezone", "America/Detroit"))
                utc_start = self.go_live_wall.astimezone(pytz.utc)
                self._start_e.insert(0,
                    utc_start.strftime(self.INPUT_UTC_FMT))

                # Parse duration HH:MM:SS → timedelta
                if self.duration_str:
                    parts = self.duration_str.split(":")
                    if len(parts) == 3:
                        h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
                        utc_end = utc_start + timedelta(
                            hours=h, minutes=m, seconds=s)
                        self._end_e.insert(0,
                            utc_end.strftime(self.INPUT_UTC_FMT))
            except Exception:
                pass

        # MicroSIP CSV
        row3 = ctk.CTkFrame(top, fg_color="transparent")
        row3.pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkLabel(row3, text="MicroSIP CSV (optional):",
                     width=150,
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C["text"], anchor="w").pack(side="left")
        self._csv_var = tk.StringVar(value="")
        ctk.CTkLabel(row3, textvariable=self._csv_var,
                     font=ctk.CTkFont("Segoe UI", 11),
                     text_color=C["text_dim"]).pack(side="left", padx=4)
        ctk.CTkButton(row3, text="Browse…", width=80, height=26,
                      fg_color=C["btn"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=self._browse_csv).pack(side="left", padx=4)

        ctk.CTkButton(top, text="⚙  Build Markers", width=150, height=30,
                      fg_color=C["blue_mid"],
                      font=ctk.CTkFont("Segoe UI", 11, "bold"),
                      command=self._build_markers).pack(pady=(4, 10))

        # Preview
        ctk.CTkLabel(self, text="Preview",
                     font=ctk.CTkFont("Segoe UI", 11, "bold"),
                     text_color=C["text"]).pack(anchor="w", padx=14, pady=(0, 2))
        self._preview = ctk.CTkTextbox(
            self, fg_color=C["surface"],
            text_color=C["text_dim"],
            font=ctk.CTkFont("Consolas", 11),
            state="disabled")
        self._preview.pack(fill="both", expand=True, padx=14, pady=(0, 6))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=8)
        ctk.CTkButton(btn_row, text="Export Audition .csv",
                      width=170, height=32,
                      fg_color=C["blue_mid"],
                      font=ctk.CTkFont("Segoe UI", 11, "bold"),
                      command=lambda: self._export("audition")).pack(
            side="left", padx=4)
        ctk.CTkButton(btn_row, text="Export Audacity .txt",
                      width=170, height=32,
                      fg_color=C["green_dim"],
                      font=ctk.CTkFont("Segoe UI", 11, "bold"),
                      command=lambda: self._export("audacity")).pack(
            side="left", padx=4)
        ctk.CTkButton(btn_row, text="Close", width=80, height=32,
                      fg_color=C["surface"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=self.destroy).pack(side="left", padx=4)

    def _browse_csv(self):
        path = filedialog.askopenfilename(
            title="Select MicroSIP Call Log CSV",
            filetypes=[("CSV", "*.csv"), ("All", "*.*")])
        if path:
            self._csv_var.set(path)

    def _parse_utc(self, s: str):
        try:
            naive = datetime.strptime(s.strip(), self.INPUT_UTC_FMT)
            return naive.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    def _parse_log_wall(self, wall_str: str):
        """Parse 'Mar 22 14:32:01' as local datetime, convert to UTC."""
        if not HAS_PYTZ:
            return None
        try:
            tz    = pytz.timezone(
                self.cfg.config.get("marker_timezone", "America/Detroit"))
            # Year not in log — use current year
            year  = datetime.now().year
            naive = datetime.strptime(
                f"{wall_str} {year}", f"{self.LOG_WALL_FMT} %Y")
            local = tz.localize(naive)
            return local.astimezone(pytz.utc).replace(tzinfo=timezone.utc)
        except Exception:
            return None

    def _secs_to_hms(self, sec: float) -> str:
        s = int(sec)
        h = s // 3600
        m = (s % 3600) // 60
        s = s % 60
        return f"{h}:{m:02d}:{s:02d}"

    def _build_markers(self):
        if not HAS_PYTZ:
            messagebox.showwarning(
                "pytz Missing",
                "pytz is required for marker export.\n"
                "Run: pip install pytz")
            return

        show_start = self._parse_utc(self._start_e.get())
        show_end   = self._parse_utc(self._end_e.get())

        if not show_start or not show_end:
            messagebox.showerror(
                "Parse Error",
                "Could not parse show times.\n"
                f"Format: Mon, 01 Jan 2025 01:00:00")
            return
        if show_end <= show_start:
            messagebox.showerror("Time Error",
                                 "Show end must be after show start.")
            return

        self._markers = []  # Now: (offset, label, duration_secs)
        import re

        # ── 1. Parse session log entries ──────────────────────────
        # v4.1.0 format:  [Mar 22 14:32:01  [00:23:45]] text
        #          or:  [Mar 22 14:32:01] text
        log_pat = re.compile(
            r"^\[([A-Za-z]{3}\s+\d+\s+\d{2}:\d{2}:\d{2})"
            r"(?:\s+\[[\d:]+\])?\]\s+(.+)$"
        )

        # Track call starts for matching
        call_starts = {}  # phone -> (offset, wall_utc)
        
        # Pattern to extract phone number and duration from call entries
        call_start_pat = re.compile(r"📞\s*Call started\s*[—-]\s*(\+?\d+)")
        call_end_pat = re.compile(
            r"📞\s*Call ended\s*[—-]\s*(\+?\d+)"
            r"(?:\s*[—-]\s*duration\s*(\d{2}):(\d{2}))?"
        )

        for line in self.session_log_lines:
            m = log_pat.match(line.strip())
            if not m:
                continue
            wall_str = m.group(1).strip()
            content  = m.group(2).strip()

            wall_utc = self._parse_log_wall(wall_str)
            if not wall_utc:
                continue
            if not (show_start <= wall_utc <= show_end):
                continue

            offset = (wall_utc - show_start).total_seconds()

            # Skip system/status lines that aren't meaningful markers
            skip_prefixes = (
                "🔴 WENT LIVE", "⏹ ENDED LIVE",
                "📡 Stream", "⚠ Stream",
                "🚨 PANIC",
            )
            if any(content.startswith(p) for p in skip_prefixes):
                continue

            # Handle call markers specially
            start_m = call_start_pat.search(content)
            end_m = call_end_pat.search(content)
            
            if start_m:
                # Track call start for matching
                phone = start_m.group(1)
                call_starts[phone] = (offset, wall_utc)
                continue  # Don't add as separate marker
                
            elif end_m:
                phone = end_m.group(1)
                dur_min = end_m.group(2)
                dur_sec = end_m.group(3)
                
                # Only create marker if we have a matching start AND duration
                if phone in call_starts and dur_min and dur_sec:
                    start_offset, _ = call_starts.pop(phone)
                    duration_secs = int(dur_min) * 60 + int(dur_sec)
                    
                    if duration_secs > 0:
                        dur_str = f"{int(dur_min):02d}:{int(dur_sec):02d}"
                        label = f"📞 Call — {phone} Duration: {dur_str}"
                        self._markers.append((start_offset, label, duration_secs))
                # Skip orphaned ends (no matching start or no duration)
                continue

            # Build clean label for non-call entries
            if "▶" in content:
                # Extract just the filename, strip duration suffix
                fn_m  = re.search(r"▶\s+(.+?)\s+\(", content)
                label = f"▶ {fn_m.group(1).strip()}" if fn_m else content
            elif "⭐" in content:
                label = content   # already has ⭐
            elif "📌" in content:
                label = content   # already has 📌
            else:
                label = content

            self._markers.append((offset, label, 0))  # 0 duration for non-calls

        # ── 2. MicroSIP CSV calls ─────────────────────────────────
        csv_path = self._csv_var.get().strip()
        if csv_path and Path(csv_path).exists():
            if not HAS_PANDAS:
                messagebox.showwarning(
                    "pandas Missing",
                    "pandas is needed to read the call CSV.\n"
                    "Run: pip install pandas")
            else:
                try:
                    import pytz as _pytz
                    df  = pd.read_csv(csv_path)
                    df2 = (
                        df.assign(
                            call_dt=pd.to_datetime(
                                df["Time"], unit="s", utc=True))
                        .loc[lambda d: (
                            d["Info"].eq("Call Ended") |
                            d["Info"].str.contains("Voicemail", na=False)
                        )]
                        .loc[lambda d: (
                            (d["call_dt"] >= pd.Timestamp(show_start)) &
                            (d["call_dt"] <= pd.Timestamp(show_end))
                        )]
                    )
                    for row in df2.itertuples():
                        call_utc = row.call_dt.to_pydatetime().replace(
                            tzinfo=timezone.utc)
                        dur      = int(getattr(row, "Duration", 0))
                        # Calculate start offset (end time - duration)
                        start_utc = call_utc - timedelta(seconds=dur)
                        offset   = (start_utc - show_start).total_seconds()
                        mm, ss   = dur // 60, dur % 60
                        name     = (getattr(row, "Name",   "") or
                                    getattr(row, "Number", ""))
                        lbl = f"📞 Call — {name} Duration: {mm:02d}:{ss:02d}"
                        self._markers.append((offset, lbl, dur))
                except Exception as e:
                    messagebox.showerror("CSV Error", str(e))

        # ── Sort + preview ────────────────────────────────────────
        self._markers.sort(key=lambda x: x[0])

        self._preview.configure(state="normal")
        self._preview.delete("1.0", tk.END)
        if not self._markers:
            self._preview.insert(tk.END,
                "No markers found in the given time window.\n"
                "Make sure your show start/end times are in UTC.")
        else:
            for offset, label, dur in self._markers:
                dur_str = f" [{self._secs_to_hms(dur)}]" if dur > 0 else ""
                self._preview.insert(
                    tk.END, f"{self._secs_to_hms(offset):>12}{dur_str}   {label}\n")
        self._preview.configure(state="disabled")

    def _export(self, fmt: str):
        if not self._markers:
            messagebox.showwarning("No Markers",
                                   "Build markers first.")
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if fmt == "audition":
            default_name = f"markers_{ts}.csv"
            filetypes    = [("Audition CSV", "*.csv"), ("All", "*.*")]
        else:
            default_name = f"labels_{ts}.txt"
            filetypes    = [("Audacity Labels", "*.txt"), ("All", "*.*")]

        path = filedialog.asksaveasfilename(
            title=f"Save {fmt.title()} Markers",
            initialfile=default_name,
            defaultextension=".csv" if fmt == "audition" else ".txt",
            filetypes=filetypes,
            initialdir=str(MARKERS_DIR))
        if not path:
            return

        try:
            import re as _re
            # Strip emojis for the Name field — keep text only
            _emoji_pat = _re.compile(
                "[\U00010000-\U0010ffff"
                "\U00002600-\U000027BF"
                "\U0001F300-\U0001FAFF"
                "\u2600-\u27BF]+",
                flags=_re.UNICODE)

            def _clean(text):
                return _emoji_pat.sub("", text).strip(" —-").strip()

            lines = []
            if fmt == "audition":
                lines.append(
                    "Name\tStart\tDuration Time\tFormat\tType\tDescription")
                for offset, label, dur in self._markers:
                    name = _clean(label)[:40].rstrip()
                    dur_hms = self._secs_to_hms(dur) if dur > 0 else "0:00:00"
                    lines.append(
                        f"{name}\t{self._secs_to_hms(offset)}\t"
                        f"{dur_hms}\tdecimal\tCue\t{label}")
            else:
                for offset, label, dur in self._markers:
                    end = offset + dur if dur > 0 else offset + 0.001
                    lines.append(f"{offset:.3f}\t{end:.3f}\t{label}")

            Path(path).write_text("\n".join(lines), encoding="utf-8")
            messagebox.showinfo(
                "Exported",
                f"Saved {len(self._markers)} markers:\n{path}")
        except Exception as e:
            messagebox.showerror("Export Error", str(e))


# ═══════════════════════════════════════════════════════════════
# ANALYTICS DASHBOARD DIALOG
# ═══════════════════════════════════════════════════════════════

class AnalyticsDashboardDialog(ctk.CTkToplevel):

    def __init__(self, parent, analytics_manager):
        super().__init__(parent)
        self.am = analytics_manager
        self.title("📊  Show Analytics")
        self.geometry("640x580")
        self.configure(fg_color=C["bg2"])
        self.grab_set()
        self.lift()
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="📊  SHOW ANALYTICS",
                     font=ctk.CTkFont("Segoe UI", 14, "bold"),
                     text_color=C["amber"]).pack(pady=(14, 4))

        totals = self.am.get_totals()
        if not totals:
            ctk.CTkLabel(self,
                text="No show data yet.\nComplete a show to start tracking.",
                font=ctk.CTkFont("Segoe UI", 12),
                text_color=C["text_dim"],
                justify="center").pack(expand=True)
            ctk.CTkButton(self, text="Close", width=80,
                          fg_color=C["surface"],
                          command=self.destroy).pack(pady=12)
            return

        # ── Summary cards ──────────────────────────────────────────
        cards = ctk.CTkFrame(self, fg_color="transparent")
        cards.pack(fill="x", padx=14, pady=6)

        def _card(parent, label, value, col=C["blue_mid"]):
            f = ctk.CTkFrame(parent, fg_color=C["surface"],
                             corner_radius=8, width=110)
            f.pack(side="left", padx=3, pady=4, fill="y")
            f.pack_propagate(False)
            ctk.CTkLabel(f, text=value,
                         font=ctk.CTkFont("Courier New", 17, "bold"),
                         text_color=col).pack(pady=(8, 2))
            ctk.CTkLabel(f, text=label,
                         font=ctk.CTkFont("Segoe UI", 11),
                         text_color=C["text_dim"]).pack(pady=(0, 8))

        avg_h = totals["avg_duration"] // 3600
        avg_m = (totals["avg_duration"] % 3600) // 60
        tot_h = totals["total_duration"] // 3600
        tot_m = (totals["total_duration"] % 3600) // 60

        _card(cards, "Shows",       str(totals["total_shows"]),  C["blue_light"])
        _card(cards, "Avg Duration",f"{avg_h}h {avg_m}m",       C["amber"])
        _card(cards, "Total On Air",f"{tot_h}h {tot_m}m",       C["green"])
        _card(cards, "Total Calls", str(totals["total_calls"]),  C["text"])
        _card(cards, "Gold Moments",str(totals["total_gold"]),   C["gold"])

        # ── Last 7 shows bar chart ────────────────────────────────
        ctk.CTkLabel(self, text="Last 7 Shows — Duration",
                     font=ctk.CTkFont("Segoe UI", 11, "bold"),
                     text_color=C["text"]).pack(
            anchor="w", padx=16, pady=(8, 2))

        chart = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=6)
        chart.pack(fill="x", padx=14, pady=(0, 6))

        durations = totals.get("last_7_durations", [])
        dates     = totals.get("last_7_dates",     [])
        max_dur   = max(durations) if durations else 1

        for dur, date in zip(reversed(durations), reversed(dates)):
            row = ctk.CTkFrame(chart, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=2)
            ctk.CTkLabel(row, text=date, width=80,
                         font=ctk.CTkFont("Consolas", 11),
                         text_color=C["text_dim"], anchor="w").pack(side="left")
            bar_w = max(4, int(310 * dur / max_dur))
            ctk.CTkFrame(row, fg_color=C["blue_mid"],
                         height=14, width=bar_w,
                         corner_radius=3).pack(side="left", padx=2)
            h, m = dur // 3600, (dur % 3600) // 60
            ctk.CTkLabel(row, text=f"{h}h {m}m",
                         font=ctk.CTkFont("Consolas", 11),
                         text_color=C["text_dim"]).pack(
                side="left", padx=4)

        # ── Top sounds ────────────────────────────────────────────
        if totals.get("top_sounds"):
            ctk.CTkLabel(self, text="Most Played Sounds",
                         font=ctk.CTkFont("Segoe UI", 11, "bold"),
                         text_color=C["text"]).pack(
                anchor="w", padx=16, pady=(4, 2))
            top_f = ctk.CTkFrame(self, fg_color=C["surface"],
                                 corner_radius=6)
            top_f.pack(fill="x", padx=14, pady=(0, 6))
            for fname, count in totals["top_sounds"]:
                row = ctk.CTkFrame(top_f, fg_color="transparent")
                row.pack(fill="x", padx=8, pady=1)
                ctk.CTkLabel(row, text=f"▶  {fname}",
                             font=ctk.CTkFont("Segoe UI", 11),
                             text_color=C["text"],
                             anchor="w").pack(side="left",
                                              fill="x", expand=True)
                ctk.CTkLabel(row, text=f"×{count}",
                             font=ctk.CTkFont("Consolas", 11, "bold"),
                             text_color=C["amber"]).pack(side="right")

        ctk.CTkButton(self, text="Close", width=80,
                      fg_color=C["surface"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=self.destroy).pack(pady=10)
