"""
config.py — Broadcast Backpack v6.0.0
All-in-one broadcast production tool.

Handles app constants, colour themes, default config values,
and the ConfigManager persistence layer.
"""

import json, shutil, copy, os
from pathlib import Path
from datetime import datetime

# ── Version ──────────────────────────────────────────────────────
VERSION       = "6.0.0"
APP_NAME      = "Broadcast Backpack"

# ── Paths ─────────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).parent
ASSET_DIR     = BASE_DIR / "assets"
DATA_DIR      = Path.home() / "BroadcastBackpack"
CONFIG_FILE   = DATA_DIR / "config.json"
SESSION_DIR   = DATA_DIR / "sessions"
RECORDING_DIR = DATA_DIR / "recordings"
AUTOSAVE_DIR  = DATA_DIR / "autosave"
LOG_DIR       = DATA_DIR / "logs"
ANALYTICS_DIR = DATA_DIR / "analytics"
MARKERS_DIR   = DATA_DIR / "markers"

# Legacy paths for migration
LEGACY_DATA_DIRS = [
    Path.home() / "IceCatCompanion_v4_1",
    Path.home() / "IceCatCompanion_v4",
    Path.home() / "IceCatCompanion",
]


# ═══════════════════════════════════════════════════════════════════
# SIMPLIFIED COLOR SYSTEM
# ═══════════════════════════════════════════════════════════════════
#
# 12 semantic keys — each theme defines these core colors.
# Derived colors (hover states, text-on-color) are computed automatically.
#
# Core Keys:
#   bg        — Main window background
#   bg2       — Secondary panels, sidebars, header
#   surface   — Cards, content areas, inputs
#   border    — All borders
#   accent    — Primary brand color (interactive elements)
#   accent2   — Secondary accent (highlights, warnings)
#   text      — Primary text
#   text_muted — Secondary/dim text
#   success   — Green (go, online, good)
#   danger    — Red (stop, error, panic)
#   warning   — Warning states (amber)
#   neutral   — Unassigned/default buttons
#

