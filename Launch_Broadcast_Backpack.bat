@echo off
title Broadcast Backpack
cd /d "%~dp0"
python main.py
if errorlevel 1 pause
