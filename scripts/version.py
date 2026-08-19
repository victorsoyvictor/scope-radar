#!/usr/bin/env python3
"""
Stamp `git describe` into web/radar.html's APP_VERSION constant.

Run this before deploying a static copy of the page (GitHub Pages, a USB
stick, opening the file directly) so the Diagnostics tab shows a real
version instead of "dev". Commit the result like any other change.

The bundled proxy (proxy/serve.py) does the same thing live, on every
request, straight from your git checkout — you don't need this script for
a copy that's only ever served that way.

No third-party packages. Python 3.9+.

    python3 scripts/version.py
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RADAR = ROOT / "web" / "radar.html"
VERSION_RE = re.compile(r'const APP_VERSION="[^"]*"')


def git_version() -> str:
    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=ROOT, capture_output=True, text=True, timeout=5,
        )
        v = out.stdout.strip()
        return v if out.returncode == 0 and v else "dev"
    except Exception:
        return "dev"


def main():
    version = git_version()
    text = RADAR.read_text(encoding="utf-8")
    new_text, n = VERSION_RE.subn(f'const APP_VERSION="{version}"', text)
    if n == 0:
        sys.exit("APP_VERSION constant not found in web/radar.html")
    RADAR.write_text(new_text, encoding="utf-8")
    print(f"Stamped APP_VERSION={version} into web/radar.html")


if __name__ == "__main__":
    main()
