"""Run the regression suite with disposable site data and no model credentials."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="subject-hub-tests-") as tmp:
        env = {k: v for k, v in os.environ.items() if not k.startswith("SUBJECT_HUB_")}
        env.update(SUBJECT_HUB_DATA=tmp, SUBJECT_HUB_ROOT=str(root),
                   PYTHONPATH=str(root / "backend"), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                                cwd=root, env=env)
    sys.exit(result.returncode)
