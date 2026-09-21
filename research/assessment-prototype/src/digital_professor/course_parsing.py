"""Conservative, course-agnostic classification and outline extraction."""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf
from pydantic import BaseModel, Field


COURSE_NUMBER = re.compile(r"(?<![a-z0-9])(?:[a-z]{2}\.)?\d{3}\.\d{3}(?![a-z0-9])", re.I)
SEMESTER = re.compile(
    r"\b(fall|summer|winter|spring|fa|su|wi|sp|f|s|w)\s*[-,]?\s*(20\d{2})\b",
    re.I,
)
OVERVIEW_HEADING = re.compile(
    r"^(?:\d+[.)]?\s*)?(?:course\s+)?(?:overview|description|about\s+the\s+course)\s*:?$",
    re.I,
)
SECTION_HEADING = re.compile(r"^(?:\d+[.)]?\s*)?(?:meetings|course\s+staff|personnel|lecture\s+sequence|homework|assignments|assessment|course\s+grade|grading|reading|textbook|policies)\b", re.I)
TEXT_HEADING = re.compile(r"^(?P<number>\d+(?:\.\d+)*)(?:[.)]|\s)\s*(?P<title>[A-Za-z][^\n]{2,100})$")


class CourseDetails(BaseModel):
    course_name: str | None = None
    course_number: str | None = None
    semester: str | None = None
    course_overview: str | None = None


class TopicEntry(BaseModel):
    title: str
    level: int = Field(ge=1)
    section_number: str | None = None
    page_number: int | None = Field(default=None, ge=1)


def _clean_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip() and not re.fullmatch(r"\[PAGE \d+\]", line.strip(), re.I)]


def classify_document(text: str, filename: str, *, image: bool = False) -> str:
    """Use document content first, with its filename as a fallback."""
    opening = text[:12000].lower()
    syllabus_signals = sum(
        marker in opening
        for marker in (
            "syllabus", "course overview", "course description", "course information",
            "instructor", "office hours", "grading", "course policies",
            "learning outcomes", "prerequisites", "required textbook",
        )
    )
    notes_signals = sum(
        marker in opening
        for marker in ("lecture notes", "chapter 1", "chapter 2", "contents", "1.1", "1.2")
    )
    if syllabus_signals >= 2 and syllabus_signals > notes_signals:
        return "syllabus"
    if notes_signals >= 2 and notes_signals > syllabus_signals:
        return "lecture_notes"
    if COURSE_NUMBER.search(opening) and SEMESTER.search(opening) and syllabus_signals:
        return "syllabus"
    name = filename.lower()
    if "syllabus" in name or "syllabi" in name:
        return "syllabus"
    if any(token in name for token in ("lecture", "notes", "slides")):
        return "lecture_notes"
    return "handwriting" if image else "document"


def extract_textbook_name(path: str | Path, text: str) -> str | None:
    """Prefer a meaningful PDF title, then the first plausible title-page line."""
    source = Path(path)
    if source.suffix.lower() == ".pdf":
        with pymupdf.open(source) as document:
            metadata_title = (document.metadata or {}).get("title") or ""
        title = metadata_title.strip(" -–—:|")
        if (
            4 <= len(title) <= 160
            and re.search(r"[a-z]{3}", title, re.I)
            and not re.search(r"^(untitled|document|microsoft|adobe|pdf|scan|image|latex|tex)\b", title, re.I)
        ):
            return title

    for line in _clean_lines(text)[:30]:
        candidate = re.sub(r"^(?:title|book title)\s*:\s*", "", line, flags=re.I).strip(" -–—:|")
        if (
            5 <= len(candidate) <= 130
            and re.search(r"[a-z]{3}", candidate, re.I)
            and not re.search(
                r"^(copyright|all rights reserved|isbn|doi|edition|volume|chapter|contents|preface|author|by |published|publisher|http|www\.)\b",
                candidate,
                re.I,
            )
            and not re.fullmatch(r"\d+", candidate)
        ):
            return candidate
    return None


