r"""
call_hook.py — MicroSIP call event forwarder for Broadcast Backpack.

Add to MicroSIP.ini (edit %APPDATA%\MicroSIP\MicroSIP.ini):

    cmdCallStart="python" "C:\path\to\call_hook.py" start
    cmdCallEnd="python" "C:\path\to\call_hook.py" end

MicroSIP passes the Caller ID as the first argument after your command.
"""

import sys
import urllib.request
import urllib.parse
import os
import datetime

PORT  = 12345
HOST  = "127.0.0.1"

# Debug log — written next to this script so we can see if MicroSIP fires it
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "call_hook_debug.log")

def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.datetime.now()} — {msg}\n")

def main():
    log(f"call_hook.py fired — args: {sys.argv}")

    if len(sys.argv) < 2:
        log("ERROR: no event argument")
        sys.exit(0)

    event  = sys.argv[1].strip().lower()
    caller = sys.argv[2].strip() if len(sys.argv) > 2 else "unknown"

    event_map = {"start": "call_start", "end": "call_end"}
    api_event = event_map.get(event)
    if not api_event:
        log(f"ERROR: unknown event '{event}'")
        sys.exit(0)

    params = urllib.parse.urlencode({"event": api_event, "caller": caller})
    url    = f"http://{HOST}:{PORT}/call?{params}"
    log(f"Sending: {url}")

    try:
        resp = urllib.request.urlopen(url, timeout=2)
        log(f"Response: {resp.read()}")
    except Exception as e:
        log(f"ERROR sending to Companion: {e}")

if __name__ == "__main__":
    main()
