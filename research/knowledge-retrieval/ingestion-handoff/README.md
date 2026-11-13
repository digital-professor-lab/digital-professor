# Ingestion → Retrieval handoff: `IngestedSource` format v1.0 (draft)

**From:** Sean (Retrieval) **To:** Ovunc (Course Context and Ingestion) **Date:** 2026-11-12 **Status:** draft for review

This is the format note promised in `specs/rag-retrieval.md` §2.1. It turns the field list there into a file format with a JSON Schema, a template, a worked example and a checker. Once we agree on it, I will update `interfaces.md` §9 (`IngestedSource`, still marked "needs Sean's sign-off") and the old example `specs/examples/calc1.retrieval.g-…json` in a PR, so the repo has one format.

## Files

| File | What it is |
|---|---|
| `README.md` | This note |
| `ingested-source.schema.json` | JSON Schema (draft 2020-12). Strict: unknown fields are rejected |
| `ingested-source.template.json` | Blank template with every field |
| `calc1.ingested-source.example.json` | A full example: a 3-page lecture-notes handout on §4.5 The Chain Rule, 12 blocks |
| `validate_ingested_source.py` | Checker: the schema plus the rules a schema cannot express |

The example content was written for this note in the style of lecture notes. It is not quoted from the textbook, and its file hash and page labels are made up. Its structure, IDs and concept tags are real: the concept IDs come from `specs/examples/calc1.course-context.json` on `oe/JDP-56` (schema 1.1, v0.7.0).

## 1. The idea

**One file = one document at one content version.** A textbook, a set of lecture notes or a problem set each gets its own file. A new version of the document gets a new file with a new `content_version`.

Each file has three layers:

| Layer | What it holds | Why Retrieval needs it |
|---|---|---|
| `pages` | The normalized text of every page, line by line | The source of truth for locations. A citation is `(document_id, content_version, page_number, line_start, line_end)`, and Delivery highlights exactly those lines |
| `sections` | The heading tree: chapter → section → subsection, each with its page/line range and concepts | Search can be narrowed to the right section first, and every search unit gets its heading path ("4 Differentiation > 4.5 The Chain Rule") |
| `blocks` | The content units in reading order: one complete definition, theorem, example, exercise, … each with its type, text, location and concepts | Each block becomes one search unit. Its type and concepts drive the evidence check |

This follows the split we agreed on 2026-10-27 (spec §2.1): **you split by content structure, I decide how to search it.** You do not need to care about token limits, embeddings or overlap. If a block is long, Retrieval splits it at embedding time. Please never split one definition or example across two blocks.

## 2. Top level

| Field | Required | Notes |
|---|---|---|
| `record_id`, `record_type`, `schema_version`, `created_at`, `producer`, `status`, `correlation_id` | Yes | The common envelope of `interfaces.md` §1.1. `record_type` = `IngestedSource`, `schema_version` = `0.1`, `producer` = `course-context-ingestion` |
| `status` | Yes | `ingested` (everything extracted), `partial` (usable, with gaps listed in `warnings`), `failed` (nothing usable: `blocks` is empty, Retrieval does not index it) |
| `ingested_source_schema_version` | Yes | `1.0`, the version of this format |
| `course_id` | Yes | `Course.id`, e.g. `calc1` |
| `course_context_ref` | Yes | `course_context_schema_version` and `content_sha256` of the Course Context file whose concept IDs you used (same idea as `QuestionSchema.built_from`) |
| `document`, `pages`, `sections`, `blocks`, `warnings` | Yes | Below. `warnings` may be empty |

## 3. `document`

| Field | Notes |
|---|---|
| `document_id` | `<course_id>:<slug>`, e.g. `calc1:lecture-notes-ch4`. **The same for every version** of the document |
| `content_version` | Any short string, e.g. `2026-11-12.1`. **Must change whenever any page line changes**, because page and line numbers are only valid for one version. Re-running the same pipeline on the same file should give the same lines |
| `document_role` | `textbook`, `lecture_notes`, `slides`, `worked_examples`, `problem_set`, `past_exam`, `syllabus`, `other`. A `syllabus` is indexed but treated as reference-only: it is never cited as evidence in production |
| `title`, `source_label` | `source_label` is the short name shown next to a citation, e.g. "Lecture notes, Section 4.5" |
| `source_file` | `filename`, `media_type`, `sha256` of the original upload, `page_count` |
| `source_provenance` | `source_document` (text taken from the original course file) or `ai_generated` (text a model wrote, like the current AI course breakdowns) |
| `review_status`, `reviewed_by`, `reviewed_at` | `reviewed` once a person has confirmed the document (right file, edition and course); otherwise `unverified` |
| `language` | `en` (V1 is English only) |

