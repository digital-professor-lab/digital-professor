"""Upload behavior with a generic filename and a mocked model fallback."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import pymupdf

from digital_professor.config import Settings
from digital_professor.course_parsing import CourseDetails
from digital_professor.source_analysis import SourceAnalysis
from webapp.backend.app import app, sources


class SourceUploadTests(unittest.TestCase):
    def tearDown(self):
        sources.clear()

    def test_generic_upload_uses_content_model_when_rules_cannot_extract(self):
        settings = Settings(
            openai_api_key="test-key",
            openai_model="gpt-4o",
            render_dpi=180,
            max_pages=5,
            input_cost_per_1m=None,
            output_cost_per_1m=None,
        )
        analysis = SourceAnalysis(
            document_type="syllabus",
            course=CourseDetails(
                course_name="Structural Analysis",
                course_number="en.560.601",
                semester="fall 2026",
                course_overview="Methods for analyzing structures.",
            ),
        )
        metadata = {
            "model": "gpt-4o",
            "elapsed_seconds": 0.1,
            "input_tokens": 20,
            "output_tokens": 30,
            "total_tokens": 50,
            "estimated_cost_usd": None,
        }
        with patch("webapp.backend.app.current_settings", return_value=settings), patch(
            "webapp.backend.app.analyze_source_text", return_value=(analysis, metadata)
        ) as fallback:
            response = TestClient(app).post(
                "/api/sources",
                files={"file": ("arbitrary-name.txt", b"Welcome to the class. Methods for analyzing structures.", "text/plain")},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["source_type"], "syllabus")
        self.assertEqual(response.json()["course"]["course_name"], "Structural Analysis")
        self.assertIsNone(response.json()["analysis_warning"])
        fallback.assert_called_once()

    def test_large_pdf_is_textbook_with_its_own_title(self):
        document = pymupdf.open()
        document.set_metadata({"title": "Probability and Statistics for Engineers"})
        first_page = document.new_page()
        first_page.insert_text((72, 72), "Probability and Statistics for Engineers")
        first_page.insert_text((72, 96), "A comprehensive introduction to probability models and statistical methods")
        for _ in range(300):
            document.new_page()
        data = document.tobytes()
        document.close()

        response = TestClient(app).post(
            "/api/sources",
            files={"file": ("anything.pdf", data, "application/pdf")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["source_type"], "textbook")
        self.assertEqual(response.json()["page_count"], 301)
        self.assertEqual(response.json()["textbook_name"], "Probability and Statistics for Engineers")

        override = TestClient(app).post(
            "/api/sources",
            files={"file": ("anything.pdf", data, "application/pdf")},
            data={"source_type": "document"},
        )
        self.assertEqual(override.status_code, 200, override.text)
        self.assertEqual(override.json()["source_type"], "document")


if __name__ == "__main__":
    unittest.main()
