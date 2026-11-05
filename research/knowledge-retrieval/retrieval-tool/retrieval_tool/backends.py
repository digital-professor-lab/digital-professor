"""Search backends behind the retrieval tool — both run **Week 3's own retrieval code**.

Alignment rule: fusion (RRF k=60, channel weights, source weights), sub-question reservation (2 passages
per facet), the soft per-file limit, the broad-keyword-only skip and the context budget are NOT
re-implemented here. Both backends call Week 3's `Retriever._search_with_vectors` unchanged, with Week 3's
production defaults (top_k 6, 40 candidates per channel, 12,000 characters, soft limit 4 per file).

* `PgvectorBackend` – Week 3's Retriever on the Docker PostgreSQL/pgvector database. The only change is
  that the two embedding models are loaded once and kept (Week 3 reloaded them on every call).
* `ReplayBackend` – replays reports that Week 3 itself produced (e.g. artifacts/evaluations/refinement_runs/
  facets_6.jsonl). Searches nothing; used to check that the tool wrapper reproduces Week 3's results.
* `InMemoryBackend` – TEST STAND-IN ONLY, for offline unit tests of the service logic. Its keyword channel is
  SQLite FTS5, not PostgreSQL full-text search, so its numbers are NOT comparable with Week 3 and it must not
  be used for benchmarks or demos. Real runs use `PgvectorBackend` on the Mac.

Swapping in Ovunc's ingested JSON later means a new data adapter; the tool contract does not change.
"""

from __future__ import annotations

import importlib
import json
import re
import sqlite3
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

import numpy as np

PILOT_SCOPE = "pilot_course_or_general"
# Week 3 production defaults (Retriever.search_many)
WEEK3_DEFAULTS = {"top_k": 6, "candidate_limit": 40, "context_chars": 12000, "max_per_document": 4,
                  "document_limit_mode": "soft", "use_lexical": True, "include_flagged": False}
# PostgreSQL `english` text-search stop words (snowball list), used to mimic to_tsvector('english')
PG_ENGLISH_STOP = set("""i me my myself we our ours ourselves you your yours yourself yourselves he him his himself she
her hers herself it its itself they them their theirs themselves what which who whom this that these those am is are
was were be been being have has had having do does did doing a an the and but if or because as until while of at by
for with about against between into through during before after above below to from up down in out on off over
under again further then once here there when where why how all any both each few more most other some such no nor
not only own same so than too very s t can will just don should now""".split())

# Text helpers used by the evidence check (not by search)
GENERIC_STOP = {
    "a", "about", "after", "all", "also", "an", "and", "answer", "any", "are", "as", "at", "be", "between",
    "by", "can", "course", "describe", "does", "do", "each", "explain", "for", "from", "has", "have", "how",
    "i", "in", "into", "is", "it", "its", "of", "on", "or", "our", "student", "students", "that", "the",
    "their", "them", "there", "these", "this", "those", "to", "use", "used", "using", "what", "when",
    "where", "which", "why", "with", "would", "you", "your", "statement", "guidance", "example",
}


