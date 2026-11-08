"""Run the full API workflow in a fresh process so app configuration is isolated."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RepairWorkflowIntegrationTests(unittest.TestCase):
    def test_isolated_api_workflow(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            env = {key: value for key, value in os.environ.items() if not key.startswith('SUBJECT_HUB_')}
            env.update(SUBJECT_HUB_ROOT=temp, SUBJECT_HUB_DATA=str(Path(temp) / 'data'),
                       SUBJECT_HUB_BANK=str(Path(temp) / 'bank'), SUBJECT_HUB_PORT='8090',
                       SUBJECT_HUB_ADMIN_PORT='8091', SUBJECT_HUB_SECRET='isolated-test-secret',
                       PYTHONPATH=str(ROOT / 'backend'), PYTHONIOENCODING='utf-8')
            run = subprocess.run([sys.executable, str(ROOT / 'tests/fixtures/repair_workflow_case.py')],
                                 cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(run.returncode, 0, run.stdout + '\n' + run.stderr)


if __name__ == '__main__':
    unittest.main()
