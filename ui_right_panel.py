"""
ui_right_panel.py — Broadcast Backpack v6.0.0
RightPanel      : fixed-width right column
ToolsSection    : Quick Folders + Website launcher
NotesSection    : two-tab notepad with autosave
SessionLogSection: timestamped session log
"""

import os, time, webbrowser, tkinter as tk, logging
import customtkinter as ctk
from tkinter import filedialog, messagebox
from datetime import datetime
from pathlib import Path

from config import C, SESSION_DIR, DATA_DIR, lighten

log = logging.getLogger("broadcast.panel")


# ═══════════════════════════════════════════════════════════════
# SECTION HEADER  — shared styled label
# ═══════════════════════════════════════════════════════════════

def _section_hdr(parent, icon: str, title: str):
    # Outer frame — slightly lighter top edge for depth
    outer = tk.Frame(parent, bg=C.get("shine", C["border"]), height=27)
    outer.pack(fill="x")
    outer.pack_propagate(False)
    # Inner body sits 1px below giving a top-edge shine
    f = tk.Frame(outer, bg=C["elevated"])
    f.pack(fill="both", expand=True, pady=(1, 0))
    tk.Label(f, text=f"  {icon}  {title.upper()}",
             bg=C["elevated"], fg=C["text"],
             font=("Segoe UI", 11, "bold"),
             padx=4, pady=4).pack(side="left")
    return f


# ═══════════════════════════════════════════════════════════════
# TOOLS SECTION
# ═══════════════════════════════════════════════════════════════

