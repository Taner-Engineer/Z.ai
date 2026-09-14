"""Тесты постоянного каталога результатов run_queue (resume без ручного seed)."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_by_path(name: str, rel: str):
    # файлы в путях с дефисом модулем не импортируются — грузим по спецификации
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


run_queue = _load_by_path("run_queue_res", "win-worker/run_queue.py")


class DropSentJobsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.jobs = Path(tmp.name) / "jobs"
        self.jobs.mkdir()

    def _mk(self, jid: str, status: str):
        d = self.jobs / jid
        d.mkdir()
        (d / "manifest.json").write_text(
            json.dumps({"id": jid, "status": status}), encoding="utf-8")

    def test_sent_dropped_others_kept(self):
        self._mk("j1", "sent")
        self._mk("j2", "waiting_approval")
        (self.jobs / "j3").mkdir()  # без manifest.json — не трогать
        self.assertEqual(run_queue.drop_sent_jobs(self.jobs), 1)
        self.assertFalse((self.jobs / "j1").exists())
        self.assertTrue((self.jobs / "j2").exists())
        self.assertTrue((self.jobs / "j3").exists())

    def test_broken_manifest_not_dropped(self):
        d = self.jobs / "j1"
        d.mkdir()
        (d / "manifest.json").write_text("{битый json", encoding="utf-8")
        self.assertEqual(run_queue.drop_sent_jobs(self.jobs), 0)
        self.assertTrue(d.exists())


class CleanupAfterDeliveryTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.results = Path(tmp.name) / "results"
        self.results.mkdir()

    def _mk(self, jid: str):
        d = self.results / jid
        d.mkdir()
        (d / "manifest.json").write_text(
            json.dumps({"id": jid, "status": "done"}), encoding="utf-8")

    def test_delivered_removed_undelivered_kept(self):
        for jid in ("j1", "j2", "j3"):
            self._mk(jid)
        self.assertEqual(
            run_queue.cleanup_after_delivery(self.results, ["j1", "j2"]), 2)
        self.assertFalse((self.results / "j1").exists())
        self.assertFalse((self.results / "j2").exists())
        self.assertTrue((self.results / "j3").exists())
        # повторный вызов безопасен
        self.assertEqual(
            run_queue.cleanup_after_delivery(self.results, ["j1", "j2"]), 0)
        self.assertTrue((self.results / "j3").exists())


if __name__ == "__main__":
    unittest.main()
