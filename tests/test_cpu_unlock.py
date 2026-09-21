"""Exercise the root helper in a container; all hardware/service calls are mocked."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.geteuid() == 0, "Run as root inside the built container")
class CPUUnlockTests(unittest.TestCase):
    def setUp(self):
        # A build container does not run systemd-tmpfiles at boot.
        Path("/run/lock").mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix="bc250-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.log = self.root / "calls"
        self.env = dict(os.environ)
        self.env.update(
            PATH=f"{self.root}:/usr/bin:/bin",
            BC250_TEST_LOG=str(self.log),
            BC250_TEST_GPU="0000:01:00.0 0300: 1002:13fe",
            BC250_TEST_ACTIVE="0",
            BC250_TEST_STOP="0",
            BC250_TEST_UNLOCK="0",
        )
        self.mock("lspci", 'printf "%s\\n" "$BC250_TEST_GPU"')
        self.mock("systemctl", '''
printf 'systemctl %s\\n' "$*" >> "$BC250_TEST_LOG"
case "$1" in
    is-active) exit "$BC250_TEST_ACTIVE" ;;
    stop) exit "$BC250_TEST_STOP" ;;
esac
''')
        self.mock("python3", '''
printf 'unlock %s\\n' "$*" >> "$BC250_TEST_LOG"
exit "$BC250_TEST_UNLOCK"
''')

    def mock(self, name, body):
        path = self.root / name
        path.write_text("#!/bin/bash\nset -eu\n" + body + "\n")
        path.chmod(0o755)

    def run_helper(self, *args):
        result = subprocess.run(
            ["/usr/bin/bc250-cpu-unlock", *args],
            env=self.env, capture_output=True, text=True, check=False,
        )
        calls = self.log.read_text().splitlines() if self.log.exists() else []
        return result, calls

    def test_wrong_hardware_never_stops_governor_or_unlocks(self):
        self.env["BC250_TEST_GPU"] = ""
        result, calls = self.run_helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not detected", result.stderr)
        self.assertEqual(calls, [])

    def test_force_argument_is_rejected_without_side_effects(self):
        result, calls = self.run_helper("-f")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, [])

    def test_success_stops_unlocks_and_restores_in_order(self):
        result, calls = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [
            "systemctl is-active --quiet cyan-skillfish-governor-smu.service",
            "systemctl stop cyan-skillfish-governor-smu.service",
            "unlock /usr/share/bc250/vendor/cpu-unlock/bc250-unlock-cores.py",
            "systemctl start cyan-skillfish-governor-smu.service",
        ])
        self.assertIn("Reboot manually", result.stdout)

    def test_failed_unlock_restores_governor_and_preserves_failure(self):
        self.env["BC250_TEST_UNLOCK"] = "17"
        result, calls = self.run_helper()
        self.assertEqual(result.returncode, 17)
        self.assertEqual(calls[-1], "systemctl start cyan-skillfish-governor-smu.service")
        self.assertNotIn("Reboot manually", result.stdout)

    def test_inactive_governor_stays_inactive(self):
        self.env["BC250_TEST_ACTIVE"] = "3"
        result, calls = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(call.startswith("systemctl start") for call in calls))

    def test_stop_failure_prevents_unlock(self):
        self.env["BC250_TEST_STOP"] = "5"
        result, calls = self.run_helper()
        self.assertEqual(result.returncode, 5)
        self.assertFalse(any(call.startswith("unlock") for call in calls))


if __name__ == "__main__":
    unittest.main()