class ToolsSection(ctk.CTkFrame):
    def __init__(self, parent, cfg):
        super().__init__(parent, fg_color=C["bg2"], corner_radius=0)
        self.cfg = cfg
        _section_hdr(self, "📁", "Quick Folders + Sites")
        self._build()

    def _build(self):
        # 6 folder buttons in 2 rows of 3
        folders_f = ctk.CTkFrame(self, fg_color="transparent")
        folders_f.pack(fill="x", padx=4, pady=(4, 2))

        self._fbtns = []
        for i in range(6):
            d = self.cfg.config["folders"][i] if i < len(
                self.cfg.config["folders"]) else {}
            label = d.get("label", f"Folder {i+1}")
            color = d.get("color","") or C["btn"]
            tc    = d.get("text_color","") or C["text"]
            b = ctk.CTkButton(
                folders_f, text=label, height=26,
                corner_radius=5,
                fg_color=color, hover_color=lighten(color, 1.2),
                text_color=tc,
                font=ctk.CTkFont("Segoe UI", 11),
                command=lambda idx=i: self._open(idx))
            b.grid(row=i//3, column=i%3,
                   padx=2, pady=1, sticky="ew")
            b.bind("<Button-3>", lambda e, idx=i: self._ctx(e, idx))
            self._fbtns.append(b)
        for c in range(3):
            folders_f.grid_columnconfigure(c, weight=1)

        # Website launcher
        web_f = ctk.CTkFrame(self, fg_color="transparent")
        web_f.pack(fill="x", padx=4, pady=(2, 6))

        # Listbox with scrollbar instead of dropdown
        list_frame = tk.Frame(web_f, bg=C["surface"], highlightthickness=1,
                              highlightbackground=C["border"])
        list_frame.pack(side="left", padx=(0, 4))
        
        self._site_scroll = tk.Scrollbar(list_frame, width=12)
        self._site_scroll.pack(side="right", fill="y")
        
        self._site_list = tk.Listbox(
            list_frame, height=4, width=18,
            bg=C["surface"], fg=C["text"],
            selectbackground=C["blue_mid"],
            selectforeground=C["text_hi"],
            font=("Segoe UI", 10),
            bd=0, highlightthickness=0,
            yscrollcommand=self._site_scroll.set,
            exportselection=False)
        self._site_list.pack(side="left", fill="both")
        self._site_scroll.config(command=self._site_list.yview)
        self._site_list.bind("<Double-1>", lambda e: self._launch())
        
        ctk.CTkButton(
            web_f, text="Go", width=32, height=26,
            fg_color=C["blue_mid"],
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            command=self._launch
        ).pack(side="left", padx=(0, 2))
        ctk.CTkButton(
            web_f, text="+", width=26, height=26,
            corner_radius=5,
            fg_color=C["btn"],
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
            command=self._add_site
        ).pack(side="left", padx=(0, 2))
        ctk.CTkButton(
            web_f, text="📥", width=26, height=26,
            corner_radius=5,
            fg_color=C["btn"],
            font=ctk.CTkFont("Segoe UI", 11),
            command=self._import_sites
        ).pack(side="left", padx=(0, 2))
        ctk.CTkButton(
            web_f, text="🗑", width=26, height=26,
            corner_radius=5,
            fg_color=C["btn"],
            font=ctk.CTkFont("Segoe UI", 11),
            command=self._del_site
        ).pack(side="left")
        
        self._refresh_sites()

    def _open(self, idx):
        folders = self.cfg.config.get("folders", [])
        if idx >= len(folders):
            return
        path = folders[idx].get("path", "")
        if not path:
            messagebox.showinfo("Empty",
                                "Right-click to assign a folder.")
            return
        if os.path.isdir(path):
            os.startfile(path)
        else:
            messagebox.showerror("Not Found",
                                 f"Folder not found:\n{path}")

    def _launch(self):
        sel = self._site_list.curselection()
        if not sel:
            return
        idx = sel[0]
        sites = self.cfg.config.get("websites", [])
        if idx < len(sites):
            webbrowser.open(sites[idx]["url"])

    def _ctx(self, e, idx):
        m = tk.Menu(self, tearoff=0,
                    bg=C["surface"], fg=C["text"],
                    activebackground=C["blue_mid"],
                    font=("Segoe UI", 11))
        m.add_command(label="📂  Assign Folder",
                      command=lambda: self._assign(idx))
        m.add_command(label="🎨  Customize Button...",
                      command=lambda: self._customize(idx))
        m.add_command(label="🗑  Clear",
                      command=lambda: self._clear(idx))
        m.tk_popup(e.x_root, e.y_root)

    def _assign(self, idx):
        path = filedialog.askdirectory(title="Select Folder")
        if path:
            folders = self.cfg.config.setdefault("folders", [])
            while len(folders) <= idx:
                folders.append({"label":f"Folder {len(folders)+1}",
                                "path":"","color":"","text_color":""})
            label = Path(path).name[:12] or f"F{idx+1}"
            folders[idx]["path"]  = path
            folders[idx]["label"] = label
            self.cfg.save()
            self._fbtns[idx].configure(text=label)

    def _customize(self, idx):
        from ui_dialogs import ButtonSettingsDialog
        folders = self.cfg.config.get("folders", [])
        d = folders[idx] if idx < len(folders) else {}
        dlg = ButtonSettingsDialog(
            self.winfo_toplevel(),
            label=d.get("label",""),
            color=d.get("color",""),
            text_color=d.get("text_color",""),
            allow_rename=True)
        self.winfo_toplevel().wait_window(dlg)
        if dlg.result:
            while len(self.cfg.config["folders"]) <= idx:
                self.cfg.config["folders"].append(
                    {"label":f"Folder {idx+1}","path":"",
                     "color":"","text_color":""})
            self.cfg.config["folders"][idx].update({
                "label":      dlg.result["label"] or d.get("label",""),
                "color":      dlg.result["color"],
                "text_color": dlg.result["text_color"],
            })
            self.cfg.save()
            self._fbtns[idx].configure(
                text=self.cfg.config["folders"][idx]["label"],
                fg_color=dlg.result["color"] or C["btn"],
                text_color=dlg.result["text_color"] or C["text"])

    def _clear(self, idx):
        if idx < len(self.cfg.config.get("folders",[])):
            self.cfg.config["folders"][idx]["path"] = ""
            self.cfg.save()

    def refresh(self):
        folders = self.cfg.config.get("folders", [])
        for i, b in enumerate(self._fbtns):
            d = folders[i] if i < len(folders) else {}
            b.configure(text=d.get("label", f"Folder {i+1}"),
                        fg_color=d.get("color","") or C["btn"],
                        text_color=d.get("text_color","") or C["text"])
        self._refresh_sites()

    def _refresh_sites(self):
        sites  = self.cfg.config.get("websites", [])
        self._site_list.delete(0, "end")
        for s in sites:
            self._site_list.insert("end", s["label"])
        if sites:
            self._site_list.selection_set(0)

    def _add_site(self):
        """Quick-add a website via a simple two-field dialog."""
        dlg = tk.Toplevel(self)
        dlg.title("Add Website")
        dlg.configure(bg=C["bg2"])
        dlg.resizable(False, False)
        dlg.grab_set()
        pad = dict(padx=10, pady=4)
        tk.Label(dlg, text="Label:", bg=C["bg2"],
                 fg=C["text"], font=("Segoe UI", 11)).grid(
                     row=0, column=0, sticky="e", **pad)
        lbl_e = tk.Entry(dlg, bg=C["surface"], fg=C["text"],
                         insertbackground=C["text"],
                         relief="flat", font=("Segoe UI", 11))
        lbl_e.grid(row=0, column=1, sticky="ew", **pad)
        tk.Label(dlg, text="URL:", bg=C["bg2"],
                 fg=C["text"], font=("Segoe UI", 11)).grid(
                     row=1, column=0, sticky="e", **pad)
        url_e = tk.Entry(dlg, width=32, bg=C["surface"],
                         fg=C["text"], insertbackground=C["text"],
                         relief="flat", font=("Segoe UI", 11))
        url_e.grid(row=1, column=1, sticky="ew", **pad)
        url_e.insert(0, "https://")

        def _ok():
            lbl = lbl_e.get().strip()
            url = url_e.get().strip()
            if not lbl or not url:
                return
            self.cfg.config.setdefault("websites", []).append(
                {"label": lbl, "url": url})
            self.cfg.save()
            self._refresh_sites()
            # Select the newly added item (last in list)
            count = self._site_list.size()
            if count > 0:
                self._site_list.selection_clear(0, "end")
                self._site_list.selection_set(count - 1)
                self._site_list.see(count - 1)
            dlg.destroy()

        btn_f = tk.Frame(dlg, bg=C["bg2"])
        btn_f.grid(row=2, column=0, columnspan=2, pady=6)
        tk.Button(btn_f, text="Add", bg=C["blue_mid"],
                  fg=C["text_hi"], relief="flat",
                  padx=14, pady=4,
                  font=("Segoe UI", 11, "bold"),
                  command=_ok).pack(side="left", padx=4)
        tk.Button(btn_f, text="Cancel", bg=C["btn"],
                  fg=C["text"], relief="flat",
                  padx=10, pady=4,
                  font=("Segoe UI", 11),
                  command=dlg.destroy).pack(side="left", padx=4)
        url_e.bind("<Return>", lambda e: _ok())
        lbl_e.focus_set()

    def _del_site(self):
        """Delete the currently selected website."""
        sel = self._site_list.curselection()
        if not sel:
            return
        idx = sel[0]
        sites = self.cfg.config.get("websites", [])
        if idx >= len(sites):
            return
        label = sites[idx]["label"]
        from tkinter import messagebox
        if messagebox.askyesno("Remove Site",
                               f"Remove '{label}'?"):
            del sites[idx]
            self.cfg.config["websites"] = sites
            self.cfg.save()
            self._refresh_sites()

    def _import_sites(self):
        """Import websites from a text file. Format: label|url per line."""
        path = filedialog.askopenfilename(
            title="Import Websites",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            messagebox.showerror("Import Failed", f"Could not read file:\n{e}")
            return

        sites = self.cfg.config.setdefault("websites", [])
        existing = {s["label"] for s in sites}
        added = 0
        skipped = 0

        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue  # skip empty lines and comments

            if "|" in line:
                # Format: label|url
                parts = line.split("|", 1)
                label = parts[0].strip()
                url   = parts[1].strip()
            else:
                # Just a URL — generate label from domain
                url = line
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    label = parsed.netloc.replace("www.", "")[:20]
                except Exception:
                    label = url[:20]

            if not url:
                continue

            # Add https:// if missing
            if not url.startswith(("http://", "https://")):
                url = "https://" + url

            # Skip duplicates
            if label in existing:
                skipped += 1
                continue

            sites.append({"label": label, "url": url})
            existing.add(label)
            added += 1

        self.cfg.save()
        self._refresh_sites()
        messagebox.showinfo(
            "Import Complete",
            f"Added {added} site(s)." +
            (f"\nSkipped {skipped} duplicate(s)." if skipped else ""))


# ═══════════════════════════════════════════════════════════════
# NOTES SECTION
# ═══════════════════════════════════════════════════════════════

class NotesSection(ctk.CTkFrame):
    def __init__(self, parent, cfg, get_elapsed=None,
                 get_is_live=None, session_log=None):
        super().__init__(parent, fg_color=C["bg2"], corner_radius=0)
        self.cfg         = cfg
        self.get_elapsed = get_elapsed or (lambda: "")
        self.get_is_live = get_is_live or (lambda: False)
        self.session_log = session_log
        self._boxes:  dict = {}
        self._tabs:   list = []
        self._cur_tab = 0
        self._autosave_job = None
        _section_hdr(self, "📝", "Notes")
        self._build()
        self._schedule_autosave()

    def _build(self):
        tab_names = self.cfg.config.get(
            "note_tabs", ["Show Notes", "Premises & Ideas"])

        # Tab buttons
        tab_bar = tk.Frame(self, bg=C["bg2"])
        tab_bar.pack(fill="x")
        self._tab_btns = []
        for i, name in enumerate(tab_names):
            b = tk.Button(
                tab_bar, text=name,
                bg=C["blue_mid"] if i == 0 else C["btn"],
                fg=C["text_hi"] if i == 0 else C["text_dim"],
                activebackground=C["blue_mid"],
                relief="flat", bd=0, padx=10,
                font=("Segoe UI", 11,
                       "bold" if i == 0 else "normal"),
                cursor="hand2",
                command=lambda idx=i: self._switch(idx))
            b.pack(side="left", fill="y", padx=1)
            self._tab_btns.append(b)

        # Clear + Save buttons on the right of the tab bar
        tk.Button(
            tab_bar, text="💾 Save",
            bg=C["btn"], fg=C["text_dim"],
            activebackground=C["btn_hover"],
            relief="flat", bd=0, padx=8,
            font=("Segoe UI", 11), cursor="hand2",
            command=self._save_and_export
        ).pack(side="right", padx=2, pady=1)

        tk.Button(
            tab_bar, text="🗑 Clear",
            bg=C["btn"], fg=C["text_dim"],
            activebackground=C["btn_hover"],
            relief="flat", bd=0, padx=8,
            font=("Segoe UI", 11), cursor="hand2",
            command=self._clear_current
        ).pack(side="right", padx=2, pady=1)

        # Text boxes (stacked, only current visible)
        self._box_frame = tk.Frame(self, bg=C["bg2"])
        self._box_frame.pack(fill="both", expand=True)

        content = self.cfg.config.get("notes_content", {})
        for i, name in enumerate(tab_names):
            box = tk.Text(
                self._box_frame,
                bg=C["surface"], fg=C["text"],
                insertbackground=C["amber"],
                selectbackground=C["blue_mid"],
                font=("Segoe UI", 11),
                relief="flat", bd=0,
                wrap="word", padx=6, pady=6)
            saved = content.get(name, "")
            if saved:
                box.insert("1.0", saved)
            self._boxes[name] = box
            self._tabs.append(name)

        # Show first tab
        self._switch(0)

    def _switch(self, idx: int):
        self._save_current()
        self._cur_tab = idx
        for name, box in self._boxes.items():
            box.pack_forget()
        tab_name = self._tabs[idx] if idx < len(self._tabs) else ""
        if tab_name in self._boxes:
            self._boxes[tab_name].pack(
                fill="both", expand=True)
        for i, b in enumerate(self._tab_btns):
            active = (i == idx)
            b.configure(
                bg=C["blue_mid"] if active else C["btn"],
                fg=C["text_hi"] if active else C["text_dim"],
                font=("Segoe UI", 11,
                       "bold" if active else "normal"))

    def _clear_current(self):
        """Clear the currently visible notes tab."""
        from tkinter import messagebox
        if self._cur_tab < len(self._tabs):
            name = self._tabs[self._cur_tab]
            if messagebox.askyesno("Clear Notes",
                                   f"Clear '{name}'?"):
                box = self._boxes.get(name)
                if box:
                    box.delete("1.0", "end")
                self.cfg.config.setdefault(
                    "notes_content", {})[name] = ""
                self.cfg.save()

    def _save_current(self):
        if self._cur_tab < len(self._tabs):
            name = self._tabs[self._cur_tab]
            if name in self._boxes:
                content = self._boxes[name].get("1.0", "end-1c")
                self.cfg.config.setdefault(
                    "notes_content", {})[name] = content

    def _insert_timestamp(self):
        fmt   = self.cfg.config.get("timestamp_format", "%H:%M:%S")
        ts    = datetime.now().strftime(fmt)
        elap  = self.get_elapsed()
        entry = f"\n[{ts}]" + (f" +{elap}" if elap else "") + " "
        if self._cur_tab < len(self._tabs):
            name = self._tabs[self._cur_tab]
            box  = self._boxes.get(name)
            if box:
                box.insert("end", entry)
                box.see("end")

    def _insert_gold(self):
        fmt   = self.cfg.config.get("timestamp_format", "%H:%M:%S")
        ts    = datetime.now().strftime(fmt)
        elap  = self.get_elapsed()
        entry = f"\n⭐ GOLD [{ts}]" + (f" +{elap}" if elap else "") + " "
        if self._cur_tab < len(self._tabs):
            name = self._tabs[self._cur_tab]
            box  = self._boxes.get(name)
            if box:
                box.insert("end", entry)
                box.see("end")
        if self.session_log:
            try:
                self.session_log.log_event("⭐ Gold Moment")
            except Exception:
                pass

    def save_all(self):
        """Save all tabs to config silently (no dialog)."""
        self._save_current()
        self.cfg.save()

    def _save_and_export(self):
        """Called by the Save button — saves config then prompts for .txt export."""
        self._save_current()
        self.cfg.save()
        self._export_to_file()

    def _export_to_file(self):
        """Export current tab's notes to a timestamped .txt file."""
        from tkinter import filedialog
        from datetime import datetime as _dt
        from pathlib import Path
        if self._cur_tab >= len(self._tabs):
            return
        name    = self._tabs[self._cur_tab]
        content = self.cfg.config.get(
            "notes_content", {}).get(name, "")
        if not content.strip():
            from tkinter import messagebox
            messagebox.showinfo("Nothing to Save",
                               "This notes tab is empty.")
            return
        ts       = _dt.now().strftime("%Y-%m-%d_%H%M")
        default  = f"notes_{name.replace(' ','_')}_{ts}.txt"
        path = filedialog.asksaveasfilename(
            title="Save Notes As",
            defaultextension=".txt",
            initialfile=default,
            filetypes=[("Text file", "*.txt"),
                       ("All files", "*.*")])
        if path:
            try:
                Path(path).write_text(content, encoding="utf-8")
            except Exception as e:
                from tkinter import messagebox
                messagebox.showerror("Save Failed", str(e))

    def get_all(self) -> dict:
        self._save_current()
        return self.cfg.config.get("notes_content", {})

    def populate_show_template(self):
        """Auto-populate Show Notes tab with template when GO LIVE is pressed."""
        try:
            if not self.cfg.config.get("show_notes_template_enabled", True):
                return
            
            # Get Show Notes tab (first tab by default)
            tab_names = self.cfg.config.get("note_tabs", ["Show Notes", "Premises & Ideas"])
            if not tab_names or not self._tabs:
                return
            show_notes_tab = self._tabs[0]  # Use actual first tab
            box = self._boxes.get(show_notes_tab)
            if not box:
                return
            
            # Check if already has substantial content (more than just whitespace)
            current = box.get("1.0", "end").strip()
            if len(current) > 10:  # Skip if has real content
                return
            
            # Clear any whitespace
            box.delete("1.0", "end")
            
            # Build template
            from datetime import datetime
            ep_num = self.cfg.config.get("episode_number", 1)
            date_str = datetime.now().strftime("%B %d, %Y")
            show_name = self.cfg.config.get("show_name", "The Chill")
            
            template = f"""═══════════════════════════════════════
{show_name} — Episode {ep_num}
{date_str}
═══════════════════════════════════════

SEGMENTS:
• 

CALLERS:
• 

HIGHLIGHTS:
• 

NOTES:

"""
            box.insert("1.0", template)
            box.mark_set("insert", "9.2")  # Position cursor after first bullet
            
            # Switch to Show Notes tab
            if self._cur_tab != 0:
                self._switch(0)
        except Exception as e:
            import logging
            logging.getLogger("broadcast.panel").warning(f"populate_show_template: {e}")

    def _schedule_autosave(self):
        interval = max(30, self.cfg.config.get(
            "autosave_interval", 5)) * 60 * 1000
        self._autosave_job = self.after(interval, self._autosave)

    def _autosave(self):
        self.save_all()
        self._schedule_autosave()


# ═══════════════════════════════════════════════════════════════
# SESSION LOG SECTION
# ═══════════════════════════════════════════════════════════════

class SessionLogSection(ctk.CTkFrame):
    def __init__(self, parent, cfg,
                 notes_fn=None, get_elapsed=None,
                 get_is_live=None):
        super().__init__(parent, fg_color=C["bg2"], corner_radius=0)
        self.cfg         = cfg
        self.notes_fn    = notes_fn or (lambda: {})
        self.get_elapsed = get_elapsed or (lambda: "")
        self.get_is_live = get_is_live or (lambda: False)
        self._paused     = False
        self._entries:   list = []
        self._log_path   = None
        self._call_start_btn = None   # set in _build
        self._call_end_btn   = None
        _section_hdr(self, "📋", "Session Log")
        self._build()
        self._schedule_autosave()

    def _build(self):
        # Action bar — compact icon buttons
        bar = tk.Frame(self, bg=C["bg2"])
        bar.pack(fill="x")

        self._pause_btn = tk.Button(
            bar, text="⏸",
            bg=C["btn"], fg=C["text_dim"],
            activebackground=C["btn_hover"],
            relief="flat", bd=0, padx=6,
            font=("Segoe UI", 12), cursor="hand2",
            command=self._toggle_pause)
        self._pause_btn.pack(side="left", padx=2, pady=2)

        tk.Button(bar, text="📋",
                  bg=C["btn"], fg=C["text_dim"],
                  activebackground=C["btn_hover"],
                  relief="flat", bd=0, padx=6,
                  font=("Segoe UI", 12), cursor="hand2",
                  command=self._copy_summary
                  ).pack(side="left", padx=2, pady=2)

        tk.Button(bar, text="💾",
                  bg=C["btn"], fg=C["text_dim"],
                  activebackground=C["btn_hover"],
                  relief="flat", bd=0, padx=6,
                  font=("Segoe UI", 12), cursor="hand2",
                  command=self._export
                  ).pack(side="left", padx=2, pady=2)

        tk.Button(bar, text="🗑",
                  bg=C["btn"], fg=C["text_dim"],
                  activebackground=C["btn_hover"],
                  relief="flat", bd=0, padx=6,
                  font=("Segoe UI", 12), cursor="hand2",
                  command=self._clear_log
                  ).pack(side="left", padx=2, pady=2)

        # ── Call buttons ──────────────────────────────────────────
        call_row = tk.Frame(self, bg=C["bg2"])
        call_row.pack(fill="x", padx=2, pady=(0, 2))

        self._call_start_btn = tk.Button(
            call_row,
            text="📞 Start Call",
            bg=C["green_dim"], fg=C["text_hi"],
            activebackground=C["green"],
            activeforeground=C["bg"],
            relief="flat", bd=0,
            padx=10, pady=4,
            font=("Segoe UI", 11, "bold"),
            cursor="hand2",
            command=self._do_start_call)
        self._call_start_btn.pack(
            side="left", fill="x", expand=True, padx=(0, 2))

        self._call_end_btn = tk.Button(
            call_row,
            text="⏹ End Call",
            bg=C["btn"], fg=C["text_dim"],
            activebackground=C["red_dim"],
            activeforeground=C["text_hi"],
            relief="flat", bd=0,
            padx=10, pady=4,
            font=("Segoe UI", 11, "bold"),
            cursor="hand2",
            state="disabled",
            command=self._do_end_call)
        self._call_end_btn.pack(
            side="left", fill="x", expand=True)

        # ── Timestamp entry row ────────────────────────────────────
        self._PLACEHOLDER = "note (optional)..."
        ts_row = tk.Frame(self, bg=C["bg2"])
        ts_row.pack(fill="x", padx=2, pady=(0, 2))

        # Log text
        log_outer = tk.Frame(self, bg=C["surface"])
        log_outer.pack(fill="both", expand=True, padx=2, pady=(0, 2))

        sb = tk.Scrollbar(log_outer, bg=C["surface"],
                          troughcolor=C["bg"], width=10)
        self._log = tk.Text(
            log_outer,
            bg=C["surface"], fg=C["text_dim"],
            insertbackground=C["text"],
            font=("Consolas", 8),
            relief="flat", bd=0,
            wrap="word", state="disabled",
            yscrollcommand=sb.set)
        sb.config(command=self._log.yview)
        sb.pack(side="right", fill="y")
        self._log.pack(side="left", fill="both", expand=True,
                       padx=4, pady=4)

        # Tags
        self._log.tag_config("ts",    foreground=C["text_dim"])
        self._log.tag_config("label", foreground=C["text"])
        self._log.tag_config("event", foreground=C["amber"])
        self._log.tag_config("live",  foreground=C["green"])
        self._log.tag_config("gold",  foreground=C["gold"])
        self._log.tag_config("music", foreground=C["blue_hi"])
        self._log.tag_config("stamp", foreground=C["amber_hi"])

        # ts_row contents:

        self._stamp_var = tk.StringVar()
        self._stamp_entry = tk.Entry(
            ts_row,
            textvariable=self._stamp_var,
            bg=C["surface"],
            fg=C["text_dim"],
            insertbackground=C["text"],
            relief="flat", bd=0,
            font=("Segoe UI", 11))
        self._stamp_entry.pack(side="left", fill="x", expand=True,
                               padx=(0, 4), ipady=4, ipadx=4)
        self._stamp_entry.bind("<Return>", lambda e: self._do_stamp())
        self._stamp_var.set(self._PLACEHOLDER)

        def _on_focus_in(e):
            if self._stamp_var.get() == self._PLACEHOLDER:
                self._stamp_var.set("")
                self._stamp_entry.configure(fg=C["text"])

        def _on_focus_out(e):
            if not self._stamp_var.get().strip():
                self._stamp_var.set(self._PLACEHOLDER)
                self._stamp_entry.configure(fg=C["text_dim"])

        self._stamp_entry.bind("<FocusIn>",  _on_focus_in)
        self._stamp_entry.bind("<FocusOut>", _on_focus_out)

        tk.Button(
            ts_row,
            text="📌 Timestamp",
            bg=C["btn"],
            fg=C["amber_hi"],
            activebackground=C["btn_hover"],
            activeforeground=C["text_hi"],
            relief="flat", bd=0,
            padx=10, pady=4,
            font=("Segoe UI", 11, "bold"),
            cursor="hand2",
            command=self._do_stamp,
        ).pack(side="right")

    def _do_stamp(self):
        raw  = self._stamp_var.get().strip()
        note = "" if raw == self._PLACEHOLDER else raw
        ts   = self._ts()
        text = f"📌 {note}" if note else "📌"
        self._entries.append({"ts": ts, "type": "stamp", "text": note})
        self._write([
            (f"[{ts}] ", "ts"),
            (text,       "stamp"),
        ])
        self._stamp_var.set("")
        self._stamp_entry.configure(fg=C["text"])
        self._stamp_entry.focus_set()

    # ── Call logging ──────────────────────────────────────────────

    def _do_start_call(self):
        ts = self._ts()
        self._entries.append({"ts": ts, "type": "event",
                               "text": "📞 Call started"})
        self._write([(f"[{ts}] ", "ts"), ("📞 Call started", "event")])
        self._call_start_btn.configure(
            state="disabled", bg=C["btn"], fg=C["text_dim"])
        self._call_end_btn.configure(
            state="normal", bg=C["red_dim"], fg=C["text_hi"])
        # Tell header to start the badge timer
        try:
            self.winfo_toplevel().header.start_call_from_log()
        except Exception:
            pass

    def _do_end_call(self):
        elapsed = 0
        try:
            elapsed = self.winfo_toplevel().header.end_call_from_log()
        except Exception:
            pass
        mm, ss = elapsed // 60, elapsed % 60
        dur = f"{mm:02d}:{ss:02d}"
        ts  = self._ts()
        txt = f"📞 Call ended — duration {dur}"
        self._entries.append({"ts": ts, "type": "event", "text": txt})
        self._write([(f"[{ts}] ", "ts"), (txt, "event")])
        self._call_start_btn.configure(
            state="normal", bg=C["green_dim"], fg=C["text_hi"])
        self._call_end_btn.configure(
            state="disabled", bg=C["btn"], fg=C["text_dim"])

    def _write(self, parts: list):
        """parts = list of (text, tag) tuples."""
        self._log.configure(state="normal")
        for text, tag in parts:
            self._log.insert("end", text, tag)
        self._log.insert("end", "\n")
        if not self._paused:
            self._log.see("end")
        self._log.configure(state="disabled")

    def _ts(self) -> str:
        """Always returns date + time. If live, appends elapsed."""
        from datetime import datetime as _dt
        wall = _dt.now().strftime("%b %d %H:%M:%S")
        if self.get_is_live():
            elap = self.get_elapsed()
            return f"{wall}  [{elap}]"
        return wall

    def _clear_log(self):
        from tkinter import messagebox
        if messagebox.askyesno("Clear Log", "Clear the session log?"):
            self._log.configure(state="normal")
            self._log.delete("1.0", "end")
            self._log.configure(state="disabled")
            self._entries.clear()
            # Reset paused state so the log is live again after clearing
            self._paused = False
            self._pause_btn.configure(
                text="⏸", fg=C["text_dim"])

    def log_event(self, text: str):
        ts = self._ts()
        self._entries.append({"ts": ts, "type": "event", "text": text})
        self._write([
            (f"[{ts}] ", "ts"),
            (text, "event"),
        ])

    def log_live_start(self):
        ts = self._ts()
        self._entries.append({"ts": ts, "type": "live_start"})
        self._write([
            (f"[{ts}] ", "ts"),
            ("🔴 WENT LIVE", "live"),
        ])

    def log_live_end(self, duration: str):
        ts = self._ts()
        self._entries.append({"ts": ts, "type": "live_end",
                               "duration": duration})
        self._write([
            (f"[{ts}] ", "ts"),
            (f"⏹ ENDED LIVE  ({duration})", "live"),
        ])

    def log_sound(self, label: str, path: str,
                  duration: float, from_queue: bool = False):
        """Log every audio play — soundboard and queue."""
        ts      = self._ts()
        dur_str = (f"{int(duration//60)}:{int(duration%60):02d}"
                   if duration > 0 else "--:--")
        src_tag = "Queue" if from_queue else "Board"
        self._entries.append({"ts": ts, "type": "sound",
                               "label": label, "duration": dur_str})
        self._write([
            (f"[{ts}] ", "ts"),
            (f"▶ {label}", "label"),
            (f"  ({dur_str}) [{src_tag}]", "ts"),
        ])

    def log_countdown_start(self, mm: int, ss: int):
        ts = self._ts()
        self._write([
            (f"[{ts}] ", "ts"),
            (f"⏱ Countdown started: {mm:02d}:{ss:02d}", "event"),
        ])

    def log_countdown_end(self):
        ts = self._ts()
        self._write([
            (f"[{ts}] ", "ts"),
            ("⏱ Countdown finished", "event"),
        ])

    def _toggle_pause(self):
        self._paused = not self._paused
        self._pause_btn.configure(
            text="▶" if self._paused else "⏸",
            fg=C["amber"] if self._paused else C["text_dim"])
        if not self._paused:
            self._log.see("end")

    def _copy_summary(self):
        try:
            import pyperclip
            pyperclip.copy(self._build_summary())
        except Exception:
            self.clipboard_clear()
            self.clipboard_append(self._build_summary())

    def _build_summary(self) -> str:
        lines = []
        for e in self._entries:
            if e["type"] == "live_start":
                lines.append(f"[{e['ts']}] Went live")
            elif e["type"] == "live_end":
                lines.append(
                    f"[{e['ts']}] Ended ({e.get('duration','')})")
            elif e["type"] == "sound":
                lines.append(
                    f"[{e['ts']}] ▶ {e.get('label','')} "
                    f"({e.get('duration','')})")
            elif e["type"] == "event":
                lines.append(f"[{e['ts']}] {e.get('text','')}")
            elif e["type"] == "stamp":
                note = e.get("text", "")
                lines.append(f"[{e['ts']}] 📌 {note}" if note
                             else f"[{e['ts']}] 📌")
        return "\n".join(lines)

    def get_summary_text(self) -> str:
        return self._build_summary()

    def entries_as_lines(self) -> list:
        """Return log entries as a list of formatted strings for marker export."""
        lines = []
        for e in self._entries:
            t = e.get("type", "")
            ts = e.get("ts", "")
            if t == "live_start":
                lines.append(f"[{ts}] 🔴 WENT LIVE")
            elif t == "live_end":
                lines.append(f"[{ts}] ⏹ ENDED LIVE ({e.get('duration','')})")
            elif t == "sound":
                dur = e.get("duration", "--:--")
                src = e.get("source", "Board")
                lines.append(f"[{ts}] ▶ {e.get('label','')}  ({dur}) [{src}]")
            elif t in ("event", "stamp"):
                lines.append(f"[{ts}] {e.get('text','')}")
        return lines

    def _export(self):
        from tkinter import filedialog
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = filedialog.asksaveasfilename(
            title="Export Session Log",
            initialfile=f"session_{ts}.txt",
            defaultextension=".txt",
            filetypes=[("Text","*.txt")])
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self._build_summary())
            except Exception as e:
                import tkinter.messagebox as mb
                mb.showerror("Export Failed", str(e))

    def _schedule_autosave(self):
        interval = max(60, self.cfg.config.get(
            "log_autosave_interval", 120)) * 1000
        self.after(interval, self._autosave)

    def _autosave(self):
        try:
            SESSION_DIR.mkdir(parents=True, exist_ok=True)
            ts   = datetime.now().strftime("%Y%m%d")
            path = SESSION_DIR / f"session_{ts}.txt"
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._build_summary())
        except Exception as e:
            log.warning(f"Session autosave: {e}")
        self._schedule_autosave()


