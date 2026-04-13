# 📻 Broadcast Backpack

**All-in-one broadcast production companion** — Soundboard, music queue, recording, streaming, and session logging in a single desktop application.

![Version](https://img.shields.io/badge/version-6.0.0-blue)
![Python](https://img.shields.io/badge/python-3.10+-green)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)

## Features

- **🎹 Soundboard** — Pinned favorites + tabbed banks, drag-and-drop assignment, per-button FX
- **🎵 Music Queue** — Drag-and-drop playlist with transport controls
- **🎙️ Tape Recorder** — Capture your show with one click
- **📡 Icecast Streaming** — Stream directly to any Icecast-compatible server
- **📋 Session Log** — Automatic timestamped event logging
- **⏱️ Show Timer** — Live elapsed time with countdown presets
- **📝 Notes & Bits** — In-app notepad and premise tracking
- **🌓 Themes** — Darkmode Blue and Classic Light, plus custom colors

## Installation

### Requirements
- Windows 10/11
- Python 3.10 or newer

### Quick Start

1. Clone or download this repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Launch:
   ```bash
   python main.py
   ```
   Or use the included `Launch_Broadcast_Backpack.bat`

### Dependencies

Core:
- `customtkinter` — Modern UI widgets
- `pygame` — Audio playback
- `tkinterdnd2` — Drag and drop support

Optional:
- `pedalboard` — Audio FX (pitch, reverb, echo, filters)
- `sounddevice` + `soundfile` — Recording and streaming
- `keyboard` — Global hotkeys

## Usage

### Soundboard
- **Drag audio files** onto any button to assign
- **Right-click** buttons to edit label, color, volume, loop, and FX
- Use **BOARD** slider to control overall soundboard volume
- Enable **Board Gain** in Settings for extra boost (0-12 dB)

### Music Queue
- **Drag files or folders** to the queue panel
- Use transport controls: ▶ Play, ⏸ Pause, ⏹ Stop, ⏮⏭ Skip
- **QUEUE** slider controls music volume independently

### Recording
- Click the **⏺ Record** button in the header
- Audio is captured from your configured input device
- For full show recording, use "Stereo Mix" or a virtual audio cable

### Streaming
- Go to **Tools → Stream Settings**
- Enter your Icecast server details
- Select the audio device to stream
- Click **Connect**

### Session Log
- Automatically logs sound plays with timestamps
- Press **Ctrl+Shift+T** to add manual timestamps
- Press **Ctrl+Shift+G** to mark "gold moments"
- Export to text or audio markers (Audition CSV, Audacity labels)

## Hotkeys

| Hotkey | Action |
|--------|--------|
| `Ctrl+Shift+L` | Toggle GO LIVE |
| `Ctrl+Shift+P` | PANIC — stop all audio |
| `Ctrl+Shift+M` | Toggle mute |
| `Ctrl+Shift+T` | Add timestamp |
| `Ctrl+Shift+G` | Gold moment |
| `Ctrl+Shift+Z` | Mini mode |
| `Ctrl+Z` | Undo |
| `Ctrl+,` | Settings |

## Data Location

All user data is stored in:
```
C:\Users\[Username]\BroadcastBackpack\
├── config.json      # Settings
├── sessions/        # Session logs
├── recordings/      # Tape recordings
├── markers/         # Exported markers
└── logs/            # Application logs
```

## Migration

If upgrading from a previous version, your settings will be automatically migrated on first launch.

## Building

To create a standalone executable:

```bash
pip install pyinstaller
pyinstaller Broadcast_Backpack.spec
```

The executable will be created in the `dist/` folder.

## License

MIT License — See LICENSE file for details.

## Contributing

Contributions welcome! Please open an issue or pull request on GitHub.

---

**Broadcast Backpack v6.0.0**  
[GitHub Repository](https://github.com/ColdKittyIce/BroadcastBackpack)