def luminance(hex_color: str) -> float:
    """Calculate relative luminance of a color (0-1)."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def text_for_bg(hex_color: str) -> str:
    """Return black or white text based on background luminance."""
    return "#000000" if luminance(hex_color) > 0.5 else "#ffffff"


def lighten(hex_col: str, amount: float = 0.15) -> str:
    """Lighten a color by mixing with white."""
    h = hex_col.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r = min(255, int(r + (255 - r) * amount))
    g = min(255, int(g + (255 - g) * amount))
    b = min(255, int(b + (255 - b) * amount))
    return f"#{r:02x}{g:02x}{b:02x}"


def darken(hex_col: str, amount: float = 0.15) -> str:
    """Darken a color by mixing with black."""
    h = hex_col.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r = max(0, int(r * (1 - amount)))
    g = max(0, int(g * (1 - amount)))
    b = max(0, int(b * (1 - amount)))
    return f"#{r:02x}{g:02x}{b:02x}"


def derive_palette(base: dict) -> dict:
    """
    Given a base theme with 12 core keys, derive all additional
    colors needed by the UI (hover states, text-on-color, etc).
    """
    p = dict(base)
    
    # Detect if dark or light theme
    is_dark = luminance(p["bg"]) < 0.5
    
    # Hover states
    if is_dark:
        p["surface_hover"] = lighten(p["surface"], 0.1)
        p["accent_hover"]  = lighten(p["accent"], 0.15)
        p["accent2_hover"] = lighten(p["accent2"], 0.15)
        p["btn_hover"]     = lighten(p["neutral"], 0.1)
    else:
        p["surface_hover"] = darken(p["surface"], 0.08)
        p["accent_hover"]  = darken(p["accent"], 0.12)
        p["accent2_hover"] = darken(p["accent2"], 0.12)
        p["btn_hover"]     = darken(p["neutral"], 0.08)
    
    # Text colors for colored backgrounds (auto black/white)
    p["text_on_accent"]  = text_for_bg(p["accent"])
    p["text_on_accent2"] = text_for_bg(p["accent2"])
    p["text_on_success"] = text_for_bg(p["success"])
    p["text_on_danger"]  = text_for_bg(p["danger"])
    p["text_on_warning"] = text_for_bg(p["warning"])
    p["text_on_neutral"] = text_for_bg(p["neutral"])
    
    # Highlight text (bright for dark themes, dark for light themes)
    p["text_hi"] = "#ffffff" if is_dark else "#000000"
    
    # Border highlight (slightly more visible than border)
    p["border_hi"] = lighten(p["border"], 0.2) if is_dark else darken(p["border"], 0.2)
    
    # Elevated surface (for raised elements)
    p["elevated"] = lighten(p["surface"], 0.08) if is_dark else darken(p["surface"], 0.03)
    
    # Pinned row (subtle tint)
    p["pinned"] = lighten(p["bg"], 0.05) if is_dark else "#e8f0e8"
    
    # Panic (always bright red)
    p["panic"] = "#cc0000"
    
    # Gold (for gold moments)
    p["gold"] = "#ffd700" if is_dark else "#c09000"
    
    # Shine/shadow for 3D effects
    p["shine"]  = lighten(p["border"], 0.3) if is_dark else "#ffffff"
    p["shadow"] = darken(p["bg"], 0.3) if is_dark else "#808080"
    
    # Success/danger dim variants
    p["success_dim"] = darken(p["success"], 0.4)
    p["danger_dim"]  = darken(p["danger"], 0.4)
    
    # Legacy compatibility aliases
    p["btn"]        = p["neutral"]
    p["blue"]       = darken(p["accent"], 0.2)
    p["blue_mid"]   = p["accent"]
    p["blue_light"] = lighten(p["accent"], 0.2)
    p["blue_hi"]    = lighten(p["accent"], 0.35)
    p["amber"]      = p["accent2"]
    p["amber_hi"]   = p["accent2_hover"]
    p["red"]        = p["danger"]
    p["red_dim"]    = p["danger_dim"]
    p["green"]      = p["success"]
    p["green_dim"]  = p["success_dim"]
    p["text_dim"]   = p["text_muted"]
    
    return p


# ── Base Themes (12 core keys each) ───────────────────────────────

THEMES_BASE = {
    "Darkmode Blue": {
        "bg":         "#060b14",
        "bg2":        "#0a1220",
        "surface":    "#0e1a2e",
        "border":     "#1a2e4a",
        "accent":     "#2a55a8",      # Primary blue
        "accent2":    "#f0a020",      # Amber
        "text":       "#c8d8f0",
        "text_muted": "#4a6688",
        "success":    "#20b85a",
        "danger":     "#e02233",
        "warning":    "#f0a020",
        "neutral":    "#0e1c30",
    },
    "Classic Light": {
        "bg":         "#f0f0f0",
        "bg2":        "#e4e4e4",
        "surface":    "#ffffff",
        "border":     "#a0a0a0",
        "accent":     "#0078d4",      # Windows blue
        "accent2":    "#e67e00",      # Orange
        "text":       "#1a1a1a",
        "text_muted": "#606060",
        "success":    "#107c10",
        "danger":     "#c42b1c",
        "warning":    "#d48806",
        "neutral":    "#e1e1e1",
    },
}

# Full derived themes
THEMES = {name: derive_palette(base) for name, base in THEMES_BASE.items()}


# ── Font scale ────────────────────────────────────────────────────
F_SM      = ("Segoe UI", 9)
F_SM_B    = ("Segoe UI", 9,  "bold")
F_MD      = ("Segoe UI", 10)
F_MD_B    = ("Segoe UI", 10, "bold")
F_LG      = ("Segoe UI", 11)
F_LG_B    = ("Segoe UI", 11, "bold")
F_HDR     = ("Segoe UI", 13, "bold")
F_MONO_SM = ("Courier New", 10)
F_MONO_MD = ("Courier New", 14, "bold")
F_MONO_LG = ("Courier New", 18, "bold")

# Active color dict — updated by apply_theme()
C: dict = dict(THEMES["Darkmode Blue"])


# ── FX defaults ───────────────────────────────────────────────────
DEFAULT_FX = {
    "volume":   {"enabled": False, "value": 1.0},
    "pitch":    {"enabled": False, "value": 0.0},
    "speed":    {"enabled": False, "value": 1.0},
    "reverb":   {"enabled": False, "value": 0.3},
    "echo":     {"enabled": False, "value": 0.3},
    "lowpass":  {"enabled": False, "value": 4000.0},
    "highpass": {"enabled": False, "value": 200.0},
}

# ── Recorder FX defaults ──────────────────────────────────────────
DEFAULT_RECORDER_FX = {
    "chipmunk": {"semitones": 6.0,   "speed": 1.35},
    "deep":     {"semitones": -6.0,  "speed": 0.72},
    "reverb":   {"room_size": 0.75,  "wet": 0.5},
    "echo":     {"delay": 0.4,       "feedback": 0.45, "mix": 0.5},
    "lofi":     {"lowpass": 3200.0,  "highpass": 500.0},
    "reverse":  {},
}

DEFAULT_GROUPS = [
    {"name": "Jingles", "rows": 2, "cols": 8, "color": ""},
    {"name": "Drops",   "rows": 2, "cols": 8, "color": ""},
    {"name": "Music",   "rows": 2, "cols": 8, "color": ""},
    {"name": "SFX",     "rows": 2, "cols": 8, "color": ""},
]


def _slot(i: int, pinned=False) -> dict:
    labels = ["Intro","Outro","Stinger","Break",
              "Bumper","Theme","Promo","Fanfare",
              "Pin 9","Pin 10"]
    return {
        "label":      (labels[i] if pinned and i < len(labels)
                       else f"Sound {i+1}"),
        "file":       "",
        "color":      "",
        "text_color": "",
        "volume":     1.0,
        "loop":       False,
        "fx":         copy.deepcopy(DEFAULT_FX),
    }


def _default_slots(pinned: int, groups: list) -> list:
    total = pinned + sum(g["rows"] * g["cols"] for g in groups)
    return [_slot(i, pinned=(i < pinned)) for i in range(total)]


DEFAULT_BITS = [
    {"text": "Add your show bits here", "done": False},
]

DEFAULT_CHECKLIST = [
    {"label": "Audio devices configured", "done": False},
    {"label": "Stream settings verified", "done": False},
    {"label": "Soundboard loaded",        "done": False},
    {"label": "Queue populated",          "done": False},
]

DEFAULT_CONFIG = {
    # Meta
    "version":              VERSION,
    "first_run":            True,

    # Window
    "window_width":         1600,
    "window_height":        960,
    "opacity":              1.0,
    "font_size":            11,

    # Visual — default to Darkmode Blue
    "color_theme":          "Darkmode Blue",
    "bg_color":             "#060b14",

    # Show profile
    "show_name":            "My Show",
    "episode_number":       1,
    "title_template":       "Episode {n} — {date}",

    # Audio
    "audio_output_device":  "Default (System)",
    "audio_input_device":   "Default (System)",
    "recording_format":     "wav",
    "recordings_folder":    str(RECORDING_DIR),
    "fade_duration":        3.0,
    "log_audio_min_secs":   30,

    # Autosave
    "autosave_interval":    5,
    "log_autosave_interval":120,

    # Soundboard
    "soundboard_groups":    DEFAULT_GROUPS,
    "soundboard_locked":    False,
    "pinned_count":         8,
    "music_bank_name":      "Music",

    # Playback modes
    "touch_play_mode":      False,
    "automix_enabled":      False,
    "automix_crossfade_sec": 3,

    # Independent volumes
    "board_volume":         1.0,
    "queue_volume":         1.0,
    "board_gain_db":        0,

    # Hotkeys
    "hotkeys": {
        "go_live":      "ctrl+shift+l",
        "panic":        "ctrl+shift+p",
        "mute":         "ctrl+shift+m",
        "timestamp":    "ctrl+shift+t",
        "gold_moment":  "ctrl+shift+g",
        "mini_mode":    "ctrl+shift+z",
    },

    # Mic
    "mic_input_device":     "Default (System)",
    "mic_duck_level":       0.3,

    # Notes
    "note_tabs":            ["Show Notes", "Premises & Ideas"],
    "notes_content":        {"Show Notes": "", "Premises & Ideas": ""},

    # Countdown
    "countdown_presets":    [5, 10, 15, 30],

    # Quick Folders
    "folders": [
        {"label": f"Folder {i+1}", "path": "", "color": "", "text_color": ""}
        for i in range(6)
    ],

    # Websites
    "websites": [
        {"label": "Website 1", "url": "", "color": "", "text_color": ""},
        {"label": "Website 2", "url": "", "color": "", "text_color": ""},
        {"label": "Website 3", "url": "", "color": "", "text_color": ""},
    ],

    # Integrations
    "discord_enabled":      False,
    "discord_webhook":      "",
    "discord_message":      "We're live!",
    "browser_preference":   "",

    # Streaming
    "stream_host":          "",
    "stream_port":          80,
    "stream_mount":         "",
    "stream_user":          "source",
    "stream_pass":          "",
    "stream_device":        "",
    "stream_bitrate":       128,
    "stream_auto_reconnect": True,
    "stream_max_reconnects": 5,

    # Soundboard slots (generated)
    "soundboard":           [],
    "pinned":               [],

    # Bits board
    "bits_board":           DEFAULT_BITS,

    # Pre-show checklist
    "checklist":            DEFAULT_CHECKLIST,

    # Visual appearance
    "playing_btn_color":        "",
    "playing_btn_blink":        False,
    "playing_btn_blink_rate":   500,
    "bank_tab_highlight_color": "",
    "bank_tab_highlight_bg":    "",
    "nowplaying_flash_secs":    30,
}


# ═══════════════════════════════════════════════════════════════════
# CONFIG MANAGER
# ═══════════════════════════════════════════════════════════════════

class ConfigManager:
    """
    Handles loading, saving, and migration of user configuration.
    """

    def __init__(self):
        self._ensure_dirs()
        self._migrate_legacy()
        self.config = self._load()
        self._upgrade()
        self.apply_theme()

    def _ensure_dirs(self):
        for d in (DATA_DIR, SESSION_DIR, RECORDING_DIR,
                  AUTOSAVE_DIR, LOG_DIR, ANALYTICS_DIR, MARKERS_DIR):
            d.mkdir(parents=True, exist_ok=True)

    def _migrate_legacy(self):
        """Migrate config from legacy IceCat folders if this is first run."""
        if CONFIG_FILE.exists():
            return  # Already have config, no migration needed
        
        for legacy_dir in LEGACY_DATA_DIRS:
            legacy_config = legacy_dir / "config.json"
            if legacy_config.exists():
                try:
                    # Copy entire legacy folder contents
                    for item in legacy_dir.iterdir():
                        dest = DATA_DIR / item.name
                        if item.is_dir():
                            if not dest.exists():
                                shutil.copytree(item, dest)
                        else:
                            if not dest.exists():
                                shutil.copy2(item, dest)
                    print(f"Migrated settings from {legacy_dir}")
                    break
                except Exception as e:
                    print(f"Migration warning: {e}")

    def _load(self) -> dict:
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text("utf-8"))
                merged = copy.deepcopy(DEFAULT_CONFIG)
                merged.update(data)
                return merged
            except Exception:
                pass
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["soundboard"] = _default_slots(
            cfg["pinned_count"], cfg["soundboard_groups"])
        cfg["pinned"] = cfg["soundboard"][:cfg["pinned_count"]]
        return cfg

    def _upgrade(self):
        """Handle version upgrades and ensure new fields exist."""
        c = self.config
        
        # Ensure soundboard slots exist
        if not c.get("soundboard"):
            c["soundboard"] = _default_slots(
                c.get("pinned_count", 8),
                c.get("soundboard_groups", DEFAULT_GROUPS))
        
        # Migrate legacy theme names
        theme = c.get("color_theme", "Darkmode Blue")
        if theme not in THEMES and theme != "Custom":
            # Map old theme names to new
            theme_map = {
                "Classic": "Classic Light",
                "Slate Broadcast": "Darkmode Blue",
                "Default Blue": "Darkmode Blue",
            }
            c["color_theme"] = theme_map.get(theme, "Darkmode Blue")
        
        # Ensure all new fields exist
        for key, default in DEFAULT_CONFIG.items():
            if key not in c:
                c[key] = copy.deepcopy(default)
        
        # Migrate legacy custom_theme keys to new system
        if c.get("custom_theme"):
            ct = c["custom_theme"]
            # Map old keys to new semantic keys if needed
            key_map = {
                "blue_mid": "accent",
                "amber": "accent2",
                "text_dim": "text_muted",
                "red": "danger",
                "green": "success",
            }
            for old_key, new_key in key_map.items():
                if old_key in ct and new_key not in ct:
                    ct[new_key] = ct[old_key]
        
        c["version"] = VERSION
        self.save()

    def save(self):
        try:
            CONFIG_FILE.write_text(
                json.dumps(self.config, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"Config save error: {e}")

    def apply_theme(self, name: str = None) -> dict:
        """Update global C dict with chosen theme palette."""
        n = name or self.config.get("color_theme", "Darkmode Blue")
        
        if n == "Custom":
            custom = self.config.get("custom_theme", {})
            # Start from Darkmode Blue base, overlay custom values
            base = dict(THEMES_BASE["Darkmode Blue"])
            for key in base:
                if key in custom:
                    base[key] = custom[key]
            palette = derive_palette(base)
        else:
            palette = THEMES.get(n, THEMES["Darkmode Blue"])
        
        C.clear()
        C.update(palette)
        self.config["bg_color"] = palette["bg"]
        return palette

    # ── Soundboard helpers ────────────────────────────────────────

    def bank_range(self, bank_idx: int) -> tuple[int, int]:
        pinned = self.config.get("pinned_count", 8)
        start = pinned
        for i, g in enumerate(self.config["soundboard_groups"]):
            size = g.get("rows", 2) * g.get("cols", 8)
            if i == bank_idx:
                return start, size
            start += size
        return pinned, 16

    def export_bank(self, bank_idx: int) -> dict:
        start, count = self.bank_range(bank_idx)
        g = self.config["soundboard_groups"][bank_idx]
        return {
            "name":  g["name"],
            "rows":  g["rows"],
            "cols":  g["cols"],
            "color": g.get("color", ""),
            "slots": copy.deepcopy(
                self.config["soundboard"][start:start + count]),
        }

    def import_bank(self, bank_idx: int, data: dict):
        start, count = self.bank_range(bank_idx)
        slots = data.get("slots", [])
        for i, slot in enumerate(slots[:count]):
            self.config["soundboard"][start + i] = slot
        self.save()

    def get_btn_custom(self, source: str, idx: int) -> dict:
        """Get custom button colors for a slot."""
        if source == "mute":
            return {}
        if source == "panic":
            return {}
        try:
            slot = self.config[source][idx]
            return {
                "color":      slot.get("color", ""),
                "text_color": slot.get("text_color", ""),
            }
        except (KeyError, IndexError):
            return {}

    def has_any_custom_colors(self) -> bool:
        for slot in self.config.get("soundboard", []):
            if slot.get("color") or slot.get("text_color"):
                return True
        return False

    def clear_custom_colors(self):
        for slot in self.config.get("soundboard", []):
            slot["color"] = ""
            slot["text_color"] = ""
        self.save()


# ── Utility functions ─────────────────────────────────────────────

def fs(cfg, delta: int = 0) -> int:
    """Get font size with optional delta."""
    return max(8, cfg.config.get("font_size", 11) + delta)
