"""Тесты router.pdf_analyze: выборка текста из середины PDF, а не с первых страниц."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf

import router

SENTENCE = ("Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do "
            "eiusmod tempor incididunt ut labore et dolore magna aliqua.")
# ~1700 символов — заметно выше порога config.PDF_CHARS_PER_PAGE (150)
PARAGRAPH = "\n".join([SENTENCE] * 14)


def make_pdf(path: Path, pages: int, texts: dict[int, str]) -> None:
    """PDF из pages пустых страниц; texts — текст по номерам страниц."""
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()
        if i in texts:
            page.insert_text((72, 100), texts[i], fontsize=8)
    doc.save(path)
    doc.close()


def make_empty_pdf(path: Path) -> None:
    """PDF без страниц: pymupdf сам такие не сохраняет, собираем минимальный валидный."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [] /Count 0 >>"]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    path.write_bytes(bytes(out))


class PdfAnalyzeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_text_in_middle_is_found(self):
        p = self.dir / "mid.pdf"
        make_pdf(p, 30, {15: PARAGRAPH, 16: PARAGRAPH, 17: PARAGRAPH})
        info = router.pdf_analyze(p)
        self.assertTrue(info["text_layer"])
        self.assertEqual(info["pages"], 30)

    def test_text_only_on_first_pages_is_ignored(self):
        # раньше выборка с первых страниц давала здесь ложное True и зря гнала в OCR
        p = self.dir / "front.pdf"
        make_pdf(p, 30, {0: PARAGRAPH, 1: PARAGRAPH, 2: PARAGRAPH})
        info = router.pdf_analyze(p)
        self.assertFalse(info["text_layer"])
        self.assertEqual(info["pages"], 30)

    def test_scan_has_no_text_layer(self):
        p = self.dir / "scan.pdf"
        make_pdf(p, 30, {})
        self.assertFalse(router.pdf_analyze(p)["text_layer"])

    def test_empty_pdf_without_exceptions(self):
        p = self.dir / "empty.pdf"
        make_empty_pdf(p)
        self.assertEqual(router.pdf_analyze(p),
                         {"pages": 0, "text_layer": False, "chars_per_page": 0})


if __name__ == "__main__":
    unittest.main()
