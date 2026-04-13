# Building Broadcast Backpack

## Prerequisites

- Windows 10/11
- Python 3.10 or newer
- pip (Python package manager)

## Setup Build Environment

1. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   pip install pyinstaller
   ```

2. **Verify installation:**
   ```bash
   python main.py
   ```
   The app should launch. Close it before building.

## Building the Executable

### Option 1: One-folder distribution (recommended)

This creates a folder with the exe and all dependencies:

```bash
pyinstaller Broadcast_Backpack.spec
```

The output will be in `dist/Broadcast_Backpack/`. The main executable is `Broadcast_Backpack.exe`.

### Option 2: Single-file executable

If you want a single .exe file (larger, slower startup):

```bash
pyinstaller --onefile --noconsole --name Broadcast_Backpack main.py
```

## Distribution

### Folder Distribution
Zip the entire `dist/Broadcast_Backpack/` folder. Users extract and run `Broadcast_Backpack.exe`.

### Creating an Installer
For a professional installer, use [Inno Setup](https://jrsoftware.org/isinfo.php) or [NSIS](https://nsis.sourceforge.io/).

## Troubleshooting

### Missing modules
If you get import errors, add them to `hiddenimports` in the .spec file.

### Missing assets
CustomTkinter themes are automatically collected. If you see theme errors, verify:
```python
ctk_datas = collect_data_files("customtkinter", includes=["**/*"])
```

### Antivirus false positives
PyInstaller executables sometimes trigger antivirus. Solutions:
- Sign the executable with a code signing certificate
- Submit to antivirus vendors for whitelisting
- Distribute as source with a launcher script

## File Structure After Build

```
dist/
└── Broadcast_Backpack/
    ├── Broadcast_Backpack.exe    # Main executable
    ├── help.html                  # Help documentation
    ├── call_hook.py               # MicroSIP integration script
    └── [runtime files]            # Python runtime & dependencies
```

## Adding an Icon

1. Create or obtain a .ico file (256x256 recommended)
2. Edit `Broadcast_Backpack.spec`:
   ```python
   icon="path/to/your/icon.ico"
   ```
3. Rebuild with PyInstaller
