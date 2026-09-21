"""Focused checks for assessment source classification and metadata extraction."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from digital_professor.course_parsing import (
    classify_document,
    extract_course_details,
    extract_topics,
)


class CourseParsingTests(unittest.TestCase):
    def test_syllabus_number_title_and_semester_variants(self):
        cases = [
            ("EN.553.762 — Sp 2026", "en.553.762", "sp 2026"),
            ("553.762 — Fall 2026", "553.762", "fall 2026"),
            ("553.762 — F 2026", "553.762", "f 2026"),
            ("553.762 — Summer 2026", "553.762", "summer 2026"),
            ("553.762 — Wi 2026", "553.762", "wi 2026"),
        ]
        for course_line, number, semester in cases:
            with self.subTest(course_line=course_line):
                text = (
                    "Nonlinear Optimization II\n"
                    f"{course_line}\n"
                    "1\nCourse overview\n"
                    "This course develops optimization theory and practical methods.\n"
                    "2\nMeetings and course staff\n"
                )
                details = extract_course_details(text)
                self.assertEqual(details.course_name, "Nonlinear Optimization II")
                self.assertEqual(details.course_number, number)
                self.assertEqual(details.semester, semester)
                self.assertEqual(
                    details.course_overview,
                    "This course develops optimization theory and practical methods.",
                )

    def test_course_name_on_same_line_as_number(self):
        details = extract_course_details("en.553.762 Nonlinear Optimization 2\nSpring 2026")
        self.assertEqual(details.course_name, "Nonlinear Optimization 2")

    def test_document_classification_and_heading_fallback(self):
        self.assertEqual(classify_document("", "762_notes.pdf"), "lecture_notes")
        self.assertEqual(classify_document("", "762_syllabus.pdf"), "syllabus")
        self.assertEqual(classify_document("", "handwriting.png", image=True), "handwriting")
        self.assertEqual(
            classify_document(
                "Course information\nInstructor: Dr. Ada\nGrading\nFall 2026",
                "random-upload.pdf",
            ),
            "syllabus",
        )
        self.assertEqual(
            classify_document(
                "Course information\nInstructor: Dr. Ada\nGrading\nFall 2026",
                "wrong-notes.pdf",
            ),
            "syllabus",
        )
        self.assertEqual(
            classify_document("Course overview\nOffice hours\nCourse grade", "upload.pdf"),
            "syllabus",
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "notes.md"
            text = "# Linear Programs\n## Duality\n### Strong duality\n"
            path.write_text(text)
            topics = extract_topics(path, text)
        self.assertEqual([topic.level for topic in topics], [1, 2, 3])
        self.assertEqual([topic.title for topic in topics], ["Linear Programs", "Duality", "Strong duality"])


if __name__ == "__main__":
    unittest.main()
