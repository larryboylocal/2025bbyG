"""Installer: an update reboots, a failed check does not replace the installed tree."""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "backbone" / "install-boot.sh"


class BootUpdateTests(unittest.TestCase):
    def test_first_install_does_not_reboot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "fxjefe-backbone"
            marker = Path(tmp) / "rebooted"
            env = os.environ.copy()
            env.update(
                {
                    "FXJEFE_BOOT_DEST": str(dest),
                    "FXJEFE_SKIP_SYSTEMD": "1",
                    "FXJEFE_SKIP_PIP": "1",
                    "FXJEFE_REBOOT_CMD": f"echo rebooted > {marker}",
                }
            )
            completed = subprocess.run(
                ["sh", str(INSTALL)],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue((dest / "READY").is_file())
            self.assertTrue((dest / "launch.sh").is_file())
            self.assertTrue((dest / ".venv" / "bin" / "python").exists())
            self.assertFalse(marker.exists())
            self.assertIn("installed", completed.stdout)

    def test_update_reboots_and_keeps_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "fxjefe-backbone"
            marker = Path(tmp) / "rebooted"
            env = os.environ.copy()
            env.update(
                {
                    "FXJEFE_BOOT_DEST": str(dest),
                    "FXJEFE_SKIP_SYSTEMD": "1",
                    "FXJEFE_SKIP_PIP": "1",
                    "FXJEFE_REBOOT_CMD": f"echo rebooted > {marker}",
                }
            )
            first = subprocess.run(
                ["sh", str(INSTALL)],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            secret = "KRAKEN_FUTURES_API_SECRET=keep-me\n"
            (dest / "kraken.env").write_text(secret, encoding="utf-8")
            second = subprocess.run(
                ["sh", str(INSTALL)],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("rebooting", second.stdout)
            self.assertEqual(marker.read_text(encoding="utf-8").strip(), "rebooted")
            self.assertEqual((dest / "kraken.env").read_text(encoding="utf-8"), secret)
            self.assertTrue((dest.parent / "fxjefe-backbone.previous").is_dir())

    def test_failed_check_leaves_the_installed_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "fxjefe-backbone"
            dest.mkdir()
            (dest / "READY").write_text("verified\n", encoding="utf-8")
            (dest / "kraken.env").write_text("KRAKEN_FUTURES_API_KEY=stay\n", encoding="utf-8")
            marker = Path(tmp) / "rebooted"
            env = os.environ.copy()
            env.update(
                {
                    "FXJEFE_BOOT_DEST": str(dest),
                    "FXJEFE_SKIP_SYSTEMD": "1",
                    "FXJEFE_SKIP_VENV": "1",
                    "FXJEFE_SELF_CHECK_CMD": "exit 1",
                    "FXJEFE_REBOOT_CMD": f"echo rebooted > {marker}",
                }
            )
            completed = subprocess.run(
                ["sh", str(INSTALL)],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual((dest / "READY").read_text(encoding="utf-8"), "verified\n")
            self.assertEqual((dest / "kraken.env").read_text(encoding="utf-8"), "KRAKEN_FUTURES_API_KEY=stay\n")
            self.assertFalse(marker.exists())
            self.assertFalse((Path(tmp) / "fxjefe-backbone.previous").exists())

    def test_installer_is_executable(self) -> None:
        mode = INSTALL.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR)


if __name__ == "__main__":
    unittest.main()
