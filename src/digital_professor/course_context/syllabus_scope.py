"""Syllabus scope: which pages of a textbook the course actually uses.

A syllabus usually lists the textbook sections it covers ("4.5 The Chain Rule", "Chapter 1"). Ingesting
and embedding the whole book costs time and memory for chapters the course never reaches. This module
reads the syllabus list, finds each entry in the PDF's own table of contents, and returns the pages to
ingest. Page numbers are not changed: pages outside the scope are simply left empty, so every citation
still points at the right page of the original file.

Entries are matched by **title first**. Section numbers often differ between editions (the JHU 110.106
syllabus follows the 4th edition, where the Chain Rule is 4.5; in the 3rd edition it is 4.4, and 4.5 is
trigonometric derivatives), so a number alone would pull in the wrong section. A number is used only for
an entry with no title, or when the numbered section shares a word with the entry's title.

The scope is applied only when it is trustworthy: the PDF has a table of contents, it is book-sized, and
most syllabus entries were found. Otherwise the whole document is ingested, as before, and the reason is
recorded.

The feature is **off by default** (the whole textbook is ingested, as in Retrieval V1). Set
``DP_TEXTBOOK_SCOPE=on`` to enable it.
"""

from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

MIN_PAGES = 100            # smaller files are ingested whole; scoping them saves little
MIN_MATCHED_SHARE = 0.6    # below this share of syllabus entries found, the scope is not trusted

_NUMBER = re.compile(r"^(\d{1,2})\.(\d{1,2})(?![\d.])\s*(.*)$")
_CHAPTER = re.compile(r"^chapters?\s+(\d{1,2})(?:\s*(?:-|–|to)\s*(\d{1,2}))?\b\s*(.*)$", re.IGNORECASE)
_REFERENCE = re.compile(r"(?<![\d.])(\d{1,2}\.\d{1,2})(?![\d.])")
_BULLET = re.compile(r"^[o•▪◦·\-–*]+\s*")
_TOC_NUMBER = re.compile(r"^(\d{1,2})(?:\.(\d{1,2}))?(?:\.(\d{1,2}))?\s+(.*)$")
_STOP = frozenset("a an and the of with from to for in on at by its their some more about using its "
                  "optional part".split())


def scope_enabled() -> bool:
    """Off unless ``DP_TEXTBOOK_SCOPE`` is on (on, 1, true, yes)."""
    return os.getenv("DP_TEXTBOOK_SCOPE", "off").strip().lower() in {"on", "1", "true", "yes"}


@dataclass(frozen=True, slots=True)
class ScopeEntry:
    """One line of the syllabus topic list."""

    number: str | None          # "4.5", or None for a chapter entry
    chapter: int | None         # set for "Chapter 1" entries
    chapter_end: int | None
    title: str                  # without the parenthetical part
    references: tuple[str, ...] = ()    # other sections named in the line ("formal definition from 3.6")
    reference_text: str = ""

    @property
    def label(self) -> str:
        if self.chapter is not None:
            return f"Chapter {self.chapter}" + (f"–{self.chapter_end}" if self.chapter_end else "")
        return " ".join(filter(None, [self.number, self.title]))


@dataclass(frozen=True, slots=True)
class TocEntry:
    title: str
    level: int
    page: int                   # first page, 1-based, as in the file
    end: int                    # last page, inclusive
    chapter: int | None
    number: str | None          # "4.4" for a section, "4" for a chapter, "4.4.2" for a subsection


@dataclass(slots=True)
class ScopePlan:
    """The pages to ingest, or ``pages=None`` with the reason the whole document is used."""

    pages: frozenset[int] | None
    total_pages: int
    reason: str = ""
    matched: list[dict[str, Any]] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)

    @property
    def applied(self) -> bool:
        return self.pages is not None

    def summary(self) -> dict[str, Any]:
        return {"applied": self.applied, "total_pages": self.total_pages,
                "indexed_pages": len(self.pages) if self.pages is not None else self.total_pages,
                "reason": self.reason, "matched": list(self.matched), "unmatched": list(self.unmatched)}

    def note(self) -> str:
        """One line for people: what was ingested and why."""
        if self.applied:
            found = len(self.matched)
            return (f"syllabus scope: {len(self.pages)} of {self.total_pages} pages "
                    f"({found} of {found + len(self.unmatched)} syllabus entries found)")
        return f"whole document ingested ({self.reason})"


