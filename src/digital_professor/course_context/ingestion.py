"""Document ingestion for the integrated local demo.

This module owns normalized pages and stable page/line mappings.  Retrieval
consumes the resulting chunks and never reparses source documents.

Stage B pipeline (deterministic, no LLM):
  1. _extract_pages   – raw text per page (PDF / DOCX / TXT / MD / TEX)
  2. _segment_blocks  – heuristic semantic segmentation: chapter → section →
                        typed block (theorem, definition, example, …)
  3. tag_blocks_with_concepts – name-match against CourseContext Concept list;
                        called separately after CourseContext is available
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, replace as dc_replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal
from uuid import uuid4


DocumentType = Literal["syllabus", "lecture_notes", "textbook", "other"]

# Aligns with Sean's schema (rag-retrieval ingestion-handoff v1.0).
# "theorem" covers lemma/corollary/proposition (printed name goes in label).
BlockType = Literal[
    "definition", "theorem", "formula", "proof",
    "example", "exercise", "solution",
    "explanation", "remark", "summary", "figure", "table", "other",
]

ConceptSource = Literal["section", "model", "human", "none"]
Visibility = Literal["student_visible", "engine_only"]


@dataclass(frozen=True, slots=True)
class SourceUpload:
    filename: str
    media_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class IngestedBlock:
    block_id: str
    document_id: str
    filename: str
    document_type: DocumentType
    content_version: str
    chapter_id: str | None
    section_id: str | None
    block_type: BlockType
    concept_ids: tuple[str, ...]
    concept_source: ConceptSource
    visibility: Visibility
    page_number: int      # page where this block starts (and ends — single-page blocks)
    page_end: int         # same as page_number; reserved for future multi-page blocks
    line_start: int
    line_end: int
    heading: str | None   # full heading line detected as block boundary
    label: str | None     # printed label, e.g. "Theorem 4.5.2 (Chain rule)"
    text: str
    provenance: str

    # Keep passage_id as an alias so the retrieval index keeps working unchanged.
    @property
    def passage_id(self) -> str:
        return self.block_id


# Backward-compatible alias used by the retrieval index.
SourceChunk = IngestedBlock


@dataclass(frozen=True, slots=True)
class IngestedDocument:
    document_id: str
    filename: str
    media_type: str
    document_type: DocumentType
    content_version: str   # first 16 hex chars of SHA-256
    file_sha256: str       # full 64 hex char SHA-256 of original upload
    title: str
    page_count: int
    pages: tuple[tuple[str, ...], ...]
    chunks: tuple[IngestedBlock, ...]


@dataclass(frozen=True, slots=True)
class CourseWorkspace:
    course_id: str
    course_name: str
    course_number: str | None
    term: str | None
    overview: str
    topics: tuple[str, ...]
    documents: tuple[IngestedDocument, ...]
    consistency_status: Literal["verified", "partially_verified", "override_confirmed"]
    consistency_notes: tuple[str, ...]
    status: Literal["published"] = "published"
    course_context: dict | None = None
    course_context_status: str | None = None
    course_context_review: dict | None = None


class IngestionError(ValueError):
    """Structured source-ingestion failure suitable for an API response."""


class CourseConsistencyError(IngestionError):
    """A suspected cross-course upload that requires explicit confirmation."""

    def __init__(self, conflicts: tuple[str, ...]) -> None:
        self.conflicts = conflicts
        super().__init__("Course-material consistency check failed: " + " ".join(conflicts))


# ---------------------------------------------------------------------------
# Structural detection patterns
# ---------------------------------------------------------------------------

_RE_CHAPTER = re.compile(
    r"^\s*(?:chapter|ch\.?)\s+(\d+)[\s.:–\-]+(.{0,120})",
    re.I,
)
_RE_SECTION = re.compile(
    r"^\s*(?:section\s+)?(\d+\.\d+(?:\.\d+)?)[\s.:–\-]+(.{0,120})"
)
_RE_APPENDIX = re.compile(r"^\s*appendix\s+([A-Z])[\s.:–\-]+(.{0,120})", re.I)

# Maps leading keyword → block type.  Ordered: longer / more-specific first.
_BLOCK_PATTERNS: list[tuple[re.Pattern[str], BlockType]] = [
    (re.compile(r"^\s*(?:definition|defn?)[\s.:]", re.I), "definition"),
    (re.compile(r"^\s*theorem[\s.:]", re.I), "theorem"),
    (re.compile(r"^\s*lemma[\s.:]", re.I), "theorem"),
    (re.compile(r"^\s*corollary[\s.:]", re.I), "theorem"),
    (re.compile(r"^\s*proposition[\s.:]", re.I), "theorem"),
    (re.compile(r"^\s*example[\s.:]", re.I), "example"),
    (re.compile(r"^\s*(?:exercise|problem|practice)[\s.:]", re.I), "exercise"),
    (re.compile(r"^\s*proof[\s.:]", re.I), "proof"),
    (re.compile(r"^\s*(?:remark|note|observation)[\s.:]", re.I), "remark"),
]

# Maximum accumulated characters before forcing a block flush (safety valve for
# pages with no structural headings, e.g. a 1500-word prose section).
_MAX_BLOCK_CHARS = 1400


def _detect_block_type(line: str) -> BlockType | None:
    for pattern, btype in _BLOCK_PATTERNS:
        if pattern.match(line):
            return btype
    return None


# ---------------------------------------------------------------------------
# Structure tracker (mutable; lives for one document's segmentation pass)
# ---------------------------------------------------------------------------

@dataclass
class _StructureTracker:
    chapter_num: int = 0
    chapter_slug: str = ""
    section_str: str = ""
    block_num: int = 0

    @property
    def chapter_id(self) -> str | None:
        return f"ch{self.chapter_num}" if self.chapter_num else None

    @property
    def section_id(self) -> str | None:
        return self.section_str or None

    def new_chapter(self, num: int, title: str) -> None:
        self.chapter_num = num
        self.chapter_slug = _slug(title)[:24] if title.strip() else f"ch{num}"
        self.section_str = ""
        self.block_num = 0

    def new_section(self, section: str) -> None:
        self.section_str = section
        self.block_num = 0

    def next_block(self) -> int:
        self.block_num += 1
        return self.block_num


# ---------------------------------------------------------------------------
# Block segmentation
# ---------------------------------------------------------------------------

def _make_block_id(doc_prefix: str, tracker: _StructureTracker,
                   page_number: int, block_num: int) -> str:
    if tracker.chapter_id and tracker.section_id:
        return f"{doc_prefix}.{tracker.chapter_id}.s{tracker.section_str}.b{block_num:02d}"
    if tracker.chapter_id:
        return f"{doc_prefix}.{tracker.chapter_id}.pg{page_number}.b{block_num:02d}"
    return f"{doc_prefix}.pg{page_number}.b{block_num:02d}"


_LABELED_BLOCK_TYPES = {
    "theorem", "definition", "example", "exercise", "proof",
    "remark", "formula", "solution",
}


def _extract_label(heading: str | None, block_type: str) -> str | None:
    """Return the printed label for labeled block types; None for structural headings."""
    if heading and block_type in _LABELED_BLOCK_TYPES:
        return heading.strip()
    return None


def _segment_page(
    page_number: int,
    lines: tuple[str, ...],
    tracker: _StructureTracker,
    document_id: str,
    filename: str,
    doc_type: DocumentType,
    content_version: str,
    doc_prefix: str,
) -> Iterator[IngestedBlock]:
    """Yield IngestedBlocks for one page, updating tracker in-place."""
    pending: list[str] = []
    block_start: int = 1
    current_type: BlockType = "explanation"
    current_heading: str | None = None

    def _flush(end_line: int) -> IngestedBlock | None:
        text = "\n".join(pending)
        if not text.strip():
            return None
        bnum = tracker.next_block()
        bid = _make_block_id(doc_prefix, tracker, page_number, bnum)
        return IngestedBlock(
            block_id=bid,
            document_id=document_id,
            filename=filename,
            document_type=doc_type,
            content_version=content_version,
            chapter_id=tracker.chapter_id,
            section_id=tracker.section_id,
            block_type=current_type,
            concept_ids=(),           # filled later by tag_blocks_with_concepts
            concept_source="none",    # updated by tag_blocks_with_concepts
            visibility="student_visible",
            page_number=page_number,
            page_end=page_number,     # single-page blocks; reserved for future multi-page
            line_start=block_start,
            line_end=end_line,
            heading=current_heading,
            label=_extract_label(current_heading, current_type),
            text=text,
            provenance="source_document",
        )

    for idx, line in enumerate(lines, 1):
        chapter_m = _RE_CHAPTER.match(line)
        section_m = _RE_SECTION.match(line)
        btype = _detect_block_type(line)
        is_boundary = bool(chapter_m or section_m or btype)
        is_too_big = sum(len(l) for l in pending) > _MAX_BLOCK_CHARS

        if pending and (is_boundary or is_too_big):
            block = _flush(idx - 1)
            if block:
                yield block
            pending = []
            current_heading = None
            current_type = "explanation"
            block_start = idx

        if chapter_m:
            tracker.new_chapter(int(chapter_m.group(1)), chapter_m.group(2))
        elif section_m:
            tracker.new_section(section_m.group(1))

        if is_boundary:
            current_type = btype or "explanation"
            current_heading = line
            block_start = idx

        pending.append(line)

    if pending:
        block = _flush(len(lines))
        if block:
            yield block


def _segment_blocks(
    pages: tuple[tuple[str, ...], ...],
    document_id: str,
    filename: str,
    doc_type: DocumentType,
    content_version: str,
    doc_prefix: str,
) -> tuple[IngestedBlock, ...]:
    tracker = _StructureTracker()
    blocks: list[IngestedBlock] = []
    for page_number, page_lines in enumerate(pages, 1):
        blocks.extend(
            _segment_page(
                page_number, page_lines, tracker,
                document_id, filename, doc_type, content_version, doc_prefix,
            )
        )
    return tuple(blocks)


# ---------------------------------------------------------------------------
# Concept tagging (deterministic name matching, no LLM)
# ---------------------------------------------------------------------------

def build_concept_index(cc: dict) -> list[tuple[re.Pattern[str], str]]:
    """Build (pattern, concept_id) pairs from Concept.name entries in a CourseContext."""
    index: list[tuple[re.Pattern[str], str]] = []
    seen: set[str] = set()
    for concept in cc.get("Concept", []):
        name: str = (concept.get("name") or "").strip()
        cid: str = (concept.get("id") or "").strip()
        if not (name and cid and cid not in seen):
            continue
        seen.add(cid)
        # Allow flexible whitespace/hyphen between words (e.g. "u-substitution")
        escaped = re.escape(name)
        flexible = re.sub(r"\\ ", r"[\\s\\-]+", escaped)
        try:
            index.append((re.compile(r"\b" + flexible + r"\b", re.I), cid))
        except re.error:
            pass
    return index


def _match_concepts(
    text: str,
    heading: str | None,
    index: list[tuple[re.Pattern[str], str]],
) -> tuple[str, ...]:
    full = f"{heading or ''} {text}"
    matched: list[str] = []
    seen: set[str] = set()
    for pattern, cid in index:
        if cid not in seen and pattern.search(full):
            matched.append(cid)
            seen.add(cid)
    return tuple(matched)


def tag_blocks_with_concepts(workspace: CourseWorkspace, cc: dict) -> CourseWorkspace:
    """Return a new CourseWorkspace with concept_ids filled in on every block.

    Two-pass approach:
      Pass 1 — name matching: tag blocks whose heading/text contains a concept name.
      Pass 2 — section propagation: untagged blocks that share a (chapter_id,
                section_id) with at least one tagged block inherit those concept_ids.
                This ensures theorem/example blocks inside a tagged section are
                in-scope even when their heading doesn't mention the concept name.

    Called after CourseContext is available (dependency: CC must exist first).
    """
    index = build_concept_index(cc)
    if not index:
        return workspace

    new_docs: list[IngestedDocument] = []
    for doc in workspace.documents:
        # Pass 1: name matching — tag blocks whose heading/text contains a concept name
        pass1 = [
            dc_replace(
                block,
                concept_ids=_match_concepts(block.text, block.heading, index),
                concept_source="section",
            )
            if _match_concepts(block.text, block.heading, index)
            else block
            for block in doc.chunks
        ]

        # Pass 2: section propagation — untagged blocks inside a tagged section
        # inherit the section's concept_ids so in-scope blocks aren't excluded from the index
        section_concepts: dict[tuple, set[str]] = {}
        for block in pass1:
            if block.concept_ids:
                key = (block.chapter_id, block.section_id)
                section_concepts.setdefault(key, set()).update(block.concept_ids)

        pass2 = [
            dc_replace(
                block,
                concept_ids=tuple(sorted(section_concepts[(block.chapter_id, block.section_id)])),
                concept_source="section",
            )
            if not block.concept_ids and (block.chapter_id, block.section_id) in section_concepts
            else block
            for block in pass1
        ]

        new_docs.append(dc_replace(doc, chunks=tuple(pass2)))

    return dc_replace(workspace, documents=tuple(new_docs))


# ---------------------------------------------------------------------------
# JSON export — IngestedSource handoff format v1.0 (Sean's schema)
# research/knowledge-retrieval/ingestion-handoff/ingested-source.schema.json
# ---------------------------------------------------------------------------

def to_ingested_source_json(
    doc: IngestedDocument,
    course_id: str,
    course_context_ref: dict,
    *,
    correlation_id: str | None = None,
) -> dict:
    """Serialize an IngestedDocument to the IngestedSource v1.0 handoff format.

    Args:
        doc: the ingested document (with concept_ids already filled by tag_blocks_with_concepts)
        course_id: Course.id from the CourseContext, e.g. "calc1"
        course_context_ref: {"course_context_schema_version": ..., "content_sha256": ...}
        correlation_id: optional run identifier; generated if omitted
    """
    now = datetime.now(timezone.utc).isoformat()
    cid = correlation_id or f"provision-{course_id}-{doc.content_version}"

    # ---- pages ----------------------------------------------------------------
    pages_out = []
    for pn, lines in enumerate(doc.pages, 1):
        non_empty = [l for l in lines if l.strip()]   # schema: no empty lines
        joined = "\n".join(non_empty)
        pages_out.append({
            "page_number": pn,
            "page_label": None,
            "lines": non_empty,
            "text_sha256": hashlib.sha256(joined.encode("utf-8")).hexdigest(),
        })

    # ---- sections -------------------------------------------------------------
    sections_out = _derive_sections(doc.chunks)

    # ---- blocks (exclude structural heading blocks — those go in sections) ----
    warnings_out: list[dict] = []
    blocks_out = []
    for block in doc.chunks:
        if _is_structural_heading(block):
            continue  # represented in sections, not blocks
        if not block.concept_ids:
            warnings_out.append({
                "code": "concept_unmapped",
                "message": f"Block {block.block_id} could not be mapped to any CourseContext concept.",
                "page_number": block.page_number,
                "block_id": block.block_id,
            })
        # Determine the innermost section_id for this block
        inner_section_id = _inner_section_id(block)
        blocks_out.append({
            "block_id": block.block_id,
            "section_id": inner_section_id,
            "type": block.block_type,
            "label": block.label,
            "text": block.text,
            "page_start": block.page_number,
            "line_start": block.line_start,
            "page_end": block.page_end,
            "line_end": block.line_end,
            "concept_ids": list(block.concept_ids),
            "concept_source": block.concept_source,
            "visibility": block.visibility,
            "for_block_id": None,
            "question_id": None,
        })

    status = "ingested" if not warnings_out else "partial"
    doc_role = _document_role(doc.document_type)

    return {
        "record_id": f"ing-{doc.document_id}-{doc.content_version}",
        "record_type": "IngestedSource",
        "schema_version": "0.1",
        "created_at": now,
        "producer": "course-context-ingestion",
        "status": status,
        "correlation_id": cid,
        "ingested_source_schema_version": "1.0",
        "course_id": course_id,
        "course_context_ref": course_context_ref,
        "document": {
            "document_id": f"{course_id}:{doc.document_id}",
            "content_version": doc.content_version,
            "document_role": doc_role,
            "title": doc.title,
            "source_label": f"{doc.title} ({doc_role.replace('_', ' ')})",
            "source_file": {
                "filename": doc.filename,
                "media_type": doc.media_type,
                "sha256": doc.file_sha256,
                "page_count": doc.page_count,
            },
            "source_provenance": "source_document",
            "review_status": "unverified",
            "reviewed_by": None,
            "reviewed_at": None,
            "language": "en",
        },
        "pages": pages_out,
        "sections": sections_out,
        "blocks": blocks_out,
        "warnings": warnings_out,
    }


def _document_role(doc_type: DocumentType) -> str:
    return {
        "textbook": "textbook",
        "lecture_notes": "lecture_notes",
        "syllabus": "syllabus",
        "other": "other",
    }.get(doc_type, "other")


def _is_structural_heading(block: IngestedBlock) -> bool:
    """True for chapter/section heading blocks — these go in sections, not blocks."""
    if not block.heading:
        return False
    return bool(
        (block.block_type == "explanation" and _RE_CHAPTER.match(block.heading))
        or (block.block_type == "explanation" and _RE_SECTION.match(block.heading)
            and len(block.text.strip().splitlines()) <= 2)
    )


def _inner_section_id(block: IngestedBlock) -> str:
    """Return the section_id string to embed in a block's export entry."""
    if block.chapter_id and block.section_id:
        return f"{block.chapter_id}.{block.section_id}"
    if block.chapter_id:
        return block.chapter_id
    return "root"


