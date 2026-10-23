"""Copy a verified tree into backbone/. Refuse to replace it when asked to skip."""

from __future__ import annotations

import compileall
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "backbone"
KEEP = ("BOOT.txt", "launch.sh", "launch.ps1", "install-boot.sh", "kraken-backbone.service")


def build() -> None:
    stamp = DEST / "READY"
    if "--no-replace" in sys.argv and stamp.exists():
        print("backbone READY stamp present; not replacing")
        return
    preserved = {}
    for name in KEEP:
        path = DEST / name
        if path.exists():
            preserved[name] = path.read_bytes()
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir()
    for name in ("shared", "terminals", "tests", "wheels", "coordinator", "requirements.txt", "README.md"):
        source = ROOT / name
        target = DEST / name
        if source.is_dir():
            shutil.copytree(
                source,
                target,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "state", ".venv"),
            )
        elif source.exists():
            shutil.copy2(source, target)
    for name, payload in preserved.items():
        (DEST / name).write_bytes(payload)
    compileall.compile_dir(str(DEST / "terminals"), quiet=1, legacy=True)
    compileall.compile_dir(str(DEST / "shared"), quiet=1, legacy=True)
    compileall.compile_dir(str(DEST / "coordinator"), quiet=1, legacy=True)
    (DEST / "READY").write_text("verified\n", encoding="utf-8")
    print(f"backbone written: {DEST}")


if __name__ == "__main__":
    build()