# ---------------------------------------------------------------------------
# Reading the syllabus
# ---------------------------------------------------------------------------

def parse_syllabus_scope(text: str) -> list[ScopeEntry]:
    """The textbook sections a syllabus lists. Text extracted from a PDF often puts the number and the
    title on separate lines ("4.5" / "The Chain Rule"); both layouts are read."""
    lines = [_BULLET.sub("", " ".join(raw.split())) for raw in text.splitlines()]
    lines = [line for line in lines if line and line.lower() not in {"o", "•"}]
    entries: list[ScopeEntry] = []
    for index, line in enumerate(lines):
        chapter = _CHAPTER.match(line)
        if chapter:
            start = int(chapter.group(1))
            end = int(chapter.group(2)) if chapter.group(2) else None
            entries.append(ScopeEntry(None, start, end if end and end > start else None, chapter.group(3).strip()))
            continue
        numbered = _NUMBER.match(line)
        if not numbered:
            continue
        title = numbered.group(3).strip()
        if not title and index + 1 < len(lines) and not (_NUMBER.match(lines[index + 1])
                                                          or _CHAPTER.match(lines[index + 1])):
            title = lines[index + 1]
        if not re.search(r"[A-Za-z]", title):
            continue                       # "10.30" with no title is a time or a figure, not a section
        extra = re.findall(r"\(([^)]*)\)", title)
        plain = re.sub(r"\([^)]*\)", " ", title)
        refs = tuple(r for part in extra for r in _REFERENCE.findall(part))
        entries.append(ScopeEntry(f"{numbered.group(1)}.{numbered.group(2)}", None, None, " ".join(plain.split()),
                                  refs, " ".join(extra)))
    return entries


# ---------------------------------------------------------------------------
# Reading the textbook's table of contents
# ---------------------------------------------------------------------------

