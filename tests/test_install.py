"""Check installer rejection paths without exposing any physical disks."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.geteuid() == 0, "Run as root inside the built container")
class InstallTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="bc250-install-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.root.chmod(0o777)
        self.called = self.root / "bootc-called"
        mock = self.root / "bootc"
        mock.write_text('#!/bin/sh\ntouch "$BC250_TEST_CALLED"\nexit 99\n')
        mock.chmod(0o755)
        self.env = dict(os.environ, PATH=f"{self.root}:/usr/bin:/bin",
                        BC250_TEST_CALLED=str(self.called))

    def check_rejected(self, args, status, text, **kwargs):
        result = subprocess.run(
            ["/usr/sbin/bc250-install", *args], env=self.env,
            capture_output=True, text=True, check=False, **kwargs,
        )
        self.assertEqual(result.returncode, status, result.stderr)
        self.assertIn(text, result.stderr)
        self.assertFalse(self.called.exists(), "Rejected input reached bootc")

    def test_missing_arguments(self):
        self.check_rejected([], 2, "Usage:")

    def test_nonroot_cannot_install(self):
        self.check_rejected(["/dev/null", "bc250", "/dev/null"], 1,
                            "must run as root", user=65534, group=65534)

    def test_non_disk_destinations(self):
        regular = self.root / "not-a-disk"
        regular.write_text("preserve me")
        for destination in (str(regular), "/dev/null"):
            with self.subTest(destination=destination):
                self.check_rejected([destination, "bc250", "/dev/null"], 2,
                                    "whole physical disk")
        self.assertEqual(regular.read_text(), "preserve me")

    def test_invalid_hostname(self):
        self.check_rejected(["/dev/null", "bad hostname", "/dev/null"], 2,
                            "Use a hostname")


if __name__ == "__main__":
    unittest.main()
