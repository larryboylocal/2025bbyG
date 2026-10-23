"""Installer and runtime starter. No orders are sent."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
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

    def test_installed_unit_command_serves_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "fxjefe-backbone"
            env = os.environ.copy()
            env.update(
                {
                    "FXJEFE_BOOT_DEST": str(dest),
                    "FXJEFE_SKIP_SYSTEMD": "1",
                    "FXJEFE_SKIP_PIP": "1",
                    "FXJEFE_REBOOT_CMD": "echo skipped",
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
            python = dest / ".venv" / "bin" / "python"
            child_env = os.environ.copy()
            child_env["PYTHONPATH"] = str(dest)
            proc = subprocess.Popen(
                [str(python), "-m", "terminals.kraken.kraken_runtime"],
                cwd=dest,
                env=child_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                body = _wait_health(proc)
                self.assertEqual(body["terminal"], "kraken")
                self.assertIs(body["live_trading"], True)
                self.assertIs(body["api_key_present"], False)
                self.assertEqual(Path(f"/proc/{proc.pid}/cwd").resolve(), dest)
            finally:
                _stop(proc)

    def test_launch_script_serves_health_from_its_own_directory(self) -> None:
        launch = ROOT / "backbone" / "launch.sh"
        proc = subprocess.Popen(
            [str(launch)],
            cwd="/tmp",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            body = _wait_health(proc)
            self.assertEqual(body["terminal"], "kraken")
            self.assertIs(body["trading_enabled"], True)
            self.assertIs(body["allow_live_trades"], True)
            self.assertIs(body["live_trading"], True)
            self.assertIs(body["api_key_present"], False)
            self.assertEqual(body["rate_limit"]["system_max_cost"], 500)
            self.assertIn(body["rate_limit"]["ceiling_cost"], (330.0, 444.4))
            self.assertEqual(Path(f"/proc/{proc.pid}/cwd").resolve(), ROOT / "backbone")
        finally:
            _stop(proc)


def _stop(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is None:
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    if proc.stdout is not None:
        proc.stdout.close()
    if proc.stderr is not None:
        proc.stderr.close()


def _wait_health(proc: subprocess.Popen[str]) -> dict:
    last_error = ""
    for _ in range(50):
        if proc.poll() is not None:
            stderr = proc.stderr.read() if proc.stderr else ""
            raise AssertionError(f"starter exited {proc.returncode}: {stderr}")
        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=0.3) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            time.sleep(0.1)
    raise AssertionError(f"health did not come up: {last_error}")


if __name__ == "__main__":
    unittest.main()