**Production rule on my side:** only `source_document` + `reviewed` material, and not a syllabus, can be cited to students. Everything else is searchable in development mode and always carries an "unverified source" warning.

## 4. `pages`

| Field | Notes |
|---|---|
| `page_number` | Physical page in the file, starting at 1, i.e. what a PDF viewer opens. **List every page**, 1 to `page_count`, when `status` is `ingested` |
| `page_label` | The printed page number, e.g. `"112"`, or `null` |
| `lines` | The normalized page text, one string per line. Line *n* is `lines[n-1]` |
| `text_sha256` | sha256 of `"\n".join(lines)` in UTF-8. It lets either side detect a changed page |

Normalization (from `course-context.md` §1.5): collapse whitespace, drop empty lines, remove running headers, footers and page numbers, and rejoin words hyphenated across lines. Keep the reading order. The lines are what a PDF text extractor gives you: math may come out garbled there (in the example, `x²` became `x2`). That is fine, because the clean math goes in the block `text` (§6).

## 5. `sections`

| Field | Notes |
|---|---|
| `section_id` | Unique in the file, e.g. `ch4.s5.1` |
| `parent_id`, `level` | The heading tree. Top level has `parent_id: null` and `level: 1`; a child is its parent's level + 1 |
| `number`, `title`, `heading_kind` | `"4.5.1"`, `"The Chain Rule"`, and one of `part`, `chapter`, `section`, `subsection`, `lecture`, `appendix`, `other` |
| `page_start`, `line_start`, `page_end`, `line_end` | Where the section starts and ends. A child lies inside its parent |
| `concept_ids` | The Course Context concepts the section teaches, main one first. May be empty |
| `structure_inferred` | `true` if no real heading, bookmark or table of contents supports this section (the fallback in `course-context.md` §1.6 step 7) |

## 6. `blocks`

Blocks are listed in reading order, do not share lines, and each lies inside the innermost section that contains it. Text that is not a block, such as a heading line, simply belongs to no block.

| Field | Notes |
|---|---|
| `block_id` | Unique in the file. Suggested: `<document_id>/<section number>/b01`. Keep it the same across versions when the block is unchanged; Retrieval does not depend on that, because its passage IDs hash the version and location |
| `section_id` | The innermost section the block is in |
| `type` | `definition`, `theorem` (also rules, propositions, lemmas, corollaries), `formula`, `proof`, `example`, `exercise`, `solution`, `explanation`, `remark`, `summary`, `figure`, `table`, `other`. **A worked example keeps its solution in the same block.** The solution of an *exercise* is a separate `solution` block |
| `label` | The printed label, e.g. `"Theorem 4.5.2 (Chain rule)"`, or `null` |
| `text` | The clean text of exactly the lines the block covers. **Math as LaTeX** in `$…$` or `$$…$$`, e.g. `$(f \circ g)'(x) = f'(g(x))\,g'(x)$`. If the source is LaTeX, keep its math; if it is a PDF, use a math-aware extractor and add a `math_uncertain` warning when you are not sure |
| `page_start`, `line_start`, `page_end`, `line_end` | The block's lines. A block may cross a page break (Example 4.5.5 in the example runs from page 1 line 24 to page 2 line 5) |
| `concept_ids` | Course Context concept IDs the block is about, **main one first**, usually 1–3. Only IDs from the Course Context file in `course_context_ref` |
| `concept_source` | How you set them: `section` (copied from the section), `model`, `human`, or `none` (then `concept_ids` is empty and you add a `concept_unmapped` warning) |
| `visibility` | `student_visible`, or `engine_only` for text that may guide the tutor but must never be shown to the student. **Every `solution` block is `engine_only`** |
| `for_block_id` | A `solution` points at its exercise; a `proof` points at its theorem |
| `question_id` | On an `exercise` that is also in the question bank: its bank ID. Then, when the student is working on that question, Retrieval can exclude the exercise and its solution (the answer-leak guard) |

**Size.** One block is one complete unit: a whole definition, a whole theorem with its formula, a whole worked example. Typical blocks are 1–20 lines. Retrieval skips text shorter than about 40 characters, so attach a lone sentence to its neighbour rather than making it a block.