# ═══════════════════════════════════════════════════════════════
# BITS BOARD SECTION
# ═══════════════════════════════════════════════════════════════

class BitsBoardSection(ctk.CTkFrame):
    """
    Scrollable list of prank premises / show bit ideas.
    Each entry has: timestamp, text, done checkbox.
    Saved to config.json (live) and bits.txt (safe keeping).
    """

    def __init__(self, parent, cfg):
        super().__init__(parent, fg_color=C["bg2"], corner_radius=0)
        self.cfg       = cfg
        self._rows     = []   # list of dicts: {frame, text_w, done_var, idx}
        self._bits_path = (
            Path(self.cfg.config.get(
                "session_folder",
                str(DATA_DIR / "sessions")))
            .parent / "bits.txt"
        )
        _section_hdr(self, "📌", "Bits Board")
        self._build()
        self._populate()

    def _build(self):
        # ── Toolbar — compact icon buttons ──────────────────────────
        bar = tk.Frame(self, bg=C["bg2"])
        bar.pack(fill="x", padx=4, pady=(2, 0))

        tk.Button(bar, text="+ Add",
                  bg=C["blue_mid"], fg=C["text_hi"],
                  activebackground=C["blue_light"],
                  relief="flat", bd=0, padx=6, pady=3,
                  font=("Segoe UI", 11, "bold"), cursor="hand2",
                  command=self._add_new
                  ).pack(side="left", padx=(0, 3))

        tk.Button(bar, text="↺",
                  bg=C["btn"], fg=C["text_dim"],
                  activebackground=C["btn_hover"],
                  relief="flat", bd=0, padx=6, pady=3,
                  font=("Segoe UI", 12), cursor="hand2",
                  command=self._reset_all
                  ).pack(side="left", padx=(0, 3))

        tk.Button(bar, text="📄",
                  bg=C["btn"], fg=C["text_dim"],
                  activebackground=C["btn_hover"],
                  relief="flat", bd=0, padx=6, pady=3,
                  font=("Segoe UI", 12), cursor="hand2",
                  command=self._open_file
                  ).pack(side="left")

        # ── Scrollable list ───────────────────────────────────────
        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color=C["bg"], height=160, corner_radius=0)
        self._scroll.pack(fill="both", expand=True,
                          padx=2, pady=(4, 2))

        # ── Add premise entry ─────────────────────────────────────
        entry_f = tk.Frame(self, bg=C["bg2"])
        entry_f.pack(fill="x", padx=4, pady=(0, 4))

        self._entry_var = tk.StringVar()
        self._entry = tk.Entry(
            entry_f,
            textvariable=self._entry_var,
            bg=C["surface"], fg=C["text"],
            insertbackground=C["text"],
            relief="flat", bd=0,
            font=("Segoe UI", 11))
        self._entry.pack(side="left", fill="x", expand=True,
                         ipady=4, ipadx=4, padx=(0, 4))
        self._entry.bind("<Return>", lambda e: self._add_new())
        self._entry.insert(0, "Type a premise or idea…")
        self._entry.configure(fg=C["text_dim"])
        self._entry.bind("<FocusIn>",  self._entry_focus_in)
        self._entry.bind("<FocusOut>", self._entry_focus_out)

        tk.Button(entry_f, text="Add",
                  bg=C["blue_mid"], fg=C["text_hi"],
                  activebackground=C["blue_light"],
                  relief="flat", bd=0, padx=10, pady=4,
                  font=("Segoe UI", 11, "bold"), cursor="hand2",
                  command=self._add_new
                  ).pack(side="left")

    def _entry_focus_in(self, e):
        if self._entry_var.get() == "Type a premise or idea…":
            self._entry_var.set("")
            self._entry.configure(fg=C["text"])

    def _entry_focus_out(self, e):
        if not self._entry_var.get().strip():
            self._entry_var.set("Type a premise or idea…")
            self._entry.configure(fg=C["text_dim"])

    # ── Data ──────────────────────────────────────────────────────

    def _bits(self) -> list:
        return self.cfg.config.setdefault("bits", [])

    def _populate(self):
        """Rebuild the scrollable list from config."""
        for w in self._scroll.winfo_children():
            w.destroy()
        self._rows.clear()

        for i, bit in enumerate(self._bits()):
            self._make_row(i, bit)

    def _make_row(self, i: int, bit: dict):
        done = bit.get("done", False)
        ts   = bit.get("ts", "")
        text = bit.get("title", "")

        row = ctk.CTkFrame(
            self._scroll,
            fg_color=C["elevated"] if done else C["surface"],
            corner_radius=4)
        row.pack(fill="x", pady=2, padx=2)

        # Done checkbox
        done_var = ctk.BooleanVar(value=done)
        ctk.CTkCheckBox(
            row, text="", variable=done_var, width=20,
            fg_color=C["green"], hover_color=C["green_dim"],
            checkmark_color=C["bg"],
            command=lambda idx=i, v=done_var: self._toggle_done(idx, v)
        ).pack(side="left", padx=(6, 2), pady=4)

        # Timestamp + text
        text_f = ctk.CTkFrame(row, fg_color="transparent")
        text_f.pack(side="left", fill="x", expand=True, padx=(0, 4))

        if ts:
            ctk.CTkLabel(text_f, text=ts,
                         font=ctk.CTkFont("Segoe UI", 11),
                         text_color=C["text_dim"],
                         anchor="w").pack(anchor="w")

        text_col = C["text_dim"] if done else C["text"]
        lbl = ctk.CTkLabel(
            text_f, text=text,
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=text_col,
            anchor="w", wraplength=200, justify="left")
        lbl.pack(anchor="w")

        # Delete button
        tk.Button(row, text="✕",
                  bg=C["elevated"] if done else C["surface"],
                  fg=C["text_dim"],
                  activebackground=C["btn_hover"],
                  relief="flat", bd=0, padx=4,
                  font=("Segoe UI", 11), cursor="hand2",
                  command=lambda idx=i: self._delete(idx)
                  ).pack(side="right", padx=4)

        self._rows.append({
            "frame": row, "done_var": done_var, "idx": i})

    # ── Actions ───────────────────────────────────────────────────

    def _add_new(self):
        text = self._entry_var.get().strip()
        if not text or text == "Type a premise or idea…":
            self._entry.focus_set()
            return
        ts  = datetime.now().strftime("%Y-%m-%d %H:%M")
        bit = {"title": text, "content": "", "done": False, "ts": ts}
        self._bits().append(bit)
        self.cfg.save()
        self._entry_var.set("")
        self._entry.configure(fg=C["text_dim"])
        self._populate()
        self._write_txt()
        # Scroll to bottom
        try:
            self._scroll._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    def _toggle_done(self, idx: int, var: ctk.BooleanVar):
        bits = self._bits()
        if idx < len(bits):
            bits[idx]["done"] = var.get()
            self.cfg.save()
            self._populate()
            self._write_txt()

    def _delete(self, idx: int):
        from tkinter import messagebox
        bits = self._bits()
        if idx >= len(bits):
            return
        name = bits[idx].get("title", f"Bit {idx+1}")
        if messagebox.askyesno("Delete",
                               f'Delete "{name[:40]}"?'):
            bits.pop(idx)
            self.cfg.save()
            self._populate()
            self._write_txt()

    def _reset_all(self):
        from tkinter import messagebox
        if messagebox.askyesno("Reset Done",
                               "Clear all Done marks?"):
            for bit in self._bits():
                bit["done"] = False
            self.cfg.save()
            self._populate()
            self._write_txt()

    def _open_file(self):
        import os
        self._write_txt()   # ensure file is current
        try:
            os.startfile(str(self._bits_path))
        except Exception:
            from tkinter import messagebox
            messagebox.showinfo("Bits File",
                                f"Saved to:\n{self._bits_path}")

    # ── Text file ────────────────────────────────────────────────

    def _write_txt(self):
        """Write all premises to bits.txt for safe keeping."""
        try:
            self._bits_path.parent.mkdir(parents=True, exist_ok=True)
            lines = ["Broadcast Backpack — Bits Board",
                     f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                     "=" * 50, ""]
            for bit in self._bits():
                done  = bit.get("done", False)
                ts    = bit.get("ts", "")
                title = bit.get("title", "")
                status = "[DONE] " if done else "[ ]    "
                lines.append(f"{status}{title}")
                if ts:
                    lines.append(f"       Added: {ts}")
                lines.append("")
            self._bits_path.write_text(
                "\n".join(lines), encoding="utf-8")
        except Exception as e:
            log.warning(f"Bits file write failed: {e}")



