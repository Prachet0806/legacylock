"""Hard correctness/import gates plus explicit lint/type backlog nonregression.

Run from backend: python ../scripts/quality_gate.py. The checked-in baseline
records current diagnostic counts by file and rule. New counts fail; reductions
pass. It is a ratchet, not a declaration that the full repository is type-clean.
"""

import collections
import json
import re
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
baseline_path = root / "docs/quality-baseline.json"


def collect():
    hard = subprocess.run(
        [sys.executable, "-m", "ruff", "check", ".", "--select", "I,F"],
        cwd=root / "backend",
        capture_output=True,
        text=True,
    )
    if hard.returncode:
        raise RuntimeError(hard.stdout + hard.stderr)
    ruff = subprocess.run(
        [sys.executable, "-m", "ruff", "check", ".", "--output-format", "json"],
        cwd=root / "backend",
        capture_output=True,
        text=True,
    )
    if ruff.returncode not in (0, 1):
        raise RuntimeError("Ruff failed to run")
    counts = collections.Counter()
    for d in json.loads(ruff.stdout):
        path = Path(d["filename"]).relative_to(root / "backend").as_posix()
        counts[f"ruff:{path}:{d['code']}"] += 1
    mypy = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            ".",
            "--show-error-codes",
            "--no-error-summary",
            "--no-pretty",
            "--no-color-output",
        ],
        cwd=root / "backend",
        capture_output=True,
        text=True,
    )
    if mypy.returncode not in (0, 1):
        raise RuntimeError("Mypy failed to run")
    for line in mypy.stdout.splitlines():
        if ": error:" not in line:
            continue
        match = re.match(r"(.+?):(?:[0-9]+:)? error:.*\[([^]]+)\]$", line)
        if not match:
            raise RuntimeError("Unclassified mypy failure: " + line)
        counts[f"mypy:{match[1].replace(chr(92), '/')}:{match[2]}"] += 1
    return dict(sorted(counts.items()))


if __name__ == "__main__":
    current = collect()
    if "--record-baseline" in sys.argv:
        baseline_path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
        print("Recorded explicit diagnostic baseline; review changes before merging.")
    else:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        regressions = {k: v for k, v in current.items() if v > baseline.get(k, 0)}
        if regressions:
            print(json.dumps(regressions, indent=2))
            sys.exit(1)
        print(
            f"Hard gates passed; no new lint/type diagnostics ({sum(current.values())} tracked backlog diagnostics)."
        )
