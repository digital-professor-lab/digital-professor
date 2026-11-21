"""Course retrieval for the product: ingested course blocks -> Retrieval V1 (``specs/rag-retrieval.md``).

Knowledge preparation and retrieval meet here.

At publication (T1, provisioning) ``build_course_retrieval`` turns the blocks that Course Context
ingested from the uploaded files into a retrieval index:

    IngestedBlock -> catalog rows + embedding inputs -> BGE / Qwen vectors -> Retrieval V1 service

At a tutoring turn (T3) ``ToolCourseRetrieval.search`` sends one ``RetrievalRequest`` to that service and
gets a ``GroundingBundle`` or ``RetrievalStop`` back. Search and selection are Week 3's own code with
Week 3's thresholds (``retrieval_tool.backends.IngestedCourseBackend``); this module only adapts data.

``search`` keeps the call shape of the demo's ``CourseRetrievalIndex`` and returns the same
``RetrievedPassage`` objects, so the Engine and the browser need no change to show sources.

Which index a course gets (``DP_RETRIEVAL_MODE``):

* ``auto`` (default)  Retrieval V1 when its package, the Week 3 code and the embedding models are all
                      available; otherwise the demo keyword index, with the reason recorded.
* ``tool``            Retrieval V1, or an error that says what is missing.
* ``keyword``         the demo keyword index.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from digital_professor.course_context.ingestion import CourseWorkspace, IngestedBlock
from digital_professor.retrieval.index import CourseRetrievalIndex, RetrievedPassage

_log = logging.getLogger(__name__)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
RETRIEVAL_TOOL_DIR = REPOSITORY_ROOT / "research" / "knowledge-retrieval" / "retrieval-tool"
VECTOR_CACHE_DIR = REPOSITORY_ROOT / ".cache" / "retrieval_index"

# Week 3 embedding settings (prepare_embedding_inputs.py, generate_embeddings.py, search.py)
MODEL_REPOSITORIES = {
    "bge_base_en_v1_5": "BAAI/bge-base-en-v1.5",
    "qwen3_embedding_0_6b": "Qwen/Qwen3-Embedding-0.6B",
}
DEFAULT_MODELS = tuple(MODEL_REPOSITORIES)
DOCUMENT_BATCH_SIZES = {"bge_base_en_v1_5": 16, "qwen3_embedding_0_6b": 4}
BGE_QUERY_PROMPT = "Represent this sentence for searching relevant passages: "
MAX_BGE_TOKENS = 384
OVERLAP_WORDS = 25
WORDS_PER_SEGMENT_WITHOUT_TOKENIZER = 220   # stays under 384 BGE tokens for ordinary English prose
PILOT_SCOPE = "pilot_course_or_general"     # the one scope label Week 3's search serves by default

# The Engine does not yet tell Retrieval which tutoring action it chose, and its action names are not the
# shared twelve. Until it does, every search is a system pre-fetch for an explanation (policy mode "must").
DEFAULT_ACTION_TYPE = "explain"


class RetrievalUnavailable(RuntimeError):
    """Retrieval V1 cannot be built here; the message says what is missing."""


# ---------------------------------------------------------------------------
# Encoders
# ---------------------------------------------------------------------------
class SentenceTransformerEncoder:
    """BGE and Qwen as Week 3 used them: same repositories, revisions, query prompts and normalization.

    Models are loaded once, on first use. The model files come from the Hugging Face cache: ``HF_HOME`` when
    set, otherwise Week 3's own cache folder when ``WEEK3_KB`` points at it, otherwise the default cache.
    """

    def __init__(self, models: Sequence[str] = DEFAULT_MODELS, *, revisions: Mapping[str, str] | None = None,
                 device: str = "auto") -> None:
        unknown = [key for key in models if key not in MODEL_REPOSITORIES]
        if unknown:
            raise RetrievalUnavailable(f"unknown embedding model key(s): {', '.join(unknown)}")
        self.models = tuple(models)
        self.revisions = dict(revisions or {})
        self.device = device
        self._loaded: dict[str, Any] = {}

    @staticmethod
    def installed() -> bool:
        return importlib.util.find_spec("sentence_transformers") is not None

    def _cache_folder(self) -> str | None:
        if os.environ.get("HF_HOME"):
            return None
        week3_kb = os.environ.get("WEEK3_KB")
        candidate = Path(week3_kb) / ".cache" / "huggingface" if week3_kb else None
        if candidate and candidate.exists():
            hub = candidate / "hub"
            return str(hub if hub.exists() else candidate)
        return None

    def _model(self, key: str) -> Any:
        if key not in self._loaded:
            from sentence_transformers import SentenceTransformer
            device = self.device
            if device == "auto":
                import torch
                device = "mps" if torch.backends.mps.is_available() else "cpu"
            self._loaded[key] = SentenceTransformer(MODEL_REPOSITORIES[key], revision=self.revisions.get(key),
                                                    device=device, cache_folder=self._cache_folder())
        return self._loaded[key]

    def cache_tag(self, key: str) -> str:
        """Names the model version in the vector cache, so vectors of another revision are never reused."""
        return (self.revisions.get(key) or "unpinned")[:12]

    def tokenizer(self) -> Any:
        """The BGE tokenizer, used to keep each embedding input under Week 3's 384-token limit."""
        key = "bge_base_en_v1_5" if "bge_base_en_v1_5" in self.models else self.models[0]
        return self._model(key).tokenizer

    def encode_documents(self, key: str, texts: list[str]) -> np.ndarray:
        vectors = self._model(key).encode(texts, batch_size=DOCUMENT_BATCH_SIZES[key], show_progress_bar=False,
                                          convert_to_numpy=True, normalize_embeddings=True)
        return np.asarray(vectors, dtype=np.float32)

    def encode_queries(self, key: str, texts: list[str]) -> np.ndarray:
        model = self._model(key)
        if key == "bge_base_en_v1_5":
            vectors = model.encode([BGE_QUERY_PROMPT + text for text in texts], batch_size=16,
                                   normalize_embeddings=True, convert_to_numpy=True)
        else:
            vectors = model.encode(texts, prompt_name="query", batch_size=4,
                                   normalize_embeddings=True, convert_to_numpy=True)
        return np.asarray(vectors, dtype=np.float32)