# ═══════════════════════════════════════════════════════════════
# QUICK COPY SNIPPETS
# ═══════════════════════════════════════════════════════════════

class SnippetsSection(ctk.CTkFrame):
    def __init__(self, parent, cfg):
        super().__init__(parent, fg_color=C["bg2"], corner_radius=0)
        self.cfg = cfg
        self._build()

    def _build(self):
        _section_hdr(self, "📎", "Quick Copy")
        hdr2 = tk.Frame(self, bg=C["bg2"])
        hdr2.pack(fill="x", padx=4, pady=(0, 2))
        tk.Button(hdr2, text="+ Add",
                  bg=C["btn"], fg=C["text_dim"],
                  activebackground=C["btn_hover"],
                  relief="flat", bd=0, padx=8,
                  font=("Segoe UI", 11), cursor="hand2",
                  command=self._add).pack(side="right", padx=2, pady=1)

        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent",
                                               height=90)
        self._scroll.pack(fill="x", padx=2, pady=(0, 4))
        self._populate()

    def _populate(self):
        for w in self._scroll.winfo_children():
            w.destroy()
        for i, s in enumerate(self.cfg.config.get("snippets", [])):
            row = tk.Frame(self._scroll, bg=C["bg2"])
            row.pack(fill="x", pady=1)
            tk.Button(row, text=s["label"], anchor="w",
                      bg=C["btn"], fg=C["text"],
                      activebackground=C["btn_hover"],
                      relief="flat", bd=0, padx=8, pady=3,
                      font=("Segoe UI", 11), cursor="hand2",
                      command=lambda t=s["text"]: self._copy(t)
                      ).pack(side="left", fill="x", expand=True, padx=(0,2))
            tk.Button(row, text="✏", width=3,
                      bg=C["btn"], fg=C["text_dim"],
                      activebackground=C["btn_hover"],
                      relief="flat", bd=0,
                      font=("Segoe UI", 11), cursor="hand2",
                      command=lambda idx=i: self._edit(idx)
                      ).pack(side="left", padx=1)
            tk.Button(row, text="🗑", width=3,
                      bg=C["btn"], fg=C["text_dim"],
                      activebackground=C["btn_hover"],
                      relief="flat", bd=0,
                      font=("Segoe UI", 11), cursor="hand2",
                      command=lambda idx=i: self._delete(idx)
                      ).pack(side="left", padx=1)

    def _copy(self, text: str):
        try:
            import pyperclip
            pyperclip.copy(text)
        except Exception:
            self.clipboard_clear()
            self.clipboard_append(text)

    def _add(self): self._editor(None)
    def _edit(self, i): self._editor(i)

    def _editor(self, idx):
        import customtkinter as _ctk
        w = _ctk.CTkToplevel(self)
        w.title("Quick Copy Snippet")
        w.geometry("360x200")
        w.configure(fg_color=C["bg2"])
        w.grab_set()
        _ctk.CTkLabel(w, text="Label:", font=_ctk.CTkFont("Segoe UI", 12)).pack(pady=(14,0))
        le = _ctk.CTkEntry(w, width=310, font=_ctk.CTkFont("Segoe UI", 12))
        le.pack(pady=4)
        _ctk.CTkLabel(w, text="Text:", font=_ctk.CTkFont("Segoe UI", 12)).pack()
        te = _ctk.CTkEntry(w, width=310, font=_ctk.CTkFont("Segoe UI", 12))
        te.pack(pady=4)
        if idx is not None:
            s = self.cfg.config["snippets"][idx]
            le.insert(0, s["label"]); te.insert(0, s["text"])
        def save():
            l, t = le.get().strip(), te.get().strip()
            if l and t:
                sn = {"label": l, "text": t}
                if idx is not None:
                    self.cfg.config["snippets"][idx] = sn
                else:
                    self.cfg.config.setdefault("snippets", []).append(sn)
                self.cfg.save(); self._populate(); w.destroy()
        _ctk.CTkButton(w, text="Save", fg_color=C["blue_mid"],
                       font=_ctk.CTkFont("Segoe UI", 12),
                       command=save).pack(pady=8)

    def _delete(self, idx):
        from tkinter import messagebox
        if messagebox.askyesno("Delete", "Remove this snippet?"):
            self.cfg.config.get("snippets", []).pop(idx)
            self.cfg.save(); self._populate()