**Figures and tables.** Put the caption and a short description of what the figure shows in `text`. If you cannot, add `figure_text_missing` or `table_text_missing`.

## 7. IDs and versions

- `document_id` is stable across versions; `content_version` changes when any page line changes.
- `section_id` and `block_id` are unique within a file.
- Concept IDs are opaque strings taken from the Course Context. If the Course Context is regenerated with new IDs, the file needs a new `course_context_ref` and re-tagging.
- An updated document is a new file. The old file stays valid until the new version is published, so a tutoring turn never switches version halfway (`architecture.md` §6).

## 8. `status` and `warnings`

Each warning is `{code, message, page_number?, block_id?}`. Codes: `page_unreadable`, `ocr_low_confidence`, `math_uncertain`, `structure_inferred`, `concept_unmapped`, `figure_text_missing`, `table_text_missing`, `page_range_skipped`, `other`. A `partial` or `failed` file has at least one warning that says what is missing.

## 9. What Retrieval does with each field

| Your field | What it lets Retrieval do |
|---|---|
| `document_id`, `content_version`, page and line ranges | Stable passage IDs, version-pinned citations, real `page_number` / `line_start` / `line_end` and a `highlight_url` for Delivery. Today these are `null` |
| `source_provenance`, `review_status`, `document_role` | Decide what may be cited in production; keep a syllabus as reference only |
| `sections` (tree and titles) | The heading path that goes in front of each block at embedding time; narrowing a search to the right section |
| block `type` | The evidence check can use the type: a "statement of the chain rule" need is met by a `theorem` block, a "worked example" need by an `example` block. Today it guesses from wording |
| block `concept_ids` | Search the question's concept first and widen only if nothing is found; replaces the old `Source` / `source_ids` mapping, which Course Context v0.7.0 removed |
| block `text` with LaTeX | Exact formula matching for formula needs; exact quotes in the tutor's reply |
| `visibility`, `for_block_id`, `question_id` | Keep answers out of student-facing text; exclude the current question's own exercise and solution |

**Check on our side.** I ran the example through the retrieval tool with a throwaway adapter (term-overlap search, no Week 3 database). A request for "statement of the chain rule" + "worked example" returned the theorem block first and marked the statement need *covered*. The development corpus never got that far, because it has no theorem text. The example need stayed *not covered* only because the current rules do not read block `type` yet. That is the adapter I build next.

## 10. How to check a file

```bash
pip install -U "jsonschema>=4"
python validate_ingested_source.py calc1.ingested-source.example.json \
    --course-context <path to>/specs/examples/calc1.course-context.json --preview
```

It checks the schema, unique IDs, that every range is inside the pages, that blocks are in reading order without overlap and inside their section, the solution and proof links, the page hashes, and that every concept ID exists in the Course Context file. `--preview` lists what Retrieval will index. Exit code 0 means no errors.

## 11. Differences from the proposed `IngestedSource` in `interfaces.md` §9

| `interfaces.md` §9 (10-15 draft) | This format | Why |
|---|---|---|
| `chunks` optional; who chunks is open | `blocks` required; you split by content, I decide search units | The split agreed on 10-27, spec §2.1 |
| `source_ids` required | Removed; blocks carry `concept_ids` | Course Context v0.7.0 removed `Source` |
| `pages[].normalized_text` + `line_count` | `pages[].lines` + `text_sha256` | Line numbers cannot drift from the text |
| `ingest_status` | Envelope `status` | One status field |
| — | `sections`, `document_role`, `source_provenance`, `review_status`, `visibility`, `course_context_ref` | Needed for section narrowing, the production citation rule and the answer-leak guard |

## 12. Open points for us to agree

1. **Input files.** Which real materials will you ingest first (lecture notes or textbook, PDF or LaTeX)? With LaTeX source the block math is exact; with PDFs we should look at `math_uncertain` on a sample.
2. **Concept tagging.** Copying section concepts to blocks (`concept_source: section`), then a model pass for blocks that touch other concepts, seems enough for V1. Does that fit your pipeline?
3. **Where files go.** Suggestion: `ingested/<course_id>/<document slug>/<content_version>.json`, written once and never edited; a new version is a new file.
4. **First sample.** One chapter (e.g. Chapter 4, Derivatives) in this format, so I can build the adapter against your real output.
