"""Выполняется ВНУТРИ контейнера docling:cpu (python3 /work/convert_one.py in.pdf out.md no-ocr|ocr).

Кэш моделей лежит на смонтированном томе — модели не перекачиваются при каждом запуске.
Аргумент ocr включает full-page OCR для сканов; для PDF с текстовым слоем — off.
"""
import sys
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption


def main():
    src, dst, mode = sys.argv[1], sys.argv[2], sys.argv[3]
    opts = PdfPipelineOptions()
    opts.do_ocr = mode == "ocr"
    opts.do_table_structure = True
    conv = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )
    result = conv.convert(src)
    Path(dst).write_text(result.document.export_to_markdown(), encoding="utf-8")


if __name__ == "__main__":
    main()
