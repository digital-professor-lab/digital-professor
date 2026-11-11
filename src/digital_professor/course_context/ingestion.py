"""Document ingestion for the integrated local demo.

This module owns normalized pages and stable page/line mappings.  Retrieval
consumes the resulting chunks and never reparses source documents.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4


DocumentType = Literal["syllabus", "lecture_notes", "textbook", "other"]


@dataclass(frozen=True, slots=True)
class SourceUpload:
    filename: str
    media_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class SourceChunk:
    passage_id: str
    document_id: str
    filename: str
    document_type: DocumentType
    content_version: str
    page_number: int
    line_start: int
    line_end: int
    heading: str | None
    text: str


@dataclass(frozen=True, slots=True)
class IngestedDocument:
    document_id: str
    filename: str
    document_type: DocumentType
    content_version: str
    page_count: int
    pages: tuple[tuple[str, ...], ...]
    chunks: tuple[SourceChunk, ...]


@dataclass(frozen=True, slots=True)
class CourseWorkspace:
    course_id: str
    course_name: str
    course_number: str | None
    term: str | None
    overview: str
    topics: tuple[str, ...]
    documents: tuple[IngestedDocument, ...]
    consistency_status: Literal["verified", "partially_verified"]
    consistency_notes: tuple[str, ...]
    status: Literal["published"] = "published"
    course_context: dict | None = None
    course_context_status: str | None = None
    course_context_review: dict | None = None


class IngestionError(ValueError):
    """Structured source-ingestion failure suitable for an API response."""


class DocumentIngestionService:
    """Parse uploaded sources, preserve page lines, and create bounded chunks."""

    def ingest_course(self, uploads: list[SourceUpload]) -> CourseWorkspace:
        if not uploads:
            raise IngestionError("At least one syllabus and one notes file are required.")
        documents = tuple(self._ingest_document(upload) for upload in uploads)
        syllabi = [doc for doc in documents if doc.document_type == "syllabus"]
        knowledge = [
            doc for doc in documents if doc.document_type in {"lecture_notes", "textbook"}
        ]
        if not syllabi:
            raise IngestionError("No syllabus was identified; the course was not published.")
        if not knowledge:
            raise IngestionError(
                "No lecture notes or textbook were identified; add course material before publishing."
            )

        syllabus_text = "\n".join(line for page in syllabi[0].pages for line in page)
        course_number = _course_number(syllabus_text)
        course_name = _course_name(syllabus_text, course_number)
        consistency_status, consistency_notes = _check_course_consistency(
            course_name, course_number, knowledge
        )
        course_id = _slug(course_number or course_name or f"course-{uuid4().hex[:8]}")
        topics = _topics(knowledge)
        return CourseWorkspace(
            course_id=course_id,
            course_name=course_name or "Untitled course",
            course_number=course_number,
            term=_term(syllabus_text),
            overview=_overview(syllabus_text),
            topics=topics,
            documents=documents,
            consistency_status=consistency_status,
            consistency_notes=consistency_notes,
        )

    def _ingest_document(self, upload: SourceUpload) -> IngestedDocument:
        pages = _extract_pages(upload)
        if not any(any(line.strip() for line in page) for page in pages):
            raise IngestionError(f"No embedded text was found in {upload.filename}.")
        content_version = hashlib.sha256(upload.data).hexdigest()[:16]
        document_id = f"document-{uuid4()}"
        doc_type = _classify(upload.filename, pages)
        chunks = _chunk_pages(
            pages, document_id, upload.filename, doc_type, content_version
        )
        return IngestedDocument(
            document_id=document_id,
            filename=upload.filename,
            document_type=doc_type,
            content_version=content_version,
            page_count=len(pages),
            pages=pages,
            chunks=chunks,
        )


def _extract_pages(upload: SourceUpload) -> tuple[tuple[str, ...], ...]:
    suffix = Path(upload.filename).suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(upload.data))
        texts = [page.extract_text() or "" for page in reader.pages]
    elif suffix == ".docx":
        from docx import Document

        document = Document(io.BytesIO(upload.data))
        texts = ["\n".join(paragraph.text for paragraph in document.paragraphs)]
    elif suffix in {".txt", ".md", ".tex", ""}:
        texts = [upload.data.decode("utf-8", errors="replace")]
    else:
        raise IngestionError(
            f"Unsupported file type for {upload.filename}; use PDF, DOCX, TXT, MD, or TEX."
        )
    return tuple(tuple(_normalize_lines(text)) for text in texts)


def _normalize_lines(text: str) -> list[str]:
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = re.sub(r"\s+", " ", raw).strip()
        if line:
            lines.append(line)
    return lines


def _classify(filename: str, pages: tuple[tuple[str, ...], ...]) -> DocumentType:
    text = " ".join(line for page in pages[:5] for line in page).lower()
    name = filename.lower()
    if len(pages) > 300:
        return "textbook"
    syllabus_terms = ("syllabus", "course description", "grading", "office hours")
    if "syllabus" in name or sum(term in text for term in syllabus_terms) >= 2:
        return "syllabus"
    note_terms = ("lecture", "chapter", "theorem", "example", "definition")
    if any(term in name for term in ("note", "lecture", "chapter")) or any(
        term in text for term in note_terms
    ):
        return "lecture_notes"
    return "other"


def _chunk_pages(
    pages: tuple[tuple[str, ...], ...],
    document_id: str,
    filename: str,
    document_type: DocumentType,
    content_version: str,
) -> tuple[SourceChunk, ...]:
    chunks: list[SourceChunk] = []
    for page_number, lines in enumerate(pages, 1):
        start = 0
        while start < len(lines):
            end = start
            chars = 0
            while end < len(lines) and (chars < 1200 or end == start):
                chars += len(lines[end]) + 1
                end += 1
            selected = lines[start:end]
            heading = selected[0] if selected and _looks_like_heading(selected[0]) else None
            passage_id = f"{document_id}:p{page_number}:l{start + 1}-{end}"
            chunks.append(
                SourceChunk(
                    passage_id=passage_id,
                    document_id=document_id,
                    filename=filename,
                    document_type=document_type,
                    content_version=content_version,
                    page_number=page_number,
                    line_start=start + 1,
                    line_end=end,
                    heading=heading,
                    text="\n".join(selected),
                )
            )
            start = end
    return tuple(chunks)


def _looks_like_heading(text: str) -> bool:
    return len(text) <= 100 and (
        bool(re.match(r"^(chapter|section|lecture|unit|\d+(?:\.\d+)*)\b", text, re.I))
        or (text.isupper() and len(text.split()) <= 12)
    )


def _topics(documents: list[IngestedDocument]) -> tuple[str, ...]:
    values: list[str] = []
    for document in documents:
        for chunk in document.chunks:
            if chunk.heading and chunk.heading not in values:
                values.append(chunk.heading)
            if len(values) >= 30:
                return tuple(values)
    if values:
        return tuple(values)
    words: dict[str, int] = {}
    stop = {"this", "that", "with", "from", "have", "will", "your", "into", "using"}
    for document in documents:
        for chunk in document.chunks:
            for word in re.findall(r"[A-Za-z][A-Za-z-]{4,}", chunk.text.lower()):
                if word not in stop:
                    words[word] = words.get(word, 0) + 1
    return tuple(word for word, _ in sorted(words.items(), key=lambda item: -item[1])[:15])


def _course_number(text: str) -> str | None:
    match = re.search(r"\b(?:[a-z]{2}[.\s-]?)?\d{3}[.]\d{3}\b", text, re.I)
    return match.group(0).strip() if match else None


def _course_name(text: str, number: str | None) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if number:
        for index, line in enumerate(lines):
            if number.lower() in line.lower():
                candidate = re.sub(re.escape(number), "", line, flags=re.I).strip(" :-–—")
                if len(candidate) >= 4:
                    return candidate[:160]
                if index + 1 < len(lines):
                    return lines[index + 1][:160]
    return lines[0][:160] if lines else None


def _term(text: str) -> str | None:
    match = re.search(
        r"\b(?:fall|summer|winter|spring|fa|su|wi|sp|f|s|w)\s+20\d{2}\b",
        text,
        re.I,
    )
    return match.group(0) if match else None


def _check_course_consistency(
    course_name: str | None,
    course_number: str | None,
    documents: list[IngestedDocument],
) -> tuple[Literal["verified", "partially_verified"], tuple[str, ...]]:
    """Reject explicit conflicts and retain uncertainty when identity is absent."""
    expected_number = _canonical_course_number(course_number)
    expected_tokens = _identity_tokens(course_name)
    verified: list[str] = []
    uncertain: list[str] = []
    conflicts: list[str] = []
    for document in documents:
        header_lines = [line for page in document.pages[:5] for line in page][:25]
        head = "\n".join(header_lines)
        observed_number = _course_number(head)
        observed_title = _explicit_course_title(head, observed_number)
        observed_tokens = _identity_tokens(observed_title)
        if expected_number and observed_number:
            if expected_number != _canonical_course_number(observed_number):
                conflicts.append(
                    f"{document.filename} identifies course {observed_number}, "
                    f"but the syllabus identifies {course_number}."
                )
            else:
                verified.append(f"{document.filename}: matching course number")
            continue
        if expected_tokens and observed_tokens:
            if expected_tokens.isdisjoint(observed_tokens):
                conflicts.append(
                    f"{document.filename} identifies '{observed_title}', "
                    f"which does not match syllabus course '{course_name}'."
                )
            else:
                verified.append(f"{document.filename}: matching course title signal")
            continue
        uncertain.append(
            f"{document.filename}: no explicit course number or course-title signal; "
            "included with review recommended"
        )
    if conflicts:
        raise IngestionError(
            "Course-material consistency check failed: " + " ".join(conflicts)
        )
    notes = tuple(verified + uncertain)
    return ("partially_verified" if uncertain else "verified"), notes


def _canonical_course_number(value: str | None) -> str | None:
    return re.sub(r"[^a-z0-9]", "", value.lower()) if value else None


def _explicit_course_title(text: str, number: str | None) -> str | None:
    for line in (item.strip() for item in text.splitlines()[:20] if item.strip()):
        lowered = line.lower()
        if lowered.startswith(("this course", "course description", "course overview")):
            continue
        if number and number.lower() in lowered:
            candidate = re.sub(re.escape(number), "", line, flags=re.I).strip(" :-–—")
            if len(candidate) >= 4:
                return candidate[:160]
        if len(line) <= 120 and re.search(r"\b(course|lecture notes|class)\b", line, re.I):
            candidate = re.sub(
                r"\b(course|lecture notes|class|syllabus)\b", " ", line, flags=re.I
            )
            candidate = re.sub(r"\s+", " ", candidate).strip(" :-–—")
            if len(candidate) >= 4:
                return candidate[:160]
    return None


def _identity_tokens(value: str | None) -> set[str]:
    if not value:
        return set()
    ignored = {
        "and", "the", "for", "with", "introduction", "introductory", "advanced",
        "course", "lecture", "notes", "class", "fall", "spring", "summer", "winter",
    }
    return {
        token
        for token in re.findall(r"[a-z][a-z0-9]+", value.lower())
        if token not in ignored and not token.isdigit()
    }


def _overview(text: str) -> str:
    match = re.search(
        r"(?:course\s+(?:description|overview))\s*[:\-]?\s*(.{80,1200}?)(?=\n[A-Z][^\n]{2,60}\n|$)",
        text,
        re.I | re.S,
    )
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip()
    return re.sub(r"\s+", " ", text).strip()[:800]


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or f"course-{uuid4().hex[:8]}"