def default_encoder(week3_root: Path) -> SentenceTransformerEncoder | None:
    """The Week 3 encoders when sentence-transformers is installed; ``DP_RETRIEVAL_MODELS`` narrows the set."""
    if not SentenceTransformerEncoder.installed():
        return None
    wanted = [key.strip() for key in os.environ.get("DP_RETRIEVAL_MODELS", "").split(",") if key.strip()]
    revisions: dict[str, str] = {}
    manifest = week3_root / "data" / "embeddings" / "input_manifest.json"
    if manifest.exists():
        models = json.loads(manifest.read_text(encoding="utf-8")).get("models", {})
        revisions = {key: spec["revision"] for key, spec in models.items() if spec.get("revision")}
    return SentenceTransformerEncoder(wanted or DEFAULT_MODELS, revisions=revisions)


# ---------------------------------------------------------------------------
# Ingested blocks -> catalog rows and embedding inputs
# ---------------------------------------------------------------------------
def highlight_url(course_id: str, block: IngestedBlock) -> str:
    return (f"/api/courses/{course_id}/sources/{block.document_id}"
            f"?page={block.page_number}&line_start={block.line_start}&line_end={block.line_end}")


def _heading_only(block: IngestedBlock) -> bool:
    """A chapter or section title on its own (at most two lines). It names a topic but states nothing, so it
    is not a passage; its text becomes the section path of the blocks under it."""
    from digital_professor.course_context.ingestion import _is_structural_heading
    return _is_structural_heading(block) and len(block.text.strip().splitlines()) <= 2