def read_toc(pdf_bytes: bytes) -> tuple[list[TocEntry], int]:
    """The PDF outline as flat entries with page ranges, and the page count. Empty when there is none."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    total = len(reader.pages)
    raw: list[tuple[str, int, int]] = []

    def walk(items: list[Any], level: int) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item, level + 1)
                continue
            try:
                page = reader.get_destination_page_number(item) + 1
            except Exception:
                continue
            title = " ".join(str(getattr(item, "title", "") or "").split())
            if title and page >= 1:
                raw.append((title, level, page))

    try:
        walk(reader.outline, 1)
    except Exception:
        return [], total
    entries: list[TocEntry] = []
    for index, (title, level, page) in enumerate(raw):
        # A range ends where the next entry at the same or a higher level starts (that page is shared).
        end = total
        for later_title, later_level, later_page in raw[index + 1:]:
            if later_level <= level and later_page >= page:
                end = max(page, later_page)
                break
        match = _TOC_NUMBER.match(title)
        number = None
        chapter = None
        if match:
            parts = [p for p in match.group(1, 2, 3) if p]
            number = ".".join(parts)
            chapter = int(parts[0])
        entries.append(TocEntry(title, level, page, end, chapter, number))
    return entries, total


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _tokens(text: str) -> list[str]:
    words = re.sub(r"[’'`]", "", text.lower())
    words = re.sub(r"^\d+(?:\.\d+)*\s+", "", words)
    return [w for w in re.findall(r"[a-z]+", words) if w not in _STOP and len(w) > 1]


def _same_word(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) >= 5 and len(b) >= 5 and a[:5] == b[:5]:
        return True                                   # extreme / extrema, theorems / theorem
    return min(len(a), len(b)) >= 6 and SequenceMatcher(None, a, b).ratio() >= 0.8   # hopital / hospital


def _overlap(entry_words: list[str], toc_words: list[str]) -> int:
    return sum(any(_same_word(w, t) for t in toc_words) for w in entry_words)


def _best_by_title(entry: ScopeEntry, sections: list[TocEntry]) -> TocEntry | None:
    words = _tokens(entry.title)
    if not words:
        return None
    best: tuple[float, float, int, TocEntry] | None = None
    for section in sections:
        toc_words = _tokens(section.title)
        hits = _overlap(words, toc_words)
        if not hits:
            continue
        coverage = hits / len(words)
        precision = hits / max(len(toc_words), 1)
        same_chapter = int(entry.number is not None and section.chapter == int(entry.number.split(".")[0]))
        key = (coverage, precision, same_chapter, section)
        if best is None or key[:3] > best[:3]:
            best = key
    if best is None or best[0] < 0.5 or (best[0] < 1.0 and len(words) == 1):
        return None
    # "Rule" alone matches many sections: a weak match must at least stay in the syllabus chapter.
    if best[0] < 0.75 and not best[2]:
        return None
    return best[3]


def _by_number(number: str, sections: list[TocEntry]) -> TocEntry | None:
    return next((s for s in sections if s.number == number), None)


def plan_textbook_scope(pdf_bytes: bytes, entries: list[ScopeEntry]) -> ScopePlan:
    """The pages of a textbook PDF that the syllabus entries cover."""
    try:
        toc, total = read_toc(pdf_bytes)
    except Exception as error:                        # an unreadable outline never stops ingestion
        return ScopePlan(None, 0, f"the table of contents could not be read: {type(error).__name__}")
    if total < MIN_PAGES:
        return ScopePlan(None, total, f"the file has {total} pages, fewer than {MIN_PAGES}")
    if not entries:
        return ScopePlan(None, total, "the syllabus lists no textbook sections")
    numbered = [t for t in toc if t.number]
    if not numbered:
        return ScopePlan(None, total, "the PDF has no table of contents with numbered sections")
    sections = [t for t in numbered if "." in t.number]
    chapters = {t.chapter: t for t in numbered if "." not in t.number}

    pages: set[int] = set()
    matched: list[dict[str, Any]] = []
    unmatched: list[str] = []

    def take(entry_label: str, toc_entry: TocEntry, how: str) -> None:
        # A syllabus section is a whole section in its own edition. When the title matched a subsection
        # here ("4.4.1 The Chain Rule"), take the whole section ("4.4"), so neighbouring material in the
        # same section (related rates, logarithmic derivatives) is not lost.
        if toc_entry.number and toc_entry.number.count(".") >= 2:
            parent = _by_number(".".join(toc_entry.number.split(".")[:2]), sections)
            if parent is not None:
                how = f"{how}, via {toc_entry.title}"
                toc_entry = parent
        pages.update(range(toc_entry.page, toc_entry.end + 1))
        matched.append({"syllabus": entry_label, "textbook": toc_entry.title,
                        "pages": f"{toc_entry.page}-{toc_entry.end}", "by": how})

    for entry in entries:
        if entry.chapter is not None:
            found = [chapters.get(c) for c in range(entry.chapter, (entry.chapter_end or entry.chapter) + 1)]
            if all(found):
                for chapter_entry in found:
                    take(entry.label, chapter_entry, "chapter")
            else:
                unmatched.append(entry.label)
            continue
        hit = _best_by_title(entry, sections)
        how = "title"
        if hit is None:
            candidate = _by_number(entry.number, sections) if entry.number else None
            if candidate is not None and (not _tokens(entry.title)
                                          or _overlap(_tokens(entry.title), _tokens(candidate.title))):
                hit, how = candidate, "number"
        if hit is None:
            unmatched.append(entry.label)
            continue
        take(entry.label, hit, how)
        for reference in entry.references:            # "with formal definition from 3.6"
            candidate = _by_number(reference, sections)
            if candidate is not None and _overlap(_tokens(entry.reference_text), _tokens(candidate.title)):
                take(f"{entry.label} (refers to {reference})", candidate, "reference")

    share = (len(entries) - len(unmatched)) / len(entries)
    if share < MIN_MATCHED_SHARE:
        return ScopePlan(None, total, f"only {len(entries) - len(unmatched)} of {len(entries)} syllabus entries "
                         "were found in the table of contents", matched, unmatched)
    if len(pages) >= total * 0.95:
        return ScopePlan(None, total, "the syllabus covers almost the whole book", matched, unmatched)
    return ScopePlan(frozenset(pages), total, "", matched, unmatched)
