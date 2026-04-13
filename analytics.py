"""
analytics.py — Broadcast Backpack v6.0.0
Tracks per-show statistics and saves them as JSON files.
Each completed show saves one file to ~/BroadcastBackpack/analytics/
"""

import json, logging
from pathlib import Path
from datetime import datetime

log = logging.getLogger("broadcast.analytics")


class AnalyticsManager:

    def __init__(self, analytics_dir: Path):
        self._dir     = analytics_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._session = None
        self._live_start_wall = None

    # ── Session lifecycle ─────────────────────────────────────────

    def start_show(self, wall_time: datetime = None):
        self._live_start_wall = wall_time or datetime.now()
        self._session = {
            "date":           self._live_start_wall.strftime("%Y-%m-%d"),
            "start_time":     self._live_start_wall.isoformat(),
            "end_time":       None,
            "duration_secs":  0,
            "sounds_played":  0,
            "gold_moments":   0,
            "timestamps":     0,
            "calls":          0,
            "manual_notes":   0,
            "panic_count":    0,
            "mute_count":     0,
            "stream_live":    False,
            "stream_reconnects": 0,
            "top_sounds":     {},
        }

    def end_show(self, duration_secs: float):
        if not self._session:
            return
        self._session["end_time"]      = datetime.now().isoformat()
        self._session["duration_secs"] = int(duration_secs)
        self._save()

    # ── Event recording ────────────────────────────────────────────

    def record_sound(self, filename: str):
        if not self._session:
            return
        self._session["sounds_played"] += 1
        fname = Path(filename).name if filename else "unknown"
        top   = self._session["top_sounds"]
        top[fname] = top.get(fname, 0) + 1

    def record_gold(self):
        if self._session:
            self._session["gold_moments"] += 1

    def record_timestamp(self):
        if self._session:
            self._session["timestamps"] += 1

    def record_call(self):
        if self._session:
            self._session["calls"] += 1

    def record_manual_note(self):
        if self._session:
            self._session["manual_notes"] += 1

    def record_panic(self):
        if self._session:
            self._session["panic_count"] += 1

    def record_mute(self):
        if self._session:
            self._session["mute_count"] += 1

    def record_stream_live(self):
        if self._session:
            self._session["stream_live"] = True

    def record_stream_reconnect(self):
        if self._session:
            self._session["stream_reconnects"] = \
                self._session.get("stream_reconnects", 0) + 1

    # ── Historical data ────────────────────────────────────────────

    def load_all(self) -> list:
        records = []
        for f in sorted(self._dir.glob("show_*.json"), reverse=True):
            try:
                records.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                pass
        return records

    def get_totals(self) -> dict:
        records = self.load_all()
        if not records:
            return {}
        total_dur = sum(r.get("duration_secs", 0) for r in records)
        n         = len(records)
        all_sounds: dict = {}
        for r in records:
            for fname, cnt in r.get("top_sounds", {}).items():
                all_sounds[fname] = all_sounds.get(fname, 0) + cnt
        top5 = sorted(all_sounds.items(),
                      key=lambda x: x[1], reverse=True)[:5]
        return {
            "total_shows":      n,
            "total_duration":   total_dur,
            "avg_duration":     total_dur // n if n else 0,
            "total_sounds":     sum(r.get("sounds_played", 0) for r in records),
            "total_gold":       sum(r.get("gold_moments",  0) for r in records),
            "total_calls":      sum(r.get("calls",         0) for r in records),
            "top_sounds":       top5,
            "last_7_durations": [r.get("duration_secs", 0) for r in records[:7]],
            "last_7_dates":     [r.get("date", "?")        for r in records[:7]],
        }

    # ── Internal ─────────────────────────────────────────────────

    def _save(self):
        if not self._session:
            return
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self._dir / f"show_{ts}.json"
        try:
            path.write_text(
                json.dumps(self._session, indent=2), encoding="utf-8")
            log.info(f"Analytics saved: {path.name}")
        except Exception as e:
            log.warning(f"Analytics save failed: {e}")