def _section_titles(workspace: CourseWorkspace) -> dict[tuple[str, str | None, str | None], str]:
    titles: dict[tuple[str, str | None, str | None], str] = {}
    for document in workspace.documents:
        for block in document.chunks:
            if _heading_only(block):
                title = " ".join(block.text.split())[:120]
                titles.setdefault((document.document_id, block.chapter_id, block.section_id), title)
    return titles


def _section_path(block: IngestedBlock, titles: Mapping[tuple[str, str | None, str | None], str]) -> str:
    chapter = titles.get((block.document_id, block.chapter_id, None)) or block.chapter_id
    section = titles.get((block.document_id, block.chapter_id, block.section_id)) or block.section_id
    return " > ".join(part for part in (chapter, section if block.section_id else None) if part)


def _short_label(block: IngestedBlock) -> str | None:
    """The printed name of a block, e.g. "Theorem 3.2 (Chain rule)", cut from the block's first line."""
    if not block.label:
        return None
    label = " ".join(block.label.split())
    close = label.find(")")
    stop = label.find(". ")
    if 0 < close < 80 and (stop < 0 or label.find("(") < stop):
        return label[:close + 1]
    return label[:stop] if 0 < stop < 80 else label[:80]


def _split_for_embedding(prefix: str, body: str, count_tokens: Callable[[str], int] | None) -> list[str]:
    """Week 3's ``split_text``: whole words, at most 384 BGE tokens per input, 25 words of overlap."""
    words = body.split()
    if not words:
        return []
    if count_tokens is None:
        size = WORDS_PER_SEGMENT_WITHOUT_TOKENIZER
        if len(words) <= size:
            return [prefix + " ".join(words)]
        out, start = [], 0
        while start < len(words):
            end = min(len(words), start + size)
            out.append(prefix + " ".join(words[start:end]))
            if end == len(words):
                break
            start = max(start + 1, end - OVERLAP_WORDS)
        return out
    full = prefix + " ".join(words)
    if count_tokens(full) <= MAX_BGE_TOKENS:
        return [full]
    out, start = [], 0
    while start < len(words):
        low, high, best = start + 1, len(words), start
        while low <= high:
            mid = (low + high) // 2
            if count_tokens(prefix + " ".join(words[start:mid])) <= MAX_BGE_TOKENS:
                best, low = mid, mid + 1
            else:
                high = mid - 1
        if best == start:      # one "word" longer than the budget (e.g. a long formula): keep it alone, truncated by the model
            best = start + 1
        out.append(prefix + " ".join(words[start:best]))
        if best == len(words):
            break
        start = max(start + 1, best - OVERLAP_WORDS)
    return out


