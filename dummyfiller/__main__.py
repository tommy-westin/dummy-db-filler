"""Startar webbgränssnittet lokalt:  python -m dummyfiller [port]"""
from __future__ import annotations

import subprocess
import sys
import threading
import webbrowser
from pathlib import Path


def main() -> int:
    port = sys.argv[1] if len(sys.argv) > 1 else "8501"
    app = Path(__file__).with_name("app.py")
    cmd = [sys.executable, "-m", "streamlit", "run", str(app),
           "--server.address=localhost",          # nås bara från den egna datorn
           "--server.port", port,
           "--server.headless=true",              # ingen e-postfråga vid första start
           "--browser.gatherUsageStats=false"]    # ingen användningsstatistik skickas
    threading.Timer(2.5, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
