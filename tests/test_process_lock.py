import tempfile
import unittest
from pathlib import Path

from operations.process_lock import LockUnavailableError, ProcessLock


class ProcessLockTests(unittest.TestCase):
    def test_duplicate_acquisition_fails_and_release_allows_reacquisition(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "scraper.lock"
            first = ProcessLock(lock_path)
            second = ProcessLock(lock_path)
            first.acquire()
            self.addCleanup(first.release)

            with self.assertRaises(LockUnavailableError):
                second.acquire()

            first.release()
            second.acquire()
            second.release()

    def test_context_manager_releases_lock_after_exception(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "scraper.lock"
            with self.assertRaisesRegex(RuntimeError, "boom"):
                with ProcessLock(lock_path):
                    raise RuntimeError("boom")

            with ProcessLock(lock_path):
                pass


if __name__ == "__main__":
    unittest.main()
