"""Тесты daemon._handle_pdf: громкое предупреждение о потере OCR-слоя при DJVU->PDF."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# daemon в шапке импортирует fcntl (flock) — модуль существует только на Unix;
# в тестируемом коде не используется (только блок __main__), подменяем заглушкой
sys.modules.setdefault("fcntl", MagicMock())

import daemon

TEXT_INFO = {"pages": 30, "text_layer": True, "chars_per_page": 350}
SCAN_INFO = {"pages": 30, "text_layer": False, "chars_per_page": 15}


class HandlePdfTest(unittest.TestCase):
    def _run(self, info: dict, src_has_text: bool):
        """Прогон _handle_pdf со всеми внешними зависимостями в моках."""
        with patch.object(daemon.router, "pdf_analyze", return_value=info), \
             patch.object(daemon.vault, "create_note", return_value=Path("NUL")), \
             patch.object(daemon.vault, "set_status"), \
             patch.object(daemon.gpu_queue, "enqueue") as enqueue, \
             patch.object(daemon, "log") as log, \
             patch.object(daemon, "STATS", {"done": 0, "errors": 0}):
            daemon._handle_pdf(Path("book.pdf"), title_hint="Книга", source_url="",
                               scope="books", src_has_text=src_has_text)
        return log, enqueue

    def test_text_layer_kept_goes_to_convert(self):
        log, enqueue = self._run(TEXT_INFO, src_has_text=True)
        self.assertEqual(enqueue.call_args[0][0], "convert")
        for call in log.call_args_list:
            self.assertNotIn("OCR-слой", str(call))

    def test_lost_text_layer_warns_and_goes_to_ocr(self):
        log, enqueue = self._run(SCAN_INFO, src_has_text=True)
        self.assertEqual(enqueue.call_args[0][0], "ocr")
        logged = [str(call) for call in log.call_args_list]
        self.assertTrue(any("у DJVU был OCR-слой" in s for s in logged))

    def test_plain_pdf_scan_no_warning(self):
        log, enqueue = self._run(SCAN_INFO, src_has_text=False)
        self.assertEqual(enqueue.call_args[0][0], "ocr")
        for call in log.call_args_list:
            self.assertNotIn("OCR-слой", str(call))


if __name__ == "__main__":
    unittest.main()