def build_catalog_rows(workspace: CourseWorkspace, *, count_tokens: Callable[[str], int] | None = None,
                       ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Documents, passages (one per ingested block) and embedding inputs, in the shapes Week 3's code reads."""
    documents: dict[str, dict[str, Any]] = {}
    passages: dict[str, dict[str, Any]] = {}
    records: list[dict[str, Any]] = []
    titles = _section_titles(workspace)
    for document in workspace.documents:
        documents[document.document_id] = {
            "course_id": workspace.course_id, "document_id": document.document_id, "filename": document.filename,
            "source_type": document.document_type,
            # An uploaded course file is an original source, but nobody has reviewed its blocks one by one.
            "review_status": "unverified", "provenance": "source_document",
            "sha256": document.file_sha256, "content_version": document.content_version,
            "snapshot_path": f"uploads/{document.filename}", "line_count": sum(len(page) for page in document.pages),
        }
        for block in document.chunks:
            text = block.text.strip()
            if not text or block.block_id in passages or _heading_only(block):
                continue
            path = _section_path(block, titles)
            passages[block.block_id] = {
                "passage_id": block.block_id, "document_id": block.document_id, "passage_kind": block.block_type,
                "raw_latex": text, "readable_text": text, "scope_status": PILOT_SCOPE,
                "start_line": block.line_start, "end_line": block.line_end, "page_number": block.page_number,
                "section_path": path, "label": _short_label(block), "visibility": block.visibility,
                "content_version": block.content_version, "concept_ids": list(block.concept_ids),
                "highlight_url": highlight_url(workspace.course_id, block),
            }
            prefix = f"Course: {workspace.course_name}. Section: {path or 'Front matter'}. Content: "
            segments = _split_for_embedding(prefix, text, count_tokens)
            for index, value in enumerate(segments):
                records.append({
                    "record_id": f"passage:{block.block_id}:{index}", "entity_type": "passage",
                    "entity_id": block.block_id, "course_id": workspace.course_id,
                    "document_id": block.document_id, "input_text": value,
                    "input_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
                    "section_path": path, "segment_index": index, "segment_count": len(segments),
                    "scope_status": PILOT_SCOPE, "source_line_start": block.line_start,
                    "source_line_end": block.line_end, "source_type": document.document_type,
                    "review_status": "unverified",
                })
    return documents, passages, records


def _embed_records(records: list[dict[str, Any]], encoder: Any, key: str, cache_dir: Path | None) -> np.ndarray:
    """Vectors for every embedding input; inputs already embedded for the same file version are read from disk.

    Only an encoder that names its model version (``cache_tag``) uses the cache.
    """
    tag = encoder.cache_tag(key) if hasattr(encoder, "cache_tag") else None
    if tag is None:
        cache_dir = None
    vectors: dict[str, np.ndarray] = {}
    by_document: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_document.setdefault(record["document_id"], []).append(record)
    for document_id, rows in by_document.items():
        cache_file = None
        if cache_dir is not None:
            digest = hashlib.sha256("|".join(sorted(r["input_sha256"] for r in rows)).encode()).hexdigest()[:16]
            cache_file = cache_dir / key / tag / f"{document_id[:60]}-{digest}.npz"
            if cache_file.exists():
                try:
                    saved = np.load(cache_file)
                    vectors.update(dict(zip(saved["shas"].tolist(), saved["vectors"])))
                    continue
                except Exception as error:      # an unreadable cache file is rebuilt, never trusted
                    _log.warning("ignoring unreadable vector cache %s: %s", cache_file, error)
        todo = list({r["input_sha256"]: r["input_text"] for r in rows}.items())
        matrix = np.asarray(encoder.encode_documents(key, [text for _, text in todo]), dtype=np.float32)
        if matrix.shape[0] != len(todo):
            raise RetrievalUnavailable(f"{key} returned {matrix.shape[0]} vectors for {len(todo)} inputs")
        vectors.update({sha: matrix[i] for i, (sha, _) in enumerate(todo)})
        if cache_file is not None:
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                np.savez(cache_file, shas=np.array([sha for sha, _ in todo]), vectors=matrix)
            except OSError as error:
                _log.warning("could not write vector cache %s: %s", cache_file, error)
    return np.stack([vectors[r["input_sha256"]] for r in records])


# ---------------------------------------------------------------------------
# The course index used by the application
# ---------------------------------------------------------------------------
def _import_retrieval_tool() -> Any:
    try:
        import retrieval_tool
    except ImportError:
        if not (RETRIEVAL_TOOL_DIR / "retrieval_tool" / "__init__.py").exists():
            raise RetrievalUnavailable("the retrieval_tool package is not installed") from None
        sys.path.append(str(RETRIEVAL_TOOL_DIR))
        try:
            import retrieval_tool
        except ImportError as error:
            raise RetrievalUnavailable(f"the retrieval_tool package cannot be imported: {error}") from error
    return retrieval_tool


@dataclass
class RetrievalInfo:
    """What a course's index is, for ``/api/status``, logs and the trace."""

    mode: str                                   # "retrieval_tool" or "keyword_demo"
    backend: str
    semantic_channel: bool
    models: tuple[str, ...] = ()
    passages: int = 0
    embedding_inputs: int = 0
    snapshot_id: str | None = None
    build_seconds: float = 0.0
    note: str | None = None                     # why the keyword index is in use, when it is

    def to_dict(self) -> dict[str, Any]:
        return {key: (list(value) if isinstance(value, tuple) else value) for key, value in self.__dict__.items()}


@dataclass
class _Turn:
    record: dict[str, Any] | None = None
    request: dict[str, Any] | None = None
    passages: tuple[RetrievedPassage, ...] = field(default_factory=tuple)


class ToolCourseRetrieval:
    """One published course served by Retrieval V1. Same ``search`` call as the demo keyword index."""

    def __init__(self, workspace: CourseWorkspace, *, encoder: Any = None, week3_root: Path | None = None,
                 cache_dir: Path | None = None, judge: Any = None, options: Any = None) -> None:
        started = time.perf_counter()
        tool = _import_retrieval_tool()
        from retrieval_tool.backends import BackendUnavailable, Catalog, IngestedCourseBackend
        from retrieval_tool.planner import ConceptCatalog, RetrievalPlanner
        from retrieval_tool.service import CoursePolicy, RetrievalService

        try:
            root = week3_root or tool.retrieval_root()
        except FileNotFoundError as error:
            raise RetrievalUnavailable(f"the Week 3 retrieval code is not checked out ({error})") from error
        self.course_id = workspace.course_id
        self._blocks: dict[tuple[str, int, int, int], IngestedBlock] = {
            (block.document_id, block.page_number, block.line_start, block.line_end): block
            for document in workspace.documents for block in document.chunks}

        models = tuple(getattr(encoder, "models", DEFAULT_MODELS)) if encoder is not None else ()
        try:
            count_tokens = None
            if encoder is not None and hasattr(encoder, "tokenizer"):
                tokenizer = encoder.tokenizer()
                count_tokens = lambda text: len(tokenizer.encode(text, add_special_tokens=True, truncation=False))  # noqa: E731
            documents, passages, records = build_catalog_rows(workspace, count_tokens=count_tokens)
            if not records:
                raise RetrievalUnavailable("the course has no ingested text to index")
            vectors = {key: _embed_records(records, encoder, key, cache_dir) for key in models}
        except RetrievalUnavailable:
            raise
        except Exception as error:      # model files missing, out of memory, ...
            raise RetrievalUnavailable(f"embedding the course failed: {str(error)[:300]}") from error

        catalog = Catalog(root=root, documents=documents, passages=passages, issues=[], concept_passages={},
                          course_names={workspace.course_id: workspace.course_name})
        try:
            backend = IngestedCourseBackend(
                root, catalog=catalog, records=records, vectors=vectors, models=models or DEFAULT_MODELS,
                encoder=(lambda key, texts: encoder.encode_queries(key, list(texts))) if encoder is not None else None)
        except BackendUnavailable as error:
            hint = " (pip install 'psycopg[binary]' pgvector)" if "psycopg" in str(error) or "pgvector" in str(error) else ""
            raise RetrievalUnavailable(f"{error}{hint}") from error

        versions = "+".join(sorted(document.content_version for document in workspace.documents))
        snapshot = f"snap.{workspace.course_id}.{hashlib.sha256(versions.encode()).hexdigest()[:12]}"
        policy = CoursePolicy(
            course_id=workspace.course_id, policy_version=f"{workspace.course_id}-retrieval-policy@demo-0.1",
            retrieval_snapshot_id=snapshot,
            # Uploaded files are original sources that no one has reviewed block by block: served as a pilot.
            allow_unverified_sources="pilot",
            # Whether student text may go to an external model (the Jev judge) is a team decision (spec Q15).
            external_processing_allowed=False)
        planner = None
        if workspace.course_context:
            try:
                planner = RetrievalPlanner({workspace.course_id: ConceptCatalog.from_course_context(
                    workspace.course_context, source="uploaded course context")})
            except (KeyError, TypeError, AttributeError) as error:
                _log.warning("Course Context has no usable concept list for retrieval planning: %s", error)
        self.service = RetrievalService(
            backend, catalog, {workspace.course_id: policy}, judge=judge, options=options, planner=planner,
            scope_checker=lambda text, *, course_id, source_types, policy: backend.assess(text, source_types=source_types))
        self.policy = policy
        self._tool = tool
        self._last = _Turn()
        self.info = RetrievalInfo(
            mode="retrieval_tool", backend=backend.name, semantic_channel=backend.semantic_available, models=models,
            passages=len(passages), embedding_inputs=len(records), snapshot_id=snapshot,
            build_seconds=round(time.perf_counter() - started, 2),
            note=None if backend.semantic_available else "no embedding model: keyword channel only")

    # ------------------------------------------------------------------ turn time
    def search(self, query: str, *, top_k: int = 4, concept_ids: Sequence[str] = (),
               concept_names: Sequence[str] = (), topic: str | None = None, question_prompt: str | None = None,
               student_message: str | None = None, action_type: str = DEFAULT_ACTION_TYPE,
               session_id: str | None = None, turn_id: str | None = None, question_id: str | None = None,
               correlation_id: str | None = None, include_engine_only: bool = False,
               ) -> tuple[RetrievedPassage, ...]:
        """One retrieval for one turn. The full record is in ``last_record`` (GroundingBundle or RetrievalStop).

        With ``topic`` or ``concept_names`` the request is built from that structured context only
        (``query_origin = structured``); the student's own words are then used for the scope check, never
        searched. Without them the question being worked on is searched (``question_prompt``, else
        ``query``) and treated as student wording.
        """
        from retrieval_tool.tool_schema import ToolArgumentError, TurnContext, build_request, build_structured_request

        ids = {"session_id": session_id or "session-unknown", "turn_id": turn_id or "turn-0",
               "question_id": question_id or f"{self.course_id}.unknown-question",
               "correlation_id": correlation_id or f"correlation-{hashlib.sha256(query.encode()).hexdigest()[:12]}"}
        decision = self._tool.recommend_grounding(action_type)
        names = [name for name in concept_names if name]
        context = TurnContext(
            course_id=self.course_id, action_type=action_type, retrieval_snapshot_id=self.policy.retrieval_snapshot_id,
            concept_ids=list(concept_ids) if names or topic else [], concept_names=names,
            question_prompt=question_prompt, student_message=student_message, intent_summary=topic,
            evidence_summary=(student_message or "")[:500] or None, **ids)
        limit = max(1, min(int(top_k), 10))
        try:
            if names or topic:
                request = build_structured_request(context, decision, top_k=limit)
            else:
                # No schema for this question yet: search the question the student is working on. Their
                # latest message ("I am stuck") is checked for scope but is not a search query.
                text = " ".join((question_prompt or query).split())[:300]
                request = build_request(
                    {"query": text, "purpose": decision.purposes[0], "contains_student_wording": True,
                     "evidence_needs": [{"need_type": need, "description": text[:200]}
                                        for need in decision.need_types[:4]]},
                    context, top_k=limit, producer="tutoring-engine:prefetch")
        except ToolArgumentError as error:
            self._last = _Turn(record={"record_type": "RetrievalStop", "stop_reason": "invalid_request",
                                       "reason_code": "invalid_request", "validation_errors": error.errors})
            return ()
        record = self.service.handle(request)
        found: list[RetrievedPassage] = []
        for passage in record.get("passages") or []:
            block = self._blocks.get((passage["document_id"], passage["page_number"],
                                      passage["line_start"], passage["line_end"]))
            if block is None or (passage.get("visibility") == "engine_only" and not include_engine_only):
                continue
            # Retrieval V1 reports a rank, not a comparable score (spec §7.7); the reciprocal rank keeps the
            # demo's score column ordered without inventing a calibrated number.
            found.append(RetrievedPassage(passage=block, score=round(1.0 / passage["retrieval_rank"], 4),
                                          highlight_url=passage["highlight_url"] or highlight_url(self.course_id, block)))
        self._last = _Turn(record=record, request=request, passages=tuple(found))
        return self._last.passages

    # ------------------------------------------------------------------ what happened
    @property
    def last_record(self) -> dict[str, Any] | None:
        return self._last.record

    @property
    def last_request(self) -> dict[str, Any] | None:
        return self._last.request

    def last_outcome(self) -> dict[str, Any]:
        """A short, loggable summary of the latest search."""
        record = self._last.record or {}
        outcome = {"mode": self.info.mode, "backend": self.info.backend,
                   "status": record.get("retrieval_status") or record.get("stop_reason") or "not_run",
                   "record_type": record.get("record_type"),
                   "warnings": sorted({w["code"] for w in record.get("warnings") or []}),
                   "uncovered_needs": record.get("uncovered_needs") or []}
        if record.get("reason_code"):
            outcome["reason_code"] = record["reason_code"]
        if self._last.request:
            outcome["query"] = self._last.request["query"]
            outcome["query_origin"] = self._last.request["query_origin"]
        return outcome


def describe_index(index: Any) -> RetrievalInfo:
    info = getattr(index, "info", None)
    if isinstance(info, RetrievalInfo):
        return info
    return RetrievalInfo(mode="keyword_demo", backend="keyword_overlap", semantic_channel=False)


def last_outcome(index: Any, passages: Sequence[RetrievedPassage]) -> dict[str, Any]:
    """The latest search of either index kind, in one shape for logs and the trace."""
    if isinstance(index, ToolCourseRetrieval):
        return index.last_outcome()
    info = describe_index(index)
    return {"mode": info.mode, "backend": info.backend, "warnings": [], "uncovered_needs": [],
            "status": "supported" if passages else "no_support_found", "record_type": None}


def build_course_retrieval(workspace: CourseWorkspace, *, mode: str | None = None, encoder: Any = None) -> Any:
    """The index for a newly published course (see the module docstring for the modes)."""
    mode = (mode or os.environ.get("DP_RETRIEVAL_MODE") or "auto").strip().lower()
    if mode not in ("auto", "tool", "keyword"):
        raise ValueError("DP_RETRIEVAL_MODE must be auto, tool or keyword")

    def keyword(note: str) -> CourseRetrievalIndex:
        index = CourseRetrievalIndex(workspace)
        index.info = RetrievalInfo(mode="keyword_demo", backend="keyword_overlap", semantic_channel=False,
                                   passages=sum(len(d.chunks) for d in workspace.documents), note=note)
        return index

    if mode == "keyword":
        return keyword("DP_RETRIEVAL_MODE=keyword")
    try:
        tool = _import_retrieval_tool()
        try:
            root = tool.retrieval_root()
        except FileNotFoundError:
            raise RetrievalUnavailable("the Week 3 retrieval code is not checked out; run "
                                       "bash research/knowledge-retrieval/retrieval-tool/scripts/setup_week3.sh") from None
        if encoder is None:
            encoder = default_encoder(root)
        if encoder is None and mode == "auto":
            raise RetrievalUnavailable("sentence-transformers is not installed, so there is no vector channel; "
                                       "pip install -e 'research/knowledge-retrieval/retrieval-tool[embeddings,postgres]'")
        return ToolCourseRetrieval(workspace, encoder=encoder, week3_root=root, cache_dir=VECTOR_CACHE_DIR)
    except RetrievalUnavailable as error:
        if mode == "tool":
            raise
        _log.warning("Retrieval V1 is not available for %s; using the demo keyword index: %s",
                     workspace.course_id, error)
        return keyword(str(error))