def _stem(token: str) -> str:
    for suffix in ("ations", "ation", "ings", "ing", "ies", "ed", "es", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            return token[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return token


def terms(text: str) -> list[str]:
    text = re.sub(r"\\[a-zA-Z]+", " ", text)  # drop LaTeX command names
    return [_stem(t) for t in re.findall(r"[a-z][a-z0-9]*|\d+", text.lower()) if t not in GENERIC_STOP and len(t) >= 2]


# ---------------------------------------------------------------------------
# Catalog (document inventory + passage text); shared by service and backends
# ---------------------------------------------------------------------------
@dataclass
class Catalog:
    root: Path
    documents: dict[str, dict[str, Any]]
    passages: dict[str, dict[str, Any]]
    issues: list[dict[str, Any]]
    concept_passages: dict[str, list[str]]
    course_names: dict[str, str]

    @classmethod
    def load(cls, root: Path) -> "Catalog":
        catalog = root / "data" / "catalog"
        read = lambda name: [json.loads(line) for line in (catalog / name).read_text(encoding="utf-8").splitlines() if line.strip()]  # noqa: E731
        documents = {d["document_id"]: d for d in read("documents.jsonl")}
        passages = {p["passage_id"]: p for p in read("passages.jsonl")}
        concept_passages: dict[str, list[str]] = defaultdict(list)
        for row in read("concept_evidence.jsonl"):
            concept_passages[row["concept_id"]].append(row["passage_id"])
        issues = read("review_issues.jsonl") if (catalog / "review_issues.jsonl").exists() else []
        manifest = json.loads((catalog / "manifest.json").read_text(encoding="utf-8"))
        names = {cid: c.get("name", cid) for cid, c in manifest.get("courses", {}).items()}
        return cls(root, documents, passages, issues, dict(concept_passages), names)

    def courses(self) -> set[str]:
        return {d["course_id"] for d in self.documents.values()}

    def documents_for(self, course_id: str) -> list[dict[str, Any]]:
        return [d for d in self.documents.values() if d["course_id"] == course_id]

    def open_issues(self, document_id: str, start: int, end: int) -> list[dict[str, Any]]:
        return [i for i in self.issues if i["document_id"] == document_id
                and start <= i["source_line"] <= end and i.get("status") != "resolved"]

    def row(self, passage_id: str) -> dict[str, Any]:
        p = self.passages[passage_id]
        d = self.documents[p["document_id"]]
        return {**p, "course_id": d["course_id"], "filename": d["filename"], "source_type": d["source_type"],
                "review_status": d["review_status"], "document_sha256": d["sha256"],
                "known_issues": self.open_issues(p["document_id"], p["start_line"], p["end_line"])}


class BackendUnavailable(RuntimeError):
    """Index or encoder fault → the service returns `failed`, never `no_support_found`."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class SearchBackend(Protocol):
    name: str
    semantic_available: bool

    def run(self, question: str, facets: list[str], *, course_id: str, include_unconfirmed: bool = False,
            include_outside_course: bool = False, **week3_options: Any) -> dict[str, Any]:
        """Week 3 report (schema 1.1) for one question with explicit sub-questions (facets)."""

    def query_facets(self, question: str) -> list[str]: ...

    def close(self) -> None: ...


# ---------------------------------------------------------------------------
# Loading Week 3 code (never modified)
# ---------------------------------------------------------------------------
def load_week3_package(root: Path) -> tuple[Any, Any, Any]:
    """`digital_professor.retrieval` from output/github-ready/src → (search, request_policy, report_contract)."""
    src = str(root / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    try:
        search = importlib.import_module("digital_professor.retrieval.search")
        policy = importlib.import_module("digital_professor.retrieval.request_policy")
        contract = importlib.import_module("digital_professor.retrieval.report_contract")
    except ImportError as error:
        raise BackendUnavailable("index_unavailable", f"cannot import Week 3 retrieval code from {src}: {error}") from error
    return search, policy, contract


def load_week3_rules(root: Path) -> tuple[Any, Any]:
    """Only Week 3's pure-Python modules (request_policy, report_contract); no database driver needed."""
    src = str(root / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    try:
        return (importlib.import_module("digital_professor.retrieval.request_policy"),
                importlib.import_module("digital_professor.retrieval.report_contract"))
    except ImportError as error:
        raise BackendUnavailable("index_unavailable", f"cannot import Week 3 rules from {src}: {error}") from error


def load_week3_folder(week3_kb: Path) -> tuple[Any, Any, Any]:
    """The live Week 3 folder (week3/knowledge_base/retrieval): knows its postgres/.env and model cache."""
    path = str(week3_kb / "retrieval")
    if path not in sys.path:
        sys.path.insert(0, path)
    try:
        return importlib.import_module("search"), importlib.import_module("request_policy"), \
            importlib.import_module("report_contract")
    except ImportError as error:
        raise BackendUnavailable("index_unavailable", f"cannot import Week 3 retrieval code from {path}: {error}") from error


def run_week3(retriever: Any, contract: Any, question: str, facets: list[str], *, course_id: str,
              include_unconfirmed: bool, include_outside_course: bool, **options: Any) -> dict[str, Any]:
    """Exactly what Week 3 `search_many` does for one question, but with caller-given facets."""
    settings = {**WEEK3_DEFAULTS, **{k: v for k, v in options.items() if v is not None}}
    question = " ".join(question.split())
    facets = [f for f in dict.fromkeys(" ".join(f.split()) for f in facets) if f and f.lower() != question.lower()]
    texts = [question, *facets]
    started = time.perf_counter()
    try:
        vectors = retriever._encode_questions(texts) if retriever.models else {}
    except Exception as error:
        raise BackendUnavailable("encoder_unavailable", f"query encoder failed: {error}") from error
    vec = lambda text: {k: vectors[k][texts.index(text)] for k in retriever.models}  # noqa: E731
    try:
        report = retriever._search_with_vectors(
            question, vec(question), course_id=course_id, include_unconfirmed=include_unconfirmed,
            include_outside_course=include_outside_course, include_flagged=settings["include_flagged"],
            top_k=settings["top_k"], candidate_limit=settings["candidate_limit"],
            context_chars=settings["context_chars"], use_lexical=settings["use_lexical"],
            max_per_document=settings["max_per_document"], document_limit_mode=settings["document_limit_mode"],
            facet_vectors=[(f, vec(f)) for f in facets])
    except BackendUnavailable:
        raise
    except ValueError:
        raise
    except Exception as error:
        raise BackendUnavailable("index_unavailable", f"Week 3 search failed: {error}") from error
    report["retrieval_seconds"] = time.perf_counter() - started
    contract.validate_report_contract(report)
    return report


# ---------------------------------------------------------------------------
# In-memory backend: Week 3 Retriever with its database reads served from files
# ---------------------------------------------------------------------------
Encoder = Callable[[str, list[str]], np.ndarray]  # (model_key, texts) -> (n, dim) normalized vectors


class _MemoryData:
    def __init__(self, root: Path, catalog: Catalog, model_keys: tuple[str, ...]) -> None:
        embeddings = root / "data" / "embeddings"
        self.catalog = catalog
        self.records = [json.loads(l) for l in (embeddings / "embedding_inputs.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
        self.by_id = {r["record_id"]: r for r in self.records}
        self.vectors: dict[str, np.ndarray] = {}
        for key in model_keys:
            rows = [json.loads(l) for l in (embeddings / key / "rows.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
            matrix = np.load(embeddings / key / "vectors.npy")
            order = {r["record_id"]: r["row_index"] for r in rows}
            self.vectors[key] = matrix[[order[r["record_id"]] for r in self.records]]
        self.fts = sqlite3.connect(":memory:", check_same_thread=False)
        self.fts.execute("CREATE VIRTUAL TABLE t USING fts5(body, tokenize='porter unicode61')")
        self.fts.executemany("INSERT INTO t(rowid, body) VALUES (?, ?)",
                             [(i, r["input_text"]) for i, r in enumerate(self.records)])

    def eligible(self, course_id: str | None, scopes: list[str], include_flagged: bool) -> list[int]:
        keep = []
        for i, r in enumerate(self.records):
            if r["scope_status"] not in scopes or (course_id and r["course_id"] != course_id):
                continue
            if not include_flagged and self.catalog.open_issues(r["document_id"], r["source_line_start"], r["source_line_end"]):
                continue
            keep.append(i)
        return keep


def _websearch_terms(query_text: str) -> tuple[list[str], str]:
    """Rough `websearch_to_tsquery('english')`: words are ANDed unless the text uses OR."""
    parts = re.split(r"\s+OR\s+", query_text)
    mode = "OR" if len(parts) > 1 else "AND"
    words = [w for w in re.findall(r"[A-Za-z0-9]+", query_text.lower()) if w not in PG_ENGLISH_STOP and w != "or"]
    return list(dict.fromkeys(words)), mode


def _make_memory_retriever(base: type, data: _MemoryData, encoder: Encoder | None, models: tuple[str, ...]) -> Any:
    class _Result:
        def __init__(self, row: dict[str, Any]) -> None:
            self.row = row

        def fetchone(self) -> dict[str, Any]:
            return self.row

    class _CourseLookup:
        """Serves the only SQL `_search_with_vectors` runs directly (does the course exist?)."""

        def execute(self, sql: str, params: Any = None) -> _Result:
            if "FROM courses" in sql:
                return _Result({"exists": params[0] in data.catalog.courses()})
            raise RuntimeError(f"unexpected SQL in memory backend: {sql[:60]}")

        def close(self) -> None:
            pass

    class MemoryRetriever(base):  # type: ignore[misc, valid-type]
        def __init__(self) -> None:  # no database connection
            self.models = tuple(models) if encoder is not None else ()
            self.device = "cpu"
            self.last_encoding_timings: dict[str, dict[str, float]] = {}
            self.conn = _CourseLookup()
            self.source_types = {d["source_type"] for d in data.catalog.documents.values()}
            self.source_types_by_course = defaultdict(set)
            for d in data.catalog.documents.values():
                self.source_types_by_course[d["course_id"]].add(d["source_type"])

        def close(self) -> None:
            pass

        def _encode_questions(self, questions: list[str]) -> dict[str, np.ndarray]:
            return {key: np.asarray(encoder(key, questions), dtype=np.float32) for key in self.models}  # type: ignore[misc]

        @staticmethod
        def _filters(course_id: str | None, scopes: list[str], include_flagged: bool) -> tuple[str, list[Any]]:
            return "__memory__", [course_id, list(scopes), include_flagged]

        def _vector_channel(self, key: str, vector: np.ndarray, filter_sql: str, filter_params: list[Any],
                            candidate_limit: int) -> list[str]:
            index = data.eligible(*filter_params)
            if not index:
                return []
            sims = data.vectors[key][index] @ np.asarray(vector, dtype=np.float32)   # cosine; same order as <=>
            order = np.argsort(-sims, kind="stable")[:candidate_limit]
            return [data.records[index[j]]["record_id"] for j in order]

        def _lexical_channel(self, query_text: str, filter_sql: str, filter_params: list[Any],
                             candidate_limit: int) -> list[str]:
            words, mode = _websearch_terms(query_text or "")
            if not words:
                return []
            match = f" {mode} ".join(f'"{w}"' for w in words)
            allowed = set(data.eligible(*filter_params))
            rows = data.fts.execute("SELECT rowid, bm25(t) FROM t WHERE t MATCH ? ORDER BY bm25(t), rowid", (match,)).fetchall()
            ranked = [data.records[i]["record_id"] for i, _ in rows if i in allowed]
            return ranked[:candidate_limit]

        def _hydrate(self, ids: list[str]) -> dict[str, dict[str, Any]]:
            out = {}
            for record_id in ids:
                r = data.by_id[record_id]
                pid = r["entity_id"] if r["entity_type"] == "passage" else data.catalog.concept_passages[r["entity_id"]][-1]
                p = data.catalog.passages[pid]
                d = data.catalog.documents[r["document_id"]]
                out[record_id] = {
                    "record_id": record_id, "entity_type": r["entity_type"], "entity_id": r["entity_id"],
                    "section_path": r.get("section_path", ""), "segment_index": r["segment_index"],
                    "scope_status": r["scope_status"], "input_text": r["input_text"], "passage_id": pid,
                    "raw_latex": p["raw_latex"], "readable_text": p.get("readable_text", ""),
                    "start_line": p["start_line"], "end_line": p["end_line"], "filename": d["filename"],
                    "snapshot_path": d["snapshot_path"], "source_type": d["source_type"],
                    "review_status": d["review_status"],
                    "known_issues": [{k: i[k] for k in ("issue_id", "severity", "status", "description")}
                                     for i in data.catalog.open_issues(r["document_id"], p["start_line"], p["end_line"])],
                    "course_id": r["course_id"], "course_name": data.catalog.course_names.get(r["course_id"], r["course_id"]),
                }
            return out

    return MemoryRetriever()


class InMemoryBackend:
    """Week 3 retrieval code over the Week 3 files. Deterministic; no database needed."""

    name = "in_memory"

    def __init__(self, root: Path, *, catalog: Catalog | None = None, encoder: Encoder | None = None,
                 models: tuple[str, ...] = ("bge_base_en_v1_5", "qwen3_embedding_0_6b")) -> None:
        self.search_module, self.policy_module, self.contract = load_week3_package(root)
        catalog = catalog or Catalog.load(root)
        self.data = _MemoryData(root, catalog, models if encoder is not None else ())
        self.retriever = _make_memory_retriever(self.search_module.Retriever, self.data, encoder, models)
        self.semantic_available = bool(self.retriever.models)

    @property
    def records(self) -> list[dict[str, Any]]:
        return self.data.records

    @property
    def vectors(self) -> dict[str, np.ndarray]:
        return self.data.vectors

    def query_facets(self, question: str) -> list[str]:
        return self.policy_module.query_facets(question)

    def run(self, question: str, facets: list[str], *, course_id: str, include_unconfirmed: bool = False,
            include_outside_course: bool = False, **options: Any) -> dict[str, Any]:
        return run_week3(self.retriever, self.contract, question, facets, course_id=course_id,
                         include_unconfirmed=include_unconfirmed, include_outside_course=include_outside_course, **options)

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# PostgreSQL / pgvector backend (Week 3 index, run on the Mac with Docker)
# ---------------------------------------------------------------------------
class PgvectorBackend:
    """Week 3's Retriever on the Docker database; only change: encoders are loaded once."""

    name = "pgvector"

    def __init__(self, root: Path, *, device: str = "auto", week3_kb: Path | None = None,
                 models: tuple[str, ...] = ("bge_base_en_v1_5", "qwen3_embedding_0_6b")) -> None:
        # Prefer the live Week 3 folder (its postgres/.env, Docker DB and .cache/huggingface model files);
        # otherwise the packaged copy in output/github-ready (needs infra/postgres/.env and a model cache).
        if week3_kb is not None and (week3_kb / "retrieval" / "search.py").exists():
            search, policy, contract = load_week3_folder(week3_kb)
            manifest_path = week3_kb / "embeddings" / "input_manifest.json"
        else:
            search, policy, contract = load_week3_package(root)
            manifest_path = root / "data" / "embeddings" / "input_manifest.json"
        self.policy_module, self.contract = policy, contract

        class CachedEncoderRetriever(search.Retriever):  # type: ignore[misc, name-defined]
            """Same query prompts and revisions as Week 3; each SentenceTransformer is loaded once."""

            _loaded: dict[str, Any] = {}

            def _encode_questions(self, questions: list[str]) -> dict[str, np.ndarray]:
                from sentence_transformers import SentenceTransformer
                import torch
                dev = self.device
                if dev == "auto":
                    dev = "mps" if torch.backends.mps.is_available() else "cpu"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                out = {}
                for key in self.models:
                    if key not in self._loaded:
                        spec = manifest["models"][key]
                        self._loaded[key] = SentenceTransformer(spec["repository"], revision=spec["revision"],
                                                                device=dev, local_files_only=True)
                    model = self._loaded[key]
                    if key == "bge_base_en_v1_5":
                        texts = ["Represent this sentence for searching relevant passages: " + q for q in questions]
                        vectors = model.encode(texts, batch_size=16, normalize_embeddings=True, convert_to_numpy=True)
                    else:
                        vectors = model.encode(questions, prompt_name="query", batch_size=4,
                                               normalize_embeddings=True, convert_to_numpy=True)
                    out[key] = np.asarray(vectors, dtype=np.float32)
                return out

        try:
            self.retriever = CachedEncoderRetriever(models=models, device=device)
        except Exception as error:  # database down, manifest mismatch, ...
            code = "index_encoder_mismatch" if "do not match" in str(error) else "index_unavailable"
            raise BackendUnavailable(code, str(error)) from error
        self.semantic_available = True

    def query_facets(self, question: str) -> list[str]:
        return self.policy_module.query_facets(question)

    def warm_up(self) -> None:
        """Load both embedding models now (about 5 s once) instead of during the first student's turn."""
        self.retriever._encode_questions(["warm-up query"])

    def run(self, question: str, facets: list[str], *, course_id: str, include_unconfirmed: bool = False,
            include_outside_course: bool = False, **options: Any) -> dict[str, Any]:
        return run_week3(self.retriever, self.contract, question, facets, course_id=course_id,
                         include_unconfirmed=include_unconfirmed, include_outside_course=include_outside_course, **options)

    def close(self) -> None:
        self.retriever.close()


# ---------------------------------------------------------------------------
# Replay backend: Week 3's own saved reports, no search
# ---------------------------------------------------------------------------
class ReplayBackend:
    """Returns the report Week 3 produced for the same question text. Raises if the question was not recorded."""

    name = "week3_replay"
    semantic_available = True

    def __init__(self, root: Path, runs_file: Path) -> None:
        self.policy_module, self.contract = load_week3_rules(root)
        rows = [json.loads(l) for l in Path(runs_file).read_text(encoding="utf-8").splitlines() if l.strip()]
        self.reports = {" ".join(r["report"]["question"].split()): r["report"] for r in rows}
        self.calls: list[dict[str, Any]] = []

    def query_facets(self, question: str) -> list[str]:
        return self.policy_module.query_facets(question)

    def run(self, question: str, facets: list[str], *, course_id: str, include_unconfirmed: bool = False,
            include_outside_course: bool = False, **options: Any) -> dict[str, Any]:
        key = " ".join(question.split())
        if key not in self.reports:
            raise BackendUnavailable("index_unavailable", f"question not in the replay file: {key[:80]}")
        self.calls.append({"question": key, "facets": facets, "course_id": course_id, **options})
        report = json.loads(json.dumps(self.reports[key]))
        self.contract.validate_report_contract(report)
        return report

    def close(self) -> None:
        pass