def _nearby_course_name(lines: list[str], code_index: int) -> str | None:
    for offset in (0, -1, 1, -2, 2):
        index = code_index + offset
        if not 0 <= index < len(lines):
            continue
        candidate = COURSE_NUMBER.sub("", lines[index])
        candidate = SEMESTER.sub("", candidate).strip(" -–—:|,.")
        if (
            4 <= len(candidate) <= 100
            and re.search(r"[a-z]{3}", candidate, re.I)
            and not re.search(r"syllabus|adapted|instructor|office|copyright|page\s+\d", candidate, re.I)
        ):
            return candidate
    return None


def _join_paragraph(lines: list[str]) -> str:
    result = ""
    for line in lines:
        if result.endswith("-") and line[:1].islower():
            result = (result if result.split()[-1].lower() in {"bound-"} else result[:-1]) + line
        else:
            result += (" " if result else "") + line
    return result.strip()


def _course_overview(lines: list[str]) -> str | None:
    for index, line in enumerate(lines[:100]):
        if not OVERVIEW_HEADING.fullmatch(line):
            continue
        body: list[str] = []
        for following in lines[index + 1 :]:
            if body and (SECTION_HEADING.match(following) or re.fullmatch(r"\d{1,2}", following)):
                break
            if SECTION_HEADING.match(following) or re.fullmatch(r"\d{1,2}", following):
                continue
            body.append(following)
            if len(" ".join(body)) > 2500:
                break
        overview = _join_paragraph(body)
        return overview or None
    return None


def extract_course_details(text: str) -> CourseDetails:
    """Match in lowercase while retaining the source's course-title capitalization."""
    lines = _clean_lines(text)
    opening = lines[:80]
    code_match = next(
        ((index, match) for index, line in enumerate(opening) if (match := COURSE_NUMBER.search(line))),
        None,
    )
    semester_match = SEMESTER.search("\n".join(opening))
    return CourseDetails(
        course_name=_nearby_course_name(opening, code_match[0]) if code_match else None,
        course_number=code_match[1].group(0).lower() if code_match else None,
        semester=" ".join(semester_match.groups()).lower() if semester_match else None,
        course_overview=_course_overview(lines),
    )


def extract_topics(path: str | Path, text: str) -> list[TopicEntry]:
    """Use PDF bookmarks when present; otherwise extract obvious text headings."""
    source = Path(path)
    if source.suffix.lower() == ".pdf":
        with pymupdf.open(source) as document:
            outline = document.get_toc()
        if outline:
            counters: list[int] = []
            topics: list[TopicEntry] = []
            for level, title, page in outline:
                while len(counters) < level:
                    counters.append(0)
                counters = counters[:level]
                counters[-1] += 1
                topics.append(
                    TopicEntry(
                        title=title.strip(),
                        level=level,
                        section_number=".".join(str(number) for number in counters),
                        page_number=page or None,
                    )
                )
            return topics

    topics = []
    page_number: int | None = None
    for raw in text.splitlines():
        line = raw.strip()
        page_marker = re.fullmatch(r"\[PAGE (\d+)\]", line, re.I)
        if page_marker:
            page_number = int(page_marker.group(1))
            continue
        latex_heading = re.match(r"\\(section|subsection|subsubsection)\*?\{([^}]+)\}", line)
        markdown_heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        numbered_heading = TEXT_HEADING.match(line)
        if latex_heading:
            level = {"section": 1, "subsection": 2, "subsubsection": 3}[latex_heading.group(1)]
            title, number = latex_heading.group(2), None
        elif markdown_heading:
            level, title, number = len(markdown_heading.group(1)), markdown_heading.group(2), None
        elif numbered_heading:
            number, title = numbered_heading.group("number"), numbered_heading.group("title")
            level = number.count(".") + 1
        else:
            continue
        if re.search(r"\.\s*\.\s*\.", title) or len(title) > 100:
            continue
        topics.append(TopicEntry(title=title.strip(), level=level, section_number=number, page_number=page_number))
    return topics