def _derive_sections(blocks: tuple[IngestedBlock, ...]) -> list[dict]:
    """Build the sections array from the chapter/section heading blocks."""
    # Collect chapter and section heading blocks in order
    chapter_heading: dict[str, IngestedBlock] = {}
    section_heading: dict[tuple, IngestedBlock] = {}
    for b in blocks:
        if not _is_structural_heading(b):
            continue
        if b.section_id is None and b.chapter_id and b.chapter_id not in chapter_heading:
            chapter_heading[b.chapter_id] = b
        elif b.section_id and b.chapter_id:
            key = (b.chapter_id, b.section_id)
            if key not in section_heading:
                section_heading[key] = b

    # Compute (page_start, line_start, page_end, line_end) for each structural context
    def _range(ch: str | None, sec: str | None) -> dict:
        matching = [b for b in blocks if b.chapter_id == ch and b.section_id == sec]
        if not matching:
            return {"page_start": 1, "line_start": 1, "page_end": 1, "line_end": 1}
        ps = min(b.page_number for b in matching)
        ls = min(b.line_start for b in matching if b.page_number == ps)
        pe = max(b.page_end for b in matching)
        le = max(b.line_end for b in matching if b.page_end == pe)
        return {"page_start": ps, "line_start": ls, "page_end": pe, "line_end": le}

    sections: list[dict] = []
    seen_chapters: list[str] = []
    seen_sections: list[tuple] = []

    for b in blocks:
        ch = b.chapter_id
        if ch and ch not in seen_chapters:
            seen_chapters.append(ch)
            hb = chapter_heading.get(ch)
            m = _RE_CHAPTER.match(hb.heading) if hb else None
            # Range: all blocks in this chapter
            ch_blocks = [x for x in blocks if x.chapter_id == ch]
            if ch_blocks:
                ps = min(x.page_number for x in ch_blocks)
                pe = max(x.page_end for x in ch_blocks)
                ls = min(x.line_start for x in ch_blocks if x.page_number == ps)
                le = max(x.line_end for x in ch_blocks if x.page_end == pe)
            else:
                ps = pe = ls = le = 1
            ch_concepts = sorted({cid for x in ch_blocks for cid in x.concept_ids})
            sections.append({
                "section_id": ch,
                "parent_id": None,
                "level": 1,
                "number": m.group(1) if m else None,
                "title": m.group(2).strip() if m else ch,
                "heading_kind": "chapter",
                "page_start": ps, "line_start": ls,
                "page_end": pe, "line_end": le,
                "concept_ids": ch_concepts,
                "structure_inferred": hb is None,
            })

        sec = b.section_id
        if ch and sec and (ch, sec) not in seen_sections:
            seen_sections.append((ch, sec))
            hb = section_heading.get((ch, sec))
            m = _RE_SECTION.match(hb.heading) if hb else None
            r = _range(ch, sec)
            sec_blocks = [x for x in blocks if x.chapter_id == ch and x.section_id == sec]
            sec_concepts = sorted({cid for x in sec_blocks for cid in x.concept_ids})
            sections.append({
                "section_id": f"{ch}.{sec}",
                "parent_id": ch,
                "level": 2,
                "number": m.group(1) if m else sec,
                "title": (m.group(2).strip() if m else sec) or sec,
                "heading_kind": "section",
                **r,
                "concept_ids": sec_concepts,
                "structure_inferred": hb is None,
            })

    return sections


