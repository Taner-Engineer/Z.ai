"""Тесты worker.should_run: фильтр манифестов по статусу (sent не перегоняем)."""
import importlib.util
import unittest
from pathlib import Path

# worker.py лежит в папке с дефисом — как модуль не импортируется, грузим по пути
_worker = Path(__file__).resolve().parents[1] / "gpu-worker" / "worker.py"
_spec = importlib.util.spec_from_file_location("worker", _worker)
worker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(worker)


class ShouldRunTest(unittest.TestCase):
    def test_waiting_approval_runs(self):
        self.assertTrue(worker.should_run({"status": "waiting_approval"}))

    def test_sent_skipped(self):
        self.assertFalse(worker.should_run({"status": "sent"}))

    def test_done_skipped(self):
        self.assertFalse(worker.should_run({"status": "done"}))

    def test_failed_skipped(self):
        self.assertFalse(worker.should_run({"status": "failed"}))

    def test_missing_status_runs(self):
        self.assertTrue(worker.should_run({}))

    def test_none_status_runs(self):
        self.assertTrue(worker.should_run({"status": None}))


if __name__ == "__main__":
    unittest.main()
