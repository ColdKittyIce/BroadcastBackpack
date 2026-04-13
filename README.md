<p align="center">
  <img src="https://img.shields.io/badge/version-6.0.1-blue?style=for-the-badge" alt="Version">
  <img src="https://img.shields.io/badge/python-3.10+-green?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/platform-Windows-lightgrey?style=for-the-badge&logo=windows&logoColor=white" alt="Platform">
  <img src="https://img.shields.io/badge/license-MIT-orange?style=for-the-badge" alt="License">
</p>

<h1 align="center">📻 Broadcast Backpack</h1>

<p align="center">
  <strong>All-in-one broadcast production companion</strong><br>
  Soundboard • Music Queue • Recording • Streaming • Session Logging
</p>

<p align="center">
  <a href="#-features">Features</a> •
  <a href="#-installation">Installation</a> •
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-hotkeys">Hotkeys</a> •
  <a href="#-building-from-source">Building</a>
</p>

---

## Features

<table>
<tr>
<td width="50%">

### Professional Soundboard
- **508 sound slots** across unlimited banks
- **Pinned favorites row** — always visible
- **Drag & drop** audio file assignment
- **Per-button FX** — pitch, reverb, echo, filters
- **Custom colors** for visual organization
- **Touch Play mode** for instant playback

</td>
<td width="50%">

### Smart Music Queue
- **Independent volume control** from soundboard
- **Drag & drop** playlist building
- **Shuffle, loop, crossfade** options
- **Now Playing** display with progress
- **Auto-queue** from folders

</td>
</tr>
<tr>
<td width="50%">

### Tape Recorder
- **One-click recording** of your show
- **WAV or MP3** export options
- **Pause/resume** support
- **Auto-naming** with timestamps
- Capture from any audio source

</td>
<td width="50%">

### Live Streaming
- **Icecast/Shoutcast** compatible
- **Auto-reconnect** on dropout
- **SOURCE & PUT** methods supported
- Stream directly from the app
- No external software needed

</td>
</tr>
<tr>
<td width="50%">

### Session Logging
- **Automatic timestamps** for every sound
- **Gold moment** markers (Ctrl+Shift+G)
- **Call logging** via MicroSIP integration
- **Export to Audition/Audacity** markers
- Full session history

</td>
<td width="50%">

### Customizable Interface
- **Darkmode Blue** & **Classic Light** themes
- **Custom color schemes**
- **Resizable banks** — set your own rows/cols
- **Quick folders** for fast file access
- **Website launchers** built-in

</td>
</tr>
</table>

---

## Installation

### Option 1: Download (Recommended)

1. Go to [**Releases**](https://github.com/ColdKittyIce/BroadcastBackpack/releases)
2. Download `Broadcast_Backpack_v6.0.1.zip`
3. Extract anywhere
4. Run `Broadcast_Backpack.exe`

**That's it!** No installation required.

---

### Option 2: Run from Source

```bash
# Clone the repo
git clone https://github.com/ColdKittyIce/BroadcastBackpack.git
cd BroadcastBackpack

# Install dependencies
pip install -r requirements.txt

# Launch
python main.py
```

---

## Quick Start

1. **Launch** the app
2. **Drag audio files** onto soundboard buttons to assign them
3. **Right-click buttons** to customize name, color, volume, and FX
4. **Drag music** to the bottom queue panel
5. **Press GO LIVE** when your show starts — the timer begins!
6. **Press PANIC** to instantly stop all audio

---

## Hotkeys

| Shortcut | Action |
|----------|--------|
| `Ctrl+Shift+L` | Toggle GO LIVE |
| `Ctrl+Shift+P` | **PANIC** — Stop all audio |
| `Ctrl+Shift+M` | Mute/unmute |
| `Ctrl+Shift+T` | Add timestamp to log |
| `Ctrl+Shift+G` | Mark **gold moment** ⭐ |
| `Ctrl+Shift+Z` | Toggle mini mode |
| `Ctrl+Z` | Undo last action |
| `Ctrl+,` | Open settings |

All hotkeys are customizable in Settings → Hotkeys.

---

## Audio Controls

| Control | Purpose |
|---------|---------|
| **BOARD** slider | Soundboard volume (all buttons) |
| **QUEUE** slider | Music queue volume |
| **Board Gain** | +0 to +12 dB boost for quiet sound files |
| **Per-button volume** | Right-click any button → Volume |

---

## Data Location

All your settings and files are stored in:

```
C:\Users\[You]\BroadcastBackpack\
├── config.json      # All settings & soundboard assignments
├── sessions/        # Auto-saved session logs
├── recordings/      # Tape recorder output
├── markers/         # Exported audio markers
└── logs/            # Debug logs
```

---

## Building from Source

See [BUILDING.md](BUILDING.md) for full instructions.

```bash
pip install pyinstaller
pyinstaller Broadcast_Backpack.spec --clean
```

Output: `dist\Broadcast_Backpack\Broadcast_Backpack.exe`

---

## Contributing

Contributions welcome! Feel free to:
- Report bugs via [Issues](https://github.com/ColdKittyIce/BroadcastBackpack/issues)
- Suggest features
- Submit pull requests

---

## License

[MIT License](LICENSE) — Use it, modify it, share it!

---

<p align="center">
  <strong>Built for broadcasters, by a broadcaster</strong><br>
  <sub>Created with ❤️ by <a href="https://github.com/ColdKittyIce">ColdKittyIce</a></sub>
</p>
