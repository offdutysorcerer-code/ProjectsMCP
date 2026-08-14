from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pypdf import PdfWriter

from services.config_service import ConfigService
from services.file_service import FileService


class FileServicePdfTests(unittest.TestCase):
    def make_service(self, tmp_path: Path) -> FileService:
        project_root = tmp_path / "project"
        project_root.mkdir()
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "projects": {"test": str(project_root)},
                    "settings": {
                        "max_read_bytes": 1048576,
                        "max_pdf_read_bytes": 26214400,
                    },
                }
            ),
            encoding="utf-8",
        )
        return FileService(ConfigService(config_path))

    def test_read_pdf_text_rejects_non_pdf(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self.make_service(Path(tmp))
            target = service.resolve_project_path("test", "note.txt")
            target.write_text("hello", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Only PDF"):
                service.read_pdf_text("test", "note.txt")

    def test_read_pdf_text_blocks_path_traversal(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self.make_service(Path(tmp))

            with self.assertRaisesRegex(PermissionError, "escapes project root"):
                service.read_pdf_text("test", "../outside.pdf")

    def test_read_pdf_text_returns_page_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            service = self.make_service(Path(tmp))
            target = service.resolve_project_path("test", "blank.pdf")
            writer = PdfWriter()
            writer.add_blank_page(width=72, height=72)
            with target.open("wb") as handle:
                writer.write(handle)

            result = service.read_pdf_text("test", "blank.pdf")

            self.assertEqual(result["page_count"], 1)
            self.assertEqual(result["pages_read"], [1])
            self.assertEqual(result["content"], "")
            self.assertFalse(result["truncated"])


if __name__ == "__main__":
    unittest.main()
