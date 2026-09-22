# Focused evaluation set: preparation and run guide

This set evaluates the current prototype before changing its interaction features. `cases.json` contains 10 handwritten PDF cases with reference transcriptions and 8 course-grounded tutoring prompts. One cold and one warm batch per modality have been run; the [`RESULTS_DRAFT.md`](RESULTS_DRAFT.md) interpretation and local `results/*-review.csv` scores are provisional AI-assisted review pending independent human audit. The 762 syllabus and notes are the tutoring sources. Keep all samples free of names, grades, and other student identifiers.

## Create the handwriting set

The ten one-page PDFs are stored under `evaluation/handwriting/` with filenames matching `cases.json`. They are tablet/stylus-style input rather than photos. Each file has one intended task:

| ID | Write or capture |
|---|---|
| h01 | One clean equation, such as a linear objective. |
| h02 | A fraction with an exponent. |
| h03 | Distinct subscripts and superscripts in the same expression. |
| h04 | A small matrix or vector expression. |
| h05 | Three or more handwritten solution steps, including a crossed-out or corrected step if natural. |
| h06 | An inequality constraint, such as `Ax <= b` with variable bounds. |
| h07 | A deliberately ambiguous symbol pair (for example `1/l` or `x/×`); record the intended reading separately. |
| h08 | A mathematically incorrect step that the recognizer must preserve rather than silently fix. |
| h09 | A multicolor stylus expression. |
| h10 | An expression written with variable-width calligraphy strokes. |

The `reference_markdown` fields are filled from visual inspection of the PDFs. They transcribe **exactly what is visible**, including the wrong derivative in h08, line breaks, and `$$...$$` around mathematics. h07's intended reading and the alternate symbol are recorded in `reference_note`; h09 and h10 also have capture notes. Have a second human review the references before running the model, especially h07. Keep the original PDFs unchanged for later rechecks. The run records whitespace-insensitive exact match and character error rate as surface-form measures; a reviewer marks `math_equivalent` as `yes` or `no` because different LaTeX strings can mean the same thing.

## Check the tutoring set

The eight `t` cases in `cases.json` cover definitions, explanation, course overview, a misconception, an underspecified request, and questions from pages beyond the current five-page chat-text limit. Before running, open the 762 PDFs and have a second person confirm each `expected_points` list and page reference. Do **not** edit expected points after seeing model answers. If using a different course, replace both `course_sources` paths and all eight prompts and rubrics with questions grounded in that course.

For each response, fill its row in the generated `*-review.csv`:

- `correctness`: `0` wrong or materially misleading; `1` partly correct; `2` correct on the expected points.
- `grounding`: `0` unsupported or invented source claim/page; `1` partly supported or weak citation; `2` every course-specific claim supported by the loaded text and citation. For `outside_loaded_text`, give `2` when the model explicitly states the limit and avoids invented page details.
- `uncertainty`: `0` guesses through ambiguity/missing material; `1` partly acknowledges limits; `2` clearly states relevant limits or asks for missing information. Give `2` when no uncertainty is needed and the answer is appropriately direct.
- `answer_family`: a short label for the substantive outcome of repeated answers, such as `correct_LP_definition`, `unsupported_page_claim`, or `asks_for_objective`. Use the same label for materially equivalent answers even if wording differs.
- `failure_tags`: semicolon-separated labels such as `symbol_confusion`, `dropped_step`, `invented_page`, `unsupported_claim`, `wrong_math`, or `missed_ambiguity`. Leave blank for a successful run.
- `notes`: a brief explanation and the relevant page or image region for any disputed score.

## Run later, once the set is complete

Install the root `requirements.txt`, start the assessment backend on port 8001 as described in the parent README, and check that its root `.env` configures the model and API key. The runner uses HTTP requests against that backend; it does not need the frontend. From `research/assessment-prototype/`:

```bash
PYTHONPATH=src ../../.venv/bin/python evaluation/evaluate.py validate
```

All ten PDF paths and references are now filled, so full validation should pass. This only checks preparation; it does not run the model.

To compare cold and warm timing, restart the backend immediately before each **cold** command. Run the cold command first; it measures only the first case as a stable anchor. Without restarting, run the warm command for the full set. Repeat this restart/cold/warm sequence at least three times for each modality; use `--repeats 3` for warm tutoring to measure response consistency. Keep provider, model, skills, source set, and `DP_MAX_PAGES` fixed. Example commands:

```bash
PYTHONPATH=src ../../.venv/bin/python evaluation/evaluate.py run --kind handwriting --phase cold
PYTHONPATH=src ../../.venv/bin/python evaluation/evaluate.py run --kind handwriting --phase warm --repeats 2
PYTHONPATH=src ../../.venv/bin/python evaluation/evaluate.py run --kind tutoring --phase cold
PYTHONPATH=src ../../.venv/bin/python evaluation/evaluate.py run --kind tutoring --phase warm --repeats 3
```

Use a fresh backend restart between the handwriting and tutoring cold commands. The runner writes raw responses, a review CSV, and a settings snapshot to ignored `evaluation/results/`; it never writes the API key. It captures HTTP wall time and, for tutoring, provider request time. Each source upload is an individual run. After filling the review CSVs:

Start with an empty Sources tab. The runner refuses to start if other sources are loaded, then removes only the sources it uploaded after the run. This keeps the tutoring context the same across repetitions.

```bash
PYTHONPATH=src ../../.venv/bin/python evaluation/evaluate.py summarize
```

The summary reports recognition exact match, character error rate, human-rated mathematical equivalence, tutoring rubric averages, reviewed response consistency, cold/warm latency, and common failure tags. It leaves the next improvement as a hypothesis until the scores are reviewed. The current backend sends only the first `DP_MAX_PAGES` of document text to chat, even when the PDF outline lists later pages; the `outside_loaded_text` cases deliberately test whether answers respect that limit.

For a readable view of what the model actually generated, open `evaluation/results/REVIEW.html` in a browser. It groups runs by case and shows handwritten PDF links, reference text, model transcription, tutoring answers, citations, and current review scores. After editing a review CSV or adding new runs, refresh the page by regenerating it:

```bash
python evaluation/render_review.py
```
