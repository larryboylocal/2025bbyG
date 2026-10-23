"""Run the full proof. Build backbone only when every check passes.

Exit 0 is the only state in which a commit is allowed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
    completed = subprocess.run(cmd, cwd=cwd or ROOT, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> int:
    python = os.environ.get("FXJEFE_PYTHON", sys.executable)
    run([python, "-m", "unittest", "tests.test_kraken_expectations"])
    run([python, "-m", "terminals.kraken.kraken_runtime", "--self-check"])
    run([python, str(ROOT / "terminals" / "kraken" / "scripts" / "prove_pipeline.py")])
    proof_path = ROOT / "terminals" / "kraken" / "proof" / "last_proof.json"
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    signals = proof["signals"]
    pandas_block = proof["pandas"]
    flags = proof["live_flags"]
    if signals["schema"] != "fxjefe.kraken.futures.v1" or signals["schema_valid"] is not True:
        raise SystemExit("schema validation failed")
    if signals["count"] < 1 or pandas_block["non_null_atr"] < 1 or proof["labels"]["rows"] < 1:
        raise SystemExit("pipeline output is empty")
    if flags != {
        "trading_enabled": True,
        "allow_live_trades": True,
        "live_trading": True,
        "paper_fills": False,
    }:
        raise SystemExit("live flags drifted")
    tier = proof["rate_limit"]["snapshot"]["tier"]
    ceiling = proof["rate_limit"]["snapshot"]["ceiling_cost"]
    expected = 500 * (0.8888 if tier == "high_volatility" else 0.66)
    if abs(ceiling - expected) > 1e-6:
        raise SystemExit(f"tier ceiling {ceiling} does not match {tier}")
    if proof["outcome"]["order_sent"] is not False:
        raise SystemExit("proof sent an order")
    pandas_file = pandas_block["file"]
    if ".venv" not in pandas_file and "backbone" not in pandas_file:
        raise SystemExit(f"pandas did not load from the project environment: {pandas_file}")
    run([python, str(ROOT / "tools" / "build_backbone.py")])
    backbone_python = ROOT / "backbone" / ".venv" / "bin" / "python"
    checker = str(backbone_python if backbone_python.exists() else python)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "backbone")
    print("+ backbone self-check", flush=True)
    completed = subprocess.run(
        [checker, "-m", "terminals.kraken.kraken_runtime", "--self-check"],
        cwd=ROOT / "backbone",
        env=env,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)
    ready = ROOT / "backbone" / "READY"
    if not ready.exists() or "verified" not in ready.read_text(encoding="utf-8"):
        raise SystemExit("backbone READY stamp missing")
    print("VERIFIED signal input output outcome")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
