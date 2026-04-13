# -*- mode: python ; coding: utf-8 -*-
# Broadcast_Backpack.spec — PyInstaller build spec for v6.0.0

import sys
from pathlib import Path

block_cipher = None

# Collect customtkinter assets (themes, fonts, images)
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ctk_datas   = collect_data_files("customtkinter", includes=["**/*"])
tkdnd_datas = collect_data_files("tkinterdnd2",   includes=["**/*"])

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("help.html",    "."),
        ("call_hook.py", "."),
        *ctk_datas,
        *tkdnd_datas,
    ],
    hiddenimports=[
        "customtkinter",
        "tkinterdnd2",
        "pygame",
        "pygame.mixer",
        "requests",
        "pycaw",
        "comtypes",
        "sounddevice",
        "soundfile",
        "lameenc",
        "pedalboard",
        "scipy",
        "numpy",
        "keyboard",
        "pyperclip",
        "analytics",
        "streaming",
        "network",
        "audio",
        "config",
        "ui_dialogs",
        "ui_header",
        "ui_soundboard",
        "ui_right_panel",
        "ui_bottom",
        "ui_exp_features",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "PIL", "tkinter.test"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Broadcast_Backpack",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,           # no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,               # Add icon path here if you have one: icon="icon.ico"
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Broadcast_Backpack",
)