# ---------------------------------------------------------------------------
# Ingestion service
# ---------------------------------------------------------------------------

class DocumentIngestionService:
    """Parse uploaded sources, preserve page lines, and create bounded chunks."""

    def check_consistency_fast(
        self,
        uploads: list[SourceUpload],
        *,
        allow_course_mismatch: bool = False,
    ) -> None:
        """Quick identity check using only the first few pages of each file.

        Raises CourseConsistencyError on a confirmed mismatch.  Reads at most
        _PREVIEW_PAGES pages per file so a 600-page textbook costs almost nothing.
        """
        syllabus_upload = next(
            (u for u in uploads if _classify_filename_quick(u.filename) == "syllabus"),
            None,
        )
        notes_uploads = [
            u for u in uploads
            if _classify_filename_quick(u.filename) in {"lecture_notes", "textbook", "other"}
        ]
        if syllabus_upload is None or not notes_uploads:
            return  # validation handled later in ingest_course

        syllabus_pages = _extract_first_pages(syllabus_upload)
        syllabus_text = "\n".join(line for page in syllabus_pages for line in page)
        course_number = _course_number(syllabus_text)
        course_name = _course_name(syllabus_text, course_number)

        preview_docs = [
            _make_preview_doc(u) for u in notes_uploads
        ]
        _check_course_consistency(
            course_name,
            course_number,
            preview_docs,
            allow_course_mismatch=allow_course_mismatch,
        )

    def ingest_syllabus(self, upload: SourceUpload) -> tuple[IngestedDocument, str]:
        """Parse the syllabus and return (IngestedDocument, full_syllabus_text).

        Called before full notes ingestion so CourseContext can be generated
        from syllabus text while notes are still waiting to be parsed.
        """
        doc = self._ingest_document(upload)
        text = "\n".join(line for page in doc.pages for line in page)
        return doc, text

    def ingest_course(
        self,
        uploads: list[SourceUpload],
    ) -> CourseWorkspace:
        """Full extraction and segmentation of all uploaded files.

        Consistency check is NOT performed here — call check_consistency_fast
        before this method.  CourseContext concept tagging is also separate;
        call tag_blocks_with_concepts after CourseContext is available.
        """
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
            consistency_status="verified",
            consistency_notes=(),
        )

    def _ingest_document(self, upload: SourceUpload) -> IngestedDocument:
        pages = _extract_pages(upload)
        if not any(any(line.strip() for line in page) for page in pages):
            raise IngestionError(f"No embedded text was found in {upload.filename}.")
        full_sha256 = hashlib.sha256(upload.data).hexdigest()
        content_version = full_sha256[:16]
        doc_type = _classify(upload.filename, pages)
        # Stable document_id: slug from stem so it survives re-uploads of the same file.
        doc_id = _slug(Path(upload.filename).stem) or f"doc-{uuid4().hex[:8]}"
        doc_prefix = f"{doc_type[:2]}-{doc_id}"[:40]
        chunks = _segment_blocks(pages, doc_id, upload.filename, doc_type, content_version, doc_prefix)
        stem = Path(upload.filename).stem.replace("-", " ").replace("_", " ").title()
        return IngestedDocument(
            document_id=doc_id,
            filename=upload.filename,
            media_type=upload.media_type,
            document_type=doc_type,
            content_version=content_version,
            file_sha256=full_sha256,
            title=stem,
            page_count=len(pages),
            pages=pages,
            chunks=chunks,
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_PREVIEW_PAGES = 5  # pages read by check_consistency_fast


def _extract_first_pages(
    upload: SourceUpload, max_pages: int = _PREVIEW_PAGES
) -> tuple[tuple[str, ...], ...]:
    """Extract text from the first `max_pages` pages only (cheap identity scan)."""
    suffix = Path(upload.filename).suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(upload.data))
        texts = [p.extract_text() or "" for p in reader.pages[:max_pages]]
    elif suffix == ".docx":
        from docx import Document

        doc = Document(io.BytesIO(upload.data))
        texts = ["\n".join(p.text for p in doc.paragraphs[:80])]
    elif suffix in {".txt", ".md", ".tex", ""}:
        raw = upload.data.decode("utf-8", errors="replace")
        texts = ["\n".join(raw.splitlines()[:120])]
    else:
        texts = []
    return tuple(tuple(_normalize_lines(t)) for t in texts)


def _classify_filename_quick(filename: str) -> DocumentType:
    """Classify by filename alone (no page read) for the fast consistency check."""
    name = filename.lower()
    if "syllabus" in name:
        return "syllabus"
    if any(t in name for t in ("note", "lecture", "chapter", "textbook")):
        return "lecture_notes"
    return "other"


@dataclass(frozen=True, slots=True)
class _PreviewDoc:
    """Minimal stand-in for IngestedDocument used in the fast consistency check."""
    filename: str
    pages: tuple[tuple[str, ...], ...]


def _make_preview_doc(upload: SourceUpload) -> _PreviewDoc:
    return _PreviewDoc(
        filename=upload.filename,
        pages=_extract_first_pages(upload),
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
    documents: list,  # IngestedDocument | _PreviewDoc — both have .filename and .pages
    *,
    allow_course_mismatch: bool = False,
) -> tuple[
    Literal["verified", "partially_verified", "override_confirmed"],
    tuple[str, ...],
]:
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
        if not allow_course_mismatch:
            raise CourseConsistencyError(tuple(conflicts))
        override_notes = tuple(
            f"Human override confirmed: {conflict}" for conflict in conflicts
        )
        return "override_confirmed", tuple(verified + uncertain) + override_notes
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
