"""Тесты gpu_lock (межпроцессный лок), worker.is_done и run_queue.seed_results."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gpu_lock import acquire, release


def _load_by_path(name: str, rel: str):
    # файлы в путях с дефисом модулем не импортируются — грузим по спецификации
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


worker = _load_by_path("worker_lrt", "gpu-worker/worker.py")
run_queue = _load_by_path("run_queue_lrt", "win-worker/run_queue.py")


class GpuLockTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.lock = Path(tmp.name) / "gpu.lock"

    def test_busy_then_free_again(self):
        h1 = acquire(self.lock)
        self.assertIsNotNone(h1)
        # тот же процесс, новый хэндл на тот же файл — занято
        self.assertIsNone(acquire(self.lock))
        release(h1)
        h2 = acquire(self.lock)
        self.assertIsNotNone(h2)
        release(h2)


class IsDoneTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.results = Path(tmp.name)

    def _mk(self, jid: str, status: str):
        d = self.results / jid
        d.mkdir(parents=True)
        (d / "manifest.json").write_text(
            json.dumps({"id": jid, "status": status}), encoding="utf-8")

    def test_done_detected(self):
        self._mk("job1", "done")
        self.assertTrue(worker.is_done("job1", self.results))

    def test_failed_result_counts_as_done(self):
        # failed не переделывать: наличие результата важнее статуса
        self._mk("job2", "failed")
        self.assertTrue(worker.is_done("job2", self.results))

    def test_missing_result_not_done(self):
        self.assertFalse(worker.is_done("nope", self.results))


class SeedResultsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.dst = self.dir / "results"
        self.dst.mkdir()

    def _mk(self, parent: Path, jid: str, mark: str):
        d = parent / jid
        d.mkdir(parents=True)
        (d / "manifest.json").write_text(json.dumps({"mark": mark}), encoding="utf-8")

    def test_merge_counts_first_dir_wins(self):
        a, b = self.dir / "a", self.dir / "b"
        self._mk(a, "job1", "a")
        self._mk(a, "job2", "a")
        self._mk(b, "job1", "b")  # пересечение id: приоритет у первого каталога
        self._mk(b, "job3", "b")
        self.assertEqual(run_queue.seed_results([a, b], self.dst), 3)
        got = json.loads(
            (self.dst / "job1" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(got["mark"], "a")
        self.assertTrue((self.dst / "job3" / "manifest.json").exists())

    def test_dir_without_manifest_ignored(self):
        a = self.dir / "a"
        (a / "junk").mkdir(parents=True)  # нет manifest.json — не результат
        self.assertEqual(run_queue.seed_results([a], self.dst), 0)
        self.assertFalse((self.dst / "junk").exists())


if __name__ == "__main__":
    unittest.main()