# ═══════════════════════════════════════════════════════════════
# PRE-SHOW CHECKLIST SECTION
# ═══════════════════════════════════════════════════════════════

class PreShowChecklistSection(ctk.CTkFrame):
    """Configurable go-live readiness checklist."""

    def __init__(self, parent, cfg, on_ready_change=None):
        super().__init__(parent, fg_color=C["bg2"], corner_radius=0)
        self.cfg             = cfg
        self.on_ready_change = on_ready_change
        self._vars           = []
        _section_hdr(self, "✅", "Pre-Show Checklist")
        self._build()

    def _build(self):
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=8, pady=(4, 2))
        ctk.CTkButton(hdr, text="Reset All", width=72, height=22,
                      corner_radius=4, fg_color=C["btn"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=self._reset_all).pack(side="right")
        ctk.CTkButton(hdr, text="Edit", width=44, height=22,
                      corner_radius=4, fg_color=C["btn"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=self._edit).pack(side="right", padx=(0, 3))

        self._items_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent", height=220)
        self._items_frame.pack(fill="x", padx=6, pady=(0, 4))

        self._status_lbl = ctk.CTkLabel(
            self, text="",
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=C["text_dim"])
        self._status_lbl.pack(pady=(0, 6))

        self._refresh_items()

    def _refresh_items(self):
        for w in self._items_frame.winfo_children():
            w.destroy()
        self._vars = []
        for i, item in enumerate(self.cfg.config.get("checklist", [])):
            var = ctk.BooleanVar(value=item.get("done", False))
            var.trace_add("write",
                          lambda *_, idx=i, v=var: self._on_check(idx, v))
            row = ctk.CTkFrame(self._items_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkCheckBox(
                row,
                text=item.get("label", f"Item {i+1}"),
                variable=var,
                font=ctk.CTkFont("Segoe UI", 11),
                fg_color=C["green"],
                hover_color=C["green_dim"],
                checkmark_color=C["bg"],
                text_color=C["text"]).pack(side="left", padx=8)
            self._vars.append(var)
        self._update_status()

    def _on_check(self, idx, var):
        items = self.cfg.config.get("checklist", [])
        if idx < len(items):
            items[idx]["done"] = var.get()
        self._update_status()
        if self.on_ready_change:
            self.on_ready_change(self.all_done())

    def _update_status(self):
        total = len(self._vars)
        done  = sum(1 for v in self._vars if v.get())
        if total == 0:
            self._status_lbl.configure(text="")
            return
        if done == total:
            self._status_lbl.configure(
                text="✅  All clear — ready to go live!",
                text_color=C["green"])
        else:
            self._status_lbl.configure(
                text=f"{done} / {total} complete",
                text_color=C["amber"])

    def all_done(self) -> bool:
        return all(v.get() for v in self._vars)

    def _reset_all(self):
        for v in self._vars:
            v.set(False)
        for item in self.cfg.config.get("checklist", []):
            item["done"] = False

    def _edit(self):
        _ChecklistEditDialog(self, self.cfg,
                             on_save=self._refresh_items)


class _ChecklistEditDialog(ctk.CTkToplevel):
    def __init__(self, parent, cfg, on_save=None):
        super().__init__(parent)
        self.cfg     = cfg
        self.on_save = on_save
        self.title("✅  Edit Checklist")
        self.geometry("360x440")
        self.configure(fg_color=C["bg2"])
        self.grab_set()
        self._entries = []
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="Pre-Show Checklist Items",
                     font=ctk.CTkFont("Segoe UI", 12, "bold"),
                     text_color=C["amber"]).pack(pady=(12, 6))
        self._frame = ctk.CTkScrollableFrame(self, fg_color=C["surface"])
        self._frame.pack(fill="both", expand=True, padx=12, pady=4)
        for item in self.cfg.config.get("checklist", []):
            self._add_row(item.get("label", ""))
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=8)
        ctk.CTkButton(btn_row, text="+ Add", width=80, height=28,
                      fg_color=C["btn"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=lambda: self._add_row("")).pack(
            side="left", padx=4)
        ctk.CTkButton(btn_row, text="💾 Save", width=80, height=28,
                      fg_color=C["blue_mid"],
                      font=ctk.CTkFont("Segoe UI", 11, "bold"),
                      command=self._save).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="Cancel", width=70, height=28,
                      fg_color=C["surface"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=self.destroy).pack(side="left", padx=4)

    def _add_row(self, text=""):
        row = ctk.CTkFrame(self._frame, fg_color="transparent")
        row.pack(fill="x", pady=2)
        e = ctk.CTkEntry(row, width=260,
                         font=ctk.CTkFont("Segoe UI", 11))
        e.insert(0, text)
        e.pack(side="left", padx=4)
        ctk.CTkButton(row, text="✕", width=26, height=26,
                      fg_color=C["red_dim"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      command=lambda r=row: r.destroy()).pack(side="left")
        self._entries.append(e)

    def _save(self):
        items = []
        for e in self._entries:
            try:
                val = e.get().strip()
                if val:
                    items.append({"label": val, "done": False})
            except Exception:
                pass  # entry was destroyed via ✕ button
        self.cfg.config["checklist"] = items
        self.cfg.save()
        if self.on_save:
            self.on_save()
        self.destroy()


# ═══════════════════════════════════════════════════════════════
# RIGHT PANEL  — tabbed: ✅ Pre-Show | 📋 Show
# ═══════════════════════════════════════════════════════════════

class RightPanel(ctk.CTkFrame):
    """
    Fixed-width right column with two tabs:
      ✅ Pre-Show  — checklist
      📋 Show      — Tools + Bits Board + Session Log
    """

    WIDTH = 340

    def __init__(self, parent, cfg, audio,
                 get_elapsed=None, get_is_live=None):
        super().__init__(parent, fg_color=C["bg2"],
                         corner_radius=0, width=self.WIDTH)
        self.cfg         = cfg
        self.audio       = audio
        self.get_elapsed = get_elapsed or (lambda: "")
        self.get_is_live = get_is_live or (lambda: False)
        self.pack_propagate(False)
        self._build()

    def _build(self):
        tabs = ctk.CTkTabview(
            self,
            fg_color=C["bg2"],
            segmented_button_fg_color=C["surface"],
            segmented_button_selected_color=C["blue_mid"],
            segmented_button_selected_hover_color=C["blue_light"],
            segmented_button_unselected_color=C["surface"],
            segmented_button_unselected_hover_color=C["elevated"],
            text_color=C["text_dim"],
            text_color_disabled=C["text_dim"],
            corner_radius=0)
        tabs.pack(fill="both", expand=True)

        tabs.add("✅ Pre-Show")
        tabs.add("📋 Show")

        # ── Pre-Show tab ─────────────────────────────────────────
        pre_tab = tabs.tab("✅ Pre-Show")
        self.checklist = PreShowChecklistSection(pre_tab, self.cfg)
        self.checklist.pack(fill="both", expand=True)

        # ── Show tab ──────────────────────────────────────────────
        show_tab = tabs.tab("📋 Show")

        self.tools = ToolsSection(show_tab, self.cfg)
        self.tools.pack(fill="x")

        tk.Frame(show_tab, bg=C["border"], height=1).pack(fill="x")

        self.bits_board = BitsBoardSection(show_tab, self.cfg)
        self.bits_board.pack(fill="x")

        tk.Frame(show_tab, bg=C["border"], height=1).pack(fill="x")

        self.session_log = SessionLogSection(
            show_tab, self.cfg,
            get_elapsed=self.get_elapsed,
            get_is_live=self.get_is_live)
        self.session_log.pack(fill="both", expand=True)

    def refresh_theme(self):
        """Refresh right panel colors after theme change."""
        try:
            self.configure(fg_color=C["bg2"])
        except Exception:
            pass



