"""Phase 13A runner 路徑呼叫的跨版本回歸測試。"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_RELATIVE = Path("scripts/run_phase13a_embedded_contract_sil.py")


class Phase13AScriptInvocationTests(unittest.TestCase):
    def _run_with_script_path(self, script_path: Path) -> subprocess.CompletedProcess[str]:
        evidence_root = REPO_ROOT / "experiments" / "phase13"
        evidence_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="invocation_", dir=evidence_root) as temporary:
            output_dir = Path(temporary) / "evidence"
            code = (
                "import runpy, sys; "
                "script_path = sys.argv[1]; "
                "output_dir = sys.argv[2]; "
                "sys.argv = [script_path, '--output-dir', output_dir]; "
                "runpy.run_path(script_path, run_name='__main__')"
            )
            completed = subprocess.run(
                [sys.executable, "-c", code, str(script_path), str(output_dir)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            evidence_dirs = list(output_dir.iterdir()) if output_dir.exists() else []
            self.assertTrue(
                any((directory / "commands.txt").is_file() for directory in evidence_dirs),
                msg=completed.stdout + "\n" + completed.stderr,
            )
            return completed

    def test_relative_script_invocation_writes_complete_evidence(self) -> None:
        completed = self._run_with_script_path(RUNNER_RELATIVE)
        self.assertEqual(completed.returncode, 0, msg=completed.stdout + "\n" + completed.stderr)
        self.assertIn("sil_tests=28/28", completed.stdout)

    def test_absolute_script_invocation_writes_complete_evidence(self) -> None:
        completed = self._run_with_script_path((REPO_ROOT / RUNNER_RELATIVE).resolve())
        self.assertEqual(completed.returncode, 0, msg=completed.stdout + "\n" + completed.stderr)
        self.assertIn("sil_tests=28/28", completed.stdout)


if __name__ == "__main__":
    unittest.main()
